"""Transport connected lip collars without flattening their rest bevels."""
import heapq
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from .region_deformation import SkinDisplacementField
from . import procedural_binding as Binding


def active(rig,recipe):
    return ('LIP',0) in rig.rows and (bool(recipe.get('mouth')) or bool(recipe.get('mouth_targets'))
        or 'jaw' in recipe or bool(recipe.get('tongue')) or bool(recipe.get('custom_rules')))


def closed_reference(recipe):
    if recipe.get('tongue',{}).get('protrusion',0)>0:return False
    references=[target['reference'] for target in recipe.get('mouth_targets',[])]
    return bool(references) and not recipe.get('mouth') and all(
        np.allclose(ref['upper'],ref['lower'],atol=1e-10,rtol=0) for ref in references)


def jaw_contour(rig,delta,recipe):
    """Adjust chin and cheeks while leaving the mouth collar in its pose."""
    if 'jaw' not in recipe or ('LIP',0) not in rig.rows:return delta
    points=rig.points;width=rig.widths['LIP',0];center=np.asarray(rig.info['mouth'].frame.center)
    rim=sorted({i for i,u,up in rig.rows['LIP',0]})
    distance=np.linalg.norm(points[:,None,[0,2]]-points[rim][None,:,[0,2]],axis=-1).min(1)/width
    fade=np.clip((distance-.18)/.45,0,1);fade=fade*fade*(3-2*fade)
    down=np.maximum((center[2]-points[:,2])/width,0.)
    lower=np.clip(down/.45,0,1);lower=lower*lower*(3-2*lower)
    x=(points[:,0]-center[0])/width
    weight=fade*lower*np.exp(-(x/2.)**2-(down/1.8)**2)
    weight[[i for i,m in enumerate(rig.members) if 0 not in m]]=0
    movement=np.asarray(recipe['jaw'])*width
    result=delta.copy();result+=weight[:,None]*movement
    result[:,0]-=weight*x*abs(movement[2])*.35
    return result


def closed_motion(rig,delta):
    """Deform the already closed Basis without flattening its lip bevel."""
    ids=np.array(sorted({i for i,u,up in rig.rows['LIP',0]},key=lambda i:rig.points[i,0]))
    rest=rig.points[ids];target=rest+delta[ids]
    lo,hi=rest[0,0],rest[-1,0];span=max(float(hi-lo),1e-12)
    # An open Basis still needs actual closure when its automatic closing
    # option is disabled. Only preserve the bevel of an already closed mouth.
    sample=np.linspace(lo+span*.15,hi-span*.15,15);heights={}
    for upper in (False,True):
        branch=sorted({i for i,u,up in rig.rows['LIP',0] if bool(up)==upper or u<1e-7 or u>1-1e-7},
                      key=lambda i:rig.points[i,0])
        heights[upper]=np.interp(sample,rig.points[branch,0],rig.points[branch,2])
    if np.median(heights[True]-heights[False])>span*.001:
        result=delta.copy()
        # Close height only. The two authored lip surfaces need not share
        # depth: collapsing XYZ erases the bevel and the visible mouth line.
        for i,point in Binding.closed_rim(rig.rows['LIP',0],rig.points+delta,1).items():
            result[i,1]=0.
            result[i,2]=point[2]-rig.points[i,2]
        return result
    t=(rest[:,0]-lo)/span
    count=9
    def fit(values,parameters):
        basis=Binding.spline_basis(parameters,count);bend=np.diff(np.eye(count),n=2,axis=0)
        return np.linalg.solve(basis.T@basis+.025*bend.T@bend+np.eye(count)*1e-12,basis.T@values)
    original=fit(rest,t)
    order=np.argsort(target[:,0]);goal=target[order]
    width=max(float(goal[-1,0]-goal[0,0]),1e-12)
    wanted=fit(goal,(goal[:,0]-goal[0,0])/width)
    # Mapping X monotonically and sharing one height offset preserves the
    # return faces near each corner. Zipping all their control vertices onto
    # one polygon reversed these fully pinned triangles and erased thickness.
    result=delta.copy()
    result[ids,0]=goal[0,0]+t*width-rest[:,0]
    result[ids,1]=0.
    result[ids,2]=(Binding.spline_basis(t,count)@(wanted-original))[:,2]
    return result


