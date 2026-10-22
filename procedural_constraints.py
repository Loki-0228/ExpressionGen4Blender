"""Shared geometry constraints for every procedural recipe and combination."""
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from . import procedural_surfaces as Surfaces
from . import procedural_binding as Binding
from .generation_progress import notify,count
from . import procedural_lips as Lips
from . import procedural_anatomy as Anatomy


def minimum_areas(points,delta,triangles):
    """Exact minimum signed triangle area over a relative key's entire range."""
    ids=np.asarray(triangles,dtype=np.int32).reshape((-1,3))
    p=points[ids];d=delta[ids]
    a,b=p[:,1]-p[:,0],p[:,2]-p[:,0]
    n=np.cross(a,b);area=np.linalg.norm(n,axis=1);n/=np.maximum(area[:,None],1e-25)
    da,db=d[:,1]-d[:,0],d[:,2]-d[:,0]
    quadratic=np.sum(np.cross(da,db)*n,axis=1)
    linear=np.sum((np.cross(da,b)+np.cross(a,db))*n,axis=1)
    t=np.ones(len(ids));convex=quadratic>1e-25
    t[convex]=np.clip(-linear[convex]/(2*quadratic[convex]),0,1)
    return area+linear*t+quadratic*t*t,area


def limit_motion(points,delta,triangles,margin=.005):
    """Reduce a coherent motion instead of pushing individual thin triangles."""
    minimum,rest=minimum_areas(points,delta,triangles)
    valid=rest>1e-14
    bad=valid & (minimum<rest*margin)
    if not np.any(bad):return delta,1.,0
    low,high=0.,1.
    for _ in range(30):
        middle=(low+high)/2
        area,_=minimum_areas(points,delta*middle,triangles)
        if np.any(valid & (area<rest*margin)):high=middle
        else:low=middle
    return delta*low,low,int(np.sum(bad))


def eye_surface(rig,side):
    """The target's unchanged eye stack is the obstacle, never a movable spacer."""
    if not hasattr(rig,'eye_surfaces'):rig.eye_surfaces={}
    if side not in rig.eye_surfaces:
        faces=[f for f,label in zip(rig.info['faces'],rig.info['labels']) if label in (3,5,7)
               and (1 if np.mean(rig.original_points[f,0])>=rig.info['plane'] else -1)==side]
        tree=BVHTree.FromPolygons([Vector(p) for p in rig.original_points],faces) if faces else None
        extent=max(float(np.ptp(rig.original_points,axis=0).max()),1e-9)
        rig.eye_surfaces[side]=(tree,float(rig.original_points[:,1].min()-extent*2),extent*5)
    return rig.eye_surfaces[side]


def surface_y(surface,point):
    tree,origin,length=surface
    if tree is None:return None
    hit,_,_,_=tree.ray_cast(Vector((point[0],origin,point[2])),Vector((0,1,0)),length)
    return float(hit.y) if hit is not None else None


def facial_eye_depth(rig,side,point):
    """Bridge the original skin rims locally across the aperture in X/Z."""
    if not hasattr(rig,'eye_facial_profiles'):rig.eye_facial_profiles={}
    if side not in rig.eye_facial_profiles:
        profiles={}
        for up in (False,True):
            ids=sorted({i for i,u,upper in rig.rows['EYE',side] if bool(upper)==up or u<1e-7 or u>1-1e-7})
            x,inverse=np.unique(rig.points[ids,0],return_inverse=True)
            values=np.column_stack([np.bincount(inverse,rig.points[ids,k])/np.bincount(inverse) for k in (1,2)])
            profiles[up]=(x,values)
        rig.eye_facial_profiles[side]=profiles
    bounds=[]
    for up in (False,True):
        x,values=rig.eye_facial_profiles[side][up]
        bounds.append([float(np.interp(point[0],x,values[:,k])) for k in (0,1)])
    low,high=np.asarray(bounds)
    t=float(np.clip((point[2]-low[1])/max(high[1]-low[1],1e-12),0,1))
    return float(low[0]*(1-t)+high[0]*t)


