"""Level a detached tongue at rest and confine squeezing to the lip exit."""
import numpy as np
from . import region_guides as G
from .region_contours import lip_weights
from . import procedural_surfaces as Surfaces
from .generation_progress import notify
from . import procedural_binding as Binding


MAX_EXIT_COMPRESSION=.15


def protrusion(recipe):
    return float(np.clip(recipe.get('tongue',{}).get('protrusion',0.),0.,1.))


def limit_size(rig,delta,recipe):
    """Bound final tongue strain, retaining rigid travel to the lip opening."""
    report=dict(tongue_size_gain=1.,tongue_size_limited=False)
    if protrusion(recipe)<=0 or len(rig.tongue)<2:return delta,report
    ids=np.asarray(rig.tongue,dtype=np.int32);rest=rig.points[ids]
    if not hasattr(rig,'_tongue_size_edges'):
        local={i:k for k,i in enumerate(ids)};edges=set()
        for tri,f in rig.mesh_triangles:
            if rig.info['labels'][f]!=12:continue
            for a,b in zip(tri,(*tri[1:],tri[0])):
                if a in local and b in local:edges.add(tuple(sorted((local[a],local[b]))))
        rig._tongue_size_edges=np.asarray(sorted(edges),dtype=np.int32).reshape((-1,2))
    edges=rig._tongue_size_edges
    detached=all(set(rig.members[i])=={12} for i in ids)
    before=rest+delta[ids];rotation=np.eye(3);size=1.
    if detached:
        centered=rest-rest.mean(0)
        u,s,v=np.linalg.svd(centered.T@(before-before.mean(0)))
        rotation=v.T@u.T
        if np.linalg.det(rotation)<0:v[-1]*=-1;rotation=v.T@u.T
        size=min(1.,float(s.sum()/max(float(np.sum(centered*centered)),1e-20)))
        rigid=size*centered@rotation.T+before.mean(0)
    else:rigid=rest.copy()
    bend=before-rigid;gain=1.
    if len(edges):
        a,b=edges.T;edge=rigid[b]-rigid[a];change=bend[b]-bend[a]
        length2=np.sum((rest[b]-rest[a])**2,axis=1);aa=np.sum(change*change,axis=1)
        bb=2*np.sum(edge*change,axis=1);cc=np.sum(edge*edge,axis=1)-length2*1.04**2
        valid=(length2>1e-20)&(aa>1e-24)
        if np.any(valid):
            roots=(-bb[valid]+np.sqrt(np.maximum(bb[valid]**2-4*aa[valid]*cc[valid],0)))/(2*aa[valid])
            gain=min(gain,max(float(roots.min()),0.))
    span=np.ptp(rest,axis=0);length=max(float(span[1]),1e-9)
    bounds=np.array((span[0]*1.08,span[1]*1.04,span[2]+length*.28))
    bounds=np.maximum(bounds,1e-9)
    def intrinsic_span(g):return np.ptp((rigid+g*bend)@rotation,axis=0)
    if np.any(intrinsic_span(gain)>bounds):
        lo,hi=0.,gain
        for _ in range(28):
            middle=(lo+hi)*.5
            if np.all(intrinsic_span(middle)<=bounds):lo=middle
            else:hi=middle
        gain=lo
    posed=rigid+gain*bend
    # Reducing stretching must not retract the tip behind the mouth. This is
    # a common translation, so it cannot enlarge an edge or cross-section.
    if detached:posed[:,1]+=float(before[:,1].min()-posed[:,1].min())
    result=delta.copy();result[ids]=posed-rest
    report.update(tongue_size_gain=float(gain),tongue_size_limited=bool(gain<1-1e-8),tongue_rigid_scale=size,
        tongue_basis_span=span.tolist(),tongue_final_span=np.ptp(posed,axis=0).tolist())
    return result,report


