"""Solve normalized expression recipes against the current target curves."""
import copy
import numpy as np
from functools import lru_cache
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
from . import region_guides as G, procedural_constraints as Q, procedural_binding as B, procedural_cavity as Cavity, procedural_lashes as Lashes
from .generation_progress import notify
from . import procedural_tongue as Tongue
from . import procedural_lips as Lips
from . import procedural_anatomy as Anatomy
from . import expression_runtime as Custom
from . import expression_rules as Rules

LOWER_LID_MAX_RISE=.30
LOWER_LID_MIDDLE_EXTRA=.10


@lru_cache(maxsize=512)
def coefficients(values):
    a=np.array(values,dtype=float);t=np.linspace(0,1,len(a))
    # A low-order whole-curve fit avoids new corners at reference sample bins.
    coeff=np.polynomial.polynomial.polyfit(t,a,min(6,len(a)-1))
    ends=np.polynomial.polynomial.polyval(np.array([0.,1.]),coeff).T
    return a,coeff,ends


def sampled(values,u):
    a,coeff,ends=coefficients(tuple(tuple(float(x) for x in row) for row in values))
    value=np.polynomial.polynomial.polyval(u,coeff)
    return value+(a[0]-ends[0])*(1-u)+(a[-1]-ends[1])*u


def eye_corner_weights(t,inner_end):
    """Fade corner motion with zero slope/curvature at both fade endpoints."""
    widths=np.array([.40,.40]);widths[inner_end]=.30
    distance=np.array([t,1-t]);u=np.clip(distance/widths,0,1)
    return 1-u**3*(10-15*u+6*u*u)


def lower_rise(value,limit):
    """Limit positive motion smoothly; downward corner travel stays available."""
    if value<=0:return value
    if limit<=1e-12:return 0.
    if value>=limit:return limit
    if value<=limit*.8:return value
    # Preserve the full requested range; match value, slope and curvature at
    # both knee endpoints instead of shrinking the cap with tanh.
    t=(value/limit-.8)/.2
    return limit*(.8+.2*(t+4*t**3-7*t**4+3*t**5))


def apex_weight(t,peak):
    """Move the extra lower-lid allowance with the character's arch apex."""
    t=np.asarray(t,dtype=float);peak=float(np.clip(peak,.2,.8))
    q=np.where(t<=peak,t/peak,(1-t)/(1-peak))
    q=np.clip(q,0.,1.)
    return q*q*(3-2*q)


def open_lid_rule(rig,side,motion):
    """Explicit open-eye directions in the character's original eye frame."""
    upper=rig.guide_lines['EYE',side][True];lower=rig.guide_lines['EYE',side][False]
    lo=min(upper.points[:,0]);span=max(float(np.ptp(upper.points[:,0])),1e-12)
    height=rig.heights['EYE',side];level=float(np.max(upper.points[:,2]))-motion.get('upper_drop',0.)*height
    upper_ends=np.array([rig.curve('EYE',side,True,t)[2] for t in (0,1)])
    level=max(level,float(np.max(upper_ends)))
    ends=np.array([rig.curve('EYE',side,False,t)[2] for t in (0,1)])
    parameters=np.linspace(0,1,129)
    lower_rest=np.array([rig.curve('EYE',side,False,u) for u in parameters])
    order=np.argsort(lower_rest[:,0]);lower_rest=lower_rest[order]
    body_x=lo+span*np.array((.25,.75))
    body_z=np.interp(body_x,lower_rest[:,0],lower_rest[:,2])
    def body_height(t):return body_z[0]+(body_z[1]-body_z[0])*(t-.25)/.5
    corner_shift=np.zeros(2)
    if motion.get('lower_fixed',0.)<1-1e-8:
        # A tall lower canthus is the beginning of the closing turn, not a
        # fixed high anchor for a new absolute-height cubic. Move it only by
        # the requested partial convergence; keep the horizontal lower body.
        convergence=float(np.clip(motion.get('upper_drop',0.)+motion.get('lower_lift',0.),0,.65))
        corner_shift=np.minimum(np.array([body_height(t) for t in (0.,1.)])-ends,0.)*convergence
    angry_outer_lift=height*min(max(-motion.get('upper_bias',0.),0.)*.18,.08)
    corner_shift[1 if side>0 else 0]+=angry_outer_lift
    upper_ends+=corner_shift
    def lid(u,up):
        point=rig.curve('EYE',side,up,u).copy();t=float(np.clip((point[0]-lo)/span,0,1))
        q=np.clip(np.array((t,1-t))/.16,0,1);blend=float(np.prod(q**3*(10-15*q+6*q*q)))
        if up:
            q=np.clip(np.array((t,1-t))/.30,0,1)
            point[2]+=float((1-q**3*(10-15*q+6*q*q))@corner_shift)
            outer=t if side>0 else 1-t
            drop=max(motion.get('upper_drop',0.)+motion.get('upper_bias',0.)*(outer-.5),0.)*height*blend
            # A stationary canthus is a boundary of the arch. Letting the
            # neighboring upper rim descend below its chord produces a hook
            # followed by a rapid turn back up into that canthus.
            chord=upper_ends[0]*(1-t)+upper_ends[1]*t
            available=max(point[2]-chord,0.)
            drop=available*(-np.expm1(-drop/max(available,1e-12)))
            flattened=float(np.clip(motion.get('upper_flatten',0.),0,1))
            # A C2 transition retains the canthi and joins an exactly level
            # central portion. No global cubic fit can retain that plateau.
            d=max(point[2]-level,0.);s=float(np.clip(d/max(height*.06,1e-12),0,1))
            smooth=s**3*(10-15*s+6*s*s)
            point[2]-=(1-flattened)*drop+flattened*d*smooth
            if 'upper_peak' in motion:
                peak=float(np.clip(motion['upper_peak'],.2,.8))
                a=1.;b=(1-peak)/peak
                arch=(outer**a*(1-outer)**b)/max(peak**a*(1-peak)**b,1e-12)
                target=chord+height*(1-motion.get('upper_drop',0.))*.5*arch-height*.10*4*outer*outer*(1-outer)
                gap=point[2]-target;radius=height*.055*blend
                point[2]=.5*(point[2]+target-np.sqrt(gap*gap+radius*radius))
        elif motion.get('lower_fixed',0.)<1-1e-8:
            point[2]+=min(body_height(t)-point[2],0.)*convergence
            lift=height*motion.get('lower_lift',0.)*4*t*(1-t)
            flatten=max(body_height(t)-point[2],0.)*motion.get('lower_flatten',0.)
            point[2]+=min(lift+flatten,height*LOWER_LID_MAX_RISE)*blend
        if motion.get('upper_bias',0.)<0:
            inner=t if side>0 else 1-t
            if not up:
                q=float(np.clip((inner-.70)/.30,0,1));q=q**3*(10-15*q+6*q*q)
                point[2]+=angry_outer_lift*q
        point+=Custom.offset(rig,'EYE_UPPER' if up else 'EYE_LOWER',side,u)
        return point
    if 'upper_peak' in motion:
        # Fit the intended sad arch as one curve. Applying its ceiling at
        # individual sparse rim vertices made the inner peak and outer return
        # change tangent abruptly, which also creased the attached skin.
        samples=np.linspace(0,1,129)
        cloud=np.array([lid(u,True) for u in samples]);x=(cloud[:,0]-lo)/span
        strength=float(np.clip(motion.get('upper_motion_scale',1.),0,1))
        rest=np.array([rig.curve('EYE',side,True,u) for u in samples])
        corner_motion=(cloud[[0,-1],2]-rest[[0,-1],2])
        carried=corner_motion[0]*(1-x)+corner_motion[1]*x
        cloud[:,2]=rest[:,2]+carried+strength*(cloud[:,2]-rest[:,2]-carried)
        matrix=B.spline_basis(x,7);second=np.diff(np.eye(7),n=2,axis=0)
        controls=np.zeros(7);controls[[0,-1]]=cloud[[0,-1],2]
        fixed=matrix[:,[0,-1]]@controls[[0,-1]]
        free=matrix[:,1:-1];smooth=second[:,1:-1]
        rhs=free.T@(cloud[:,2]-fixed)-.08*smooth.T@(second[:,[0,-1]]@controls[[0,-1]])
        controls[1:-1]=np.linalg.solve(free.T@free+.08*smooth.T@smooth,rhs)
        raw_lid=lid
        def lid(u,up):
            point=raw_lid(u,up)
            if up:
                t=float(np.clip((point[0]-lo)/span,0,1))
                point[2]=float((B.spline_basis([t],7)@controls)[0])
            return point
    lid.open_motion=motion
    return lid