def join_closed_depth(rig,delta,correction,recipe,contacts):
    """Keep both closed rims on the same front envelope after depth changes."""
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text)
        if side not in rig.rings or eye['closure']<1-1e-6:continue
        rows=rig.rows['EYE',side]
        for _ in range(2):
            posed=rig.points+delta+correction;clouds={}
            for upper in (False,True):
                ids=sorted({i for i,u,up in rows if bool(up)==upper or u<1e-7 or u>1-1e-7})
                cloud=posed[ids];clouds[upper]=cloud[np.argsort(cloud[:,0])]
            for i,u,upper in rows:
                other=clouds[not bool(upper)]
                bound=float(np.interp(posed[i,0],other[:,0],other[:,1]))
                if bound<posed[i,1]-1e-12:
                    correction[i,1]+=bound-posed[i,1];contacts.add(i)


def wrap_eye_motion(rig,delta,recipe):
    """Keep the facial envelope; eye layers handle their own occlusion later.

    Per-triangle outward pushes against a static eyeball made neighbouring
    lower-rim depths alternate. The ordered eye-layer solve now has the
    authority to retreat, so those pushes must not reshape the lid first.
    """
    retracted=set()
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text)
        if side not in rig.eye_skin.regions:continue
        if side in getattr(rig,'eye_anatomy',{}):continue
        
        ids=sorted(rig.eye_skin.regions[side]-rig.creases)
        envelope=np.array([min(rig.points[i,1],facial_eye_depth(rig,side,rig.points[i]+delta[i])) for i in ids])
        retracted.update(i for i,floor in zip(ids,envelope) if rig.points[i,1]+delta[i,1]<floor-rig.info['width']*1e-8)
        delta[ids,1]=np.maximum(delta[ids,1],envelope-rig.points[ids,1])
    for i,labels in enumerate(rig.members):
        if set(labels)&{3,5,7} and 0 not in labels:delta[i]=0
    delta,globe_report=Anatomy.wrap(rig,delta,recipe)
    return delta,dict(corrected=0,eye_path_samples=16,eye_depth_limited_vertices=0,
                      eye_local_profile_retractions=len(retracted),eye_immovable_overlaps=0,**globe_report)


def closed_eye_stack(rig,delta,recipe):
    """Resolve Face occlusion in highlight, iris, sclera order on every eye key.

    Each layer receives a uniform depth translation. Deeper layers retreat
    at least as far as the previous layer, so their original separation and
    shape survive both the endpoint and linear shape-key playback.
    """
    shape=np.zeros_like(delta);report=dict(eye_stack_retraction={},eye_stack_limited=0,
        eye_layer_retraction={},eye_layer_required={},eye_layer_order=['highlight','iris','sclera'])
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text)
        if side not in rig.eye_skin.regions:continue
        if side in getattr(rig,'eye_anatomy',{}):continue
        region=rig.eye_skin.regions[side]-rig.creases
        skin=[list(t) for t in rig.field.triangles if set(t)&region and not set(t)<=rig.creases]
        if not skin or np.max(np.abs(delta[np.asarray(skin)]))<1e-12:continue
        skin=np.asarray(skin);previous=0.;shifts={};requirements={}
        width=rig.widths['EYE',side];limit=width*(.24 if eye.get('closure',0.)>=1-1e-6 else .35)
        for label,name in ((5,'highlight'),(3,'iris'),(7,'sclera')):
            triangles=[list(t) for t,f in rig.mesh_triangles if rig.info['labels'][f]==label
                       and (1 if rig.original_points[list(t),0].mean()>=rig.info['plane'] else -1)==side]
            if not triangles:continue
            ids=sorted({i for t in triangles for i in t});freedom=np.zeros(len(delta));freedom[ids]=1.
            baseline,_=Surfaces.depth_bounds(rig.original_points,triangles,rig.points[skin],freedom,front=False,coherent=True)
            required=previous
            for sample,t in enumerate(np.linspace(1/16,1,16),1):
                notify(rig,'眼层依次避让：'+{'highlight':'高光','iris':'瞳孔','sclera':'眼白'}[name],sample,16)
                bound,_=Surfaces.depth_bounds(rig.original_points,triangles,(rig.points+delta*t)[skin],freedom,front=False,coherent=True)
                required=max(required,float(np.max(np.maximum(bound-baseline,0.)))/t)
            shift=min(required,limit);shape[ids,1]=shift;previous=shift
            shifts[name]=shift;requirements[name]=required
            report['eye_stack_limited']+=int(required>limit+width*1e-7)
        report['eye_stack_retraction'][side_text]=previous
        report['eye_layer_retraction'][side_text]=shifts
        report['eye_layer_required'][side_text]=requirements
    rig.eye_stack_shape=shape
    return shape,report


