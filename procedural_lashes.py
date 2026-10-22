"""Attached lash bending with preserved root burial and section measure."""
import numpy as np
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
from . import procedural_binding as B,region_core as C,procedural_surfaces as S
from .generation_progress import notify,count


def unit_vector(value):
    return value/max(float(np.linalg.norm(value)),1e-12)


def rotation(a,b):
    if min(np.linalg.norm(a),np.linalg.norm(b))<1e-12:return np.eye(3)
    return np.asarray(Vector(a).rotation_difference(Vector(b)).to_matrix())


def attach(root,edited,rest,posed,tree,triangles,transform):
    hit,normal,index,distance=tree.find_nearest(Vector(root))
    if hit is None:return None
    ids=triangles[index];a=rest[ids];b=posed[ids]
    # Transport the exact nearest point and the original embedded offset.
    matrix=np.column_stack((a[1]-a[0],a[2]-a[0]))
    uv=np.linalg.lstsq(matrix,np.asarray(hit)-a[0],rcond=None)[0]
    weights=np.array((1-uv.sum(),uv[0],uv[1]))
    # A compressed/flipped attachment triangle must not flip the strand.
    # Its barycentric point supplies translation only; orientation comes from
    # the same stable transport used by the surrounding band.
    return weights@b+transform@(edited-np.asarray(hit))


def forward_controls(controls,axis,length):
    """Keep contact corrections from folding the centerline back into its root."""
    values=(controls-controls[0])@axis
    projected=np.maximum.accumulate(np.clip(values,0.,length*1.25))
    projected[1:]=np.maximum(projected[1:],length*np.array((.08,.16,.25)))
    return controls+(projected-values)[:,None]*axis


def surface(points,triangles):
    if not triangles:return None
    extent=max(float(np.ptp(points,axis=0).max()),1e-9)
    return BVHTree.FromPolygons([Vector(p) for p in points],triangles),float(points[:,1].min()-2*extent),5*extent


def clearance(obstacle,point):
    if obstacle is None:return None
    tree,origin,length=obstacle
    hit,_,_,_=tree.ray_cast(Vector((point[0],origin,point[2])),Vector((0,1,0)),length)
    return None if hit is None else float(hit.y-point[1])


def fit_rigid_contact(rig,delta,recipe):
    """Keep eyelid XZ placement and curl; adjust whole-card depth from roots."""
    result=delta.copy();report=dict(lash_rigid_units=0,lash_rigid_before=0.,lash_rigid_after=0.)
    protected=rig.brows|rig.creases|{i for i,m in enumerate(rig.members) if 0 in m}
    protected|=getattr(rig,'upper_followers',set())
    for side_text in recipe.get('eyes',{}):
        side=int(side_text)
        if side not in rig.rings:continue
        width=rig.widths['EYE',side];units,skin=contact_units(rig,side)
        posed=rig.points+result;obstacle=surface(posed,skin)
        for unit in units:
            ids=np.asarray(unit['ids'],dtype=np.int32)
            if unit['locked'] or protected.intersection(ids):continue
            cloud=posed[ids].copy()
            original=np.array([unit['gaps'][i] if unit['gaps'][i] is not None else np.nan for i in ids])
            gaps=np.array([v if (v:=clearance(obstacle,p)) is not None else np.nan for p in cloud])
            valid=np.isfinite(original)&np.isfinite(gaps)
            # Only originally buried/near-surface roots anchor the assembly.
            # Lifted tips are clearance constraints, never attachment targets.
            roots=valid&(abs(original)<=width*.005)&np.array([i not in rig.strands for i in ids])
            if np.count_nonzero(roots)<3:continue
            lifted=valid&((original>width*.015)|np.array([i in rig.strands for i in ids]))
            error=gaps-original;score=float(np.mean(error[roots]**2))
            low=-width*.10;high=width*.10
            # Preserve each raised section's authored gap wherever it can be
            # measured. A correction cannot worsen its existing discrepancy.
            if np.any(lifted):
                tolerance=np.maximum(abs(error[lifted]),width*.002)
                low=max(low,float(np.max(error[lifted]-tolerance)))
                high=min(high,float(np.min(error[lifted]+tolerance)))
            floor=np.minimum(np.minimum(original,gaps),0.)
            high=min(high,float(np.min((gaps-floor)[valid])))
            shift=float(np.clip(np.mean(error[roots]),low,high)) if low<=high else 0.
            # X and Z remain the eyelid solver's positions. A single Y shift
            # retains the full curve, edge lengths, and root-tip separation.
            parents=unit['parents'];weights=unit['weights']
            obstacles=[posed[np.asarray(skin)]] if skin else []
            eyes=[list(t) for t,f in rig.mesh_triangles if rig.info['labels'][f] in (3,5,7)
                  and (1 if rig.original_points[list(t),0].mean()>=rig.info['plane'] else -1)==side]
            if eyes:
                eye_points=rig.original_points+getattr(rig,'eye_stack_shape',np.zeros_like(delta))
                obstacles.append(eye_points[np.asarray(eyes)])
            if len(parents) and abs(shift)>width*1e-8:
                a=np.einsum('kij,kja->kia',weights,posed[parents]).reshape((-1,3))
                faces=np.arange(len(a)).reshape((-1,3));free=np.ones(len(a))
                limits=[np.min(S.depth_bounds(a,faces,o,free,coherent=True)[0]) for o in obstacles]
                for _ in range(12):
                    b=a.copy();b[:,1]+=shift
                    if all(np.min(S.depth_bounds(b,faces,o,free,coherent=True)[0])>=limit-width*1e-5
                           for o,limit in zip(obstacles,limits)):break
                    shift*=.5
                else:shift=0.
            after=float(np.mean((error[roots]-shift)**2))
            if after<score-width**2*1e-10:
                result[ids,1]+=shift;posed[ids,1]+=shift;report['lash_rigid_units']+=1
            else:after=score
            report['lash_rigid_before']=max(report['lash_rigid_before'],float(np.sqrt(score)))
            report['lash_rigid_after']=max(report['lash_rigid_after'],float(np.sqrt(after)))
    return result,report


def is_upper(rig,side,i):
    # dict.get evaluates its default even for an existing key. Most vertices
    # already have a known side, so avoid repeating nearest-curve searches.
    if i in rig.lash_upper:return rig.lash_upper[i]
    return rig.rings[side].locate(Vector(rig.points[i]))[1]


def upper_band(rig,side):
    excluded=rig.strands|rig.brows|rig.creases|getattr(rig,'upper_followers',set())
    return [list(t) for t,f in rig.mesh_triangles if rig.info['labels'][f]==2 and not set(t)&excluded
            and (1 if rig.points[list(t),0].mean()>=rig.info['plane'] else -1)==side
            and all(is_upper(rig,side,i) for i in t)]


def upper_vertices(rig,side):
    """Include seam aliases even when every incident face also touches a tip."""
    ids={i for tri in upper_band(rig,side) for i in tri}
    for group in getattr(rig,'lash_stitches',[]):
        if ids.intersection(group):ids.update(group)
    return sorted(i for i in ids if 0 not in rig.members[i])


def lower_vertices(rig,side):
    excluded=rig.brows|rig.creases|rig.strands|getattr(rig,'upper_followers',set())
    # A returned upper-lash card uses lower motion but is not a lower band
    # to squeeze under the upper band. Doing so pushes the entire upper card
    # away from Face merely to make room for its own returned end.
    excluded|=getattr(rig,'lash_return_vertices',set())
    return [i for i,labels in enumerate(rig.members) if 2 in labels and 0 not in labels and i not in excluded
            and (1 if rig.points[i,0]>=rig.info['plane'] else -1)==side
            and not is_upper(rig,side,i)]


def band_intervals(triangles,x,tolerance):
    """Actual occupied Z intervals, not the convex hull of separate cards."""
    return BandSections(triangles)(x,tolerance)


class BandSections:
    """Reuse a fixed sheet's edges, evaluating every original triangle section.

    Only the broad phase and independent edge intersections are batched. The
    endpoint tolerance, clipping, disconnected intervals and merge order match
    band_intervals' scalar implementation, including degenerate triangles.
    """
    def __init__(self,triangles):
        a=np.asarray(triangles).reshape((-1,3,3))
        b=np.roll(a,-1,axis=1)
        self.ax=a[:,:,0];self.az=a[:,:,2];self.bz=b[:,:,2]
        self.dx=b[:,:,0]-self.ax;self.dz=self.bz-self.az
        self.low=np.minimum(self.ax,b[:,:,0]);self.high=np.maximum(self.ax,b[:,:,0])
        self.minimum=self.ax.min(1);self.maximum=self.ax.max(1)

    def __call__(self,x,tolerance):
        # Keep both original broad-phase comparisons: their rounding at an
        # endpoint can differ from algebraically rearranged comparisons.
        selected=((self.minimum<=x+tolerance)&(self.maximum>=x-tolerance)
                  &(x>=self.minimum-tolerance)&(x<=self.maximum+tolerance))
        if not selected.any():return []
        ax=self.ax[selected];az=self.az[selected];dx=self.dx[selected]
        vertical=np.abs(dx)<=tolerance
        upright=vertical&(np.abs(x-ax)<=tolerance)
        crossing=(~vertical)&(x>=self.low[selected]-tolerance)&(x<=self.high[selected]+tolerance)
        t=np.zeros_like(dx,dtype=float)
        np.divide(x-ax,dx,out=t,where=crossing);np.clip(t,0,1,out=t)
        z=az+t*self.dz[selected]
        bottom=np.minimum(np.where(upright,az,np.inf),np.where(crossing,z,np.inf)).min(1)
        top=np.maximum(np.where(upright,az,-np.inf),np.where(crossing,z,-np.inf)).max(1)
        bottom=np.minimum(bottom,np.where(upright,self.bz[selected],np.inf).min(1))
        top=np.maximum(top,np.where(upright,self.bz[selected],-np.inf).max(1))
        valid=np.isfinite(bottom)
        merged=[]
        for lo,hi in sorted(zip(bottom[valid],top[valid])):
            if merged and lo<=merged[-1][1]+tolerance:merged[-1][1]=max(merged[-1][1],hi)
            else:merged.append([lo,hi])
        return merged


def lower_turns(line):
    """Locate the horizontal-to-vertical transition near each lower canthus."""
    parameters=np.linspace(0,1,129);points=np.array([line.sample(t) for t in parameters])
    tangent=np.gradient(points[:,[0,2]],axis=0)
    vertical=abs(tangent[:,1])>abs(tangent[:,0])*1.05
    segments=[]
    for end in (0,1):
        indices=np.arange(0,46) if end==0 else np.arange(128,82,-1)
        hits=[k for k in range(len(indices)) if vertical[indices[k]]]
        if not hits or hits[0]>10:continue
        last=hits[0]
        for k in hits[1:]:
            if k-last>3:break
            last=k
        turn=int(indices[min(last+1,len(indices)-1)])
        chord=points[128 if end else 0]-points[turn]
        if abs(chord[2])<=abs(chord[0])*.8:continue
        segments.append((float(parameters[turn]),float(end)))
    return segments


def closed_curve_extension(controls,parameters):
    """Continue a closed lid smoothly, without a cubic runaway past its corners.

    Lash wings extend beyond the facial opening. Keep the endpoint tangent,
    then ease the height extension toward a horizontal wing. Depth continues
    linearly until the separate skin-contact pass supplies the surface depth.
    """
    t=np.asarray(parameters);clipped=np.clip(t,0.,1.)
    value=B.bezier(controls,clipped)
    start=3*(controls[1]-controls[0]);end=3*(controls[3]-controls[2])
    tangent=np.where((t<0)[...,None],start,end)
    distance=t-clipped;growth=distance[...,None]*tangent
    growth[...,2]=.10*np.tanh(distance/.10)*tangent[...,2]
    return value+growth


def slope_follow_weight(tangent,outward):
    """Increase toward vertical; an overhanging/inward tangent stays at one."""
    dx=float(tangent[0])*outward;dz=abs(float(tangent[2]))
    if dx<=0:return 1. if dz>1e-12 or dx<0 else 0.
    angle=np.arctan2(dz,dx)/(np.pi*.5)
    return float(angle*angle*(3-2*angle))


