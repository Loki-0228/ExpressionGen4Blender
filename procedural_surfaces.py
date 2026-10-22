"""Projected triangle overlap constraints, including tiny interior islands."""
import numpy as np
from . import procedural_gpu as GPU


def cross2(a,b):
    return a[...,0]*b[...,1]-a[...,1]*b[...,0]


def barycentric(tri,points):
    a=tri[:,1]-tri[:,0];b=tri[:,2]-tri[:,0]
    determinant=cross2(a,b)
    scale=np.maximum(np.sum(a*a,axis=1)+np.sum(b*b,axis=1),1e-30)
    valid=np.abs(determinant)>scale*1e-12
    safe=np.where(valid,determinant,1.)
    q=points-tri[:,None,0]
    u=cross2(q,b[:,None])/safe[:,None];v=cross2(a[:,None],q)/safe[:,None]
    weights=np.stack((1-u-v,u,v),axis=-1)
    inside=valid[:,None] & np.all(weights>=-1e-9,axis=-1) & np.all(weights<=1+1e-9,axis=-1)
    return weights,inside


def overlap_vertices(a,b):
    """All vertices of the convex overlap, in both triangle coordinates."""
    # The extrema of the depth difference of two planes are at these vertices.
    # Cover contained triangles, crossings, and coincident projected edges.
    wb,inside_a=barycentric(b,a);wa,inside_b=barycentric(a,b)
    identity=np.broadcast_to(np.eye(3),(len(a),3,3))
    aw=[identity,wa];bw=[wb,identity];valid=[inside_a,inside_b]
    for i in range(3):
        j=(i+1)%3;p=a[:,i];r=a[:,j]-p
        for k in range(3):
            l=(k+1)%3;q=b[:,k];s=b[:,l]-q
            denominator=cross2(r,s)
            scale=np.maximum(np.linalg.norm(r,axis=1)*np.linalg.norm(s,axis=1),1e-30)
            good=abs(denominator)>scale*1e-12;safe=np.where(good,denominator,1.)
            u=cross2(q-p,s)/safe;v=cross2(q-p,r)/safe
            good&=(u>=-1e-9)&(u<=1+1e-9)&(v>=-1e-9)&(v<=1+1e-9)
            x=np.zeros((len(a),1,3));y=x.copy()
            x[:,0,i]=1-u;x[:,0,j]=u;y[:,0,k]=1-v;y[:,0,l]=v
            aw.append(x);bw.append(y);valid.append(good[:,None])
    aw=np.maximum(np.concatenate(aw,axis=1),0.);bw=np.maximum(np.concatenate(bw,axis=1),0.)
    aw/=np.maximum(aw.sum(-1,keepdims=True),1e-30);bw/=np.maximum(bw.sum(-1,keepdims=True),1e-30)
    valid=np.concatenate(valid,axis=1)
    for tri in (a,b):
        u=tri[:,1]-tri[:,0];v=tri[:,2]-tri[:,0]
        area=abs(cross2(u,v));scale=np.maximum(np.sum(u*u+v*v,axis=-1),1e-30)
        valid&=(area>scale*1e-12)[:,None]
    return aw,bw,valid


def depth_bounds(points,triangles,obstacles,movable,front=True,coherent=False,pulse=None):
    """Minimal signed-Y bounds at complete projected triangle overlaps.

    front=True puts the moving mesh in front of every overlapping obstacle;
    front=False puts it behind them. No model-size clearance is introduced.
    coherent=True distributes one contact equally over free triangle corners
    to avoid concentrating cavity corrections on a single vertex.
    Return per-vertex correction and the number of immovable conflicts.
    """
    ids=np.asarray(triangles,dtype=np.int32).reshape((-1,3))
    obstacles=np.asarray(obstacles,dtype=float).reshape((-1,3,3))
    result=np.zeros(len(points));blocked=0
    recorder=getattr(pulse,'count',None)
    if recorder:recorder(depth_calls=1)
    if not len(ids) or not len(obstacles):return result,blocked
    other=obstacles[:,:,[0,2]];lo=other.min(1);hi=other.max(1)
    tolerance=max(float(np.ptp(obstacles.reshape((-1,3)),axis=0).max())*1e-8,1e-12)
    accelerated=GPU.try_depth(points,ids,obstacles,movable,front,coherent,tolerance,pulse)
    if accelerated is not None:return accelerated
    sign=-1. if front else 1.
    for first in range(0,len(ids),128):
        if pulse:pulse()
        local=ids[first:first+128];cloud=points[local];plane=cloud[:,:,[0,2]]
        candidates=np.all(plane.min(1)[:,None]<=hi,axis=-1)&np.all(plane.max(1)[:,None]>=lo,axis=-1)
        ia,ib=np.nonzero(candidates)
        if recorder:recorder(depth_bbox_pairs=len(local)*len(obstacles),depth_overlap_pairs=len(ia))
        if not len(ia):continue
        wa,wb,valid=overlap_vertices(plane[ia],other[ib])
        moving_y=np.sum(wa*cloud[ia,None,:,1],axis=-1)
        obstacle_y=np.sum(wb*obstacles[ib,None,:,1],axis=-1)
        needed=sign*(obstacle_y-moving_y)
        # Only a numerical tolerance is used; no added inter-layer gap.
        valid&=needed>tolerance
        freedom=movable[local[ia]][:,None,:]
        denominator=np.sum((wa if coherent else wa*wa)*freedom,axis=-1)
        blocked+=int(np.count_nonzero(valid & (denominator<=1e-12)))
        k,v=np.nonzero(valid & (denominator>1e-12))
        if not len(k):continue
        distribution=freedom[k,0] if coherent else wa[k,v]*freedom[k,0]
        changes=needed[k,v,None]*distribution/denominator[k,v,None]
        # All barycentric weights are nonnegative. Taking the largest required
        # correction per vertex satisfies every collected inequality together.
        np.maximum.at(result,local[ia[k]].ravel(),changes.ravel())
    return result*sign,blocked