def reference_pose(rig,delta,targets):
    """Bend target-sized sections along the Original's arc and tip position."""
    cloud=rig.points[rig.tongue];length=max(float(np.ptp(cloud[:,1])),1e-9)
    t=(cloud[:,1].max()-cloud[:,1])/length;skin=rig.points+delta
    width=rig.widths['LIP',0];rows=rig.rows['LIP',0];lips={}
    for up in (False,True):
        ids=sorted({i for i,u,upper in rows if bool(upper)==up or u<1e-7 or u>1-1e-7},key=lambda i:skin[i,0])
        lips[up]=skin[ids]
    left=max(p[:,0].min() for p in lips.values());right=min(p[:,0].max() for p in lips.values())
    center=(left+right)*.5;result=cloud.copy();scales=[]
    base=np.polynomial.polynomial.polyfit(t,cloud,2)
    base_center=np.polynomial.polynomial.polyval(t,base).T
    offset=cloud-base_center
    for target in targets:
        reference=target['reference'];weight=float(target['weight'])
        # Some characters have a very thick internal tongue. Keep the Basis,
        # but size the protruding pose to the Original's mouth-relative
        # envelope with one uniform reduction, never an enlargement.
        envelope=np.asarray(reference['basis_span_per_mouth'])*width
        scale=min(1.,float(np.min(envelope/np.maximum(np.ptp(cloud,axis=0),1e-9))))
        scales.append(scale)
        target_length=length*scale
        line=Binding.Line(reference['curve'])
        curve=np.array([line.sample(u)*target_length/line.length for u in t])
        posed=curve.copy();width_gain=float(np.clip(reference['width_gain'],.5,1.08))
        for k,u in enumerate(t):
            tangent=line.sample(min(u+.005,1))-line.sample(max(u-.005,0))
            tangent/=max(float(np.linalg.norm(tangent)),1e-12)
            lateral=np.array((-tangent[1],tangent[0],0.));lateral/=max(float(np.linalg.norm(lateral)),1e-12)
            normal=np.cross(lateral,tangent)*-1.
            posed[k]+=scale*(lateral*offset[k,0]*width_gain+normal*offset[k,2])
        tip_x=float(np.clip(center+reference['tip_x']*width,left+width*.04,right-width*.04))
        contact=sum((np.array([np.interp(tip_x,p[:,0],p[:,axis]) for axis in range(3)]) for p in lips.values()))*.5
        tip=contact+np.array((0.,-np.clip(reference['tip_depth'],0.,.35)*target_length,
                              np.clip(reference['tip_height'],-.28,.28)*target_length))
        posed+=tip-line.sample(1.)*target_length/line.length
        # Fit the whole exposed cross-section between the mouth corners.
        # Clamping only its centre let a wide side tongue extend past the lip.
        exposed=posed[t>=.6]
        if len(exposed):
            lower=left+width*.06-float(exposed[:,0].min())
            upper=right-width*.06-float(exposed[:,0].max())
            if lower<=upper:posed[:,0]+=float(np.clip(0.,lower,upper))
        result+=(posed-cloud)*weight
    return result,dict(tongue_reference_transport=True,tongue_reference_scales=scales)


def support_lower(rig,delta,recipe):
    """Seat a protruding tongue at the final lower lip, preserving its curl."""
    if recipe.get('tongue',{}).get('support_lip')!='lower' or not rig.tongue:return delta
    ids=np.asarray(rig.tongue);local={i:k for k,i in enumerate(ids)}
    triangles=np.asarray([[local[i] for i in tri] for tri,f in rig.mesh_triangles
                          if rig.info['labels'][f]==12 and all(i in local for i in tri)],dtype=int).reshape((-1,3))
    if not len(triangles):return delta
    skin=rig.points+delta;cloud=skin[ids];rows=rig.rows['LIP',0];width=rig.widths['LIP',0]
    chain=sorted({i for i,u,up in rows if not up or u<1e-7 or u>1-1e-7},key=lambda i:skin[i,0])
    x=float(cloud[cloud[:,1]<=np.quantile(cloud[:,1],.3),0].mean())
    depth=float(np.interp(x,skin[chain,0],skin[chain,1]))
    cut=section(cloud,triangles,depth)
    if len(cut)<3:return delta
    low,_=envelope(cut)
    dz=float(np.max(np.interp(low[:,0],skin[chain,0],skin[chain,2])-low[:,1]))
    result=delta.copy();result[ids,2]+=float(np.clip(dz,-width*.15,width*.15))
    return result