def character_arc(upper,corners,ends,height,smile=0.,flat=0.):
    """Reflect the current upper guide's curvature about its canthus chord.

    Only the fitted curve residual changes sign. The mesh, canthus tilt and
    cross-sections retain their orientation. No shared minimum arch height.
    """
    t=np.linspace(0.,1.,129);span=max(float(corners[1,0]-corners[0,0]),1e-12)
    x=np.clip((upper[:,0]-corners[0,0])/span,0.,1.)
    x,inverse=np.unique(x,return_inverse=True)
    z=np.bincount(inverse,weights=upper[:,2])/np.bincount(inverse)
    residual=np.interp(t,x,z)-((1-t)*corners[0,2]+t*corners[1,2])
    residual-=residual[0]*(1-t)+residual[-1]*t
    basis=np.column_stack((3*(1-t)**2*t,3*(1-t)*t*t))
    handles=np.linalg.lstsq(basis,residual,rcond=None)[0]
    # Fit one bracket rather than an S bend. Projection onto the concavity
    # cone preserves measured amplitude and treats both anatomical ends alike.
    candidates=[np.zeros(2)]
    if min(handles)>=0 and handles[0]<=2*handles[1] and handles[1]<=2*handles[0]:
        candidates.append(handles)
    for ray in (np.array((1.,2.)),np.array((2.,1.))):
        projected=basis@ray
        candidates.append(ray*max(float(projected@residual/max(projected@projected,1e-20)),0.))
    handles=min(candidates,key=lambda h:float(np.sum((basis@h-residual)**2)))
    curve=basis@handles;top=float(np.max(curve))
    # Tall apertures must not turn the closed line into an equally tall bow.
    # Measure curvature in eye widths, retaining the current arch's shape.
    gain=min(1.,span*(.06+.08*smile)/max(top,1e-12));handles*=gain;curve*=gain;top*=gain
    peak=float(np.mean(t[curve>=top-max(top*1e-5,1e-12)])) if top>1e-12 else .5
    controls=np.linspace(ends[0],ends[1],4)
    controls[1:3,2]+=handles*(2*smile-1)*(1-flat)
    return controls,peak,dict(method='current_upper_guide_chord_reflection',peak=peak,
                              height_ratio=top/max(height,1e-12),flat=float(flat))


def mouth_outline(rig,reference,u,upper):
    """Retarget the measured original key's outline, not a displacement fit."""
    width=rig.widths['LIP',0]
    left=(rig.curve('LIP',0,True,0)+rig.curve('LIP',0,False,0))*.5
    right=(rig.curve('LIP',0,True,1)+rig.curve('LIP',0,False,1))*.5
    center=(left+right)*.5
    values=np.asarray(reference['upper' if upper else 'lower']);t=np.linspace(0,1,len(values))
    value=np.array([np.interp(u,t,values[:,k]) for k in range(3)])
    point=rig.curve('LIP',0,upper,u).copy()
    if np.allclose(reference['upper'],reference['lower'],atol=1e-10,rtol=0):
        point=(point+rig.curve('LIP',0,not upper,u))*.5
    point[0]=center[0]+value[0]*width;point[2]=center[2]+value[2]*width
    entry=rig.guides['LIP',0][bool(upper)]
    if entry.get('base'):
        edit=lambda t:np.array(G.sample(entry['points'],t))-np.array(G.sample(entry['base'],t))
        # Endpoint edits already define the target frame. Interior manual
        # adjustments remain effective on top of the measured expression.
        residual=edit(u)-edit(0)*(1-u)-edit(1)*u
        point[[0,2]]+=residual[[0,2]]
    # Keep target depth. The reference mouth's forward motion and cavity
    # depth are not transferable offsets for the target's face thickness.
    return point


