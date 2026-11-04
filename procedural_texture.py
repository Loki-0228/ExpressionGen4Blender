"""Material-expression cards: region planes, a face shell and J-point anchors.

All three kinds share one contract. A card owns a Basis that is hidden -- the
region cards shrink behind the face shell's front surface, the anchor cards
retreat into the head along their own normal -- and one shape key per
expression that rides the fitted surface a short distance in front of it.
Turning an expression on therefore moves the card out of occlusion; nothing
relies on absolute model units.

Front is -Y, matching the skin and cavity depth conventions of the solver.
This module is bpy free so the geometry can be checked without Blender.
"""
import numpy as np

FRONT=-1.0
CLEARANCE=.010        # card offset in eye-width units
MARGIN=.010           # how far behind the face front a hidden card sits
COLLAPSE=.03          # hidden cards keep 3% of their span
SHELL_OFFSET=.004


def _unit(vector, fallback):
    vector=np.asarray(vector,dtype=float)
    length=float(np.linalg.norm(vector))
    return vector/length if length>1e-12 else np.asarray(fallback,dtype=float)


def _basis(center, normal, u, v):
    return np.column_stack((u, v, normal)), np.asarray(center,dtype=float)


def frame(points, faces):
    """Fit one region: centroid, front normal, tangents and local coordinates.

    The normal is the area-weighted mean of face normals, flipped to -Y so
    "front" always means the viewer's side. Local depth grows toward the front.
    """
    points=np.asarray(points,dtype=float)
    faces=[list(face) for face in faces]
    ids=sorted({i for face in faces for i in face})
    if len(ids)<3:raise ValueError('分区面数不足以拟合贴图平面')
    cloud=points[ids]
    normals=[]
    for face in faces:
        tri=points[np.asarray(face[:3],dtype=int)]
        normal=np.cross(tri[1]-tri[0],tri[2]-tri[0])
        length=float(np.linalg.norm(normal))
        if length>1e-14:normals.append(normal/length)
    if not normals:raise ValueError('分区面含零面积，无法确定贴图朝向')
    normal=np.mean(normals,axis=0)
    if float(normal[1])>0:normal=-normal
    normal=_unit(normal,(0.,-1.,0.))
    u=np.array((1.,0.,0.))-normal*normal[0]
    if float(np.linalg.norm(u))<1e-8:u=np.array((0.,0.,1.))-normal*normal[2]
    u=_unit(u,(1.,0.,0.));v=_unit(np.cross(normal,u),(0.,0.,1.))
    center=points[np.asarray(ids,dtype=int)].mean(axis=0)
    local=(cloud-center)@np.column_stack((u,v,normal))
    span=np.maximum(np.ptp(local[:,:2],axis=0),1e-12)
    return dict(center=center,normal=normal,u=u,v=v,ids=ids,cloud=cloud,local=local,
                width=float(span[0]),height=float(span[1]),
                scale=max(float(span[0]),float(span[1])),
                depth_back=float(local[:,2].min()),depth_front=float(local[:,2].max()))


def hull(uv):
    """Convex silhouette of the region; Andrew's monotone chain, no scipy."""
    pts=sorted({(round(float(x),12),round(float(y),12)) for x,y in np.asarray(uv)})
    if len(pts)<3:raise ValueError('分区投影点不足以构成轮廓')

    def cross(o,a,b):return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    lower=[]
    for p in pts:
        while len(lower)>=2 and cross(lower[-2],lower[-1],p)<=0:lower.pop()
        lower.append(p)
    upper=[]
    for p in reversed(pts):
        while len(upper)>=2 and cross(upper[-2],upper[-1],p)<=0:upper.pop()
        upper.append(p)
    ring=lower[:-1]+upper[:-1]
    return np.asarray(ring if len(ring)>=3 else pts,dtype=float)