def neutral(rig):
    """A rigid rest-pose correction preserves thickness, camber and volume."""
    points=rig.points.copy();ids=rig.tongue
    report=dict(changed=False,reason='no_tongue',angle_degrees=0.,translation=[0.,0.,0.])
    if len(ids)<3 or not rig.info['mouth']:return points,report
    # A welded tongue cannot be rotated without pulling on its attachment.
    # Floating tongues are the units needing a neutral orientation correction.
    all_ids={i for f,label in zip(rig.info['faces'],rig.info['labels']) if label==12 for i in f}
    if any(set(rig.members[i])!={12} for i in all_ids):
        report['reason']='attached_tongue';return points,report
    cloud=points[ids];weights=np.zeros(len(points))
    for tri,f in rig.mesh_triangles:
        if rig.info['labels'][f]!=12:continue
        a,b,c=points[list(tri)];area=np.linalg.norm(np.cross(b-a,c-a))
        for i in tri:weights[i]+=area/3
    weights=weights[ids]
    if weights.sum()<=1e-20:
        report['reason']='degenerate_tongue';return points,report
    weights/=weights.sum();center=np.sum(cloud*weights[:,None],axis=0);local=cloud-center
    values,vectors=np.linalg.eigh((local*weights[:,None]).T@local)
    if values[1]<=1e-20 or values[0]>values[1]*.65:
        report['reason']='ambiguous_tongue_plane';return points,report
    normal=vectors[:,0]
    if normal[2]<0 or (abs(normal[2])<1e-10 and normal[1]>0):normal=-normal
    # Minimal proper rotation from the fitted broad surface to the XY plane.
    target=np.array((0.,0.,1.));axis=np.cross(normal,target);cosine=float(np.dot(normal,target))
    skew=np.array(((0.,-axis[2],axis[1]),(axis[2],0.,-axis[0]),(-axis[1],axis[0],0.)))
    rotation=np.eye(3)+skew+skew@skew/max(1+cosine,1e-12)
    leveled=local@rotation.T+center
    rows=rig.rows['LIP',0]
    lips=[sum((points[i]*w for i,w in lip_weights(rows,.5,upper)),np.zeros(3)) for upper in (False,True)]
    lip_center=(lips[0]+lips[1])*.5
    # Lower a floating tongue to the closed lip height, without raising one
    # already resting lower or inventing a gap to teeth/cavity surfaces.
    translation=np.zeros(3)
    translation[2]=min(float(lip_center[2]-leveled[:,2].max()),0.)
    # Rotation alone must not move the tongue in front of its original tip.
    translation[1]=max(float(cloud[:,1].min()-leveled[:,1].min()),0.)
    points[ids]=leveled+translation
    angle=float(np.degrees(np.arccos(np.clip(cosine,-1.,1.))))
    report.update(changed=bool(np.max(abs(points[ids]-cloud))>1e-10),reason='rigid_level',
                  angle_degrees=angle,translation=translation.tolist())
    return points,report


def section(cloud,triangles,depth):
    """Actual triangle/plane intersections, avoiding a thick nearest-point bin."""
    if not len(triangles):return np.empty((0,3))
    faces=cloud[triangles];a=faces.reshape((-1,3));b=np.roll(faces,-1,axis=1).reshape((-1,3))
    span=b[:,1]-a[:,1];epsilon=max(float(np.ptp(cloud[:,1]))*1e-10,1e-12)
    valid=(abs(span)>epsilon)&((a[:,1]-depth)*(b[:,1]-depth)<=epsilon*epsilon)
    a=a[valid];b=b[valid];span=span[valid]
    return a+(b-a)*np.clip((depth-a[:,1])/span,0.,1.)[:,None]


def envelope(cut):
    """Convex cross-section bounds contain the entire tongue at the exit."""
    points=sorted(set((float(p[0]),float(p[2])) for p in cut))
    def cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    lower=[];upper=[]
    for point in points:
        while len(lower)>1 and cross(lower[-2],lower[-1],point)<=0:lower.pop()
        lower.append(point)
    for point in reversed(points):
        while len(upper)>1 and cross(upper[-2],upper[-1],point)<=0:upper.pop()
        upper.append(point)
    return np.asarray(lower),np.asarray(upper[::-1])