def merge(recipes,weights):
    """Compose parameters before geometry; closure never exceeds one."""
    if len(recipes)==1 and recipes[0].get('relation'):
        import copy
        result=copy.deepcopy(recipes[0]);result['relation_weight']=result.get('relation_weight',1.)*weights[0]
        for spec in result.get('custom_rules',[]):spec['weight']=spec.get('weight',1.)*weights[0]
        return result
    result=dict(name='混合表情',family='mixed',eyes={},mouth={},mouth_targets=[],brows={},oral={})
    upper_motion_scales={};dental_sources=[]
    for recipe,weight in zip(recipes,weights):
        if weight<=0:continue
        if Rules.has_channels(recipe,'mouth','mouth_reference','mouth_targets','oral','jaw','tongue'):
            dental_sources.append(bool(recipe.get('dental_reference')))
        import copy
        for spec in recipe.get('custom_rules',[]):
            spec=copy.deepcopy(spec);spec['weight']=spec.get('weight',1)*weight
            result.setdefault('custom_rules',[]).append(spec)
        for key in ('mouth','brows'):
            if key=='mouth' and recipe.get('mouth_reference'):
                result['mouth_targets'].append(dict(reference=recipe['mouth_reference'],weight=weight))
                continue
            for part,value in recipe.get(key,{}).items():
                result[key][part]=np.asarray(result[key].get(part,np.zeros_like(value)))+np.asarray(value)*weight
        for target in recipe.get('mouth_targets',[]):
            result['mouth_targets'].append(dict(reference=target['reference'],weight=target['weight']*weight))
        for side,eye in recipe.get('eyes',{}).items():
            row=result['eyes'].setdefault(side,dict(upper=np.zeros((17,3)),lower=np.zeros((17,3)),closure=0.,blink=0.,lower_share=0.,smile=0.,flat=0.,lash_pitch=0.,lash_shape_preserve=0.))
            row['upper']+=np.array(eye['upper'])*weight;row['lower']+=np.array(eye['lower'])*weight
            row['lower_share']+=eye['lower_share']*eye['closure']*weight
            row['smile']+=eye['smile']*eye['closure']*weight
            row['flat']+=eye.get('flat',0.)*eye['closure']*weight
            row['lash_shape_preserve']+=eye.get('lash_shape_preserve',0.)*eye['closure']*weight
            row['closure']+=eye['closure']*weight;row['lash_pitch']+=eye.get('lash_pitch',0)*weight
            if eye.get('sclera_aperture_follow'):
                row['sclera_aperture_follow']=max(row.get('sclera_aperture_follow',0.),eye['sclera_aperture_follow'])
            if eye.get('open_motion'):
                motion=row.setdefault('open_motion',{})
                source_motion=eye['open_motion']
                scale=upper_motion_scales.setdefault(side,[0.,0.,False])
                scale[0]+=source_motion.get('upper_motion_scale',1.)*weight;scale[1]+=weight
                scale[2]|='upper_motion_scale' in source_motion
                for key,value in source_motion.items():
                    if key!='upper_motion_scale':motion[key]=motion.get(key,0.)+value*weight
            if 'blink' in eye:row['blink']+=eye['blink']*weight
            elif eye['closure']>=1-1e-6:row['blink']+=weight
        for part,pose in recipe.get('baked_oral_source',recipe.get('oral',{})).items():
            row=result['oral'].setdefault(part,dict(translation=np.zeros(3),euler=np.zeros(3)))
            row['translation']+=np.array(pose['translation'])*weight
            row['euler']+=np.array(Matrix(pose['rotation']).to_euler('XYZ'))*weight
        if recipe.get('tongue'):
            t=result.setdefault('tongue',dict(centerline=np.zeros((3,3)),width_gain=1.,protrusion=0.))
            if recipe['tongue'].get('support_lip')=='lower':t['support_lip']='lower'
            t['centerline']+=np.array(recipe['tongue']['centerline'])*weight
            t['width_gain']+=(recipe['tongue']['width_gain']-1)*weight
            if recipe['tongue'].get('shape_reference'):
                t.setdefault('reference_targets',[]).append(dict(reference=recipe['tongue']['shape_reference'],weight=weight))
            for target in recipe['tongue'].get('reference_targets',[]):
                t.setdefault('reference_targets',[]).append(dict(reference=target['reference'],weight=target['weight']*weight))
            rigid=recipe['tongue'].get('rigid_reference')
            if rigid:
                motion=t.setdefault('rigid_motion',dict(translation=np.zeros(3),euler=np.zeros(3)))
                motion['translation']+=np.asarray(rigid['translation'])*weight
                motion['euler']+=np.asarray(Matrix(rigid['rotation']).to_euler('XYZ'))*weight
            if recipe['tongue'].get('rigid_motion'):
                motion=t.setdefault('rigid_motion',dict(translation=np.zeros(3),euler=np.zeros(3)))
                for key in ('translation','euler'):motion[key]+=np.asarray(recipe['tongue']['rigid_motion'][key])*weight
            protrusion=recipe['tongue'].get('protrusion')
            if protrusion is None:protrusion=float(np.max(abs(np.asarray(recipe['tongue']['centerline'])[:,1]))>1e-5)
            t['protrusion']+=float(protrusion)*weight
        if 'jaw' in recipe:result['jaw']=np.array(result.get('jaw',np.zeros(3)))+np.array(recipe['jaw'])*weight
    for side,(total,weight,explicit) in upper_motion_scales.items():
        if explicit:result['eyes'][side]['open_motion']['upper_motion_scale']=total/weight
    if dental_sources and all(dental_sources):result['dental_reference']=True
    for row in result['eyes'].values():
        row['smile']=row['smile']/row['closure'] if row['closure']>1e-9 else 0.
        row['flat']=row['flat']/row['closure'] if row['closure']>1e-9 else 0.
        row['lash_shape_preserve']=row['lash_shape_preserve']/row['closure'] if row['closure']>1e-9 else 0.
        row['lower_share']=row['lower_share']/row['closure'] if row['closure']>1e-9 else .1
        row['closure']=min(row['closure'],1.)
        row['blink']=min(row['blink'],1.)
    if result.get('tongue'):result['tongue']['protrusion']=float(np.clip(result['tongue']['protrusion'],0.,1.))
    for row in result['oral'].values():
        from mathutils import Euler
        row['rotation']=np.array(Euler(row.pop('euler'),'XYZ').to_matrix()).tolist()
    return result