def lower_rim_transport(rig,delta,side):
    """Follow the actual rim at its original material parameter.

    Interpolated section rotations retain thickness, while the anchors match
    the solved Face edges exactly. Fitting a second displacement spline here
    moved corners away from the rim and could reverse its short end segments.
    """
    rows=sorted({(u,i) for i,u,upper in rig.rows['EYE',side] if not upper or u<1e-7 or u>1-1e-7})
    indices=[i for u,i in rows];base=B.Line(rig.points[indices]);posed=rig.points[indices]+delta[indices]
    parameters=base.parameters
    quaternions=[]
    for before,after in zip(np.diff(base.points,axis=0),np.diff(posed,axis=0)):
        quaternions.append(Matrix(rotation(before,after).tolist()).to_quaternion())
    frames=[quaternions[0]]+[a.slerp(b,.5) for a,b in zip(quaternions[:-1],quaternions[1:])]+[quaternions[-1]]
    identity=Matrix.Identity(3).to_quaternion()
    def at(u,folding=1.):
        k=int(np.clip(np.searchsorted(parameters,u,side='right')-1,0,len(parameters)-2))
        t=float(np.clip((u-parameters[k])/max(parameters[k+1]-parameters[k],1e-12),0,1))
        anchor=posed[k]*(1-t)+posed[k+1]*t
        frame=frames[k].slerp(frames[k+1],t)
        frame=identity.slerp(frame,float(np.clip(folding,0,1)))
        return anchor,np.asarray(frame.to_matrix())
    def follow(point,folding=1.,parameter=None):
        u=base.project(point)[0] if parameter is None else parameter
        anchor,frame=at(u,folding)
        return anchor+frame@(point-base.sample(u)),frame,u
    return base,follow


def follow_lower_rim(rig,delta,recipe):
    """Transport lower cards on the actual solved skin rim, retaining offsets."""
    report=dict(lower_lash_follow_vertices=0)
    excluded=rig.brows|rig.creases|rig.strands|getattr(rig,'upper_followers',set())
    rig.lash_lower_transports={}
    rig.lash_lower_weights=np.zeros(len(delta));rig.lash_lower_targets=rig.points+delta.copy()
    for text,eye in recipe.get('eyes',{}).items():
        side=int(text)
        if side not in rig.rings:continue
        base,follow=lower_rim_transport(rig,delta,side)
        rig.lash_lower_transports[side]=(base,follow)
        for i,labels in enumerate(rig.members):
            if 2 not in labels or 0 in labels or i in excluded:continue
            if (1 if rig.points[i,0]>=rig.info['plane'] else -1)!=side:continue
            if rig.lash_upper.get(i,rig.rings[side].locate(Vector(rig.points[i]))[1]):continue
            point=rig.points[i]
            delta[i]=follow(point)[0]-point
            report['lower_lash_follow_vertices']+=1
    return delta,report


def lower_corner_sections(rig,delta,recipe,lids):
    """Turn vertical lower-lid cards around Y and compress Z at closure.

    The edited guide supplies the centreline; the horizontal band keeps its
    existing translation. A smooth transition retains the connected turn.
    """
    from .region_contours import lip_weights
    report=dict(lower_corner_sections=0,lower_corner_vertices=0)
    excluded=rig.strands|rig.brows|rig.creases
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text);closure=float(np.clip(eye['closure'],0,1))
        if closure<=1e-8 or side not in lids:continue
        current=rig.guide_lines['EYE',side][False]
        original=B.Line(rig.guides['EYE',side][False]['base'])
        segments=lower_turns(current)
        if not segments:continue
        def actual(u):
            weights=lip_weights(rig.rows['EYE',side],u,False)
            return sum(((rig.points[i]+delta[i])*w for i,w in weights),np.zeros(3))
        for turn,end in segments:
            before=original.sample(end)-original.sample(turn)
            after=actual(end)-actual(turn)
            length=max(float(np.linalg.norm(before[[0,2]])),1e-12)
            a=np.arctan2(before[2],before[0]);b=np.arctan2(after[2],after[0])
            angle=float(np.arctan2(np.sin(a-b),np.cos(a-b)))
            angle=float(np.clip(angle,-np.pi*.48,np.pi*.48))
            compression=float(np.clip(np.linalg.norm(after[[0,2]])/length,.08,1.))
            count=0
            for i,labels in enumerate(rig.members):
                if 2 not in labels or 0 in labels or i in excluded:continue
                if (1 if rig.points[i,0]>=rig.info['plane'] else -1)!=side:continue
                if rig.lash_upper.get(i,rig.rings[side].locate(Vector(rig.points[i]))[1]):continue
                u=original.project(rig.points[i])[0]
                if not min(turn,end)-1e-8<=u<=max(turn,end)+1e-8:continue
                distance=abs(u-turn)/max(abs(end-turn),1e-12)
                blend=float(np.clip(distance/.25,0,1));blend=blend*blend*(3-2*blend)
                theta=angle*blend;scale=1-(1-compression)*blend
                c,s=np.cos(theta),np.sin(theta)
                rotation=np.array(((c,0.,s),(0.,1.,0.),(-s,0.,c)))
                # Translate all offsets at one section together; only this
                # vertical lower piece gains rotation/compression, never upper.
                anchor=original.sample(u);offset=rotation@(rig.points[i]-anchor);offset[2]*=scale
                target=actual(u)+offset
                delta[i]=(1-closure)*delta[i]+closure*(target-rig.points[i]);count+=1
            report['lower_corner_sections']+=1;report['lower_corner_vertices']+=count
    return delta,report


def style_band(rig,delta,recipe):
    """Set actual mesh section centres, not only the guide, to the eye style."""
    report=dict(lash_style_sections=0,lash_style_max_correction=0.,lash_styles={})
    excluded=rig.strands|rig.brows|rig.creases|getattr(rig,'upper_followers',set())
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text);closure=float(np.clip(eye['closure'],0,1))
        flat=eye.get('flat',0.)>.5;smile=eye.get('smile',0.)>.5
        if side not in rig.rings or closure<1-1e-6:continue
        report['lash_styles'][str(side)]='flat' if flat else 'upward' if smile else 'downward'
        posed=rig.points+delta
        for upper in (False,True):
            ids=[i for i,labels in enumerate(rig.members) if 2 in labels and 0 not in labels and i not in excluded
                 and (1 if rig.points[i,0]>=rig.info['plane'] else -1)==side
                 and bool(rig.lash_upper.get(i,rig.rings[side].locate(Vector(rig.points[i]))[1]))==upper]
            if len(ids)<3:continue
            # Imported cards rarely share EXACT X coordinates between their
            # upper and lower edges. A one-vertex "section" erases thickness
            # when its Z is placed on the desired centreline. Sample finite
            # neighborhoods and apply one smooth translation field instead.
            source_x=rig.points[ids,0];span_x=float(np.ptp(source_x))
            if span_x<1e-9:continue
            x=np.linspace(float(source_x.min()),float(source_x.max()),65)
            sections=[]
            for value in x:
                near=np.flatnonzero(abs(source_x-value)<=span_x*.035)
                if len(near)<4:near=np.argsort(abs(source_x-value))[:min(4,len(ids))]
                sections.append(np.asarray(ids)[near])
            actual=np.array([np.median(posed[local],axis=0) for local in sections])
            lo,hi=float(actual[:,0].min()),float(actual[:,0].max());span=max(hi-lo,1e-12)
            t=np.clip((actual[:,0]-lo)/span,0,1)
            rim=sorted({i for i,u,up in rig.rows['EYE',side] if bool(up)==upper or u<1e-7 or u>1-1e-7})
            rx,inverse=np.unique(posed[rim,0],return_inverse=True)
            rz=np.bincount(inverse,posed[rim,2])/np.bincount(inverse)
            seam=np.interp(actual[:,0],rx,rz)
            # Preserve a common band/lid inset; varying mesh-guide residuals
            # must not reintroduce the original U shape in a flat closure.
            gap=float(np.median(actual[:,2]-seam))
            order=np.argsort(t);samples=np.column_stack((t,np.zeros(len(t)),seam+gap))
            controls=B.fit_bezier(samples[order],t[order]);controls[:,0]=np.linspace(0,1,4)
            current=B.fit_bezier(actual[order],t[order])
            if flat:
                # Prefer the solved seam's tilt (horizontal when feasible).
                # Keep a common offset so the card retains its cross-section.
                controls[:,2]=np.linspace(seam[0],seam[-1],4)+gap
            chord=np.linspace(controls[0,2],controls[3,2],4)
            handles=np.zeros(2)
            if smile and not flat:
                handles=B.upward_handles(controls[1:3,2]-chord[1:3])
                if np.max(handles)<span*1e-6:handles[:]=span*.002
                handles*=float(np.clip(getattr(rig,'style_options',{}).get('smile_arc',1.),.15,1.))
            elif not flat:
                # Ordinary blink also needs its final mesh checked after the
                # roll. Retained open-eye curvature must not turn it into the
                # smile key. Preserve the solved seam's measured bowl depth.
                handles=-B.upward_handles(controls[1:3,2]-chord[1:3])
            arc=B.bezier(np.r_[0.,handles,0.],np.linspace(0,1,65))
            handles*=min(1.,span*(.14 if smile else .10)/max(float(np.max(abs(arc))),1e-12))
            controls[:,2]=chord;controls[1:3,2]+=handles
            # Fit the current centre as well, retaining each vertex's offset
            # from it. Two nearby points receive nearby shifts, never two
            # independent projections onto the same thin line.
            # The correction is one polynomial across the wing as well.
            # Clamping at the median-section bounds makes its slope jump.
            vertex_t=(posed[ids,0]-lo)/span
            change=B.bezier(controls,vertex_t)[:,2]-B.bezier(current,vertex_t)[:,2]
            delta[ids,2]+=change
            report['lash_style_sections']+=len(x)
            report['lash_style_max_correction']=max(report['lash_style_max_correction'],float(np.max(abs(change))))
    return delta,report