def smooth_eye_depth(rig,delta,recipe):
    """Share local depth profiles without pulling stationary rims forward."""
    profiles={};raw=np.zeros_like(delta);pins=set();sides=[]
    posed=rig.points+delta
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text)
        if side not in rig.rings:continue
        rows=rig.rows['EYE',side]
        groups=[(False,True)] if eye['closure']>=1-1e-6 else [(False,),(True,)]
        for group in groups:
            ids=sorted({i for i,u,up in rows if bool(up) in group or u<1e-7 or u>1-1e-7})
            x,inverse=np.unique(posed[ids,0],return_inverse=True)
            values=np.full(len(x),np.inf);np.minimum.at(values,inverse,posed[ids,1])
            curve=Binding.DepthCurve(x,values)
            for upper in group:profiles[side,upper]=curve
        for i,u,upper in rows:
            depth=float(profiles[side,bool(upper)].sample(posed[i,0]))
            raw[i,1]=min(depth-posed[i,1],0.);pins.add(i)
        sides.append(side)
    if sides and np.any(raw):delta=delta+rig.eye_skin.depth_correction(raw,pins,sides)
    return delta,profiles


def finalize_skin(rig,delta,recipe):
    """Alternate contact and local fold repair before placing accessories.

    Contours remain exact. Fold repair preserves eye depth; free lip-collar
    vertices may also move in Y. No eye-layer clearance distance is added.
    """
    mobility=np.zeros_like(delta)
    affected=set(np.flatnonzero(np.linalg.norm(delta,axis=1)>rig.info['width']*1e-8).tolist())
    nearby={j for a,b in zip(rig.field.a,rig.field.b) if a in affected or b in affected for j in (a,b)}
    free=sorted((set(rig.field.free.tolist()) & nearby)-rig.eye_skin.border)
    mobility[free,0]=1.;mobility[free,2]=1.
    for text,eye in recipe.get('eyes',{}).items():
        if int(text) in getattr(rig,'eye_anatomy',{}):
            # A spherical lid changes surface direction during closure.
            # Let surrounding skin bend in depth as well as in the image
            # plane; the next contact pass still bounds the globe.
            region=rig.eye_skin.regions.get(int(text),set())
            mobility[sorted(set(free)&region),1]=1.
        if eye.get('closure',0.)>=1-1e-6:continue
        collar=rig.eye_skin.collars.get(int(text))
        if collar:
            mobility[sorted(set(free)&set(collar[2])),1]=1.
    if Lips.active(rig,recipe):
        collar=Lips.prepare(rig)
        lip_free=sorted(set(free)&set(np.flatnonzero(collar['fade']>0)))
        mobility[lip_free,1]=1.
    initial=delta.copy();corrected=0
    iterations=6 if any(int(side) in getattr(rig,'eye_anatomy',{}) for side in recipe.get('eyes',{})) else 3
    for iteration in range(iterations):
        notify(rig,'眼周接触与脸皮修正',iteration+1,iterations)
        count(getattr(rig,'progress',None),skin_constraint_passes=1)
        delta,eye_quality=wrap_eye_motion(rig,delta,recipe)
        notify(rig,'眼缘深度曲线与传播')
        delta,profiles=smooth_eye_depth(rig,delta,recipe)
        notify(rig,'脸皮局部防翻折')
        reference=delta.copy();reference[:,[0,2]]=initial[:,[0,2]]
        delta,fold=rig.field.constrain_triangles(delta,mobility=mobility,reference=reference,budget_scale=1.5,
                                               pulse=getattr(rig,'progress',None))
        corrected=max(corrected,fold['corrected'])
        if fold['max_correction']<max(rig.info['width']*1e-8,1e-12):break
    report=dict(eye_quality,face_fold_candidates=corrected,face_fold_unresolved=fold['unresolved'],
                face_max_correction=float(np.linalg.norm(delta-initial,axis=1).max()))
    delta,corner_quality=Lips.repair_open_corners(rig,delta,recipe)
    report.update(corner_quality)
    return delta,profiles,report


def lower_lip_depth(rig,delta,recipe):
    """Keep both connected lip bevels attached to their moving contour."""
    return Lips.restore(rig,delta,recipe)