def lip_clearance(rows,skin,cut,width):
    """Bound the full linear lip segments, even when the tongue falls between vertices."""
    low,high=envelope(cut);corrections={};conflicts=0;limit=width*.12
    for upper,bound in ((False,low),(True,high)):
        if len(bound)<2:continue
        sign=1. if upper else -1.
        chain=sorted({(u,i) for i,u,side in rows if side==upper or u<=1e-7 or u>=1-1e-7})
        for (u,i),(v,j) in zip(chain,chain[1:]):
            a,b=skin[i],skin[j];span=b[0]-a[0]
            if abs(span)<=width*1e-9:continue
            lo=max(min(a[0],b[0]),bound[0,0]);hi=min(max(a[0],b[0]),bound[-1,0])
            if lo>hi:continue
            samples=np.unique(np.r_[lo,hi,bound[(bound[:,0]>lo)&(bound[:,0]<hi),0]])
            for x in samples:
                t=float((x-a[0])/span);weights=(1-t,t)
                current=a[2]*(1-t)+b[2]*t
                need=(float(np.interp(x,bound[:,0],bound[:,1]))-current)*sign
                if need<=width*1e-8:continue
                movable=[(index,w) for parameter,index,w in ((u,i,weights[0]),(v,j,weights[1]))
                         if 1e-7<parameter<1-1e-7 and w>1e-8]
                weight=sum(w for index,w in movable)
                if weight<=1e-8:conflicts+=1;continue
                if need>limit*weight+width*1e-8:conflicts+=1
                change=min(need/weight,limit)
                # Compute from the unchanged lip, taking maxima per vertex.
                # The result does not depend on left/right traversal order.
                for index,w in movable:corrections[index]=sign*max(abs(corrections.get(index,0.)),change)
    # Share a contact over a finite lip arc. A correction confined to the
    # two hit vertices produces a notch on either side of the tongue.
    seeds=dict(corrections)
    for upper in (False,True):
        chain=sorted({(u,i) for i,u,side in rows if side==upper or u<=1e-7 or u>=1-1e-7})
        sign=1. if upper else -1.
        sources=[(i,abs(v)) for i,v in seeds.items() if v*sign>0]
        for u,i in chain:
            if u<=1e-7 or u>=1-1e-7:continue
            value=abs(corrections.get(i,0.))
            for j,amount in sources:
                t=float(np.clip(abs(skin[i,0]-skin[j,0])/(width*.18),0,1))
                value=max(value,amount*(1-t*t*t*(10-15*t+6*t*t)))
            if value>width*1e-10:corrections[i]=sign*value
    rim=skin[[i for i,u,upper in rows],0]
    conflicts+=int(cut[:,0].min()<rim.min()-width*1e-6 or cut[:,0].max()>rim.max()+width*1e-6)
    return corrections,conflicts


