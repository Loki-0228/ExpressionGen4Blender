"""Local ribbon repair with fixed attachments and a full shape-key path check."""
import numpy as np


def capped_overhang(reach,span,ratio):
    """Compress exterior reach with a continuous join at the canthus."""
    fraction=np.clip(reach/span,0.,1.)
    easing=(1.-fraction)**2 if ratio>=.25 else 0.
    return reach*(ratio+(1.-ratio)*easing)


def graph_distances(points,neighbors,seeds):
    """Physical arc distance, including zero-length UV seam connections."""
    import heapq
    distance=np.full(len(points),np.inf);queue=[]
    for i in seeds:distance[i]=0.;heapq.heappush(queue,(0.,int(i)))
    while queue:
        value,i=heapq.heappop(queue)
        if value>distance[i]:continue
        for j in neighbors[i]:
            candidate=value+float(np.linalg.norm(points[j]-points[i]))
            if candidate<distance[j]:
                distance[j]=candidate;heapq.heappush(queue,(candidate,int(j)))
    return distance


def shorten_curve(rest,posed,neighbors,upper,rim,width,amount,movable=None,support=None):
    """Shorten each return between its existing caps, retaining strip offsets.

    The lower lid supplies curvature, not a line onto which all vertices are
    projected. Each section keeps its offset from the old strip centre.
    """
    distance=graph_distances(rest,neighbors,np.flatnonzero(upper))
    free=~upper if movable is None else (~upper)&movable
    remaining=set(np.flatnonzero(free));result=posed.copy()
    fixed=set(np.flatnonzero(~free));ends=[]
    guide=rim if support is None else support
    origin=float(guide[:,0].mean());scale=max(float(np.ptp(guide[:,0])),width*.1)
    curve=np.polynomial.polynomial.polyfit((guide[:,0]-origin)/scale,guide[:,2],3)
    while remaining:
        component={remaining.pop()};pending=list(component)
        while pending:
            for j in neighbors[pending.pop()]&remaining:
                remaining.remove(j);component.add(j);pending.append(j)
        local=np.array(sorted(component),dtype=int)
        boundary=np.array(sorted(set.union(*(neighbors[i] for i in local))-component),dtype=int)
        terminal=boundary[~upper[boundary]]
        maximum=float(distance[terminal].mean() if len(terminal) else distance[local].max())
        if not len(boundary) or not np.isfinite(maximum) or maximum<width*.04:
            fixed.update(component);continue
        if not len(terminal):terminal=local[distance[local]>=maximum*.94]
        fixed.update(terminal);ends.extend(terminal)
        ids=np.r_[boundary,local];t=distance[ids]/maximum
        # Smooth section centres avoid following the individual toothed edge
        # of a lash. Subtract/add centres; keep each vertex's transverse offset.
        basis=np.column_stack((np.ones(len(t)),t,t*t,t*t*t))
        fitted=np.linalg.lstsq(basis,posed[ids],rcond=None)[0]
        parameter=np.clip(distance[local]/maximum,0.,1.)
        matrix=np.column_stack((np.ones(len(local)),parameter,parameter**2,parameter**3))
        centers=matrix@fitted
        start=fitted[0];end=fitted.sum(0)
        x=start[0]+parameter*(end[0]-start[0])
        height=np.polynomial.polynomial.polyval((x-origin)/scale,curve)
        za,zb=np.polynomial.polynomial.polyval((np.array((start[0],end[0]))-origin)/scale,curve)
        height+=(1.-parameter)**3*(start[2]-za)+parameter**3*(end[2]-zb)
        shift=np.column_stack((x-centers[:,0],np.zeros(len(local)),height-centers[:,2]))
        # The cap sections are exact, with a short smooth transition to them.
        fade=np.minimum(parameter/.12,(1.-parameter)/.12)
        fade=np.clip(fade,0.,1.);fade=fade*fade*(3.-2.*fade)
        result[local]+=shift*(fade*amount)[:,None]
    result[list(fixed)]=posed[list(fixed)]
    return result,np.array(sorted(fixed),dtype=int),np.asarray(ends,dtype=int)


def project_active(rows,bounds,metric,tolerance):
    """Solve only active inequalities, but certify against the complete set."""
    from .procedural_projection import project
    correction=np.zeros(rows.shape[1]);active=set()
    for _ in range(32):
        residual=rows@correction-bounds
        failed=np.flatnonzero(residual>tolerance)
        if not len(failed):return correction
        new=[int(i) for i in failed if i not in active]
        if new:
            active.update(sorted(new,key=lambda i:residual[i],reverse=True)[:128])
        selected=np.array(sorted(active),dtype=int);matrix=rows[selected]
        directions=matrix@metric;norm=np.sum(matrix*directions,axis=1)
        correction=project(matrix,bounds[selected],directions,norm,tolerance,
                           iterations=4096 if new else 16384)
        if not new:break
    return correction