def lip_surface_motion(rig,delta,recipe):
    delta=Lips.corner_transport(rig,Lips.surface_motion(rig,delta,recipe),recipe)
    return single_row_bite_lips(rig,delta,recipe)


def single_row_bite_lips(rig,delta,recipe):
    """Fit a closed-jaw aperture to a sole existing row without inventing teeth.

    A two-row reference can expose an empty band under a target's sole upper
    row. Bring the opposite lip to that row's cutting edge. The dental pose
    remains the measured reference pose; open jaws and tongue exits bypass it.
    """
    if not dental_contact_requested(recipe) or Lips.closed_reference(recipe):return delta
    kinds=[kind for kind in ('teeth_upper','teeth_lower') if kind in rig.oral_parts]
    if len(kinds)!=1 or ('LIP',0) not in rig.rows:return delta
    kind=kinds[0];faces=set(rig.oral_parts[kind]);ids=sorted({i for f in faces for i in rig.info['faces'][f]})
    cloud=rig.original_points[ids];width=rig.widths['LIP',0]
    front=cloud[:,1].min()+np.ptp(cloud[:,1])*.35
    triangles=[rig.original_points[list(t)] for t,f in rig.mesh_triangles if f in faces]
    from .region_contours import lip_weights
    sign=1 if kind=='teeth_upper' else -1;result=delta.copy();changed=0
    for i,u,upper in rig.rows['LIP',0]:
        if bool(upper)==(sign>0) or u<1e-7 or u>1-1e-7:continue
        x=rig.points[i,0]+delta[i,0];section=[]
        for tri in triangles:
            for a,b in zip(tri,np.roll(tri,-1,axis=0)):
                if (a[0]-x)*(b[0]-x)>0 or abs(a[0]-b[0])<width*1e-8:continue
                q=a+(b-a)*((x-a[0])/(b[0]-a[0]))
                if q[1]<=front:section.append(q[2])
        if not section:continue
        height=(min(section) if sign>0 else max(section))+sign*width*.015
        # The tooth edge is a secondary attachment target. It cannot pull
        # a lip through its opposite branch when a custom curve closes it.
        opposite=sum((rig.points[j,2]+delta[j,2])*weight
                     for j,weight in lip_weights(rig.rows['LIP',0],u,not upper))
        height=min(height,opposite) if sign>0 else max(height,opposite)
        current=rig.points[i,2]+delta[i,2];shift=max((height-current)*sign,0.)*sign
        result[i,2]+=shift;changed+=int(abs(shift)>width*1e-8)
    rig.lip_surface_report.update(single_dental_row=kind,single_dental_row_lip_vertices=changed)
    return result


UPPER_LIP_FOLLOW=.30


def dental_contact_requested(recipe):
    """A reference with stationary teeth retains its closed dental action."""
    if recipe.get('tongue',{}).get('protrusion',0)>0:return False
    if not (recipe.get('mouth') or recipe.get('mouth_targets')):return False
    for kind in ('teeth_upper','teeth_lower'):
        pose=recipe.get('oral',{}).get(kind,{})
        if np.max(abs(np.asarray(pose.get('rotation',np.eye(3)))-np.eye(3)))>1e-7:return False
        if np.max(abs(np.asarray(pose.get('translation',np.zeros(3)))))>1e-7:return False
    return True


def tongue_dental_space(rig,delta,recipe):
    """Open whole dental rows around the posed tongue; keep its lip support."""
    from . import procedural_cavity as C
    amount=float(recipe.get('tongue',{}).get('protrusion',0))
    report=dict(tongue_dental_space={})
    if amount<=0 or not rig.tongue:return report
    width=rig.widths['LIP',0];order=[0,2,1]
    tongue=np.asarray([tri for tri,f in rig.mesh_triangles if rig.info['labels'][f]==12],dtype=int).reshape((-1,3))
    if not len(tongue):return report
    obstacle=(rig.points+delta)[tongue][:,:,order]
    for kind,sign in (('teeth_upper',1),('teeth_lower',-1)):
        if kind not in rig.oral_parts:continue
        ids,center,rotation,translation=C.part_pose(rig,recipe,kind)
        cloud=rig.original_points.copy()
        cloud[ids]=(cloud[ids]-center)@rotation.T+center+translation
        face_set=set(rig.oral_parts[kind]);triangles=[tri for tri,f in rig.mesh_triangles if f in face_set]
        freedom=np.zeros(len(delta));freedom[ids]=1.
        need,_=Surfaces.depth_bounds(cloud[:,order],triangles,obstacle,freedom,front=sign<0,coherent=True)
        required=float(np.max(need*sign))
        shift=min(required+width*.003*amount,width*.18*amount) if required>width*1e-8 else 0.
        pose=recipe.setdefault('oral',{}).setdefault(kind,dict(rotation=np.eye(3).tolist(),translation=[0.,0.,0.]))
        move=np.asarray(pose['translation'],dtype=float).copy();move[2]+=sign*shift/width
        pose['translation']=move.tolist();report['tongue_dental_space'][kind]=sign*shift
    return report