def deform(rig,delta,recipe):
    """Move depth sections, squeeze only the throat, and open lips if needed."""
    report=dict(tongue_exit_scale=1.,tongue_lip_adjustments=0,tongue_exit_conflicts=0)
    tongue=recipe.get('tongue');ids=rig.tongue
    if not tongue or not ids or not rig.info['mouth']:return delta,report
    width=rig.widths['LIP',0];cloud=rig.points[ids]
    lo,hi=float(cloud[:,1].min()),float(cloud[:,1].max());length=max(hi-lo,1e-9)
    t=(hi-cloud[:,1])/length
    coefficients=np.asarray(tongue['centerline'])
    movement=np.polynomial.polynomial.polyval(t,coefficients).T*width
    amount=protrusion(recipe)
    targets=tongue.get('reference_targets',[])
    if amount>0 and not targets:
        # Mouth-normalized reference polynomials can dwarf a short target
        # tongue. Bound bending by the target tongue, keeping rigid travel
        # separate; neither of the protrusion recipes widens the mesh.
        root=coefficients[0]*width;bending=movement-root
        limits=np.array((max(float(np.ptp(cloud[:,0])),1e-9)*.35,length*.25,length*.25))
        gains=np.minimum(1.,limits/np.maximum(np.ptp(bending,axis=0),1e-12))
        # Depth is positioned against this mouth below. Lateral/vertical
        # reference translation also has to respect a short target tongue,
        # including partial poses that have not reached the lip plane yet.
        root[[0,2]]=np.clip(root[[0,2]],-limits[[0,2]],limits[[0,2]])
        movement=root+bending*gains
        report['tongue_target_bend_gain']=gains.tolist()
    # A short target tongue must not fold its depth sections over each other
    # because the reference's polynomial assumes a longer tongue.
    if not targets:
        derivative=np.polynomial.polynomial.polyval(np.linspace(0.,1.,65),
                                                   np.polynomial.polynomial.polyder(coefficients[:,1]))*width
        depth_gain=min(1.,length*.8/max(float(derivative.max()),1e-12))
        movement[:,1]=coefficients[0,1]*width+(movement[:,1]-coefficients[0,1]*width)*depth_gain
        report['tongue_longitudinal_gain']=float(depth_gain)
    movement[:,0]+=(cloud[:,0]-np.mean(cloud[:,0]))*((1. if amount>0 else tongue['width_gain'])-1)
    rigid_delta=np.zeros_like(cloud)
    if tongue.get('rigid_motion'):
        from mathutils import Euler
        motion=tongue['rigid_motion'];rotation=np.array(Euler(tuple(motion['euler']),'XYZ').to_matrix())
        center=cloud.mean(0)
        rigid_delta=(cloud-center)@rotation.T+center+np.asarray(motion['translation'])*width-cloud
        movement+=rigid_delta
        report['tongue_reference_rigid']=True
    entry=rig.tongue_entry()
    if entry:
        # Edits remain offsets; do not restore the old tilted guide as Basis.
        movement+=np.array([G.sample(entry['points'],u)-G.sample(entry['base'],u) for u in t])
    if targets and amount>0:
        posed,reference_report=reference_pose(rig,delta,targets)
        posed+=rigid_delta
        if entry:posed+=np.array([G.sample(entry['points'],u)-G.sample(entry['base'],u) for u in t])
        report.update(reference_report)
    else:posed=cloud+movement
    if amount<=0:delta[ids]=movement;return delta,report
    delta[ids]=posed-cloud
    delta,size_report=limit_size(rig,delta,recipe)
    report.update({'initial_'+key:value for key,value in size_report.items()})
    posed=cloud+delta[ids]
    rows=rig.rows['LIP',0];skin=rig.points+delta
    lips=[sum((skin[i]*w for i,w in lip_weights(rows,.5,upper)),np.zeros(3)) for upper in (False,True)]
    center=(lips[0]+lips[1])*.5
    # Reference displacement alone may never reach the lips on a deep, floating
    # target tongue. Anchor exposure to this target's opening, retaining a root
    # behind it and fading the repositioning with the expression weight.
    exposure=min(max(-float(np.asarray(tongue['centerline'])[:,1].sum())*width,0.),min(length*.25,width*.18)*amount)
    front=(1-amount)*lo+amount*center[1]-exposure
    if not targets:posed[:,1]+=front-float(posed[:,1].min())
    local={i:k for k,i in enumerate(ids)}
    triangles=np.asarray([[local[i] for i in tri] for tri,f in rig.mesh_triangles
                          if rig.info['labels'][f]==12 and all(i in local for i in tri)],dtype=np.int32).reshape((-1,3))
    cut=section(posed,triangles,center[1])
    if not len(cut):
        # The partial expression has not reached the lip plane yet.
        delta[ids]=posed-cloud;return delta,report
    exit=(cut.min(0)+cut.max(0))*.5
    shift=np.zeros(3) if targets else np.array((center[0]-exit[0],0.,center[2]-exit[2]))*amount
    posed+=shift;cut+=shift;exit+=shift
    if tongue.get('support_lip')=='lower':
        # Support the underside at the lip-plane section, not the raised
        # centre of the tip. The distal downward curl remains free outside.
        chain=sorted({i for i,u,up in rows if not up or u<1e-7 or u>1-1e-7},key=lambda i:skin[i,0])
        low,_=envelope(cut)
        dz=float(np.max(np.interp(low[:,0],skin[chain,0],skin[chain,2])-low[:,1]))
        posed[:,2]+=dz;cut[:,2]+=dz;exit[2]+=dz
    thickness=float(np.ptp(cut[:,2]));gap=max(float(lips[1][2]-lips[0][2]),0.)
    scale=max(1-MAX_EXIT_COMPRESSION*amount,min(1.,gap/max(thickness,1e-12)))
    # The scale is one outside a short smooth neighborhood of the lip plane.
    # Tongue tip/camber resume their unsqueezed positions beyond that zone.
    reach=max(min(max(thickness,width*.03),max(exposure*.35,width*.005),length*.10),1e-9)
    q=np.clip(abs(posed[:,1]-center[1])/reach,0.,1.)
    influence=1-q*q*q*(10-15*q+6*q*q)
    posed[:,2]=exit[2]+(posed[:,2]-exit[2])*(1-(1-scale)*influence)
    # Sparse meshes may have no vertex in the pressure zone. Recut the actual
    # deformed triangles; never ask lips to fit an imaginary thinner section.
    cut=section(posed,triangles,center[1])
    corrections,conflicts=lip_clearance(rows,skin,cut,width)
    for i,change in corrections.items():delta[i,2]+=change
    delta[ids]=posed-cloud
    report.update(tongue_exit_scale=float(np.ptp(cut[:,2])/max(thickness,1e-12)) if thickness>1e-12 else 1.,
                  tongue_exit_requested_scale=float(scale),tongue_lip_adjustments=len(corrections),tongue_exit_conflicts=conflicts,
                  tongue_exit_recovery_distance=float(reach),tongue_exit_thickness=thickness)
    return delta,report