def repair_path(rest, posed, triangles, edges, roots, stitches=(), margin=.05):
    """Remove local in-plane folds without releasing either eyelid's roots.

    Depth/contact is solved afterwards. The signed area is minimized exactly
    over the linear 0..1 shape-key interval, including interior extrema.
    Seam aliases receive the same displacement, not independent corrections.
    """
    scale=max(float(np.ptp(rest,axis=0).max()),1e-12)
    origin=rest.mean(0);p=(rest-origin)/scale;q=(posed-origin)/scale;initial=q.copy()
    parent=np.arange(len(p))
    def root(i):
        while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
        return i
    for group in stitches:
        for i in group[1:]:parent[root(i)]=root(group[0])
    aliases=np.array([root(i) for i in range(len(p))])
    pinned=set(aliases[roots]);free=np.array(sorted(set(aliases)-pinned),dtype=int)
    if not len(free):return posed
    lookup={i:k for k,i in enumerate(free)}
    mapping=np.array([lookup.get(i,-1) for i in aliases])
    a,b,c=np.asarray(triangles,dtype=int).T
    normal=np.cross(p[b]-p[a],p[c]-p[a]);area=np.linalg.norm(normal,axis=1)
    normal/=np.maximum(area[:,None],1e-20)
    valid=area>1e-12
    graph=np.eye(len(free))
    links={tuple(sorted((int(mapping[i]),int(mapping[j])))) for i,j in edges
           if mapping[i]!=mapping[j]}
    for i,j in links:
        if i>=0:graph[i,i]+=2.
        if j>=0:graph[j,j]+=2.
        if i>=0 and j>=0:graph[i,j]-=2.;graph[j,i]-=2.
    metric=np.kron(np.linalg.inv(graph),np.eye(2))
    ea,eb=np.asarray(edges,dtype=int).T
    length2=np.sum((p[ea]-p[eb])**2,axis=1)*1.45**2
    from .procedural_projection import project
    for _ in range(64):
        d=q-p;ab=p[b]-p[a];ac=p[c]-p[a]
        da=d[b]-d[a];db=d[c]-d[a]
        quad=np.einsum('ij,ij->i',np.cross(da,db),normal)
        linear=np.einsum('ij,ij->i',np.cross(da,ac)+np.cross(ab,db),normal)
        t=np.ones(len(a));convex=quad>1e-20
        t[convex]=np.clip(-linear[convex]/(2*quad[convex]),0.,1.)
        minimum=area+linear*t+quad*t*t
        bad=np.flatnonzero(valid&(minimum<area*margin-1e-10))
        diff=(q[ea]-q[eb])[:,[0,2]]
        strained=np.flatnonzero(np.sum(diff**2,axis=1)>length2+1e-10)
        if not len(bad) and not len(strained):break
        rows=[];bounds=[]
        def constraint(ids,grad,bound):
            row=np.zeros((len(free),2))
            for i,g in zip(ids,grad):
                if mapping[i]>=0:row[mapping[i]]+=g
            norm=np.linalg.norm(row)
            if norm<=1e-12:return
            rows.append(row.ravel()/norm);bounds.append(bound/norm)
        for k in bad:
            i,j,h=a[k],b[k],c[k];time=t[k]
            x=p+time*d
            gj=np.cross(x[h]-x[i],normal[k])*time
            gh=np.cross(normal[k],x[j]-x[i])*time
            # Negative gradient expresses minimum area as A @ dx <= b.
            constraint((i,j,h),np.array((gj+gh,-gj,-gh))[:,[0,2]],
                       minimum[k]-area[k]*(margin+1e-4))
        for k in strained:
            constraint((ea[k],eb[k]),np.array((2*diff[k],-2*diff[k])),
                       length2[k]-float(diff[k]@diff[k])-1e-10)
        if not rows:break
        rows=np.asarray(rows);bounds=np.asarray(bounds)
        directions=rows@metric;norm=np.sum(rows*directions,axis=1)
        step=project(rows,bounds,directions,norm,1e-8,iterations=256).reshape((-1,2))
        maximum=float(np.linalg.norm(step,axis=1).max())
        if maximum<1e-10:break
        step*=min(1.,.04/max(maximum,1e-12))
        selected=np.flatnonzero(mapping>=0)
        q[np.ix_(selected,[0,2])]+=step[mapping[selected]]
    # Retain the original depth bits and all fixed vertices exactly.
    result=posed.copy();selected=np.flatnonzero(mapping>=0)
    result[np.ix_(selected,[0,2])]+=(q-initial)[np.ix_(selected,[0,2])]*scale
    return result