def fit_upper_jaw(rig,delta,recipe):
    """Let the upper row follow a large opening before bounded dental flex."""
    report=dict(teeth_upper_jaw_adjustment=0.)
    if recipe.get('dental_reference'):return report
    if 'teeth_upper' not in rig.oral_parts or not Lips.active(rig,recipe):return report
    # Decide from the original dental action, before lip-follow modifies it.
    # Otherwise a closed reference such as い becomes an opening jaw action.
    if dental_contact_requested(recipe):return report
    from .region_contours import lip_weights
    rows=rig.rows['LIP',0];width=rig.widths['LIP',0]
    motions={up:float(np.mean([sum(delta[i,2]*w for i,w in lip_weights(rows,u,up))
                             for u in np.linspace(.2,.8,39)])) for up in (False,True)}
    opening=float(np.clip((motions[True]-motions[False]-width*.03)/(width*.12),0,1))
    if opening<=0 or motions[True]<=0:return report
    pose=recipe.setdefault('oral',{}).setdefault('teeth_upper',dict(rotation=np.eye(3).tolist(),translation=[0.,0.,0.]))
    translation=np.asarray(pose.get('translation',np.zeros(3)),dtype=float).copy()
    # Keep some tooth exposure after exporting the fitted jaw correctly.
    # Whole-row travel supplements, rather than replaces, bounded front flex.
    goal=motions[True]*UPPER_LIP_FOLLOW*opening
    extra=max(goal-translation[2]*width,0.)
    translation[2]+=extra/width;pose['translation']=translation.tolist()
    report['teeth_upper_jaw_adjustment']=extra
    return report


def fit_lower_jaw(rig,delta,recipe):
    """Retarget a separating jaw's translation before the small dental flex."""
    report=dict(teeth_lower_jaw_adjustment=0.)
    if recipe.get('dental_reference'):return report
    if 'teeth_lower' not in rig.oral_parts or ('LIP',0) not in rig.rows:return report
    poses=recipe.get('oral',{});lower=poses.get('teeth_lower')
    if not lower:return report
    translation=np.asarray(lower['translation'],dtype=float).copy()
    upper=np.asarray(poses.get('teeth_upper',{}).get('translation',np.zeros(3)))
    # Keep closed dental actions (including い) closed. Only a reference that
    # already separates the lower jaw may gain extra whole-part travel.
    if translation[2]>=upper[2]-1e-7:return report
    width=rig.widths['LIP',0];rows=rig.rows['LIP',0]
    from .region_contours import lip_weights
    motion=float(np.mean([sum(delta[i,2]*w for i,w in lip_weights(rows,u,False))
                          for u in np.linspace(.2,.8,39)]))
    ids=sorted({i for f in rig.oral_parts['teeth_lower'] for i in rig.info['faces'][f]})
    cloud=rig.original_points[ids];center=cloud.mean(0);rotation=np.asarray(lower['rotation'])
    depth=np.clip((cloud[:,1]-cloud[:,1].min())/max(float(np.ptp(cloud[:,1])),1e-12),0.,1.)
    weights=(1-depth)**2*(1+2*depth) if np.ptp(cloud[:,1])>width*.015 else np.ones(len(ids))
    rigid=(cloud-center)@rotation.T+center+translation*width
    current=float(np.average(rigid[:,2]-cloud[:,2],weights=np.maximum(weights,1e-12)))
    # The 8% limit belongs to bending, not to opening the entire lower jaw.
    extra=min(motion-current+width*.08,0.)
    translation[2]+=extra/width;lower['translation']=translation.tolist()
    report['teeth_lower_jaw_adjustment']=float(extra)
    return report