def prepare(rig):
    if hasattr(rig,'lip_collar'):return rig.lip_collar
    rows=rig.rows['LIP',0];width=rig.widths['LIP',0];graph={}
    for a,b in zip(rig.field.a,rig.field.b):
        length=float(np.linalg.norm(rig.points[a]-rig.points[b]))
        graph.setdefault(int(a),[]).append((int(b),length));graph.setdefault(int(b),[]).append((int(a),length))
    branches={up:sorted({i for i,u,upper in rows if bool(upper)==up or u<1e-7 or u>1-1e-7}) for up in (False,True)}
    distances={};radius=width*.55
    for up,seeds in branches.items():
        distance=np.full(len(rig.points),np.inf);distance[seeds]=0.
        queue=[(0.,i) for i in seeds];heapq.heapify(queue)
        blocked=set(branches[not up])-set(seeds)
        while queue:
            value,i=heapq.heappop(queue)
            if value>distance[i] or i in blocked:continue
            for j,length in graph.get(i,()):
                candidate=value+length
                if candidate<distance[j] and candidate<=radius:
                    distance[j]=candidate;heapq.heappush(queue,(candidate,j))
        distances[up]=distance
    distance=np.minimum(distances[False],distances[True])
    rim=sorted(set(branches[False])|set(branches[True]))
    edge=float(np.median(rig.field.edge_length[rim]));core=min(max(width*.035,edge*1.1),width*.09)
    outer=max(width*.23,core*2)
    t=np.clip((distance-core)/max(outer-core,1e-12),0.,1.)
    fade=1-t*t*t*(10-15*t+6*t*t)
    weights=np.array([1/np.maximum(distances[up]+max(edge*.5,width*1e-6),1e-12)**4 for up in (False,True)])
    weights/=np.maximum(weights.sum(0),1e-30)
    support=set(np.flatnonzero(distance<=core))&set(rig.field.free.tolist())
    # Detached Face pieces must keep their outer attachment boundaries fixed,
    # just as the eyelid field does. Otherwise a lip solve on the lower piece
    # pulls it away from an unchanged, coincident upper-face seam.
    pins=(set(graph)-set(rig.field.free.tolist()))|rig.eye_skin.border
    field=SkinDisplacementField(rig.points,rig.info['faces'],rig.info['labels'],set(graph),pins,fidelity=.12)
    # Topology selects the front mouth neighbourhood, including slanted and
    # back-facing lip return faces; it cannot jump to the back of the head.
    faces=[list(t) for t,f in rig.mesh_triangles if rig.info['labels'][f]==0
           and not set(t)<=rig.creases and np.min(distance[list(t)])<radius]
    front=[]
    for tri in faces:
        p=rig.points[tri];normal=np.cross(p[1]-p[0],p[2]-p[0])
        if normal[1]<-1e-15:front.append(tri)
    tree=BVHTree.FromPolygons([Vector(p) for p in rig.points],front) if front else None
    rig.lip_collar=dict(branches=branches,distance=distance,fade=fade,weights=weights,support=support,
                        field=field,faces=faces,tree=tree,width=width)
    return rig.lip_collar


def follow(rig,delta):
    collar=prepare(rig);result=np.zeros_like(delta)
    selected=np.flatnonzero(collar['fade']>0)
    for branch,up in enumerate((False,True)):
        ids=[i for u,i in sorted({(u,i) for i,u,upper in rig.rows['LIP',0] if bool(upper)==up or u<1e-7 or u>1-1e-7})]
        line=Binding.Line(rig.points[ids]);count=min(9,max(4,len(ids)))
        basis=Binding.spline_basis(line.parameters,count);bend=np.diff(np.eye(count),n=2,axis=0)
        controls=np.linalg.solve(basis.T@basis+.04*bend.T@bend+np.eye(count)*1e-12,basis.T@delta[ids])
        def center(u):return line.sample(u)+(Binding.spline_basis([u],count)@controls)[0]
        for i in selected:
            u=line.project(rig.points[i])[0]
            rotation=Binding.spatial_frame(center,u)@Binding.spatial_frame(line.sample,u).T
            shift=center(u)+rotation@(rig.points[i]-line.sample(u))-rig.points[i]
            result[i]+=shift*collar['weights'][branch,i]
    return result