def inside(uv, ring):
    """Even-odd point-in-polygon, vectorised over the query points."""
    uv=np.asarray(uv,dtype=float);ring=np.asarray(ring,dtype=float)
    x,y=uv[:,0],uv[:,1];hit=np.zeros(len(uv),dtype=bool)
    a,b=ring[:-1],ring[1:]
    for (x0,y0),(x1,y1) in zip(a,b):
        straddle=(y0>y)!=(y1>y)
        span=y1-y0
        xint=x0+(y-y0)*(x1-x0)/np.where(abs(span)<1e-12,1e-12,span)
        hit^=straddle&(x<xint)
    return hit


def lattice(ring, columns=8, rows=8, inset=.06):
    """Lattice samples inside an inset outline plus their index grid.

    Returns (samples Nx2, grid rows x columns of indices into samples, -1 for
    samples that fell outside). A degenerate card returns the ring and None so
    callers can fall back to a triangle fan.
    """
    ring=np.asarray(ring,dtype=float)
    if len(ring)<3:raise ValueError('轮廓点数不足')
    center=ring.mean(axis=0)
    ring=center+(ring-center)*(1.0-float(np.clip(inset,0.,.4)))
    lo,hi=ring.min(axis=0),ring.max(axis=0);span=np.maximum(hi-lo,1e-12)
    columns=max(int(columns),2);rows=max(int(rows),2)
    xs=lo[0]+span[0]*(np.arange(columns)+.5)/columns
    ys=lo[1]+span[1]*(np.arange(rows)+.5)/rows
    xx,yy=np.meshgrid(xs,ys,indexing='xy')
    candidates=np.column_stack((xx.ravel(),yy.ravel()))
    keep=inside(candidates,ring)
    if np.count_nonzero(keep)<3:return ring,None
    remap=np.full(len(candidates),-1,dtype=int)
    remap[np.flatnonzero(keep)]=np.arange(int(np.count_nonzero(keep)))
    return candidates[keep],remap.reshape((rows,columns))


def triangles(grid):
    """Two triangles per fully kept cell, wound toward the front normal."""
    if grid is None:return None
    rows,columns=grid.shape;faces=[]
    for r in range(rows-1):
        for c in range(columns-1):
            a,b,d,e=grid[r,c],grid[r,c+1],grid[r+1,c],grid[r+1,c+1]
            if min(a,b,d,e)<0:continue
            faces.append((int(a),int(b),int(e)));faces.append((int(a),int(e),int(d)))
    return faces


def upper_bands(uv, band=.33, columns=14, rows=3, expand=1.):
    # One arched strip per eye. The region holds both eyes, so it is split at
    # its middle in X. Each strip's top edge traces the highest point of the eye
    # in every column and the strip reaches down `band` of the eye height.
    # Returns (samples Nx2, triangles wound toward the front normal).
    uv=np.asarray(uv,dtype=float)
    if len(uv)<6:raise ValueError('分区投影点不足以构成弧形带')
    columns=max(int(columns),3);rows=max(int(rows),2)
    split=float((uv[:,0].min()+uv[:,0].max())*.5)
    samples=[];faces=[];base=0
    for group in (uv[uv[:,0]<split],uv[uv[:,0]>=split]):
        if len(group)<3:continue
        lo,hi=float(group[:,0].min()),float(group[:,0].max())
        if hi-lo<1e-9:continue
        inner=np.linspace(lo,hi,columns);reach=(hi-lo)/(columns-1)
        top=np.full(columns,np.nan)
        for i,x in enumerate(inner):
            near=group[abs(group[:,0]-x)<=reach*.75]
            if len(near):top[i]=near[:,1].max()
        known=~np.isnan(top)
        top=np.interp(inner,inner[known],top[known])
        padded=np.r_[top[0],top,top[-1]]
        top=(padded[:-2]+padded[1:-1]+padded[2:])/3.
        mid=(lo+hi)*.5;half=(hi-lo)*.5*max(float(expand),1.)
        xs=np.linspace(mid-half,mid+half,columns)
        top=np.interp(xs,inner,top)
        thickness=float(np.clip(band,.05,1.))*max(float(np.ptp(group[:,1])),1e-9)
        for r in range(rows):
            samples.append(np.column_stack((xs,top-thickness*(1.-r/(rows-1)))))
        grid=base+np.arange(rows*columns).reshape((rows,columns))
        faces.extend(triangles(grid))
        base+=rows*columns
    if not faces:raise ValueError('分区投影点不足以构成弧形带')
    return np.vstack(samples),faces