def cover_closed_seam(rig,delta,recipe):
    """Translate whole upper-band sections until their footprint covers the rim."""
    report=dict(lash_seam_sections=0,lash_seam_coverage_conflicts=0,lash_seam_rigid_sides=0)
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text)
        if side not in rig.rings or eye['closure']<1-1e-6:continue
        band=upper_band(rig,side)
        if not band:continue
        posed=rig.points+delta;ids=upper_vertices(rig,side)
        rim=sorted({i for i,u,upper in rig.rows['EYE',side]},key=lambda i:posed[i,0])
        x,inverse=np.unique(posed[rim,0],return_inverse=True)
        z=np.bincount(inverse,weights=posed[rim,2])/np.bincount(inverse)
        span=max(float(x[-1]-x[0]),1e-12);tolerance=span*1e-8
        events=np.unique(np.r_[x,posed[ids,0]])
        events=events[(events>=x[0])&(events<=x[-1])]
        events=np.unique(np.r_[events,(events[:-1]+events[1:])*.5])
        if side<0:events=events[::-1]
        samples=[];bounds=[];centers=[];sections=BandSections(posed[np.asarray(band)])
        for number,value in enumerate(events):
            if number%16==0:notify(rig,'检查睫毛片对闭合线的覆盖',number,len(events))
            intervals=sections(value,tolerance)
            if not intervals:report['lash_seam_coverage_conflicts']+=1;continue
            height=float(np.interp(value,x,z))
            lo,hi=min(intervals,key=lambda pair:max(pair[0]-height,height-pair[1],0.))
            inset=min((hi-lo)*.04,span*.0001)
            samples.append((value-x[0])/span);bounds.append((height-hi+inset,height-lo-inset));centers.append((lo+hi)*.5)
        if not samples:continue
        t=np.asarray(samples);s=1-t;basis=np.column_stack((s**3,3*s*s*t,3*s*t*t,t**3))
        limits=np.asarray(bounds);limit=rig.heights['EYE',side]*.4
        # Dykstra projections give the smallest whole-curve correction that
        # satisfies every occupied section. Anatomical order is mirror stable.
        rows=np.vstack((basis,-basis,np.eye(4),-np.eye(4)))
        rhs=np.r_[limits[:,1],-limits[:,0],np.full(8,limit)]
        preserve=float(np.clip(max(eye.get('lash_shape_preserve',0.),eye.get('flat',0.)),0,1))
        lo=max(float(limits[:,0].max()),-limit);hi=min(float(limits[:,1].min()),limit)
        rigid=eye.get('flat',0.)>.5 or preserve>=1-1e-6
        if rigid or (preserve>0 and lo<=hi):
            # A whole-band translation retains every relative section angle.
            # Incompatible footprints remain reported rather than turning
            # Nagomi into another bow or undoing full shape preservation.
            shift=float(np.clip(0.,lo,hi)) if lo<=hi else float(np.clip((lo+hi)*.5,-limit,limit))
            controls=np.full(4,shift);report['lash_seam_rigid_sides']+=1
        else:
            style_rows=None
            if eye.get('flat',0.)<=.5:
                # Constrain the FINAL band centre, not just its correction.
                # Smile has nonpositive second differences; ordinary blink
                # has nonnegative ones. Coverage must preserve both styles.
                center=np.linalg.lstsq(basis,np.asarray(centers),rcond=None)[0]
                style_rows=np.array(((1.,-2.,1.,0.),(0.,1.,-2.,1.)))
                if eye.get('smile',0.)<=.5:style_rows=-style_rows
                style_rhs=-style_rows@center-span*1e-6
                rows=np.vstack((rows,style_rows));rhs=np.r_[rhs,style_rhs]
            # Penalize differences between section shifts more strongly for
            # smiles. All occupied-section and travel constraints still apply.
            differences=np.diff(np.eye(4),axis=0)
            metric=np.linalg.inv(np.eye(4)+12*preserve*(differences.T@differences))
            directions=rows@metric;norm=np.sum(directions*rows,axis=1)
            controls=np.zeros(4);errors=np.zeros_like(rows)
            for _ in range(96):
                previous=controls.copy()
                for k,row in enumerate(rows):
                    candidate=controls+errors[k]
                    controls=candidate-directions[k]*max(float(row@candidate-rhs[k]),0.)/max(norm[k],1e-20)
                    errors[k]=candidate-controls
                if np.max(abs(controls-previous))<tolerance and np.max(rows@controls-rhs)<tolerance:break
            if style_rows is not None and np.max(style_rows@controls-style_rhs)>tolerance:
                # An infeasible coverage request must not reverse the style.
                controls[:]=float(np.clip((lo+hi)*.5,-limit,limit))
        t=(posed[ids,0]-x[0])/span
        shift=B.bezier(controls,t)
        priority=getattr(rig,'lash_lower_weights',np.zeros(len(delta)))
        delta[ids,2]+=shift*(1-priority[ids]);report['lash_seam_sections']+=len(samples)
        # Count the actual final footprint, including all triangle sections.
        final=rig.points+delta;sections=BandSections(final[np.asarray(band)])
        for number,value in enumerate(events):
            if number%16==0:notify(rig,'核对睫毛片覆盖',number,len(events))
            intervals=sections(value,tolerance)
            height=float(np.interp(value,x,z))
            if intervals and not any(lo-tolerance<=height<=hi+tolerance for lo,hi in intervals):
                report['lash_seam_coverage_conflicts']+=1
    return delta,report


def contact_units(rig,side):
    """One contact translation for each connected card, including its strands."""
    cache=getattr(rig,'_lash_contact_units',{})
    if side in cache:return cache[side]
    excluded=rig.brows
    triangles=[list(t) for t,f in rig.mesh_triangles if (rig.info['labels'][f]==2 or set(t)<=rig.creases) and not set(t)&excluded
               and (1 if rig.original_points[list(t),0].mean()>=rig.info['plane'] else -1)==side]
    parent={i:i for tri in triangles for i in tri}
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for tri in triangles:
        for i in tri[1:]:parent[root(i)]=root(tri[0])
    for group in getattr(rig,'lash_stitches',[]):
        local=[i for i in group if i in parent]
        for i in local[1:]:parent[root(i)]=root(local[0])
    # Separate mesh islands can still be one authored lash assembly. Attach
    # marked strands to the band before contact so their roots cannot drift.
    band_ids=sorted(set(parent)-rig.strands)
    contact_x=rig.original_points[:,0].copy()
    for strand in rig.lashes:
        if strand['side']!=side:continue
        strand_ids=[i for i in strand['vertices'] if i in parent]
        if not strand_ids or not band_ids:continue
        anchor=np.asarray(strand['base'][0])
        nearest=min(band_ids,key=lambda i:float(np.linalg.norm(rig.original_points[i]-anchor)))
        if np.linalg.norm(rig.original_points[nearest]-anchor)>rig.widths['EYE',side]*.15:continue
        for i in strand_ids:
            parent[root(i)]=root(nearest)
            if i in rig.strands:contact_x[i]=anchor[0]
    groups={}
    for tri in triangles:groups.setdefault(root(tri[0]),[]).append(tri)
    region=rig.eye_skin.regions.get(side,set())-rig.creases
    skin=[list(t) for t in rig.field.triangles if set(t)&region and not set(t)<=rig.creases]
    before=surface(rig.original_points,skin);units=[];tolerance=rig.widths['EYE',side]*1e-7
    for faces in groups.values():
        ids=sorted({i for tri in faces for i in tri})
        gaps={i:clearance(before,rig.original_points[i]) for i in ids}
        buried={i for i,gap in gaps.items() if gap is not None and gap<-tolerance}
        # Clip mixed root/tip triangles at the ORIGINAL skin boundary. Hidden
        # Basis regions never trigger contact, but follow the card passively.
        parents=[];weights=[]
        for tri in faces:
            depth=np.array([gaps[i] if gaps[i] is not None else tolerance for i in tri])
            polygon=list(np.eye(3));clipped=[]
            for a,b in zip(polygon,polygon[1:]+polygon[:1]):
                da,db=float(a@depth),float(b@depth)
                if da>=0:clipped.append(a)
                if (da<0<db) or (db<0<da):clipped.append(a+(b-a)*da/(da-db))
            for k in range(1,len(clipped)-1):
                parents.append(tri);weights.append([clipped[0],clipped[k],clipped[k+1]])
        units.append(dict(ids=ids,buried=buried,gaps=gaps,locked=any(0 in rig.members[i] and i not in rig.creases for i in ids),contact_x=contact_x,
                          parents=np.asarray(parents,dtype=np.int32).reshape((-1,3)),
                          weights=np.asarray(weights,dtype=float).reshape((-1,3,3))))
    cache[side]=(units,skin);rig._lash_contact_units=cache
    return cache[side]


def contact_field(rig,unit,samples,limits,side,fit=False):

    """Fit one smooth depth displacement to a card and its attached strands."""

    ids=unit['ids'];x=unit['contact_x'][ids];lo=float(x.min());span=float(np.ptp(x))

    # Rim ownership fixes the tangential motion. Whole-section depth contact

    # still has to fit the rotated card to Face; freezing Y leaves a rolled

    # corner suspended at its pre-contact depth.

    mobility=np.ones(len(ids))

    if span<rig.widths['EYE',side]*.15:

        return np.full(len(ids),min(float(np.min(limits)),0.) if not fit else float(np.min(limits)))*mobility

    t=np.clip((np.asarray(samples)-lo)/span,0,1)

    knots=np.linspace(0,1,13)

    def basis(parameters):

        return B.spline_basis(parameters,len(knots))

    matrix=basis(t)

    # Penalize sharp changes, while allowing the inner and outer portions to

    # follow different depths. Each cross-section translates without scaling.

    first=np.diff(np.eye(len(knots)),axis=0);second=np.diff(np.eye(len(knots)),n=2,axis=0)

    metric=np.linalg.inv(np.eye(len(knots))+.2*first.T@first+2*second.T@second)

    # Project an inward goal onto the complete contact envelope. Starting

    # from local minima can leave otherwise free sections suspended in front

    # of Face even though moving the whole section inward is feasible.

    value=np.full(len(knots),float(np.max(limits))+rig.widths['EYE',side]*.02) if fit else np.zeros(len(knots))

    directions=matrix@metric;norm=np.sum(matrix*directions,axis=1)

    errors=np.zeros_like(matrix);tol=rig.widths['EYE',side]*1e-8

    for _ in range(128):

        previous=value.copy()

        for k,row in enumerate(matrix):

            trial=value+errors[k]

            value=trial-directions[k]*max(float(row@trial-limits[k]),0.)/max(norm[k],1e-12)

            errors[k]=trial-value

        if np.max(abs(value-previous))<tol and np.max(matrix@value-limits)<tol:break

    # Uniform residual clearance keeps all sampled constraints satisfied.

    value-=max(float(np.max(matrix@value-limits)),0.)

    return (basis(np.clip((x-lo)/span,0,1))@value)*mobility


def conform_band(rig,delta,recipe):
    """Fit whole cards; contact cannot stretch just their roots or sections."""
    report=dict(lash_band_sections=0,lash_band_depth_conflicts=0,lash_contact_mode='whole_section_contact')
    for side_text in recipe.get('eyes',{}):
        side=int(side_text)
        if side not in rig.rings:continue
        units,skin=contact_units(rig,side);posed=rig.points+delta;after=surface(posed,skin)
        for unit in units:
            if unit['locked']:continue
            limits=[];samples=[]
            anchors=[i for i in unit['ids'] if i not in rig.strands]
            if not anchors:anchors=unit['ids']
            for i in anchors:
                gap=clearance(after,posed[i]);old=unit['gaps'][i]
                if gap is None:continue
                attachment=min(old,rig.widths['EYE',side]*.01) if old is not None else 0.
                limits.append(gap-attachment)
                samples.append(unit['contact_x'][i])
            if not limits:continue
            delta[unit['ids'],1]+=contact_field(rig,unit,samples,np.asarray(limits),side,fit=True)
            report['lash_band_sections']+=1
    return delta,report


