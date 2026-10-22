"""Density-independent strip profiles and constrained global cubic curve fits."""
import numpy as np

VERSION=3


def strip_centerline(points,faces,samples=65,side=1):
    """Sample the occupied strip cross-section, not averages of vertex bins.

    Faces belong to one already separated accessory. Repeated front/back faces
    and unequal subdivisions therefore cannot bias the center toward one edge.
    """
    points=np.asarray(points,dtype=float)
    ids=sorted({i for face in faces for i in face})
    if not ids:return []
    lo,hi=np.min(points[ids,0]),np.max(points[ids,0]);width=hi-lo
    if width<=1e-12:return []
    edges=[[(points[a],points[b]) for a,b in zip(face,face[1:]+face[:1])] for face in faces]
    profile=[];previous=None
    # Track both eyes from their inner corner to the outer wing. Starting at
    # global min-X chooses opposite anatomical ends on mirrored multilayer cards.
    sections=np.linspace(lo+width*1e-8,hi-width*1e-8,samples)
    for x in sections if side>0 else sections[::-1]:
        intervals=[]
        for row in edges:
            hits=[]
            for a,b in row:
                if abs(b[0]-a[0])<=width*1e-12:continue
                t=(x-a[0])/(b[0]-a[0])
                if min(a[0],b[0])<=x<max(a[0],b[0]):hits.append(a+(b-a)*t)
            hits.sort(key=lambda p:p[2])
            # Concave strips can produce several filled intervals at a slice.
            for a,b in zip(hits[::2],hits[1::2]):intervals.append([a.copy(),b.copy()])
        merged=[]
        for a,b in sorted(intervals,key=lambda pair:pair[0][2]):
            if merged and a[2]<=merged[-1][1][2]+width*1e-9:
                if b[2]>merged[-1][1][2]:merged[-1][1]=b
            else:merged.append([a,b])
        if not merged:continue
        centers=[(a+b)/2 for a,b in merged]
        if previous is None:
            index=max(range(len(merged)),key=lambda i:merged[i][1][2]-merged[i][0][2])
        else:index=min(range(len(centers)),key=lambda i:np.linalg.norm(centers[i][1:]-previous[1:]))
        previous=centers[index];profile.append(previous)
    return np.asarray(profile if side>0 else profile[::-1]).tolist()


def _basis(t,knots,degree):
    t=np.minimum(np.asarray(t,dtype=float),np.nextafter(1.,0.))
    rows=((t[:,None]>=knots[:-1]) & (t[:,None]<knots[1:])).astype(float)
    for order in range(1,degree+1):
        count=len(knots)-order-1;out=np.zeros((len(t),count))
        for i in range(count):
            a=knots[i+order]-knots[i];b=knots[i+order+1]-knots[i+1]
            if a>0:out[:,i]+=(t-knots[i])/a*rows[:,i]
            if b>0:out[:,i]+=(knots[i+order+1]-t)/b*rows[:,i+1]
        rows=out
    return rows


def _derivative(t,knots):
    low=_basis(t,knots,2);out=np.zeros((len(t),len(knots)-4))
    for i in range(out.shape[1]):
        a=knots[i+3]-knots[i];b=knots[i+4]-knots[i+1]
        if a>0:out[:,i]+=3/a*low[:,i]
        if b>0:out[:,i]-=3/b*low[:,i+1]
    return out


def fit(points,kind,segments=None):
    """Fit a whole curve, with fixed ends, robust residuals and curvature cost.

    Return exact cubic Bezier spans of the fitted B-spline. Blender's automatic
    handles are not used to interpolate noisy samples a second time.
    """
    raw=np.asarray(points,dtype=float)
    if (kind=='LASH' and segments is None) or len(raw)<2:return None
    length=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(raw,axis=0),axis=1))]
    if length[-1]<=1e-12:return None
    good=np.r_[True,np.diff(length)>length[-1]*1e-12]
    raw=raw[good];length=length[good]/length[-1]
    controls=(int(segments)+3 if segments is not None else
              10 if kind.startswith('LIP_') else 8 if kind.startswith('EYE_') else 6)
    if not 4<=controls<=67:raise ValueError('拟合段数须在 1～64 之间')
    t=np.linspace(0,1,max(65,controls*4))
    samples=np.column_stack([np.interp(t,length,raw[:,axis]) for axis in range(3)])
    knots=np.r_[np.zeros(4),np.linspace(0,1,controls-2)[1:-1],np.ones(4)]
    matrix=_basis(t,knots,3)
    penalty=np.diff(np.eye(controls),n=2,axis=0)
    coefficient=.02 if kind in ('BROW','CREASE') else .005
    ends=np.stack((samples[0],samples[-1]))
    rhs=samples-matrix[:,[0,-1]]@ends
    penalized=-penalty[:,[0,-1]]@ends
    weights=np.ones(len(t));solution=np.zeros((controls,3));solution[[0,-1]]=ends
    span=max(np.linalg.norm(np.ptp(samples,axis=0)),1e-12)
    for _ in range(4):
        scale=np.sqrt(weights)[:,None]
        lhs=np.vstack((matrix[:,1:-1]*scale,np.sqrt(coefficient)*penalty[:,1:-1]))
        values=np.vstack((rhs*scale,np.sqrt(coefficient)*penalized))
        solution[1:-1]=np.linalg.lstsq(lhs,values,rcond=None)[0]
        errors=np.linalg.norm(matrix@solution-samples,axis=1)
        cutoff=max(np.median(errors)*2.5,span*.002)
        weights=np.minimum(1,cutoff/np.maximum(errors,1e-15))
    breaks=np.unique(knots)
    anchors=_basis(breaks,knots,3)@solution;derivatives=_derivative(breaks,knots)@solution
    left=anchors.copy();right=anchors.copy()
    for i,h in enumerate(np.diff(breaks)):
        right[i]=anchors[i]+derivatives[i]*h/3
        left[i+1]=anchors[i+1]-derivatives[i+1]*h/3
    anchors[0]=samples[0];anchors[-1]=samples[-1]
    return dict(version=VERSION,method='robust_global_cubic_bspline',points=anchors.tolist(),
                left=left.tolist(),right=right.tolist(),rms=float(np.sqrt(np.mean(errors**2))),
                max_error=float(max(errors)),samples=len(samples))