def surface_motion(rig,delta,recipe):
    """Use finite travel along the actual facial profile, not tangent extrapolation."""
    if not active(rig,recipe):return delta
    rig.lip_surface_report=dict(lip_surface_profile_limited=0)
    if closed_reference(recipe):return delta
    collar=prepare(rig);tree=collar['tree'];width=collar['width'];limited=0
    if tree is None:return delta
    origin=float(rig.points[:,1].min()-rig.info['width']*2);length=rig.info['width']*5
    def depth(x,z):
        hit,_,_,_=tree.ray_cast(Vector((float(x),origin,float(z))),Vector((0,1,0)),length)
        return None if hit is None else float(hit.y)
    visited=set();requests={}
    for i,u,upper in rig.rows['LIP',0]:
        if i in visited:continue
        visited.add(i);move=delta[i].copy();sign=1 if upper else -1
        if move[2]*sign<=width*1e-8:continue
        rest=rig.points[i];probe=width*1e-5*sign
        start=depth(rest[0],rest[2]+probe)
        if start is None:limited+=1;continue
        last=start
        for t in np.linspace(1/12,1,12):
            value=depth(rest[0]+move[0]*t,rest[2]+move[2]*t+probe)
            if value is None:limited+=1;break
            last=value
        requests[i]=last-start
    # Ray hits near the nose and on the lip return strip are not separate
    # lip features. Share their finite depth travel on a smooth branch,
    # with a bounded excursion, before transporting the attached bevel.
    for upper in (False,True):
        rows=[(i,u) for i,u,up in rig.rows['LIP',0] if bool(up)==upper or u<1e-7 or u>1-1e-7]
        if not any(i in requests for i,u in rows):continue
        ts=np.array([u for i,u in rows]);values=np.array([requests.get(i,0.) for i,u in rows])
        bound=width*.10;limited+=int(np.count_nonzero(abs(values)>bound))
        values=bound*np.tanh(values/max(bound,1e-12))
        basis=Binding.spline_basis(ts,7);bend=np.diff(np.eye(7),n=2,axis=0)
        controls=np.linalg.solve(basis.T@basis+.8*bend.T@bend+np.eye(7)*1e-9,basis.T@values)
        for (i,u),value in zip(rows,basis@controls):
            if i in requests:delta[i,1]+=value
    rig.lip_surface_report=dict(lip_surface_profile_limited=limited)
    return delta


def deform(rig,raw,recipe):
    if not active(rig,recipe):return rig.field.deform(raw)
    raw=raw.copy();raw[list(rig.eye_skin.border)]=0.
    collar=prepare(rig);seed=raw.copy();ids=rig.field.free
    posed=rig.points+raw;heights={};sample=np.linspace(.05,.95,33)
    for up,branch in collar['branches'].items():
        chain=sorted(branch,key=lambda i:rig.points[i,0]);x=rig.points[chain,0]
        heights[up]=np.interp(sample,(x-x[0])/max(float(x[-1]-x[0]),1e-12),posed[chain,2])
    amount=0. if closed_reference(recipe) else float(np.clip((np.max(heights[True]-heights[False])/collar['width']-.015)/.10,0,1))
    amount=amount*amount*(3-2*amount)
    opened=opening_skin(rig,raw) if amount>0 else None
    weight=collar['fade'][ids,None]
    seed[ids]=seed[ids]*(1-weight)+follow(rig,raw)[ids]*weight
    result=collar['field'].deform(seed)
    result=collar['field'].smooth_displacement(result,bending=2.)
    result=smooth_open_collar(rig,result,raw)
    if opened is None:return result
    candidate=result*(1-amount)+opened*amount
    # A wide return strip can invert when its edge frame turns. Keep the
    # existing transport if edge attachment adds inversions over the key's
    # full interpolation range. This depends on geometry, not model names.
    from .procedural_constraints import minimum_areas
    def folds(value):
        minimum,rest=minimum_areas(rig.points,value,collar['faces'])
        return int(np.count_nonzero((rest>1e-14)&(minimum<rest*.005)))
    previous,current=folds(result),folds(candidate)
    accepted=current<=previous
    rig.lip_surface_report.update(lip_opening_candidate_folds=current,
        lip_opening_previous_folds=previous,lip_opening_transport_accepted=accepted)
    return candidate if accepted else result