def skin_behind_band(rig,delta,recipe):
    """Avoid fixed Face with whole cards, exempting originally hidden pieces."""
    report=dict(lash_skin_depth_vertices=0,lash_skin_depth_conflicts=0,lash_contact_vertices=0,
                lash_contact_units=0,lash_basis_buried_vertices=0,lash_locked_contact_units=0,lash_contact_max_shift=0.)
    for side_text in recipe.get('eyes',{}):
        side=int(side_text)
        if side not in rig.rings:continue
        units,skin=contact_units(rig,side);parents=[];weights=[];owners=[]
        for number,unit in enumerate(units):
            report['lash_basis_buried_vertices']+=len(unit['buried'])
            parents.extend(unit['parents']);weights.extend(unit['weights']);owners.extend([number]*len(unit['parents']))
        if not parents:continue
        parents=np.asarray(parents);weights=np.asarray(weights);owners=np.repeat(owners,3)
        ids=np.arange(len(owners)).reshape((-1,3));freedom=np.ones(len(owners))
        eyes=[list(t) for t,f in rig.mesh_triangles if rig.info['labels'][f] in (3,5,7)
              and (1 if rig.original_points[list(t),0].mean()>=rig.info['plane'] else -1)==side]
        original=np.einsum('kij,kja->kia',weights,rig.original_points[parents]).reshape((-1,3))
        # Preserve pre-existing TRIANGLE penetration, including interiors.
        # Vertex-only clearance misses curved Face between the card corners;
        # dividing that old overlap by the first path weight launches lashes.
        baseline_skin=(S.depth_bounds(original,ids,rig.original_points[np.asarray(skin)],freedom,coherent=True)[0]
                       if skin else np.zeros(len(original)))
        baseline_eye=(S.depth_bounds(original,ids,rig.original_points[np.asarray(eyes)],freedom,coherent=True)[0]
                      if eyes else np.zeros(len(original)))
        contact_start=delta[:,1].copy()
        shifts=np.zeros(len(owners));path_shifts=np.zeros(len(owners))
        for number,t in enumerate(np.linspace(1/32,1,32),1):
            notify(rig,'整片睫毛与脸皮路径接触',number,32)
            count(getattr(rig,'progress',None),lash_eye_path_weights=1)
            posed=rig.points+delta*t
            cloud=np.einsum('kij,kja->kia',weights,posed[parents]).reshape((-1,3))
            if skin:
                change,_=S.depth_bounds(cloud,ids,posed[np.asarray(skin)],freedom,coherent=True,pulse=getattr(rig,'progress',None))
                request=np.minimum(change-baseline_skin,0.)/t
                path_shifts=np.minimum(path_shifts,request)
                if number==32:shifts=np.minimum(shifts,request)
            if eyes:
                eye_points=rig.original_points+getattr(rig,'eye_stack_shape',np.zeros_like(delta))*t
                change,_=S.depth_bounds(cloud,ids,eye_points[np.asarray(eyes)],freedom,coherent=True,pulse=getattr(rig,'progress',None))
                request=np.minimum(change-baseline_eye,0.)/t
                path_shifts=np.minimum(path_shifts,request)
                if number==32:shifts=np.minimum(shifts,request)
        # A linear key cannot always keep contact throughout the path AND
        # end on the skin. Preserve final attachment; disclose path conflicts
        # instead of amplifying an early overlap into a floating endpoint.
        for number,unit in enumerate(units):
            selected=owners==number
            if not np.any(selected) or np.min(shifts[selected])>=-rig.widths['EYE',side]*1e-8:continue
            if unit['locked']:
                # Moving only free roots would stretch a card welded to Face.
                # Keep it intact and disclose the incompatible attachment.
                report['lash_locked_contact_units']+=1;report['lash_skin_depth_conflicts']+=1
                continue
            samples=np.einsum('kij,kj->ki',weights,unit['contact_x'][parents]).ravel()[selected]
            correction=contact_field(rig,unit,samples,shifts[selected],side)
            delta[unit['ids'],1]+=correction
            report['lash_contact_max_shift']=max(report['lash_contact_max_shift'],float(np.max(abs(correction))))
            report['lash_contact_units']+=1;report['lash_contact_vertices']+=len(unit['ids'])
        # Check the actual result after interpolation of the section field.
        # Contact/style labels alone are not evidence of a collision-free key.
        tolerance=rig.widths['EYE',side]*1e-5
        for attempt in range(4):
            posed=rig.points+delta
            cloud=np.einsum('kij,kja->kia',weights,posed[parents]).reshape((-1,3))
            residual=np.zeros(len(owners))
            if skin:
                change,_=S.depth_bounds(cloud,ids,posed[np.asarray(skin)],freedom,coherent=True)
                residual=np.minimum(residual,change-baseline_skin)
            if eyes:
                eye_points=rig.original_points+getattr(rig,'eye_stack_shape',np.zeros_like(delta))
                change,_=S.depth_bounds(cloud,ids,eye_points[np.asarray(eyes)],freedom,coherent=True)
                residual=np.minimum(residual,change-baseline_eye)
            if np.min(residual)>=-tolerance or attempt==3:break
            for number,unit in enumerate(units):
                selected=owners==number
                if unit['locked'] or not np.any(selected) or np.min(residual[selected])>=-tolerance:continue
                samples=np.einsum('kij,kj->ki',weights,unit['contact_x'][parents]).ravel()[selected]
                delta[unit['ids'],1]+=contact_field(rig,unit,samples,residual[selected],side)
        report['lash_skin_depth_conflicts']+=int(np.count_nonzero(residual<-tolerance))
        applied=np.einsum('kij,kj->ki',weights,(delta[:,1]-contact_start)[parents]).ravel()
        report['lash_path_contact_conflicts']=report.get('lash_path_contact_conflicts',0)+int(np.count_nonzero(path_shifts-applied<-tolerance))
        obstacle=surface(posed,skin);gaps=[]
        for unit in units:
            anchors=[i for i in unit['ids'] if i not in rig.strands]
            if not anchors:continue
            x=unit['contact_x'][anchors];span=max(float(np.ptp(x)),1e-12)
            sections={}
            for i,position in zip(anchors,x):
                gap=clearance(obstacle,posed[i]);old=unit['gaps'][i]
                if gap is None:continue
                offset=min(old,rig.widths['EYE',side]*.01) if old is not None else 0.
                section=min(int((position-float(x.min()))/span*16),15)
                sections[section]=min(sections.get(section,float('inf')),gap-offset)
            gaps.extend(max(gap,0.) for gap in sections.values())
        report['lash_attachment_max_gap']=max(report.get('lash_attachment_max_gap',0.),max(gaps,default=0.))
        report['lash_attachment_conflicts']=report.get('lash_attachment_conflicts',0)+sum(gap>rig.widths['EYE',side]*.015 for gap in gaps)
    report['eye_constraint_priority']='contact_and_closure_before_style'
    return delta,report


def fold_vertical_sections(rig,delta,recipe):
    """Curl the hanging end as a constant-curvature strip, retaining thickness."""
    rig.lash_fold_transforms={};rig.lash_before_fold=rig.points+delta.copy()
    report=dict(lash_fold_vertices=0,lash_fold_max_angle=0.,lash_fold_contact_conflicts=0,lash_fold_compressed_sections=0)
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text);closure=float(np.clip(eye['closure'],0,1));pair=rig.lash_lines.get(side)
        if closure<1-1e-6 or pair is None:continue
        base=pair[0];segments=lower_turns(base)
        band=upper_band(rig,side);ids=sorted({i for tri in band for i in tri if 0 not in rig.members[i]})
        if not segments or len(ids)<3:continue
        posed=rig.points+delta
        u=np.array([base.project(rig.points[i])[0] for i in ids]);sections=[]
        for turn,end in segments:
            selected=np.flatnonzero((u>=min(turn,end)-1e-8)&(u<=max(turn,end)+1e-8))
            if not len(selected):continue
            local=posed[np.asarray(ids)[selected]]
            pivot=local[np.argmax(local[:,2])].copy();pivot[1]=float(np.median(local[:,1]))
            length=max(float(pivot[2]-local[:,2].min()),rig.widths['EYE',side]*1e-5)
            before=base.sample(end)-base.sample(turn)
            angle=min(np.arctan2(abs(before[2]),max(abs(before[0]),1e-12)),np.deg2rad(85.))*closure
            # Cylindrical bending preserves centreline arc length. Bound the
            # radius by card depth, avoiding an inverted inside surface.
            depth=max(float(np.max(abs(local[:,1]-pivot[1]))),1e-12)
            curvature=min(angle/length,.3/depth);angle=curvature*length
            if curvature<1e-8:continue
            for k in selected:
                blend=float(np.clip(abs(u[k]-turn)/max(abs(end-turn)*.6,1e-12),0,1))
                blend=blend**3*(10-15*blend+6*blend*blend)
                bend=curvature*blend
                if bend<1e-8:continue
                i=ids[k];distance=max(float(pivot[2]-posed[i,2]),0.);theta=bend*distance
                offset=posed[i,1]-pivot[1];target=posed[i].copy()
                target[1]=pivot[1]+(1-np.cos(theta))/bend+offset*np.cos(theta)
                target[2]=pivot[2]-np.sin(theta)/bend+offset*np.sin(theta)
                delta[i]=target-rig.points[i];report['lash_fold_vertices']+=1
            sections.append(dict(turn=turn,end=end,pivot=pivot,curvature=curvature))
            report['lash_fold_max_angle']=max(report['lash_fold_max_angle'],float(np.rad2deg(angle)))
        rig.lash_fold_transforms[side]=sections
    return delta,report