def solve(rig,recipe,profile,lower_lid_scale=1.):
    notify(rig,'准备表情规则与附属绑定')
    recipe=copy.deepcopy(recipe)
    styles=getattr(rig,'style_options',{})
    for eye in recipe.get('eyes',{}).values():
        if eye.get('smile',0.)>.5:
            eye['lash_shape_preserve']=float(styles.get('smile_preserve',eye.get('lash_shape_preserve',.85)))
    Custom.evaluate(rig,recipe)
    notify(rig,'计算眼缘、嘴唇与眉毛目标')
    lash_recipe=dict(recipe,eyes={s:e for s,e in recipe.get('eyes',{}).items() if int(s) not in getattr(rig,'eye_anatomy',{})})
    points=rig.points;delta=np.zeros_like(points);poses={};active={};upper_motion=set();warnings=[];closure_arcs={}
    closed_rim_vertices=0
    rig.lash_pose_curves={}
    rig.inner_lid_floors={};rig.lash_open_transports={};rig.lash_final_transports={};rig.lash_fold_transforms={}
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text)
        if side not in rig.rings:continue
        globe=side in getattr(rig,'eye_anatomy',{})
        width=rig.widths['EYE',side];ring=rig.rings[side]
        height=getattr(rig,'heights',{}).get(('EYE',side),ring.frame.height)
        gain=height/max(width*profile['neutral_eyes'][side_text]['width_height_ratio'],1e-9)
        closure=eye['closure'];smile=float(np.clip(eye['smile'],0,1))
        lid_scale=float(np.clip(lower_lid_scale,0,1))
        # Style chooses a feasible seam, never disables a closure boundary.
        # A spherical-eye smile recruits the lower lid and cheek. The flat-eye
        # travel cap cannot lift a deeply bowed anatomical rim into an arch.
        lower_limit=height*(LOWER_LID_MAX_RISE+(.20*smile if globe else 0.))
        middle_extra=height*LOWER_LID_MIDDLE_EXTRA*smile
        clouds=[]
        for branch in (False,True):
            cloud=np.array([rig.curve('EYE',side,branch,t) for t in np.linspace(0,1,65)])
            order=np.argsort(cloud[:,0]);clouds.append(cloud[order])
        corner_moves=np.array([(sampled(eye['upper'],end)+sampled(eye['lower'],end))*.5*width for end in (0,1)])
        corner_moves[:,2]*=gain
        corner_moves[:,1]=0.
        corner_moves[:,2]=np.minimum(corner_moves[:,2],lower_limit)
        # A shared canthus cannot simultaneously move upper down and lower up
        # if translated vertically. Keep its height during closure.
        directional=closure>1e-6 and not recipe.get('guide_preview')
        if directional:corner_moves[:,2]=0.
        if directional and globe:corner_moves[:]=0.
        
        corners=np.array([(rig.curve('EYE',side,True,end)+rig.curve('EYE',side,False,end))*.5 for end in (0,1)])
        inner_end=int(np.argmin(abs(corners[:,0]-rig.info['plane'])))
        low=clouds[0];left,right=low[0,0],low[-1,0]
        # The inner corner may descend to the horizontal lower-lid body.
        # Do not use the minimum across its steep tail or pin its old height.
        lower_ids=sorted({i for i,u,upper in rig.rows['EYE',side] if not upper or u<1e-7 or u>1-1e-7})
        original_lower=rig.original_points[lower_ids]
        inner_floor=B.lower_body_height(original_lower,rig.info['plane'])
        rig.inner_lid_floors[side]=inner_floor
        if directional and not globe:
            target=max(inner_floor+lower_limit*.65,corners[inner_end,2]-height*.45)
            corner_moves[inner_end,2]=min(target-corners[inner_end,2],0.)
        # Fit one whole closure arc in the edited target's position/tilt frame.
        # Do not copy the lower rim's local polygon or sampling irregularities.
        flat=float(np.clip(eye.get('flat',0.),0,1))
        # The original canthi define the chord, including character-specific
        # tilt. Curvature is measured relative to that chord, never flattened
        # by replacing the endpoints with a clamped horizontal baseline.
        ts=np.linspace(0,1,129)
        ends=corners+corner_moves
        seam_controls,peak,arc_report=character_arc(clouds[1],corners,ends,height,smile,flat)
        if smile>.5 and flat<.5:
            chord=np.linspace(seam_controls[0,2],seam_controls[-1,2],4)
            handles=seam_controls[1:3,2]-chord[1:3]
            preserve=float(np.clip(eye.get('lash_shape_preserve',.85),0,1))
            seam_controls[1:3,2]=chord[1:3]+handles*preserve+float(np.mean(handles))*(1-preserve)
            seam_controls[:,2]=chord+(seam_controls[:,2]-chord)*float(np.clip(styles.get('smile_arc',1.),.15,1.))
        depth=np.column_stack((ts,np.interp(left+(right-left)*ts,low[:,0],low[:,1]),np.zeros(len(ts))))
        seam_controls[:,1]=B.fit_bezier(depth,ts)[:,1]
        if closure>=1-1e-6:
            correction=np.array([(Custom.offset(rig,'EYE_UPPER',side,t)+Custom.offset(rig,'EYE_LOWER',side,t))*.5 for t in ts])
            seam_controls+=B.fit_bezier(correction,ts)
        closure_arcs[str(side)]=arc_report
        # Direction and lower travel bound the style fit. A steep canthus may
        # turn at its pivot, but never below the horizontal lower-lid floor.
        cap=np.interp(left+(right-left)*ts,low[:,0],low[:,2])+lower_limit+middle_extra*apex_weight(ts,peak)
        seam_low=np.interp(left+(right-left)*ts,low[:,0],low[:,2])
        seam_high=np.minimum(cap,np.interp(left+(right-left)*ts,clouds[1][:,0],clouds[1][:,2]))
        if globe and directional:
            # Blink follows the lower rim; a smile meets above the canthus
            # chord. Merely adding a small lift to the lower bowl leaves both
            # expressions concave and visually indistinguishable.
            chord=seam_low[0]*(1-ts)+seam_low[-1]*ts
            smile_arc=float(np.clip(styles.get('smile_arc',1.),.15,1.))
            smile_z=chord+height*.18*smile_arc*4*ts*(1-ts)
            native=np.column_stack((left+(right-left)*ts,
                np.interp(left+(right-left)*ts,low[:,0],low[:,1]),
                seam_low*(1-smile)+smile_z*smile))
            seam_controls=B.fit_bezier(native,ts)
            arc_report['method']='globe_smile_arch' if smile>.5 else 'globe_lower_rim_closure'
            arc_report['lower_lid_max_rise_ratio']=lower_limit/height
        styled=(smile>.5 or flat>.5) and not globe
        if directional:
            if closure>=1-1e-6 and not globe:
                # Only the steep canthus portion rotates down. The horizontal
                # lower rim still rises by at most its original allowance.
                line=rig.guide_lines['EYE',side][False]
                for turn,end in Lashes.lower_turns(line):
                    pivot=line.sample(turn);edge=line.sample(end)
                    x=left+(right-left)*ts
                    selected=(x>=min(pivot[0],edge[0])-1e-9)&(x<=max(pivot[0],edge[0])+1e-9)
                    seam_low[selected]=np.minimum(seam_low[selected],pivot[2])
                distance=ts if inner_end==0 else 1-ts
                inner=distance<=.22
                q=np.clip(distance/.22,0,1);relax=1-q**3*(10-15*q+6*q*q)
                seam_low=np.minimum(seam_low,seam_low*(1-relax)+inner_floor*relax)
                seam_low[inner]=np.maximum(seam_low[inner],inner_floor)
            seam_high=np.maximum(seam_high,seam_low)
            if styled:
                seam_controls,conflicts,style=B.styled_closure(seam_controls,ts,seam_low,seam_high,flat=flat>.5,preference=lid_scale)
                arc_report.update(style)
            else:
                seam_controls[:,2]-=(1-lid_scale)*float(np.mean(seam_high-seam_low))
                seam_controls,conflicts=B.bounded_height(seam_controls,ts,seam_low,seam_high)
            arc_report.update(direction_priority=True,curvature_bound_conflicts=conflicts)
        if globe and directional:
            fitted=B.bezier(seam_controls,ts)[:,2]
            bow=fitted-(fitted[0]*(1-ts)+fitted[-1]*ts)
            index=int(np.argmax(abs(bow)))
            arc_report.update(peak=float(ts[index]),height_ratio=float(abs(bow[index])/height),
                              chord_bow_ratio=float(bow[len(ts)//2]/height))
        def reference_lid(u,upper,side=side,eye=eye,width=width,gain=gain,closure=closure,corner_moves=corner_moves,corners=corners,inner_end=inner_end,lower_limit=lower_limit,middle_extra=middle_extra,left=left,right=right,seam_controls=seam_controls,peak=peak,directional=directional,seam_low=seam_low,seam_high=seam_high,ts=ts,styled=styled):
            anchor=rig.curve('EYE',side,upper,u)
            movement=sampled(eye['upper' if upper else 'lower'],u)*width;movement[2]*=gain
            movement[1]=0.
            x=anchor[0]
            t=float(np.clip((x-left)/max(right-left,1e-9),0,1))
            arch=float(apex_weight(t,peak))
            rise_limit=lower_limit+middle_extra*arch
            weights=eye_corner_weights(t,inner_end)
            closed=B.bezier(seam_controls,t)
            if directional and not styled:closed[2]=np.clip(closed[2],np.interp(t,ts,seam_low),np.interp(t,ts,seam_high))
            # Ordinary closure forms a shallow bowl; smile closure forms an
            # arch. Upper and lower lids share the entire seam and both ends.
            contact=float(np.clip((closure-.8)/.2,0,1));contact=contact*contact*(3-2*contact)
            partial=anchor+movement
            for end,weight in enumerate(weights):
                if weight<=0:continue
                common=corners[end];common_move=corner_moves[end]
                own_move=sampled(eye['upper' if upper else 'lower'],end)*width;own_move[2]*=gain
                own_move[1]=0.
                partial+=(common+common_move-rig.curve('EYE',side,upper,end)-own_move)*weight
            rise=partial[2]-anchor[2]
            partial[2]+=(lower_rise(rise,rise_limit)-rise)*(max(weights) if upper else 1.)
            result=partial*(1-contact)+closed*contact
            if closure<1-1e-6:result+=Custom.offset(rig,'EYE_UPPER' if upper else 'EYE_LOWER',side,u)
            if directional:result[2]=min(result[2],anchor[2]) if upper else max(result[2],anchor[2])
            return result
        # Every eye action uses one cubic per branch, including partially open
        # expressions. Their handles retain the reference's overall intent.
        parameters=np.linspace(0,1,65);curves={}
        branch_active={upper:bool(recipe.get('guide_preview') or np.max(np.abs(eye['upper' if upper else 'lower']))>1e-10 or eye.get('blink',0)>0) for upper in (False,True)}
        for upper in (False,True):branch_active[upper]|=any(k==('EYE_UPPER' if upper else 'EYE_LOWER') and s==side for k,s,key in rig.custom_offsets)
        branch_active[True]|=any(k in ('LASH_LINE','LASH','CREASE') and s==side for k,s,key in rig.custom_offsets)
        if eye.get('open_motion'):
            branch_active[True]=True;branch_active[False]=eye['open_motion'].get('lower_fixed',0.)<1-1e-8
        if branch_active[True]:upper_motion.add(side)
        for upper in (False,True):
            curves[upper]=B.fit_bezier([reference_lid(u,upper) for u in parameters],parameters)
        # The two branches share endpoints. Correct handles as a whole rather
        # than clipping samples; an inactive upper/lower branch stays at rest.
        for end in (0,-1):
            common=(curves[False][end]+curves[True][end])*.5
            for controls in curves.values():controls[end]=common
        lower_rest=np.array([rig.curve('EYE',side,False,u) for u in parameters])
        lower_t=np.clip((lower_rest[:,0]-left)/max(right-left,1e-9),0.,1.)
        cap=lower_rest[:,2]+lower_limit+middle_extra*apex_weight(lower_t,peak)
        branch_bounds={}
        if directional:
            for upper in (False,True):
                rest=np.array([rig.curve('EYE',side,upper,u) for u in parameters])
                other=np.interp(rest[:,0],clouds[not upper][:,0],clouds[not upper][:,2])
                lower=np.minimum(other,rest[:,2]) if upper else rest[:,2]
                higher=rest[:,2] if upper else np.maximum(rest[:,2],np.minimum(other,cap))
                curves[upper],conflicts=B.bounded_height(curves[upper],parameters,lower,higher)
                branch_bounds[upper]=(lower,higher)
                arc_report['curvature_bound_conflicts']+=conflicts
        else:
            for end,index in ((0,0),(-1,-1)):
                shift=max(float(curves[False][end,2]-cap[index]),0.)
                for controls in curves.values():controls[end,2]-=shift
            shape=3*parameters[1:-1]*(1-parameters[1:-1])
            excess=B.bezier(curves[False],parameters[1:-1])[:,2]-cap[1:-1]
            curves[False][1:3,2]-=max(float(np.max(excess/shape)),0.)
        def lid(u,upper,side=side,closure=closure,curves=curves,seam_controls=seam_controls,left=left,right=right,branch_active=branch_active,preview=bool(recipe.get('guide_preview')),directional=directional,seam_low=seam_low,seam_high=seam_high,ts=ts,branch_bounds=branch_bounds,parameters=parameters,styled=styled):
            anchor=rig.curve('EYE',side,upper,u)
            if preview or not branch_active[bool(upper)]:return anchor
            if closure>=1-1e-6:
                t=float(np.clip((anchor[0]-left)/max(right-left,1e-9),0,1))
                result=B.bezier(seam_controls,t)
                if directional and not styled:result[2]=np.clip(result[2],np.interp(t,ts,seam_low),np.interp(t,ts,seam_high))
            else:
                result=B.bezier(curves[bool(upper)],u)
                if directional:
                    lo,hi=branch_bounds[bool(upper)];result[2]=np.clip(result[2],np.interp(u,parameters,lo),np.interp(u,parameters,hi))
            return result
        if eye.get('open_motion') and closure<1-1e-6:
            explicit_lid=open_lid_rule(rig,side,eye['open_motion'])
            if closure<=1e-8 and not np.any(eye['upper']) and not np.any(eye['lower']):lid=explicit_lid
            else:
                def combined(u,upper,base_lid=lid,explicit_lid=explicit_lid,side=side,closure=closure):
                    rest=rig.curve('EYE',side,upper,u)
                    return base_lid(u,upper)+(explicit_lid(u,upper)-rest)*(1-closure)
                combined.open_motion=eye['open_motion'];lid=combined
        active[side]=lid
        for i,u,upper in rig.rows['EYE',side]:delta[i]=lid(u,upper)-points[i]
        if closure>=1-1e-6:
            joined=B.closed_rim(rig.rows['EYE',side],points+delta,side)
            for i,point in joined.items():delta[i]=point-points[i]
            closed_rim_vertices+=len(joined)
        for i,labels in enumerate(rig.members):
            if i in rig.brows or 0 in labels or 2 not in labels:continue
            if (1 if points[i,0]>=rig.info['plane'] else -1)!=side:continue
            u,upper=ring.locate(Vector(points[i]))
            upper=rig.lash_upper.get(i,upper)
            # Project on the corrected curve once, retaining the mesh branch.
            # X-only lookup collapses a near-vertical canthus to one position.
            if hasattr(rig,'parameter'):u=rig.parameter('EYE',side,upper,points[i])
            anchor=rig.neutral('EYE',side,upper,u)
            delta[i]=lid(u,upper)-anchor
            if upper and not globe and side in upper_motion and hasattr(rig,'lash_position') and i not in rig.strands:
                posed=rig.lash_position(side,points[i],lid,closure,eye.get('lash_shape_preserve',0.),eye.get('flat',0.))
                if posed is not None:delta[i]=posed-points[i]
        for s,kind,ids,entry in rig.accessories:
            if s!=side or kind!='CREASE':continue
            for i in ids:
                u=rig.parameter('EYE',side,True,points[i]) if hasattr(rig,'parameter') else ring.locate(Vector(points[i]),True)[0]
                delta[i]=lid(u,True)-rig.curve('EYE',side,True,u)
                # The edited crease's own offset remains effective.
                delta[i]+=B.edit_offset(entry,points[i])
    delta,open_rim_quality=Lashes.prepare_open_rim(rig,delta,lash_recipe,active)
    # Solve eyelid skin locally, before combining independent mouth/brow work.
    # The aperture and its attached accessories retain their exact targets.
    eye_raw=delta.copy()
    notify(rig,'平滑眼周脸皮')
    eye_delta=rig.eye_skin.deform(eye_raw,active)
    eye_delta=Anatomy.skin_motion(rig,eye_raw,eye_delta,recipe)
    for side_text,coefficients in recipe.get('brows',{}).items():
        side=int(side_text);width=rig.widths.get(('EYE',side))
        if not width:continue
        all_ids=sorted({i for s,kind,ids,entry in rig.accessories if s==side and kind=='BROW' for i in ids})
        center=points[all_ids,0].mean() if all_ids else 0.
        for s,kind,ids,entry in rig.accessories:
            if s!=side or kind!='BROW' or not ids:continue
            # One centre for every overlapping strip of the same eyebrow.
            # Per-strip centres separated coincident vertices during rotation.
            for i in ids:
                x=(points[i,0]-center)/width;delta[i]=np.polynomial.polynomial.polyval(x,np.array(coefficients))*width
                delta[i]+=B.edit_offset(entry,points[i])
    mouth=rig.info['mouth'];width=rig.widths.get(('LIP',0),0)
    if (recipe.get('mouth') or recipe.get('mouth_targets')) and mouth:
        def lip(u,upper):
            anchor=rig.curve('LIP',0,upper,u);result=anchor.copy()
            if recipe.get('mouth'):result+=sampled(recipe['mouth']['upper' if upper else 'lower'],u)*width
            for target in recipe.get('mouth_targets',[]):
                result+=(mouth_outline(rig,target['reference'],u,upper)-anchor)*target['weight']
            result+=Custom.offset(rig,'LIP_UPPER' if upper else 'LIP_LOWER',0,u)
            return result
        for i,u,upper in rig.rows['LIP',0]:
            hit=lip(u,upper);opposite=lip(u,not upper)
            if (hit[2]-opposite[2])*(1 if upper else -1)<0:hit[2]=(hit[2]+opposite[2])/2
            delta[i]=hit-points[i]
    # Resolve the exit before skin/teeth/cavity follow the mouth. A squeezed
    # throat can request a little lip motion without crushing the whole tongue.
    delta,tongue_quality=Tongue.deform(rig,delta,recipe)
    delta=Custom.apply_controls(rig,delta)
    delta=Q.lip_surface_motion(rig,delta,recipe)
    if Lips.closed_reference(recipe) and ('LIP',0) in rig.rows:
        delta=Lips.closed_motion(rig,delta)
    notify(rig,'求解面部位移场')
    skin=Lips.deform(rig,delta-eye_raw,recipe)
    # Transfer only the mouth field. A second Face layer may own the other
    # eye's controls, so copying the combined pose would erase that eye.
    mouth_followers=getattr(rig,'mouth_followers',None)
    if mouth_followers is not None and Lips.active(rig,recipe):
        skin=mouth_followers.apply(skin)
    delta=skin+eye_delta
    delta,lip_quality=Q.lower_lip_depth(rig,delta,recipe)
    delta,depth_profiles,eye_quality=Q.finalize_skin(rig,delta,recipe)
    quality=dict(eye_quality,unresolved=0,max_correction=0.,motion_scale=1.,eye_layers_shifted=0,closure_arcs=closure_arcs)
    quality.update(tongue_quality)
    quality.update(lip_quality)
    quality.update(open_rim_quality)
    quality['closed_rim_vertices']=closed_rim_vertices
    notify(rig,'眼缘深度传递至睫毛带')
    Lashes.update_open_depth(rig,depth_profiles)
    # Skin and lashes share the same local depth interpolation. An unchanged
    # lower rim must not move because a whole-eye envelope overshoots it.
    for side,lid in list(active.items()):
        def depth(x,upper,side=side):
            return float(depth_profiles[side,bool(upper)].sample(x))
        def wrapped(u,upper,lid=lid,depth=depth):
            point=lid(u,upper).copy();point[1]=depth(point[0],upper)
            return point
        wrapped.depth=depth
        active[side]=wrapped
        for i,labels in enumerate(rig.members):
            if 2 not in labels or 0 in labels or i in rig.brows or i in rig.creases or i in rig.strands:continue
            if (1 if points[i,0]>=rig.info['plane'] else -1)!=side:continue
            _,upper=rig.rings[side].locate(Vector(points[i]))
            upper=rig.lash_upper.get(i,upper)
            u=rig.parameter('EYE',side,upper,points[i])
            delta[i]=wrapped(u,upper)-rig.neutral('EYE',side,upper,u)
            if upper and side not in getattr(rig,'eye_anatomy',{}) and side in upper_motion:
                eye=recipe['eyes'][str(side)]
                shared=rig.lash_open_transports.get(side)
                posed=shared(points[i])[0] if shared else rig.lash_position(side,points[i],wrapped,eye['closure'],eye.get('lash_shape_preserve',0.),eye.get('flat',0.))
                if posed is not None:delta[i]=posed-points[i]
    eye_shape,eye_stack_quality=Q.closed_eye_stack(rig,delta,recipe)
    quality.update(eye_stack_quality)
    notify(rig,'绑定眉毛与睫毛')
    delta=Q.accessory_depth(rig,delta,lash_recipe)
    delta,lower_corner_quality=Lashes.follow_lower_rim(rig,delta,lash_recipe)
    quality.update(lower_corner_quality)
    delta,style_quality=Lashes.style_band(rig,delta,lash_recipe)
    quality.update(style_quality)
    notify(rig,'睫毛片覆盖闭合线')
    delta,coverage_quality=Lashes.cover_closed_seam(rig,delta,lash_recipe)
    quality.update(coverage_quality)
    delta,fold_quality=Lashes.fold_vertical_sections(rig,delta,lash_recipe)
    quality.update(fold_quality)
    delta,sweep_quality=Lashes.finish_upper_sweep(rig,delta,lash_recipe,active)
    quality.update(sweep_quality)
    delta,wing_quality=Lashes.lower_owned_upper_sections(rig,delta,lash_recipe)
    quality.update(wing_quality)
    
    delta,order_quality=Lashes.cover_lower_band(rig,delta,lash_recipe)
    quality.update(order_quality)
    notify(rig,'单根睫毛随睫毛带运动')
    delta,lash_quality=Lashes.deform(rig,delta,lash_recipe,active)
    quality.update(lash_quality)
    notify(rig,'双眼皮与上眼皮部件跟随睫毛曲线')
    delta,crease_quality=Lashes.follow_creases(rig,delta,lash_recipe,active)
    quality.update(crease_quality)
    notify(rig,'整片睫毛贴合')
    delta,band_quality=Lashes.conform_band(rig,delta,lash_recipe)
    quality.update(band_quality)
    notify(rig,'整片睫毛向外避让脸皮')
    delta,contact_quality=Lashes.skin_behind_band(rig,delta,lash_recipe)
    quality.update(contact_quality)
    delta,order_quality=Lashes.finish_closed_order(rig,delta,lash_recipe)
    quality.update(order_quality)
    delta,legacy_lash_quality=Lashes.follow_legacy_closed_strands(rig,delta,lash_recipe,active)
    quality.update(legacy_lash_quality)
    delta,joint_lash_quality=Lashes.fit_legacy_contact_layers(rig,delta,lash_recipe)
    quality.update(joint_lash_quality)
    delta,attachment_quality=Anatomy.follow_attachments(rig,delta,recipe)
    quality.update(attachment_quality)
    quality.update(Lashes.audit_closed_band(rig,delta,lash_recipe))
    quality.update(Lashes.audit_attachment(rig,delta,lash_recipe))
    quality.update(Lashes.audit_connections(rig,delta))
    # Contact is final: no style/fold pass may undo either depth boundary.
    notify(rig,'舌头外表面接触')
    delta,exterior_quality=Tongue.keep_exterior(rig,delta,recipe)
    quality.update(exterior_quality)
    delta=Tongue.support_lower(rig,delta,recipe)
    # Dental shapes account for their bone; cavity shapes follow Face directly.
    # Shared skin rim vertices retain their face motion on the skin copy.
    for i,labels in enumerate(rig.members):
        if (8 in labels or 9 in labels) and 0 not in labels and 12 not in labels:delta[i]=0
    notify(rig,'牙齿随唇约束')
    quality.update(Q.fit_upper_jaw(rig,delta,recipe))
    quality.update(Q.fit_lower_jaw(rig,delta,recipe))
    rig.last_teeth_deformation,teeth_quality=Q.teeth_deformation(rig,delta,recipe)
    quality.update(teeth_quality)
    quality.update(Q.close_dental_contact(rig,recipe))
    quality.update(Q.tongue_dental_space(rig,delta,recipe))
    notify(rig,'口腔连续变形')
    cavity,cavity_quality=Cavity.deform(rig,delta,recipe)
    rig.last_oral_deformation={**rig.last_teeth_deformation,**cavity,'_eyes':eye_shape}
    quality.update(cavity_quality)
    notify(rig,'核对最终形变')
    if hasattr(rig,'triangles'):
        minimum,rest=Q.minimum_areas(points,delta,rig.triangles)
        bad=int(np.sum((rest>1e-14)&(minimum<rest*.005)))
        # Remaining conflicts are reported after local repair. Do not shrink
        # every eye/mouth action to hide one incompatible triangle.
        quality.update(limited_triangles=quality['face_fold_candidates'],unresolved=bad+quality['eye_depth_limited_vertices']+quality['eye_immovable_overlaps']+quality['cavity_depth_limited_vertices']+quality['cavity_unresolved_overlaps']+quality['cavity_ambiguous_rims']+quality['lash_exposure_conflicts']+quality['lash_band_depth_conflicts']+quality['lash_skin_depth_conflicts']+quality['tongue_exit_conflicts']+quality['tongue_exterior_conflicts'],deformation='local_smooth_skin_with_fixed_contour_fold_repair')
    from . import procedural_contacts as Contacts
    delta,rig.last_oral_deformation,oral_quality=Contacts.finish(rig,delta,recipe,rig.last_oral_deformation)
    quality.update(oral_quality)
    if 'jaw' in recipe and not any(recipe.get(k) for k in ('eyes','mouth','mouth_targets','brows','oral','tongue','custom_rules')):
        # A contour-only jaw key leaves the complete closed mouth and oral
        # interior at Basis, including incidental contact/neutral corrections.
        delta=np.zeros_like(delta)
        rig.last_oral_deformation={kind:np.zeros_like(value) for kind,value in rig.last_oral_deformation.items()}
    delta=Lips.jaw_contour(rig,delta,recipe)
    followers=getattr(rig,'face_followers',None)
    if followers is not None:
        delta=followers.apply(delta)
        quality['face_follower_vertices']=len(followers.vertices)
    # The crease-follow pass can move Face-labelled strips after the earlier
    # skin repair. Report the finished mesh too, not only that earlier stage.
    final_area,rest_area=Q.minimum_areas(points,delta,rig.field.triangles)
    quality['final_face_fold_unresolved']=int(np.sum((rest_area>1e-14)&(final_area<rest_area*.005)))
    quality['unresolved']+=oral_quality['oral_face_unresolved']+oral_quality['tongue_cavity_unresolved']+oral_quality['tongue_teeth_unresolved']
    quality['auxiliary_shape_keys']=0
    quality['custom_rules']=rig.custom_rule_report
    notify(rig,'保存变形后曲线')
    rig.last_expression_curves=Custom.capture_curves(rig,delta)
    quality['unresolved']+=quality.get('lash_seam_coverage_conflicts',0)
    quality['unresolved']+=quality.get('lash_fold_contact_conflicts',0)
    quality['unresolved']+=quality.get('lash_final_seam_conflicts',0)+quality.get('eye_stack_limited',0)
    quality['unresolved']+=quality.get('lower_lid_order_conflicts',0)
    quality['unresolved']+=quality.get('lower_lash_final_depth_conflicts',0)+quality.get('lower_lash_final_exposed_vertices',0)
    quality['unresolved']+=quality.get('lash_attachment_conflicts',0)+quality.get('lash_path_contact_conflicts',0)
    quality['unresolved']+=quality.get('lash_seam_connection_conflicts',0)
    quality['unresolved']+=sum(row.get('style_bound_conflicts',0) for row in closure_arcs.values())
    # The solver works on a private recipe. Export its fitted jaw poses along
    # with the local dental shapes, so baking/drivers use the same transform
    # that the contact solver checked.
    rig.last_oral_poses=copy.deepcopy(recipe.get('oral',{}))
    return delta,quality