def exposed_pieces(points,triangles,lip_depth):
    """Clip to the outside of the lip plane, retaining original barycentrics."""
    result=[]
    for ids in triangles:
        gap=points[ids,1]-lip_depth(points[ids,0]);polygon=list(np.eye(3));clipped=[]
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            da,db=float(a@gap),float(b@gap)
            if da<=0:clipped.append(a)
            if (da<0 and db>0) or (da>0 and db<0):clipped.append(a+(b-a)*(da/(da-db)))
        for k in range(1,len(clipped)-1):result.append((ids,np.array([clipped[0],clipped[k],clipped[k+1]])))
    return result


def keep_exterior(rig,delta,recipe):
    """Keep the exposed underside and sidewalls in front of final Face.

    Contact moves whole original-Y sections in depth, including their upper
    copies, so it cannot flatten the tongue or separate its two surfaces.
    Only the lower/outward faces impose constraints; the opposite face does
    not. Internal depth sections remain fixed.
    """
    report=dict(tongue_exterior_vertices=0,tongue_exterior_conflicts=0,tongue_exterior_depth=0.)
    amount=protrusion(recipe)
    if amount<=0 or not rig.tongue or ('LIP',0) not in rig.rows:return delta,report
    ids=np.asarray(rig.tongue,dtype=np.int32);local={i:k for k,i in enumerate(ids)}
    triangles=np.asarray([[local[i] for i in tri] for tri,f in rig.mesh_triangles
                          if rig.info['labels'][f]==12 and all(i in local for i in tri)],dtype=np.int32).reshape((-1,3))
    if not len(triangles):return delta,report
    rest=rig.points[ids];cloud=rest+delta[ids];skin=rig.points+delta;width=rig.widths['LIP',0]
    surface=rest[triangles];normal=np.cross(surface[:,1]-surface[:,0],surface[:,2]-surface[:,0])
    normal/=np.maximum(np.linalg.norm(normal,axis=1)[:,None],1e-20)
    # Pick the lower broad surface and outward edge faces in the leveled Basis.
    # Upward-facing broad triangles never force the tongue to clear Face.
    selected=(normal[:,2]<-.15)|((normal[:,2]<.35)&((normal[:,1]<-.15)|(abs(normal[:,0])>.3)))
    triangles=triangles[selected]
    if not len(triangles):return delta,report
    rows=rig.rows['LIP',0];lips=[]
    for upper in (False,True):
        chain=[i for u,i in sorted({(u,i) for i,u,up in rows if bool(up)==upper or u<1e-7 or u>1-1e-7})]
        x,inverse=np.unique(skin[chain,0],return_inverse=True)
        y=np.bincount(inverse,skin[chain,1])/np.bincount(inverse)
        lips.append((x,y))
    def lip_depth(x):return sum(np.interp(x,a,b) for a,b in lips)*.5
    length=max(float(np.ptp(rest[:,1])),1e-12);parameter=(rest[:,1].max()-rest[:,1])/length
    internal=parameter[cloud[:,1]>=lip_depth(cloud[:,0])-width*1e-8]
    fixed=float(internal.max()) if len(internal) else 0.
    knots=np.unique(np.r_[np.linspace(0.,1.,17),fixed])
    segment=np.minimum(np.searchsorted(knots,parameter,side='right')-1,len(knots)-2)
    fraction=(parameter-knots[segment])/np.maximum(knots[segment+1]-knots[segment],1e-12)
    basis=np.zeros((len(ids),len(knots)));indices=np.arange(len(ids))
    basis[indices,segment]=1-fraction;basis[indices,segment+1]=fraction
    movable=(knots>fixed+1e-9).astype(float)
    face_ids=np.asarray([tri for tri,f in rig.mesh_triangles if rig.info['labels'][f]==0
                         and not set(tri).issubset(rig.creases)],dtype=np.int32).reshape((-1,3))
    obstacles=skin[face_ids];other=obstacles[:,:,[0,2]];lo=other.min(1);hi=other.max(1)
    # Contact may spend only the exposure still available after posing. It
    # must not undo the target-size limit by pushing the tip far out again.
    maximum=min(length*.35,width*.22)*amount
    exposure=max(float(np.max(lip_depth(cloud[:,0])-cloud[:,1])),0.)
    correction=np.zeros(len(knots));budget=max(maximum-exposure,0.);tolerance=width*1e-8
    def contacts(posed):
        coefficients=[];depths=[]
        pieces=exposed_pieces(posed,triangles,lip_depth)
        for first in range(0,len(pieces),64):
            notify(rig,'吐舌下表面与外侧接触',first,len(pieces))
            batch=pieces[first:first+64]
            source=np.array([row[0] for row in batch]);weights=np.array([row[1] for row in batch])
            moved=np.einsum('kij,kja->kia',weights,posed[source]);plane=moved[:,:,[0,2]]
            ia,ib=np.nonzero(np.all(plane.min(1)[:,None]<=hi,axis=-1)&np.all(plane.max(1)[:,None]>=lo,axis=-1))
            if not len(ia):continue
            wa,wb,valid=Surfaces.overlap_vertices(plane[ia],other[ib])
            need=np.sum(wa*moved[ia,None,:,1],axis=-1)-np.sum(wb*obstacles[ib,None,:,1],axis=-1)
            pair,vertex=np.nonzero(valid&(need>tolerance))
            if not len(pair):continue
            parents=np.einsum('ki,kij->kj',wa[pair,vertex],weights[ia[pair]])
            coefficients.append(np.einsum('ki,kij->kj',parents,basis[source[ia[pair]]]))
            depths.append(need[pair,vertex])
        if not depths:return np.empty((0,len(knots))),np.empty(0)
        return np.concatenate(coefficients),np.concatenate(depths)
    posed=cloud.copy()
    detached=all(set(rig.members[i])=={12} for i in ids)
    if detached:
        # A floating tongue has no fixed root. Move it as one piece for
        # contact instead of pulling exposed sections away from its root.
        used=0.
        for _ in range(4):
            _,need=contacts(posed)
            if not len(need):break
            step=min(float(need.max()),max(budget-used,0.))
            if step<=tolerance:break
            used+=step;posed[:,1]-=step
        _,remaining=contacts(posed);delta[ids,1]-=used
        report.update(tongue_exterior_vertices=len(ids) if used>tolerance else 0,
            tongue_exterior_conflicts=len(remaining),tongue_exterior_depth=used)
        return delta,report
    for _ in range(4):
        coefficients,need=contacts(posed)
        if not len(need):break
        coefficients*=movable;freedom=coefficients.sum(1)
        usable=freedom>1e-10
        addition=np.zeros_like(correction)
        row,column=np.nonzero(coefficients[usable]>1e-10)
        np.maximum.at(addition,column,(need[usable]/freedom[usable])[row])
        candidate=np.minimum(correction+addition,budget)*movable
        # Nondecreasing forward motion along root->tip prevents section order
        # reversing. Smooth by only raising bounds, never losing a contact.
        for step in range(3):
            smoothed=candidate.copy();smoothed[1:-1]=(candidate[:-2]+2*candidate[1:-1]+candidate[2:])*.25
            candidate=np.maximum(candidate,smoothed)*movable
        candidate=np.maximum.accumulate(candidate)*movable
        if np.max(candidate-correction)<=tolerance:break
        correction=candidate;posed=cloud.copy();posed[:,1]-=basis@correction
    _,remaining=contacts(posed)
    change=basis@correction
    delta[ids,1]-=change
    report.update(tongue_exterior_vertices=int(np.count_nonzero(change>tolerance)),
                  tongue_exterior_conflicts=len(remaining),tongue_exterior_depth=float(change.max()))
    return delta,report