def finish_upper_sweep(rig,delta,recipe,lids,only_open=False):
    """Transport full rest sections on one final curve, with continuous frames."""
    rig.lash_final_transports=dict(getattr(rig,'lash_open_transports',{}))
    report=dict(lash_sweep_vertices=0,lash_sweep_max_correction=0.,lash_sweep_section_distortion=0.)
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text);lid=lids.get(side);pair=rig.lash_lines.get(side)
        if (eye['closure']<1-1e-6)!=only_open:continue
        explicit=bool(eye.get('open_motion')) and eye['closure']<1-1e-6
        if only_open and not explicit:continue
        if lid is None or pair is None or (eye['closure']<=1e-8 and not explicit):continue
        ids=upper_vertices(rig,side)
        if len(ids)<4:continue
        base=pair[0];parameters=np.array([base.project(rig.points[i])[0] for i in ids])
        def initial(point):
            return rig.lash_transport(side,point,lid,eye['closure'],eye.get('lash_shape_preserve',0.),eye.get('flat',0.))
        expected=np.array([initial(rig.points[i])[0] for i in ids])
        residual=rig.points[ids]+delta[ids]-expected
        # The style/coverage/fold stages determine the final centre. Their
        # per-section translations must also turn the section frames; leaving
        # the original frames in place produces an angular sheared ribbon.
        count=7;matrix=B.spline_basis(parameters,count)
        second=np.diff(np.eye(count),n=2,axis=0)
        controls=np.linalg.solve(matrix.T@matrix+.35*second.T@second+np.eye(count)*1e-9,matrix.T@residual)
        sample_t=np.linspace(0,1,65)
        original_centres=np.array([initial(base.sample(t))[0] for t in sample_t])
        centre_controls=B.fit_bezier(original_centres,sample_t)
        rest_controls=None;seam_controls=None;seam_lo=0.;seam_span=1.;inset=0.;depth_inset=0.
        if eye['closure']>=1-1e-6 or explicit:
            # The guide may run along an edge of a thick, tapered card. Its
            # varying offset is not a new centreline bend. Measure the rest
            # section centres, then retain only offsets *within* each section.
            rest_centres=[];posed_centres=[];posed=rig.points+delta
            for t in sample_t:
                near=np.flatnonzero(abs(parameters-t)<=.04)
                if len(near)<4:near=np.argsort(abs(parameters-t))[:min(4,len(ids))]
                local=np.asarray(ids)[near]
                rest_centres.append(np.mean(rig.points[local],axis=0))
                posed_centres.append(np.mean(posed[local],axis=0))
            # Sparse front/back card vertices can swap the nearest section
            # abruptly. Fitting 13 controls to those means introduces loops
            # and up to a 180-degree frame flip into an otherwise smooth band.
            # A monotone cubic keeps the measured span and a continuous frame.
            rest_controls=B.fit_bezier(rest_centres,sample_t)
            centre_controls=B.fit_bezier(posed_centres,sample_t)
            controls[:]=0.
            rim=sorted({i for i,u,upper in rig.rows['EYE',side] if not explicit or upper or u<1e-7 or u>1-1e-7})
            x,inverse=np.unique(posed[rim,0],return_inverse=True)
            z=np.bincount(inverse,posed[rim,2])/np.bincount(inverse)
            y=np.bincount(inverse,posed[rim,1])/np.bincount(inverse)
            seam_lo=float(x[0]);seam_span=max(float(x[-1]-x[0]),1e-12)
            t=(x-seam_lo)/seam_span
            if explicit:
                curve=np.array([lid(u,True) for u in sample_t]);order=np.argsort(curve[:,0]);curve=curve[order]
                seam_lo=float(curve[0,0]);seam_span=max(float(curve[-1,0]-curve[0,0]),1e-12)
                t=(curve[:,0]-seam_lo)/seam_span;curve[:,0]=t
                seam_controls=np.linalg.lstsq(B.spline_basis(t,13),curve,rcond=None)[0]
            else:
                seam_controls=B.fit_bezier(np.column_stack((t,y,z)),t)
                chord=np.linspace(seam_controls[0,2],seam_controls[-1,2],4)
                handles=B.upward_handles(seam_controls[1:3,2]-chord[1:3])
                if eye.get('flat',0.)>.5:handles[:]=0.
                elif eye.get('smile',0.)<=.5:handles=-handles
                seam_controls[:,2]=chord;seam_controls[1:3,2]+=handles
            # The closed band is anchored to the same XYZ seam as Face.
            # Old open-eye depth and a negative median Z residual must not
            # suspend it in front of, or separate it below, the lower band.
            if not explicit:inset=max(float(np.median(np.asarray(posed_centres)[:,2]-B.bezier(seam_controls,(np.asarray(posed_centres)[:,0]-seam_lo)/seam_span)[:,2])),0.)
            upper_ids=sorted({i for i,u,up in rig.rows['EYE',side] if up or u<1e-7 or u>1-1e-7})
            rest_x,group=np.unique(rig.original_points[upper_ids,0],return_inverse=True)
            rest_y=np.bincount(group,rig.original_points[upper_ids,1])/np.bincount(group)
            centers=np.asarray(rest_centres)
            depth_inset=float(np.clip(np.median(centers[:,1]-np.interp(centers[:,0],rest_x,rest_y)),-rig.widths['EYE',side]*.05,0.))
            if explicit:
                rest_z=np.bincount(group,rig.original_points[upper_ids,2])/np.bincount(group)
                inset=float(np.clip(np.median(centers[:,2]-np.interp(centers[:,0],rest_x,rest_z)),0.,rig.widths['EYE',side]*.08))
        folds=[]
        # A closing arc changes height and depth, not the material's span.
        # Ordinary blinks retain the original inner-corner correction.
        lock_span=rest_controls is not None and not explicit
        ordinary=eye.get('smile',0.)<=.5 and eye.get('flat',0.)<=.5
        inner_end=0. if abs(base.sample(0.)[0]-rig.info['plane'])<abs(base.sample(1.)[0]-rig.info['plane']) else 1.
        def make_transport(base,centre_controls,controls,folds,rest_controls,seam_controls,seam_lo,seam_span,inset,depth_inset,lock_span,ordinary,inner_end):
            def centre(t):
                point=B.bezier(centre_controls,t)+(B.spline_basis([t],len(controls))@controls)[0]
                if lock_span:
                    rest=(B.spline_basis([t],len(rest_controls))@rest_controls)[0]
                    keep=1.
                    if ordinary:
                        q=float(np.clip(abs(t-inner_end)/.38,0,1))
                        keep=.9*(1-q**3*(10-15*q+6*q*q))
                    point[0]+=keep*(rest[0]-point[0])
                if seam_controls is not None:
                    t=(point[0]-seam_lo)/seam_span
                    if len(seam_controls)==4:
                        repaired=bool(getattr(rig,'recovered_lash_groups',[])) or any(
                            r.get('reason')=='eyelid_surface_support' for r in rig.info['accessory_ownership']['components'])
                        seam=(closed_curve_extension(seam_controls,t) if repaired
                              else B.bezier(seam_controls,t))
                    else:
                        clipped=float(np.clip(t,0,1));seam=(B.spline_basis([clipped],len(seam_controls))@seam_controls)[0]
                        if t!=clipped:
                            lo=max(clipped-.001,0.);hi=min(clipped+.001,1.)
                            ends=B.spline_basis([lo,hi],len(seam_controls))@seam_controls
                            seam+=(ends[1]-ends[0])/(hi-lo)*(t-clipped)
                    point[1]=seam[1]+depth_inset;point[2]=seam[2]+inset
                return point
            def rest_centre(t):
                return base.sample(t) if rest_controls is None else (B.spline_basis([t],len(rest_controls))@rest_controls)[0]
            def transport(point):
                u=base.project(point)[0]
                anchor=centre(u)
                before=B.spatial_frame(rest_centre,u);after=B.spatial_frame(centre,u)
                angle=0.
                for fold in folds:
                    if not min(fold['turn'],fold['end'])<=u<=max(fold['turn'],fold['end']):continue
                    blend=float(np.clip(abs(u-fold['turn'])/max(abs(fold['end']-fold['turn'])*.6,1e-12),0,1))
                    blend=blend**3*(10-15*blend+6*blend*blend)
                    angle+=fold['curvature']*blend*max(float(fold['pivot'][2]-anchor[2]),0.)
                angle*=1 if after[0,0]>=0 else -1
                c,s=np.cos(angle),np.sin(angle)
                roll=np.array(((1.,0.,0.),(0.,c,-s),(0.,s,c)))
                transform=after@roll@before.T
                if getattr(rig, 'lash_return_groups', []):
                    planar=np.arctan2(before[2,0],before[0,0])-np.arctan2(after[2,0],after[0,0])
                    transform=np.asarray(Matrix.Rotation(float(planar),3,'Y'))
                target=anchor+transform@(np.asarray(point)-rest_centre(u))
                # Lock the centreline span above, not each vertex after its
                # rotation. Overwriting X here shears the section and breaks
                # its continuous join to the lower-owned canthus.
                return target,transform,after[:,0]
            return transport
        transport=make_transport(base,centre_controls,controls,folds,rest_controls,seam_controls,seam_lo,seam_span,inset,depth_inset,lock_span,ordinary,inner_end)
        transported=[transport(rig.points[i]) for i in ids]
        target=np.array([item[0] for item in transported])
        report['lash_sweep_section_distortion']=max(report['lash_sweep_section_distortion'],max(float(np.max(abs(frame.T@frame-np.eye(3)))) for _,frame,_ in transported))
        report['lash_sweep_max_correction']=max(report['lash_sweep_max_correction'],float(np.max(np.linalg.norm(target-rig.points[ids]-delta[ids],axis=1))))
        delta[ids]=target-rig.points[ids];rig.lash_final_transports[side]=transport
        report['lash_sweep_vertices']+=len(ids)
    return delta,report


def prepare_open_rim(rig,delta,recipe,lids):
    """The open facial rim and lash band use the same section transport."""
    report={}
    rig.lash_open_transports={};rig.lash_open_depth={}
    count=0
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text);lid=lids.get(side)
        if eye['closure']>=1-1e-6 or lid is None or side not in rig.lash_lines:continue
        if side not in rig.lash_open_transports:
            def make_transport(side,lid,eye):
                return lambda point:rig.lash_transport(side,point,lid,eye['closure'],eye.get('lash_shape_preserve',0.),eye.get('flat',0.))
            rig.lash_open_transports[side]=make_transport(side,lid,eye)
        transport=rig.lash_open_transports[side];rows=rig.rows['EYE',side]
        fixed=eye.get('open_motion',{}).get('lower_fixed',0.)>=1-1e-8
        lower_ids={i for i,u,upper in rows if not upper or u<1e-7 or u>1-1e-7}
        upper_ids={i for i,u,upper in rows if upper or u<1e-7 or u>1-1e-7}
        explicit=bool(eye.get('open_motion'))
        if explicit:upper_ids-=lower_ids
        end_ids=[min(rows,key=lambda row:abs(row[1]-end))[0] for end in (0,1)]
        before={i:rig.points[i]+delta[i].copy() for i in end_ids}
        lower_curve=rig.points[sorted(lower_ids)]+delta[sorted(lower_ids)]
        lower_curve=lower_curve[np.argsort(lower_curve[:,0])]
        base=rig.lash_lines[side][0]
        parameters={i:u for i,u,up in rows}
        for i in upper_ids:
            point=rig.points[i];u=base.project(point)[0];anchor=base.sample(u)
            # Face is a surface attached to the band, not a thick band
            # cross-section. Rotating its long transverse offset folds the
            # inner rim across the fixed lower canthus and into the nose.
            target=point+transport(anchor)[0]-anchor
            
            if explicit:
                floor=float(np.interp(target[0],lower_curve[:,0],lower_curve[:,2]))
                target[2]=min(max(target[2],floor),point[2])
            delta[i]=target-point
        ends=[rig.points[i]+delta[i]-before[i] for i in end_ids]
        for i,u,upper in rows:
            if i in upper_ids:continue
            if fixed:delta[i]=0.;continue
            if explicit:
                delta[i]=lid(u,False)-rig.points[i]
                continue
            q=np.clip(np.array((u,1-u))/.25,0,1);weight=1-q**3*(10-15*q+6*q*q)
            delta[i]+=weight@np.asarray(ends)
        ids=sorted(upper_ids|set(end_ids));posed=rig.points[ids]+delta[ids]
        x,group=np.unique(posed[:,0],return_inverse=True)
        y=np.bincount(group,posed[:,1])/np.bincount(group)
        rig.lash_open_depth[side]=B.DepthCurve(x,y);count+=len(ids)
    rig.lash_final_transports=dict(rig.lash_open_transports)
    report['open_rim_shared_vertices']=count
    return delta,report


def update_open_depth(rig,profiles):
    """Transfer only the later facial depth correction to the shared sweep."""
    for side,transport in list(getattr(rig,'lash_open_transports',{}).items()):
        before=rig.lash_open_depth[side];after=profiles[side,True]
        def updated(transport,before,after):
            def follow(point):
                posed,frame,axis=transport(point);posed=posed.copy()
                posed[1]+=float(after.sample(posed[0])-before.sample(posed[0]))
                return posed,frame,axis
            return follow
        follow=updated(transport,before,after)
        
        rig.lash_open_transports[side]=follow
    rig.lash_final_transports=dict(rig.lash_open_transports)


def orbital_section_transport(rig,delta,side,roll_corners=False):
    """Rotate sections continuously around the entire actual orbital rim.

    Include the lower continuations in the binding curve. Projecting a long
    vertical wing to one upper-guide endpoint treats its length as thickness.
    The open rim is one material curve, so no upper/lower transform seam is
    needed at either canthus.
    """
    rows=rig.rows['EYE',side]
    chains={up:sorted({(u,i) for i,u,upper in rows if upper==up or u<1e-7 or u>1-1e-7}) for up in (False,True)}
    lower_ids=[i for u,i in chains[False]];upper_ids=[i for u,i in chains[True]]
    middle=len(lower_ids)//2
    indices=lower_ids[middle:0:-1]+upper_ids+lower_ids[-2:middle-1:-1]
    base=B.Line(rig.points[indices]);posed=rig.points[indices]+delta[indices]
    edges=[Matrix(rotation(a,b).tolist()).to_quaternion() for a,b in zip(np.diff(base.points,axis=0),np.diff(posed,axis=0))]
    if roll_corners:
        # A closed aperture has coincident upper/lower paths. Turning the
        # entire corner in XZ makes the material double back on itself. Roll
        # its section toward depth instead; the lower rim still supplies the
        # exact anchor and the card retains its cross-section and X span.
        edges=[Matrix.Rotation(min(float(q.angle),np.pi*.5),3,'X').to_quaternion() for q in edges]
    frames=[edges[0]]+[a.slerp(b,.5) for a,b in zip(edges[:-1],edges[1:])]+[edges[-1]]
    # Lightly soften changes between neighboring section rotations. This
    # rounds the wing's outer edge without shortening its cross-section.
    frames=[frames[0]]+[q.slerp(a.slerp(b,.5),.20) for a,q,b in zip(frames[:-2],frames[1:-1],frames[2:])]+[frames[-1]]
    first=base.parameters[middle];last=base.parameters[middle+len(upper_ids)-1]
    transition=max((last-first)*.20,1e-12)
    def ownership(u):
        distance=min(u-first,last-u)
        q=float(np.clip(1-distance/transition,0,1))
        return q**3*(10-15*q+6*q*q)
    def follow(point):
        u=base.project(point)[0];k=int(np.clip(np.searchsorted(base.parameters,u,side='right')-1,0,len(indices)-2))
        t=float(np.clip((u-base.parameters[k])/max(base.parameters[k+1]-base.parameters[k],1e-12),0,1))
        frame=np.asarray(frames[k].slerp(frames[k+1],t).normalized().to_matrix())
        anchor=posed[k]*(1-t)+posed[k+1]*t
        return anchor+frame@(point-base.sample(u)),frame,frame[:,0]
    follow.base=base;follow.ownership=ownership
    return follow