def accessory_depth(rig,delta,recipe):
    """Keep each eyebrow's overlapping strips together; creases follow the band later."""
    posed=rig.points+delta
    faces=[f for f,l in zip(rig.info['faces'],rig.info['labels']) if l==0 and not set(f).issubset(rig.creases)]
    if not faces:return delta
    extent=max(float(np.ptp(posed,axis=0).max()),1e-9);origin=float(min(posed[:,1].min(),rig.points[:,1].min())-extent*2)
    old=(BVHTree.FromPolygons([Vector(p) for p in rig.points],faces),origin,extent*5)
    new=(BVHTree.FromPolygons([Vector(p) for p in posed],faces),origin,extent*5)
    for side in (-1,1):
        if str(side) not in recipe.get('eyes',{}) and str(side) not in recipe.get('brows',{}):continue
        brow_ids=[];follow=[];bounds=[];affected=False
        for i,labels in enumerate(rig.members):
            if i not in rig.brows:continue
            if i in rig.strands or (1 if rig.points[i,0]>=rig.info['plane'] else -1)!=side:continue
            before=surface_y(old,rig.points[i]);after=surface_y(new,posed[i])
            if i in rig.brows:
                brow_ids.append(i)
                affected=affected or np.linalg.norm(delta[i])>1e-12
                if before is not None and after is not None:
                    follow.append(after-before-delta[i,1])
                    affected=affected or abs(after-before)>1e-12
                if after is not None:
                    clearance=max(before-rig.points[i,1],0.) if before is not None else 0.
                    bounds.append(after-clearance-posed[i,1])
        # Include stationary brows when the animated face moves in front of
        # them. One common correction preserves coincident and layered strips.
        if affected and brow_ids and (follow or bounds):
            shift=float(np.median(follow)) if follow else 0.
            if bounds:shift=min(shift,min(bounds))
            delta[brow_ids,1]+=shift
    return delta


def teeth_deformation(rig,delta,recipe):
    """Depth layers share a bounded Z displacement; contacts handle depth.

    Dental flex is additional to the rigid jaw pose. A single smooth function
    of the original Y coordinate moves the front toward its lip, retaining the
    back attachment. No width or height scaling is applied. Convert the result
    back into pre-armature coordinates before storing it in the main key.
    """
    width=rig.widths.get(('LIP',0),0.);shapes={};amounts={};clips={};limited=[]
    # Calibrated upper/lower row poses already contain their distinct travel.
    # Adding another lip-follow bend doubles that travel and makes stationary
    # dental actions float. Depth contacts and closing the rest gap still run.
    if recipe.get('dental_reference'):
        return shapes,dict(teeth_z_adjustments=amounts,teeth_y_clip=clips,teeth_limited=limited)
    if width<=0 or not (recipe.get('mouth') or recipe.get('mouth_targets') or 'jaw' in recipe):
        return shapes,dict(teeth_z_adjustments=amounts,teeth_y_clip=clips,teeth_limited=limited)
    from .region_contours import lip_weights
    rows=rig.rows['LIP',0];branches={}
    for upper in (True,False):
        controls=[lip_weights(rows,u,upper) for u in np.linspace(0,1,65)]
        rest=np.array([sum((rig.points[i]*w for i,w in row),np.zeros(3)) for row in controls])
        posed=np.array([sum(((rig.points[i]+delta[i])*w for i,w in row),np.zeros(3)) for row in controls])
        branches[upper]=(rest,posed)
    # Reference actions such as い keep both tooth rows shut. Their lip height
    # changes must bend the closed dental unit together, not part its rows.
    tooth_kinds=('teeth_upper','teeth_lower')
    joined=all(kind in rig.oral_parts for kind in tooth_kinds)
    for kind in tooth_kinds:
        pose=recipe.get('oral',{}).get(kind,{})
        joined=joined and np.max(abs(np.asarray(pose.get('rotation',np.eye(3)))-np.eye(3)))<1e-7
        joined=joined and np.max(abs(np.asarray(pose.get('translation',np.zeros(3)))))<1e-7
    if joined:
        all_ids=sorted({i for kind in tooth_kinds for f in rig.oral_parts[kind] for i in rig.info['faces'][f]})
        joined_depth=(float(rig.original_points[all_ids,1].min()),float(rig.original_points[all_ids,1].max()))
        joined_motion=float(np.mean([(lip[13:52,2]-rest[13:52,2]).mean() for rest,lip in branches.values()]))
    for upper in (True,False):
        kind='teeth_'+('upper' if upper else 'lower')
        if kind not in rig.oral_parts:continue
        ids=sorted({i for f in rig.oral_parts[kind] for i in rig.info['faces'][f]})
        cloud=rig.original_points[ids];center=cloud.mean(0)
        pose=recipe.get('oral',{}).get(kind,{})
        rotation=np.asarray(pose.get('rotation',np.eye(3)));translation=np.asarray(pose.get('translation',np.zeros(3)))*width
        rigid=(cloud-center)@rotation.T+center+translation
        lo,hi=joined_depth if joined else (np.min(cloud[:,1]),np.max(cloud[:,1]));span=hi-lo
        depth=np.clip((cloud[:,1]-lo)/max(span,1e-12),0,1)
        weight=(1-depth)**2*(1+2*depth) if span>width*.015 else np.ones(len(ids))
        rest,lip=branches[upper]
        lip_motion=float((lip[13:52,2]-rest[13:52,2]).mean())
        rigid_front=float(np.average(rigid[:,2]-cloud[:,2],weights=np.maximum(weight,1e-12)))
        requested=joined_motion if joined else lip_motion-rigid_front
        offset=float(np.clip(requested,-width*.08,width*.08))
        if abs(offset-requested)>1e-12:limited.append(kind)
        posed=rigid.copy();posed[:,2]+=offset*weight
        # Actual Face triangles, including the lip bevel, are checked later
        # by oral_face. An unbounded per-tooth Y clamp to the lip centreline
        # distorted the row before that bounded contact solve could run.
        local=(posed-rigid)@rotation
        if np.any(np.abs(local)>1e-12):
            shape=np.zeros_like(rig.points);shape[ids]=local;shapes[kind]=shape
        amounts[kind]=offset;clips[kind]=0.
    return shapes,dict(teeth_z_adjustments=amounts,teeth_y_clip=clips,teeth_limited=limited)