def smooth_open_collar(rig,delta,raw):
    """Regularize opening height along lip bands without flattening their bevel.

    Aperture controls can be smooth while the front bevel has a valence-induced
    cusp. Only share vertical displacement along nearly longitudinal Face
    edges. Do not average across upper/lower lips, change depth, or pull the
    bevel onto the aperture plane. Existing triangle/contact repair runs next.
    """
    collar=prepare(rig);field=collar['field']
    posed=rig.points+raw;heights={}
    sample=np.linspace(.2,.8,17)
    for up,branch in collar['branches'].items():
        ordered=sorted(branch,key=lambda i:rig.points[i,0])
        t=(rig.points[ordered,0]-rig.points[ordered[0],0])/max(float(np.ptp(rig.points[ordered,0])),1e-12)
        heights[up]=np.interp(sample,t,posed[ordered,2])
    gap=float(np.median(heights[True]-heights[False]))
    opening=float(np.clip((gap/collar['width']-.025)/.12,0,1))
    opening=opening*opening*(3-2*opening)
    rim=sorted(set(collar['branches'][False])|set(collar['branches'][True]))
    # Along-band averaging assumes the opening has not strongly compressed
    # its width or stretched its height. In those regimes the corner/shell
    # solve owns the deformation; this small cusp repair must not worsen it.
    width_ratio=float(np.ptp(posed[rim,0]))/collar['width']
    width_safe=float(np.clip((width_ratio-.70)/.20,0,1))
    height_safe=float(np.clip((1.-gap/collar['width'])/.20,0,1))
    opening*=width_safe**2*(3-2*width_safe)*height_safe**2*(3-2*height_safe)
    if not opening:return delta
    x=(rig.points[:,0]-rig.points[rim,0].min())/collar['width']
    ends=np.clip(np.minimum(x,1-x)/.18,0,1);ends=ends**3*(10-15*ends+6*ends*ends)
    middle=np.clip((np.minimum(x,1-x)-.16)/.20,0,1)
    middle=middle**3*(10-15*middle+6*middle*middle)
    rate=collar['fade']*ends*middle*opening*.65
    movable=np.zeros(field.n);movable[field.free]=1;rate*=movable
    edge=rig.points[field.a]-rig.points[field.b]
    alignment=abs(edge[:,0])/np.maximum(np.linalg.norm(edge,axis=1),1e-12)
    owner=np.argmax(collar['weights'],axis=0)
    weights=field.w*np.clip((alignment-.7)/.3,0,1)**4*(owner[field.a]==owner[field.b])
    degree=np.bincount(field.a,weights,minlength=field.n)+np.bincount(field.b,weights,minlength=field.n)
    result=delta.copy()
    for _ in range(4):
        diff=(result[field.a,2]-result[field.b,2])*weights
        lap=np.bincount(field.a,diff,minlength=field.n)-np.bincount(field.b,diff,minlength=field.n)
        result[:,2]-=lap/np.maximum(degree,1e-12)*rate
    correction=abs(result[:,2]-delta[:,2])
    rig.lip_surface_report.update(lip_collar_smooth_vertices=int(np.count_nonzero(correction>collar['width']*1e-8)),
                                  lip_collar_smooth_max=float(correction.max()))
    return result


def restore(rig,delta,recipe):
    report=dict(lower_lip_depth_vertices=0,lower_lip_depth_correction=0.,lip_collar_vertices=0)
    if not active(rig,recipe):return delta,report
    collar=prepare(rig);ids=sorted(collar['support'])
    # Collar points are soft shape goals. Re-pinning every bevel vertex after
    # ARAP restored folded corners and prevented the final skin repair.
    correction=np.zeros_like(delta)
    report.update(getattr(rig,'lip_surface_report',{}))
    report['lip_collar_vertices']=len(ids)
    report['lip_collar_correction']=float(np.linalg.norm(correction,axis=1).max())
    return delta+correction,report