def lower_owned_upper_sections(rig,delta,recipe):
    """Turn a detached returned card on its lower-rim direction at its upper root.

    One rigid frame per physical card retains its length and thickness. The
    upper card supplies the attachment point; projecting every vertex onto a
    different lower-rim segment would detach the root and shear the hook.
    """
    report=dict(upper_lash_lower_follow_vertices=0,upper_lash_lower_follow_max_shift=0.,upper_lash_inner_smoothed_sides=[])
    owners={r['id']:r for r in rig.info['accessory_ownership']['components']}
    for group in getattr(rig,'lash_return_groups',[]):
        side=group['side'];eye=recipe.get('eyes',{}).get(str(side),{})
        closure=float(eye.get('closure',0.))
        if closure<1-1e-6:continue
        ids=group['vertices'];host=set(owners[group['parent']]['vertices'])
        triangles=[list(t) for t,f in rig.mesh_triangles if set(t)<=host]
        if not triangles:continue
        tree=BVHTree.FromPolygons([Vector(p) for p in rig.points],triangles)
        roots=[tree.find_nearest(Vector(rig.points[i])) for i in ids]
        k=min(range(len(ids)),key=lambda j:roots[j][3]);root=rig.points[ids[k]]
        hit,normal,number,distance=roots[k];triangle=triangles[number]
        a=rig.points[triangle];uv=np.linalg.lstsq(np.column_stack((a[1]-a[0],a[2]-a[0])),np.asarray(hit)-a[0],rcond=None)[0]
        weights=np.array((1-uv.sum(),*uv));posed=rig.points+delta
        # The final host rotation carries the small embedded root offset.
        transport=rig.lash_final_transports.get(side)
        frame=transport(root)[1] if transport else np.eye(3)
        anchor=weights@posed[triangle]+frame@(root-np.asarray(hit))
        tip=rig.points[max(ids,key=lambda i:np.linalg.norm(rig.points[i]-root))]
        source=tip-root
        lower,follow=rig.lash_lower_transports[side]
        u=lower.project(tip)[0];lo=max(0.,u-.025);hi=min(1.,u+.025)
        tangent=follow(lower.sample(hi))[0]-follow(lower.sample(lo))[0]
        if tangent[0]*side>0:tangent=-tangent
        # Keep the authored depth profile. A free 3D shortest rotation can
        # stand the thin card upright when the orbital tangent has depth.
        # The return bends in the face plane, on the lower lid's XZ tangent.
        angle=np.arctan2(source[2],source[0])-np.arctan2(tangent[2],tangent[0])
        angle=float(np.arctan2(np.sin(angle),np.cos(angle)))
        angle=float(np.clip(angle,-np.deg2rad(150.),np.deg2rad(150.)))
        turn=np.asarray(Matrix.Rotation(angle,3,'Y'))
        for i in ids:
            target=anchor+turn@(rig.points[i]-root)
            report['upper_lash_lower_follow_max_shift']=max(report['upper_lash_lower_follow_max_shift'],float(np.linalg.norm(target-rig.points[i]-delta[i])))
            delta[i]=target-rig.points[i]
        report['upper_lash_lower_follow_vertices']+=len(ids)
    return delta,report


def covering_shift(parameters,lower,upper,evaluate,edge_bounds=None,pulse=None):
    """One C2 displacement curve constrained by both sides of the ribbon."""
    count=13;matrix=B.spline_basis(parameters,count)
    second=np.diff(np.eye(count),n=2,axis=0)
    metric=np.linalg.inv(np.eye(count)+4*second.T@second)
    if edge_bounds is not None:
        edge_matrix,edge_lower,edge_upper=edge_bounds
        matrix=np.vstack((matrix,edge_matrix))
        lower=np.r_[lower,edge_lower];upper=np.r_[upper,edge_upper]
    rows=np.vstack((matrix,-matrix));bounds=np.r_[upper,-np.asarray(lower)]
    directions=rows@metric;norm=np.sum(rows*directions,axis=1)
    tolerance=max(float(np.ptp(bounds))*1e-7,1e-11)
    from .procedural_projection import project
    controls=project(rows,bounds,directions,norm,tolerance,pulse=pulse)
    return B.spline_basis(evaluate,count)@controls


def lower_edge_bounds(rig,posed,local,band,seam_x,seam_z,origin,span,width):
    """Constrain real triangle edges at changes in the upper silhouette.

    Interior edge positions interpolate the displacement of their endpoints;
    evaluating the smooth curve at the interior position would instead test
    a curved surface that the exported mesh does not contain.
    """
    selected=set(local);edges=set()
    for tri,f in rig.mesh_triangles:
        if set(tri)<=selected:
            edges.update(tuple(sorted((tri[k],tri[(k+1)%3]))) for k in range(3))
    events=np.unique(posed[np.asarray(band),0]);sections=BandSections(posed[np.asarray(band)])
    rows=[];bounds=[];links=[]
    for i,j in sorted(edges):
        a,b=posed[[i,j]]
        if abs(a[0]-b[0])<width*1e-9:continue
        lo,hi=sorted((a[0],b[0]));xs=events[(events>lo+width*1e-9)&(events<hi-width*1e-9)]
        knots=np.r_[lo,xs,hi]
        xs=np.unique(np.r_[xs,(knots[:-1]+knots[1:])*.5,np.linspace(lo,hi,9)[1:-1]])
        ts=(xs-a[0])/(b[0]-a[0])
        basis=B.spline_basis((rig.points[[i,j],0]-origin)/span,13)
        for x,t in zip(xs,ts):
            intervals=sections(x,width*1e-8)
            if not intervals:continue
            seam=float(np.interp(x,seam_x,seam_z))
            bottom,top=min(intervals,key=lambda p:max(p[0]-seam,seam-p[1],0.))
            inset=min((top-bottom)*.02,width*.001);height=a[2]*(1-t)+b[2]*t
            rows.append(basis[0]*(1-t)+basis[1]*t)
            bounds.append((bottom+inset-height,top-inset-height));links.append((i,j,t))
    return np.asarray(rows).reshape((-1,13)),np.asarray(bounds).reshape((-1,2)),links


def cover_lower_band(rig,delta,recipe):
    """Fit both lower-strip edges inside the upper footprint, then behind it."""
    report=dict(lower_lid_order_vertices=0,lower_lid_order_conflicts=0,lower_lid_depth_vertices=0)
    excluded=rig.brows|rig.creases|rig.strands|getattr(rig,'upper_followers',set())
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text)
        if eye['closure']<1-1e-6 or side not in rig.rings:continue
        band=upper_band(rig,side)
        ids=lower_vertices(rig,side)
        if not band or not ids:continue
        posed=rig.points+delta;triangles=posed[np.asarray(band)];width=rig.widths['EYE',side]
        rim=sorted({i for i,u,up in rig.rows['EYE',side]})
        seam_x,groups=np.unique(posed[rim,0],return_inverse=True)
        seam_z=np.bincount(groups,posed[rim,2])/np.bincount(groups)
        checked={};sections=BandSections(triangles)
        for i in ids:
            intervals=sections(posed[i,0],width*1e-8)
            if not intervals:continue
            # Every lower vertex at a section must tuck under the SAME
            # ribbon. Choosing its nearest interval independently can send
            # opposite edges to separate front/back cards, making a smooth
            # covering curve mathematically impossible.
            seam=float(np.interp(posed[i,0],seam_x,seam_z))
            lo,hi=min(intervals,key=lambda p:max(p[0]-seam,seam-p[1],0.))
            inset=min((hi-lo)*.02,width*.001);checked[i]=(lo+inset,hi-inset)
        if not checked:continue
        units,_=contact_units(rig,side);selected=set(ids)
        for unit in units:
            local=sorted(set(unit['ids'])&selected)
            if not local or unit['locked']:continue
            bound=[i for i in local if i in checked]
            if not bound:continue
            x=rig.points[local,0];origin=float(x.min());span=max(float(np.ptp(x)),1e-12)
            t=(rig.points[bound,0]-origin)/span
            low=np.array([checked[i][0]-posed[i,2] for i in bound]);high=np.array([checked[i][1]-posed[i,2] for i in bound])
            controls=np.column_stack((np.linspace(0,1,4),np.zeros(4),np.zeros(4)))
            controls,conflicts=B.bounded_height(controls,t,low,high)
            shift=B.bezier(controls,(x-origin)/span)[:,2]
            
            delta[local,2]+=shift
            report['lower_lid_order_vertices']+=int(np.count_nonzero(abs(shift)>width*1e-8))
        posed=rig.points+delta
        report['lower_lid_order_conflicts']+=int(sum(not lo-width*1e-6<=posed[i,2]<=hi+width*1e-6 for i,(lo,hi) in checked.items()))
        lower_triangles=[list(t) for t,f in rig.mesh_triangles if set(t)<=selected]
        freedom=np.zeros(len(delta));freedom[ids]=1.
        if lower_triangles:
            required,_=S.depth_bounds(posed,lower_triangles,posed[np.asarray(band)],freedom,front=False,coherent=True)
            for unit in units:
                local=sorted(set(unit['ids'])&selected)
                if not local or unit['locked'] or np.max(required[local])<=width*1e-8:continue
                subset=dict(ids=local,contact_x=unit['contact_x'])
                shift=-contact_field(rig,subset,subset['contact_x'][local],-required[local],side)
                delta[local,1]+=shift;report['lower_lid_depth_vertices']+=int(np.count_nonzero(shift>width*1e-8))
    return delta,report


def audit_closed_band(rig,delta,recipe):
    """Measure seam coverage after the sweep and final depth contact."""
    report=dict(lash_final_seam_sections=0,lash_final_seam_conflicts=0)
    posed=rig.points+delta
    for side_text,eye in recipe.get('eyes',{}).items():
        side=int(side_text)
        if eye['closure']<1-1e-6 or side not in rig.rings:continue
        band=upper_band(rig,side)
        if not band:continue
        rim=sorted({i for i,u,upper in rig.rows['EYE',side]})
        x,inverse=np.unique(posed[rim,0],return_inverse=True)
        z=np.bincount(inverse,posed[rim,2])/np.bincount(inverse)
        samples=np.unique(np.r_[x,(x[:-1]+x[1:])*.5]);tolerance=rig.widths['EYE',side]*1e-7
        triangles=posed[np.asarray(band)]
        for value in samples:
            intervals=band_intervals(triangles,value,tolerance);height=float(np.interp(value,x,z))
            report['lash_final_seam_sections']+=1
            report['lash_final_seam_conflicts']+=int(not any(lo-tolerance<=height<=hi+tolerance for lo,hi in intervals))
    return report


def finish_closed_order(rig,delta,recipe):

    """Keep the lower cards behind the upper assembly after Face contact."""

    report=dict(lower_lash_final_exposed_vertices=0,lower_lash_final_depth_conflicts=0,

                lower_lash_order_max_shift=0.,lower_lash_order_inward_shift=0.)

    excluded=rig.brows|rig.creases|rig.strands|getattr(rig,'upper_followers',set())

    for text,eye in recipe.get('eyes',{}).items():

        side=int(text)

        if eye['closure']<1-1e-6 or side not in rig.rings:continue

        upper=upper_band(rig,side);upper_ids={i for tri in upper for i in tri}

        lower=set(lower_vertices(rig,side))

        triangles=[list(t) for t,f in rig.mesh_triangles if set(t)<=lower]

        if not upper or not triangles:continue

        units,skin=contact_units(rig,side);freedom=np.zeros(len(delta));freedom[list(upper_ids)]=1.

        width=rig.widths['EYE',side];posed=rig.points+delta


        change,_=S.depth_bounds(posed,upper,posed[np.asarray(triangles)],freedom,coherent=True)

        for unit in units:

            bound=sorted(upper_ids&set(unit['ids']))

            if not bound or unit['locked'] or np.min(change[bound])>=-width*1e-7:continue

            shift=contact_field(rig,unit,unit['contact_x'][bound],change[bound],side)

            delta[unit['ids'],1]+=shift

            report['lower_lash_order_max_shift']=max(report['lower_lash_order_max_shift'],float(np.max(abs(shift))))

        posed=rig.points+delta

        remaining,_=S.depth_bounds(posed,upper,posed[np.asarray(triangles)],freedom,coherent=True)

        report['lower_lash_final_depth_conflicts']+=int(np.count_nonzero(remaining<-width*1e-6))

        for i in lower:

            intervals=band_intervals(posed[np.asarray(upper)],posed[i,0],width*1e-7)

            report['lower_lash_final_exposed_vertices']+=int(not any(lo-width*1e-6<=posed[i,2]<=hi+width*1e-6 for lo,hi in intervals))

    return delta,report