def _nearest(local, uv):
    if not len(local):raise ValueError('分区没有可投影的顶点')
    distance=((np.asarray(uv,dtype=float)[:,None,:]-local[None,:,:2])**2).sum(axis=2)
    return np.argmin(distance,axis=1)


def footprint(fr, points, faces, reach=1.6):
    """Face-shell depths under this card's footprint, in the card's frame.

    Only face vertices whose tangent-plane position falls near the region are
    kept, so a nose or chin cannot decide whether an eye card is hidden.
    """
    ids=sorted({i for face in faces for i in face})
    if not ids:raise ValueError('缺少面部顶点，无法把贴图收进脸壳')
    ids=np.asarray(ids,dtype=int)
    local=(np.asarray(points,dtype=float)[ids]-fr['center'])@np.column_stack(
        (fr['u'],fr['v'],fr['normal']))
    span=max(float(fr['scale']),1e-9)*max(float(reach),1.0)
    region=fr['local'][:,:2]
    keep=np.all(abs(local[:,:2]-region.mean(axis=0))<=span,axis=1)
    if np.count_nonzero(keep)<3:keep=np.ones(len(ids),dtype=bool)
    return local[keep,2]


def fitted(fr, uv, clearance=CLEARANCE, neighbors=4):
    """Card samples a near distance in front of the region surface.

    A sample takes the front-most depth among its nearest region points, then
    one shared clearance (in eye-width units) lifts it off the skin. Using the
    local front rather than a single nearest vertex keeps the patch above a
    bowled eyelid instead of letting it dip between samples.
    """
    uv=np.asarray(uv,dtype=float)
    cloud=fr['local']
    if not len(cloud):raise ValueError('分区没有可投影的顶点')
    distance=((uv[:,None,:]-cloud[None,:,:2])**2).sum(axis=2)
    count=max(1,min(int(neighbors),len(cloud)))
    nearest=np.argsort(distance,axis=1)[:,:count]
    depth=cloud[nearest,2].max(axis=1)+float(max(clearance,0.))*fr['scale']
    return fr['center']+uv[:,0:1]*fr['u']+uv[:,1:2]*fr['v']+depth[:,None]*fr['normal']


def hidden(fr, uv, behind=None, margin=MARGIN, collapse=COLLAPSE):
    """Shrink the card and park it just behind every face point it overlaps.

    `behind` is the least-front face depth under the footprint (for example
    ``footprint(...).min()``). The card then cannot poke through the skin at
    any sample, and the shared margin keeps it clear of z-fighting.
    """
    uv=np.asarray(uv,dtype=float)
    center=uv.mean(axis=0)
    shrink=center+(uv-center)*float(np.clip(collapse,0.,1.))
    # Default to the region's own back rim: still behind every region sample.
    back=float(fr['depth_back'] if behind is None else behind)
    depth=back-float(max(margin,0.))*fr['scale']
    return fr['center']+shrink[:,0:1]*fr['u']+shrink[:,1:2]*fr['v']+np.full(len(shrink),depth)[:,None]*fr['normal']


def face_depth(fr, faces, points):
    """Most front depth of the face shell along this card's normal."""
    ids=sorted({i for face in faces for i in face})
    if not ids:raise ValueError('缺少面部顶点，无法把贴图收进脸壳')
    local=(np.asarray(points,dtype=float)[np.asarray(ids,dtype=int)]-fr['center'])@fr['normal']
    return float(local.max())