def opening_skin(rig,raw):
    """Transport return faces by their attached lip edges, then spread travel.

    Nearest-curve projection can bind a return face to the adjacent corner
    segment. The actual shared edge fixes that ambiguity. Its local XZ frame
    preserves the front silhouette and its depth follows the same edge.
    """
    collar=prepare(rig)
    if 'edge_links' not in collar:
        rim=set(collar['branches'][False])|set(collar['branches'][True]);edges=set();links={}
        for up in (False,True):
            chain=[i for u,i in sorted({(u,i) for i,u,upper in rig.rows['LIP',0] if bool(upper)==up or u<1e-7 or u>1-1e-7})]
            edges.update(tuple(sorted((a,b))) for a,b in zip(chain,chain[1:]))
        free=set(collar['field'].free)
        for poly,label in zip(rig.info['faces'],rig.info['labels']):
            if label!=0:continue
            for a,b in zip(poly,poly[1:]+poly[:1]):
                if tuple(sorted((a,b))) not in edges:continue
                edge=(rig.points[b]-rig.points[a])[[0,2]];length=float(np.linalg.norm(edge))
                if length<collar['width']*1e-8:continue
                normal=np.array((-edge[1],edge[0]))/length
                for i in poly:
                    if i not in free:continue
                    offset=(rig.points[i]-rig.points[a])[[0,2]]
                    links.setdefault(i,[]).append((a,b,float(offset@edge/(length*length)),float(offset@normal)))
        collar['edge_links']=links
        collar['opening_field']=SkinDisplacementField(rig.points,rig.info['faces'],rig.info['labels'],
            collar['field'].free,set(links)|rim,fidelity=.001)
    posed=rig.points+raw;seed=raw.copy()
    for i,links in collar['edge_links'].items():
        goals=[]
        for a,b,t,offset in links:
            edge=(posed[b]-posed[a])[[0,2]];length=max(float(np.linalg.norm(edge)),1e-12)
            goal=rig.points[i].copy()
            goal[[0,2]]=posed[a,[0,2]]+t*edge+np.array((-edge[1],edge[0]))/length*offset
            s=float(np.clip(t,0,1));goal[1]+=raw[a,1]*(1-s)+raw[b,1]*s
            goals.append(goal-rig.points[i])
        seed[i]=np.mean(goals,axis=0)
    field=collar['opening_field']
    result=field.smooth_displacement(field.solve(seed),bending=2.)
    rig.lip_surface_report.update(lip_edge_follow_vertices=len(collar['edge_links']),lip_opening_field='topology_edge_transport')
    return result


def corner_transport(rig,delta,recipe):
    """Turn a corner return as one unit, blending C2 into the two lip branches.

    A thick rim can double back in X near the endpoint. Mapping each of its
    vertices to unrelated upper/lower arc samples pulls a fan into a blade.
    A shared endpoint frame retains that return-face shape. Monotone rims
    retain their opening arc: rotating a closed rest rim there creates a cusp.
    """
    if not active(rig,recipe) or closed_reference(recipe):return delta
    rows=rig.rows['LIP',0];width=rig.widths['LIP',0]
    corners=[min(rows,key=lambda row:row[1])[0],max(rows,key=lambda row:row[1])[0]]
    posed=rig.points+delta;result=delta.copy()
    chains=[sorted([(u,j) for j,u,up in rows if up==upper or u<1e-7 or u>1-1e-7]) for upper in (False,True)]
    for end,i in enumerate(corners):
        # Detect an actual inward/outward return along either bound branch.
        # Do not infer one merely from the presence of a shared endpoint.
        direction=1 if not end else -1;backtracking=0.
        for chain in chains:
            local=[j for u,j in (chain if not end else reversed(chain)) if (u<=.25 if not end else u>=.75)]
            travel=np.diff(rig.points[local,0])*direction
            backtracking=max(backtracking,float(np.maximum(-travel,0).sum())/width)
        influence=float(np.clip((backtracking-.001)/.009,0,1))
        if not influence:continue
        center=rig.points[i];goal=posed[i];inside=.2 if not end else .8
        def mean_at(points):
            return np.mean([np.array([np.interp(inside,[u for u,j in chain],points[[j for u,j in chain],axis])
                                     for axis in range(3)]) for chain in chains],axis=0)
        old=mean_at(rig.points)-center;new=mean_at(posed)-goal
        angle=np.arctan2(new[2],new[0])-np.arctan2(old[2],old[0]);c,s=np.cos(angle),np.sin(angle)
        rotation=np.array([[c,0,-s],[0,1,0],[s,0,c]])
        for j,u,upper in rows:
            distance=abs(rig.points[j,0]-center[0])/width
            if distance>=.24:continue
            t=distance/.24;weight=(1-t*t*t*(10-15*t+6*t*t))*influence
            target=goal+rotation@(rig.points[j]-center)-rig.points[j]
            result[j]=result[j]*(1-weight)+target*weight
    return result