def audit_attachment(rig,delta,recipe):
    """Measure the delivered geometry, including the final depth ordering."""
    posed=rig.points+delta;report=dict(lash_attachment_max_gap=0.,lash_attachment_conflicts=0)
    for text in recipe.get('eyes',{}):
        side=int(text)
        if side not in rig.rings:continue
        units,skin=contact_units(rig,side);obstacle=surface(posed,skin)
        for unit in units:
            anchors=[i for i in unit['ids'] if i not in rig.strands]
            if not anchors:continue
            x=unit['contact_x'][anchors];span=max(float(np.ptp(x)),1e-12);sections={}
            for i,position in zip(anchors,x):
                gap=clearance(obstacle,posed[i]);old=unit['gaps'][i]
                if gap is None:continue
                offset=min(old,rig.widths['EYE',side]*.01) if old is not None else 0.
                section=min(int((position-float(x.min()))/span*16),15)
                sections[section]=min(sections.get(section,float('inf')),gap-offset)
            gaps=[max(gap,0.) for gap in sections.values()]
            report['lash_attachment_max_gap']=max(report['lash_attachment_max_gap'],max(gaps,default=0.))
            report['lash_attachment_conflicts']+=sum(gap>rig.widths['EYE',side]*.015 for gap in gaps)
    return report


def audit_connections(rig,delta):
    """Check physical seam copies after every contact and follower pass."""
    posed=rig.points+delta;maximum=0.;conflicts=0
    tolerance=max(rig.widths.values(),default=1.)*1e-6
    for group in getattr(rig,'lash_stitches',[]):
        separation=float(np.linalg.norm(np.ptp(posed[group],axis=0)))
        maximum=max(maximum,separation);conflicts+=int(separation>tolerance)
    attached=np.flatnonzero(getattr(rig,'lash_lower_weights',np.zeros(len(delta)))>=1-1e-6)
    attachment_error=float(np.max(np.linalg.norm(posed[attached]-rig.lash_lower_targets[attached],axis=1))) if len(attached) else 0.
    return dict(lash_seam_separation=maximum,lash_seam_connection_conflicts=conflicts,
                lower_wing_priority_vertices=len(attached),lower_wing_attachment_error=attachment_error)


def band_motion_curve(rig,delta,side,lid=None,eye=None):
    """One smooth final XYZ motion curve shared by upper-lid attachments."""
    ids=sorted({i for tri in upper_band(rig,side) for i in tri})
    if len(ids)<3:return None
    x=rig.points[ids,0];lo=float(x.min());span=max(float(np.ptp(x)),1e-12)
    base=rig.lash_lines.get(side,(None,None))[0]
    arc=base is not None and lid is not None and eye is not None
    location=np.array([base.project(rig.points[i])[0] for i in ids]) if arc else (x-lo)/span
    values=delta[ids].copy()
    if arc:
        final=getattr(rig,'lash_final_transports',{}).get(side)
        expected=np.array([final(rig.points[i])[0] if final else rig.lash_position(side,rig.points[i],lid,eye['closure'],eye.get('lash_shape_preserve',0.),eye.get('flat',0.)) for i in ids])
        values-=expected-rig.points[ids]
    parameters=np.linspace(0,1,65);samples=[]
    for t in parameters:
        near=np.flatnonzero(abs(location-t)<=.035)
        if len(near)<3:near=np.argsort(abs(location-t))[:min(3,len(ids))]
        samples.append(np.median(values[near],axis=0))
    matrix=B.spline_basis(parameters);regular=np.diff(np.eye(13),n=2,axis=0)
    controls=np.linalg.solve(matrix.T@matrix+.2*regular.T@regular+np.eye(13)*1e-9,matrix.T@np.asarray(samples))
    def evaluate(point):
        t=base.project(point)[0] if arc else (point[0]-lo)/span
        return (B.spline_basis([np.clip(t,0,1)])@controls)[0]
    return evaluate


def follow_creases(rig,delta,recipe,lids=None):
    """Attach creases to eye-only Face motion, independent of brows/lashes."""
    rest=rig.points;motion=getattr(rig,'crease_skin_motion',np.zeros_like(delta))
    rims={i for rows in rig.rows.values() for i,u,upper in rows};changed=set()
    accessories=list(rig.accessories)+[(s,'CREASE',ids,None) for s,ids in getattr(rig,'upper_follower_groups',[])]
    for side in rig.rings:
        triangles=[list(t) for t in rig.field.triangles if not set(t)&rig.creases
                   and set(t)&rig.eye_skin.regions.get(side,set())]
        if not triangles:continue
        tree=BVHTree.FromPolygons([Vector(p) for p in rest],triangles)
        for s,kind,ids,entry in accessories:
            if s!=side or kind!='CREASE':continue
            for i in sorted(set(ids)-rims-rig.brows):
                if str(side) not in recipe.get('eyes',{}):
                    delta[i]=0.;changed.add(i);continue
                hit,normal,index,distance=tree.find_nearest(Vector(rest[i]))
                if hit is None:continue
                tri=triangles[index];cloud=rest[tri]
                uv=np.linalg.lstsq(np.column_stack((cloud[1]-cloud[0],cloud[2]-cloud[0])),np.asarray(hit)-cloud[0],rcond=None)[0]
                weights=np.array((1-uv.sum(),uv[0],uv[1]))
                delta[i]=weights@motion[tri]
                if entry is not None:delta[i]+=B.edit_offset(entry,rest[i])
                changed.add(i)
    return delta,dict(crease_follow_vertices=len(changed))

def bend(points,root,axis,length,controls,transform,section_dimension):
    axial=(points-root)@axis;u=np.clip(axial/length,0,1)
    offset=points-root-axial[:,None]*axis
    centers=B.bezier(controls,u)
    tangent=3*((1-u)[:,None]**2*(controls[1]-controls[0])+2*(u*(1-u))[:,None]*(controls[2]-controls[1])+u[:,None]**2*(controls[3]-controls[2]))
    norm=np.linalg.norm(tangent,axis=1);speed=np.maximum(norm,length*.1)
    tangent/=np.maximum(norm[:,None],1e-12)
    # Local arc stretch times section measure remains approximately constant.
    # Cards have one transverse dimension; solid strands have two.
    scale=np.clip((length/speed)**(1/section_dimension),.75,1.33)
    posed=np.array([p+rotation(transform@axis,d)@transform@(q*s) for p,d,q,s in zip(centers,tangent,offset,scale)])
    posed+=(axial-length*u)[:,None]*tangent
    weight=np.clip((u-.2)/.3,0,1);weight=weight**3*(10-15*weight+6*weight*weight)
    attached=controls[0]+(points-root)@transform.T
    return attached*(1-weight[:,None])+posed*weight[:,None],u,weight


def deform(rig,delta,recipe,lids,shared_closed=False):
    """Bend each strand once; shared band vertices remain exact anchors."""
    if not rig.lashes or not recipe.get('eyes'):
        return delta,dict(lash_bent_units=0,lash_exposure_conflicts=0)
    rest=rig.points;posed=rest+delta
    band={i for unit in rig.lashes for i in unit.get('band_vertices',[])}
    root_faces={side:[] for side in rig.rings};band_faces={side:[] for side in rig.rings}
    for tri,f in rig.mesh_triangles:
        label=rig.info['labels'][f];ids=set(tri)
        skin=label==0 and not ids.issubset(rig.creases)
        strip=label==2 and not ids.intersection(rig.strands|rig.brows|rig.creases)
        if skin or strip:
            side=1 if rest[list(tri),0].mean()>=rig.info['plane'] else -1
            if side in root_faces:root_faces[side].append(list(tri))
            if strip and side in band_faces and not ids.intersection(getattr(rig,'upper_followers',set())):band_faces[side].append(list(tri))
    trees={side:BVHTree.FromPolygons([Vector(p) for p in rest],faces) for side,faces in root_faces.items() if faces}
    band_trees={side:BVHTree.FromPolygons([Vector(p) for p in rest],faces) for side,faces in band_faces.items() if faces}
    total=np.zeros_like(delta);counts=np.zeros(len(delta));units=0;conflicts=0;shared_follow=0
    physical=rig.lashes
    motion_curves={int(side):band_motion_curve(rig,delta,int(side),lids.get(int(side)),eye) for side,eye in recipe.get('eyes',{}).items()}
    for number,unit in enumerate(physical,1):
        notify(rig,'单根睫毛随睫毛带运动',number,len(physical))
        eye=recipe.get('eyes',{}).get(str(unit['side']))
        side=unit['side'];lid=lids.get(side)
        if eye is None or lid is None:continue
        ids=sorted(set(unit['vertices'])-band-{i for i in unit['vertices'] if 0 in rig.members[i]})
        if not ids:continue
        root,tip=np.asarray(unit['base']);edited_root,edited_tip=np.asarray(unit['points'])
        length=float(np.linalg.norm(tip-root))
        if length<1e-9:continue
        final=getattr(rig,'lash_final_transports',{}).get(side)
        use_shared=((shared_closed and eye.get('closure', 0.0) >= 1 - 1e-06) and final is not None and np.allclose(unit['base'], unit['points'], atol=1e-10, rtol=0))
        transport=final(root) if final else rig.lash_transport(side,root,lid,eye['closure'],eye.get('lash_shape_preserve',0.),eye.get('flat',0.))
        if transport is not None:
            guide_root,motion,hinge=transport
        else:
            # No band guide: follow the upper eye's translation without
            # manufacturing a rotation from a single mesh triangle.
            u=rig.parameter('EYE',side,True,root)
            guide_root=root+lid(u,True)-rig.neutral('EYE',side,True,u)
            motion=np.eye(3);hinge=np.array((1.,0.,0.))
        tree=band_trees.get(side);triangles=band_faces.get(side,[])
        if tree is None:tree=trees.get(side);triangles=root_faces.get(side,[])
        folds=getattr(rig,'lash_fold_transforms',{}).get(side,[])
        if folds and tree is not None and final is None:
            before=attach(root,edited_root,rest,rig.lash_before_fold,tree,triangles,motion)
            u=rig.lash_lines[side][0].project(root)[0]
            for fold in folds:
                if before is None or not min(fold['turn'],fold['end'])-1e-8<=u<=max(fold['turn'],fold['end'])+1e-8:continue
                blend=float(np.clip(abs(u-fold['turn'])/max(abs(fold['end']-fold['turn'])*.6,1e-12),0,1))
                blend=blend**3*(10-15*blend+6*blend*blend)
                angle=fold['curvature']*blend*max(float(fold['pivot'][2]-before[2]),0.);c,s=np.cos(angle),np.sin(angle)
                motion=np.array(((1.,0.,0.),(0.,c,-s),(0.,s,c)))@motion
        curve=motion_curves.get(side)
        anchor=guide_root+curve(root)+motion@(edited_root-root) if curve is not None else None
        if anchor is None and tree is not None:anchor=attach(root,edited_root,rest,posed,tree,triangles,motion)
        if anchor is None:anchor=guide_root+motion@(edited_root-root)
        axis=unit_vector(tip-root)
        edited_axis=edited_tip-edited_root
        transform=motion@rotation(axis,edited_axis)
        shared=[i for i in unit.get('band_vertices',[]) if i<len(rest)]
        if shared:
            predicted=anchor+(rest[shared]-root)@transform.T
            anchor+=np.mean(posed[shared]-predicted,axis=0)
        start=unit_vector(transform@axis)
        pitch=float(np.clip(eye.get('lash_pitch',0),-1.4,1.4))
        end=np.asarray(Matrix.Rotation(pitch,3,Vector(hinge)))@start
        direction=unit_vector(start+end)
        controls=np.array((anchor,anchor+start*length/3,anchor+direction*length-end*length/3,anchor+direction*length))
        line=B.bezier(controls,np.linspace(0,1,65));arc=np.linalg.norm(np.diff(line,axis=0),axis=1).sum()
        controls[1:]=anchor+(controls[1:]-anchor)*length/max(float(arc),1e-12)
        controls=forward_controls(controls,start,length)
        cloud=rest[ids];cross_section=cloud-root-np.outer((cloud-root)@axis,axis)
        singular=np.linalg.svd(cross_section,compute_uv=False)
        dimension=2 if len(singular)>1 and singular[1]>max(singular[0]*.03,1e-12) else 1
        # Contact is a later, whole-card operation, shared with the band.
        # Never pin the root while pushing only its handles or exposed tips.
        candidate,u,weight=bend(cloud,root,axis,length,controls,transform,dimension)
        if use_shared:
            # Keep the continuous band pose as the neutral strand motion.
            # A recipe's pitch adds only its curl, not a second root rotation.
            straight=np.array([anchor+start*length*t for t in (0.,1/3,2/3,1.)])
            uncurled,_,_=bend(cloud,root,axis,length,straight,transform,dimension)
            shared=np.array([final(rest[i])[0]+(curve(rest[i]) if curve is not None else 0.) for i in ids])
            candidate=shared+(candidate-uncurled)
            shared_follow+=len(ids)
        total[ids]+=candidate-rest[ids];counts[ids]+=1;units+=1
    moving=np.flatnonzero(counts)
    delta[moving]=total[moving]/counts[moving,None]
    return delta,dict(lash_bent_units=units,lash_exposure_conflicts=conflicts,lash_shared_follow_vertices=shared_follow,
                      lash_joined_fragments=len(rig.lashes)-len(physical))