def shell(points, faces, offset=SHELL_OFFSET, scale=1., limit=True):
    """Transparent curved shell over the whole face, offset along normals."""
    points=np.asarray(points,dtype=float)
    faces=[list(face) for face in faces]
    normals=np.zeros_like(points)
    for face in faces:
        tri=points[np.asarray(face[:3],dtype=int)]
        normal=np.cross(tri[1]-tri[0],tri[2]-tri[0])
        for i in face:normals[i]+=normal
    lengths=np.maximum(np.linalg.norm(normals,axis=1)[:,None],1e-14)
    normals/=lengths
    ids=sorted({i for face in faces for i in face})
    # Offset along the Face polygons' own normals exactly as modelled; no sign flip.
    distance=np.full(len(points),float(max(offset,0.))*float(max(scale,1e-9)))
    if limit:
        # A vertex never moves further than half its shortest adjacent edge; otherwise the tiny
        # triangles around the eyes are pushed through themselves and turn inside out.
        reach=np.full(len(points),np.inf)
        for face in faces:
            for a,b in zip(face,face[1:]+face[:1]):
                length=float(np.linalg.norm(points[a]-points[b]))
                if length>1e-12:
                    reach[a]=min(reach[a],length);reach[b]=min(reach[b],length)
        distance=np.minimum(distance,.5*reach)
    return points+normals*distance[:,None]


def anchor(position, rotation, width=.1, height=.1, axis=1):
    """Quad and front direction at a user anchor.

    `axis` names the local column that points into the head, so the card front
    is its negation. Blender uses local -Y (the module's front convention);
    PMX uses local -Z. The other two columns span the card.
    """
    matrix=np.asarray(rotation,dtype=float).reshape((3,3))
    axis=int(np.clip(axis,0,2))
    into=_unit(matrix[:,axis],(0.,1.,0.))
    front=-into
    others=[column for column in (0,1,2) if column!=axis]
    right=_unit(matrix[:,others[0]],(1.,0.,0.));up=_unit(matrix[:,others[1]],(0.,0.,1.))
    center=np.asarray(position,dtype=float)
    hw=max(float(width),0.)*.5;hh=max(float(height),0.)*.5
    corners=np.array((center-right*hw-up*hh,center+right*hw-up*hh,
                      center+right*hw+up*hh,center-right*hw+up*hh))
    return corners,front


def anchor_hidden(corners, front, depth, margin=MARGIN, collapse=COLLAPSE):
    """Retract an anchor card into the head shell along its own normal."""
    corners=np.asarray(corners,dtype=float);front=_unit(front,(0.,0.,-1.))
    center=corners.mean(axis=0)
    back=center-front*(float(max(depth,0.))+float(max(margin,0.)))
    return back+(corners-center)*float(np.clip(collapse,0.,1.))


def hide_behind_face(points, hosts, targets, margin=.004):
    """Displacement that parks Target vertices behind the face shell.

    `hosts` are Face vertices the accessory can be occluded by; `targets` are
    the accessory vertices (brows, lashes, crease strips) that should vanish.
    Each target moves back along +Y until it clears the foremost face vertex
    near it. Nothing is deleted, so the mesh keeps its topology and UVs.
    """
    points=np.asarray(points,dtype=float)
    hosts=np.asarray(list(hosts) if not isinstance(hosts,np.ndarray) else hosts,dtype=int)
    targets=np.asarray(list(targets) if not isinstance(targets,np.ndarray) else targets,dtype=int)
    rise=np.zeros_like(points)
    if not len(hosts) or not len(targets):return rise
    cloud=points[hosts]
    scale=max(float(np.ptp(points[hosts,0])),1e-9)
    for start in range(0,len(targets),512):
        block=targets[start:start+512]
        # The face plane is X/Z; Y is depth. Using X/Y would compare heights.
        delta=cloud[None,:,[0,2]]-points[block,None,:][:,:,[0,2]]
        distance=(delta*delta).sum(axis=2)
        nearest=cloud[np.argmin(distance,axis=1)]
        # Only trusted hosts hold the accessory; a distant face point would
        # push a brow through the back of the head.
        keep=(np.min(distance,axis=1)<= (scale*.35)**2)
        shift=(nearest[:,1]+float(max(margin,0.))*scale)-points[block,1]
        rise[block,1]=np.where(keep,np.maximum(shift,0.),0.)
    return rise