def repair_open_corners(rig,initial,recipe):
    """Resolve coupled lip triangles with one damped least-squares step.

    The exact minimum signed area across key strength supplies the constraint.
    Nearby corner controls have low mobility; central lip controls remain
    exact. Travel is bounded, and a failed solve retains a reported residual.
    """
    if not active(rig,recipe) or closed_reference(recipe):return initial,{}
    collar=prepare(rig);width=collar['width'];mobility=np.zeros_like(initial)
    free=sorted(set(rig.field.free)&set(np.flatnonzero(collar['fade']>0)));mobility[free]=1.
    for i,u,upper in rig.rows['LIP',0]:
        distance=min(u,1-u)
        if distance<.22:mobility[i]=.25*(1-distance/.22)**2
    triangles=np.asarray(rig.field.triangles);rest=rig.points[triangles]
    a=rest[:,1]-rest[:,0];b=rest[:,2]-rest[:,0];n=np.cross(a,b);area=np.linalg.norm(n,axis=1);n/=np.maximum(area[:,None],1e-25)
    selected=np.flatnonzero(np.any(mobility>0,axis=1));lookup=np.full(len(initial),-1);lookup[selected]=np.arange(len(selected))
    weights=np.sqrt(mobility)*np.clip(rig.field.edge_length[:,None],width*.02,width*.2)
    usable=area>1e-14;movable=np.any(lookup[triangles]>=0,axis=1)
    def state(delta):
        d=delta[triangles];da=d[:,1]-d[:,0];db=d[:,2]-d[:,0]
        aa=np.sum(np.cross(da,db)*n,axis=1);bb=np.sum((np.cross(da,b)+np.cross(a,db))*n,axis=1)
        t=np.ones(len(area));positive=aa>1e-25;t[positive]=np.clip(-bb[positive]/(2*aa[positive]),0,1)
        return rest+d*t[:,None,None],(area+bb*t+aa*t*t)/np.maximum(area,1e-25),t
    result=initial.copy();iterations=0
    for iteration in range(80):
        p,ratio,t=state(result);violated=np.flatnonzero(usable&(ratio<.04)&movable)
        if not len(violated):break
        if len(violated)>512:break  # Keep a pathological mesh from allocating a dense unbounded solve.
        grad=np.stack([np.cross(p[:,1]-p[:,2],n),np.cross(p[:,2]-p[:,0],n),np.cross(p[:,0]-p[:,1],n)],axis=1)*t[:,None,None]/np.maximum(area[:,None,None],1e-25)
        jac=np.zeros((len(violated),len(selected)*3));rhs=np.maximum(.04-ratio[violated],0)
        for j,triangle in enumerate(triangles[violated]):
            for k,i in enumerate(triangle):
                if lookup[i]>=0:jac[j,lookup[i]*3:lookup[i]*3+3]+=grad[violated[j],k]*weights[i]
        diagonal=np.linalg.norm(jac,axis=1);valid=diagonal>1e-12;jac=jac[valid]/diagonal[valid,None];rhs=rhs[valid]/diagonal[valid]
        if not len(rhs):break
        step=(jac.T@np.linalg.solve(jac@jac.T+np.eye(len(rhs))*.003,rhs)).reshape((-1,3))*weights[selected]
        step*=min(1.,width*.015/max(float(np.linalg.norm(step,axis=1).max()),1e-20))
        error=np.maximum(.02-ratio[usable],0);score=float(error@error);accepted=False
        for gain in (1.,.5,.25,.125,.0625):
            candidate=result.copy();candidate[selected]+=step*gain
            travel=candidate-initial
            travel*=np.minimum(1.,width*.12/np.maximum(np.linalg.norm(travel,axis=1),1e-20))[:,None]
            candidate=initial+travel
            _,r,_=state(candidate);error=np.maximum(.02-r[usable],0)
            if float(error@error)<score:result=candidate;accepted=True;iterations=iteration+1;break
        if not accepted:break
    _,ratio,_=state(result)
    return result,dict(face_fold_unresolved=int(np.sum(usable&(ratio<.005))),
        mouth_corner_iterations=iterations,mouth_corner_correction=float(np.linalg.norm(result-initial,axis=1).max()))