def fit_legacy_contact_layers(rig,delta,recipe):
    """Joint depth contact on unchanged frontal geometry, including seam aliases."""
    report=dict(lash_joint_depth_vertices=0,lash_joint_depth_conflicts=0,lash_joint_depth_max_shift=0.)
    if not getattr(rig, 'lash_return_groups', []):return delta,report
    from .procedural_projection import project
    from .procedural_constraints import facial_eye_depth
    aliases={i:min(group) for group in rig.lash_stitches for i in group}
    edited={i for unit in rig.lashes if not np.allclose(unit['base'],unit['points'],atol=1e-8,rtol=0) for i in unit['vertices']}
    for text,eye in recipe.get('eyes',{}).items():
        side=int(text)
        if eye.get('closure',0.)<1-1e-6:continue
        selected={i for i,labels in enumerate(rig.members) if 2 in labels and 0 not in labels and i not in rig.brows|rig.creases|edited
                  and (1 if rig.points[i,0]>=rig.info['plane'] else -1)==side}
        # Tiny detached lower cards have no meaningful internal lid parameter.
        # Preserve their authored shape with one translation, including contact.
        small_cards=[g for g in rig.info['accessory_ownership']['components']
                     if g.get('reason')=='lower_surface_attachment' and g['side']==side
                     and set(g['vertices'])<=selected
                     and np.max(np.ptp(rig.points[g['vertices']],axis=0))<rig.widths['EYE',side]*.08]
        for group in small_cards:
            ids=group['vertices'];delta[ids]=np.mean(delta[ids],axis=0)
        def root(i):
            while aliases.get(i,i)!=i:i=aliases[i]
            return i
        for group in rig.lash_return_groups+small_cards:
            ids=sorted(set(group['vertices'])&selected)
            if not ids:continue
            representative=root(ids[0])
            for i in ids:
                other=root(i)
                if other!=representative:aliases[other]=representative
        representatives=sorted({root(i) for i in selected});lookup={i:k for k,i in enumerate(representatives)}
        n=len(representatives)
        if not n or n>1024:continue
        mapping={i:lookup[root(i)] for i in selected}
        basis=np.zeros((len(delta),n))
        for i,k in mapping.items():basis[i,k]=1.
        units,skin=contact_units(rig,side);original_gaps={i:v for unit in units for i,v in unit['gaps'].items()}
        posed=rig.points+delta;obstacle=surface(posed,skin);goals=np.zeros(n);counts=np.zeros(n)
        for i,k in mapping.items():
            gap=clearance(obstacle,posed[i]);old=original_gaps.get(i)
            if gap is None:continue
            if old is None:old=facial_eye_depth(rig,side,rig.points[i])-rig.points[i,1]
            goals[k]+=gap-old;counts[k]+=1
        goals/=np.maximum(counts,1.)
        target=posed.copy();target[:,1]+=basis@goals
        rows=[];bounds=[]
        # Embedded roots cannot be traded for extra free-edge clearance.
        # Their original contact remains the attachment envelope.
        width=rig.widths['EYE',side]
        roots={mapping[i] for i in selected if original_gaps.get(i) is not None
               and abs(original_gaps[i])<=width*.015 and i not in rig.lash_return_vertices}
        def contacts(triangles,other_ids,other_points,sign,variable_other=False):
            if not triangles or not other_ids:return
            triangles=np.asarray(triangles,dtype=int);other_ids=np.asarray(other_ids,dtype=int)
            other=other_points[other_ids];plane=other[:,:,[0,2]];lo,hi=plane.min(1),plane.max(1)
            for start in range(0,len(triangles),64):
                tris=triangles[start:start+64];cloud=target[tris];xz=cloud[:,:,[0,2]]
                ia,ib=np.nonzero(np.all(xz.min(1)[:,None]<=hi,axis=-1)&np.all(xz.max(1)[:,None]>=lo,axis=-1))
                if not len(ia):continue
                wa,wb,valid=S.overlap_vertices(xz[ia],plane[ib])
                current=sign*(np.sum(wb*other[ib,None,:,1],axis=-1)-np.sum(wa*cloud[ia,None,:,1],axis=-1))
                rest=sign*(np.sum(wb*rig.original_points[other_ids[ib]][:,None,:,1],axis=-1)-np.sum(wa*rig.original_points[tris[ia]][:,None,:,1],axis=-1))
                matrix=np.einsum('kij,kja->kia',wa,basis[tris[ia]])
                if variable_other:matrix-=np.einsum('kij,kja->kia',wb,basis[other_ids[ib]])
                rows.extend((sign*matrix)[valid]);bounds.extend((current-np.minimum(rest,0.))[valid])
        triangles=[list(t) for t,f in rig.mesh_triangles if set(t)<=selected]
        contacts(triangles,skin,target,1.)
        eyes=[list(t) for t,f in rig.mesh_triangles if rig.info['labels'][f] in (3,5,7)
              and (1 if rig.points[list(t),0].mean()>=rig.info['plane'] else -1)==side]
        contacts(triangles,eyes,rig.original_points+getattr(rig,'eye_stack_shape',np.zeros_like(delta)),1.)
        upper=upper_band(rig,side);lower=set(lower_vertices(rig,side))
        lower_triangles=[list(t) for t,f in rig.mesh_triangles if set(t)<=lower]
        contacts(lower_triangles,upper,target,-1.,variable_other=True)
        records={r['id']:r for r in rig.info['accessory_ownership']['components']}
        for group in rig.lash_return_groups:
            if group['side']!=side:continue
            host=set(records[group['parent']]['vertices'])
            host_triangles=[list(t) for t,f in rig.mesh_triangles if set(t)<=host]
            tree=BVHTree.FromPolygons([Vector(p) for p in rig.points],host_triangles)
            hits=[tree.find_nearest(Vector(rig.points[i])) for i in group['vertices']]
            nearest=min(range(len(hits)),key=lambda k:hits[k][3])
            for i,(hit,normal,number,distance) in [(group['vertices'][nearest],hits[nearest])]:
                tri=host_triangles[number];a=rig.points[tri]
                uv=np.linalg.lstsq(np.column_stack((a[1]-a[0],a[2]-a[0])),np.asarray(hit)-a[0],rcond=None)[0]
                weights=np.array((1-uv.sum(),*uv))
                row=basis[i]-weights@basis[tri]
                offset=rig.points[i,1]-weights@rig.points[tri,1]
                residual=offset-(target[i,1]-weights@target[tri,1])
                rows.extend((row,-row));bounds.extend((residual+rig.widths['EYE',side]*1e-6,-residual+rig.widths['EYE',side]*1e-6))
        if not rows:continue
        rows=np.asarray(rows);bounds=np.asarray(bounds)
        metric=np.eye(n);metric[list(roots),list(roots)]=20.;edges=set()
        for tri in triangles:
            edges.update(tuple(sorted((mapping[a],mapping[b]))) for a,b in zip(tri,tri[1:]+tri[:1]) if mapping[a]!=mapping[b])
        for a,b in edges:metric[a,a]+=.2;metric[b,b]+=.2;metric[a,b]-=.2;metric[b,a]-=.2
        inverse=np.linalg.inv(metric);directions=rows@inverse;norm=np.sum(rows*directions,axis=1)
        tolerance=rig.widths['EYE',side]*1e-6
        correction=project(rows,bounds,directions,norm,tolerance,iterations=2048,pulse=getattr(rig,'progress',None))
        changes=basis@(goals+correction)
        delta[:,1]+=changes
        report['lash_joint_depth_vertices']+=int(np.count_nonzero(abs(changes)>tolerance))
        report['lash_joint_depth_max_shift']=max(report['lash_joint_depth_max_shift'],float(np.max(abs(changes))))
        report['lash_joint_depth_conflicts']+=int(np.count_nonzero(rows@correction-bounds>tolerance*2))
    return delta,report


def follow_legacy_closed_strands(rig,delta,recipe,lids):
    """Attach omitted strands to the completed legacy pose, never refit it.

    The existing band/contact solver finishes first. Only free strand vertices
    are copied back, so they cannot trigger a different main-band contact pose.
    Edited strands and every shared root retain the original deformation.
    """
    
    eyes={side:eye for side,eye in recipe.get('eyes',{}).items() if eye.get('closure',0.)>=1-1e-6}
    if not eyes or not rig.lashes:return delta,{}
    trial=dict(recipe,eyes=eyes)
    candidate,report=deform(rig,delta.copy(),trial,lids,shared_closed=True)
    band={i for unit in rig.lashes for i in unit.get('band_vertices',[])}
    selected={i for unit in rig.lashes if str(unit['side']) in eyes
              and np.allclose(unit['base'],unit['points'],atol=1e-10,rtol=0)
              for i in unit['vertices'] if i not in band and 0 not in rig.members[i]}
    edited={i for unit in rig.lashes if not np.allclose(unit['base'],unit['points'],atol=1e-10,rtol=0)
            for i in unit['vertices']}
    for group in getattr(rig,'lash_stitches',[]):
        if edited.intersection(group):edited.update(group)
    ids=sorted((selected&rig.strands)-edited-rig.brows-rig.creases-getattr(rig,'upper_followers',set()))
    if not ids:return delta,dict(legacy_lash_follow_vertices=0)
    delivered=delta.copy();delivered[ids]=candidate[ids];candidate=delivered
    # Root vertices stay fixed to the already solved band. On a different
    # topology this can make a shared pose incompatible with an existing tip.
    # Reject the WHOLE connected strand if it adds a fold anywhere during
    # shape-key playback; do not weaken the existing signed-area constraint.
    from .procedural_constraints import minimum_areas
    chosen=set(ids);parent={i:i for i in ids}
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    def join(group):
        local=sorted(chosen.intersection(group))
        for i in local[1:]:parent[root(i)]=root(local[0])
    for unit in rig.lashes:join(unit['vertices'])
    for group in getattr(rig,'lash_stitches',[]):join(group)
    triangles=[t for t,f in rig.mesh_triangles if chosen.intersection(t)]
    for triangle in triangles:join(triangle)
    original,area=minimum_areas(rig.points,delta,triangles)
    trial,unused=minimum_areas(rig.points,candidate,triangles)
    rejected={root(i) for triangle in np.asarray(triangles)[(area>1e-14)&(trial<np.minimum(original,area*.005))]
              for i in triangle if i in chosen}
    seam_tolerance=max(rig.widths.values(),default=1.)*1e-6
    before=rig.points+delta;after=rig.points+candidate
    for group in getattr(rig,'lash_stitches',[]):
        old_gap=float(np.linalg.norm(np.ptp(before[group],axis=0)))
        new_gap=float(np.linalg.norm(np.ptp(after[group],axis=0)))
        if new_gap>max(old_gap,seam_tolerance):
            rejected.update(root(i) for i in group if i in chosen)
    accepted=[i for i in ids if root(i) not in rejected]
    delta[accepted]=candidate[accepted]
    return delta,dict(legacy_lash_follow_vertices=len(accepted),legacy_lash_follow_rejected_groups=len(rejected))