def close_dental_contact(rig,recipe):
    """Bring two intact rows to first contact, keeping the original Basis."""
    report=dict(dental_contact_requested=dental_contact_requested(recipe),dental_contact_available=False,dental_closing_shift=0.)
    if not report['dental_contact_requested']:return report
    if not all(kind in rig.oral_parts for kind in ('teeth_upper','teeth_lower')):return report
    from . import procedural_surfaces as S,procedural_cavity as Cavity
    clouds=[]
    for kind in ('teeth_upper','teeth_lower'):
        ids,center,rotation,translation=Cavity.part_pose(rig,recipe,kind)
        shape=getattr(rig,'last_teeth_deformation',{}).get(kind,np.zeros_like(rig.points))
        points=rig.original_points.copy();points[ids]=(points[ids]+shape[ids]-center)@rotation.T+center+translation
        faces=set(rig.oral_parts[kind]);triangles=[t for t,f in rig.mesh_triangles if f in faces]
        clouds.append(points[np.asarray(triangles,dtype=int)])
    upper,lower=clouds
    if not len(upper) or not len(lower):return report
    a,b=np.nonzero(np.all(upper.min(1)[:,None,:2]<=lower.max(1)[None,:,:2],axis=-1)&
                   np.all(lower.min(1)[None,:,:2]<=upper.max(1)[:,None,:2],axis=-1))
    gaps=[]
    for start in range(0,len(a),128):
        ia,ib=a[start:start+128],b[start:start+128]
        wa,wb,valid=S.overlap_vertices(upper[ia,:,:2],lower[ib,:,:2])
        gap=np.sum(wa*upper[ia,None,:,2],axis=-1)-np.sum(wb*lower[ib,None,:,2],axis=-1)
        if valid.any():gaps.append(float(np.min(gap[valid])))
    if not gaps:return report
    gap=min(gaps);width=rig.widths['LIP',0]
    # A negative gap is an existing dental overlap, not permission to drive
    # the lower teeth farther into the upper row. No tooth scaling is used.
    shift=max(gap,0.)
    if shift>width*.30:
        return report
    if shift>width*1e-7:
        pose=recipe.setdefault('oral',{}).setdefault('teeth_lower',dict(rotation=np.eye(3).tolist(),translation=[0.,0.,0.]))
        pose['translation'][2]+=shift/width
    report.update(dental_contact_available=True,dental_closing_shift=shift,dental_gap_before=gap)
    return report
