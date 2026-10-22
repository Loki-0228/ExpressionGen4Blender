"""Copy solved positive-side positions to paired negative-side vertices."""
from collections import defaultdict
import copy
import numpy as np
from mathutils import Vector
from mathutils.kdtree import KDTree
from mathutils.bvhtree import BVHTree
from .expression_rules import has_channels


class SymmetryError(ValueError):
    pass


def reflection(points,plane):
    result=np.asarray(points).copy();result[...,0]=2*plane-result[...,0];return result


def pairing(rig):
    if hasattr(rig,'_symmetry_pairing'):return rig._symmetry_pairing
    points=rig.original_points;plane=rig.info['plane'];tol=max(rig.info['width']*1e-5,1e-9)
    # An unmapped neighboring face is not a different anatomical part.
    labels=[tuple(sorted(v-{-1,-2})) for v in rig.members]
    membership=[(labels[i],i in rig.brows,i in rig.creases,i in rig.strands,rig.lash_upper.get(i)) for i in range(len(points))]
    degrees=[[] for _ in points]
    for f,label in zip(rig.info['faces'],rig.info['labels']):
        for i in f:degrees[i].append((label,len(f)))
    groups=defaultdict(list)
    for i,p in enumerate(points):groups[(membership[i],tuple(sorted(degrees[i])))].append(i)
    mapping=np.full(len(points),-1,dtype=np.int32)
    for ids in groups.values():
        right=[i for i in ids if points[i,0]>plane+tol];left=[i for i in ids if points[i,0]<plane-tol]
        center=[i for i in ids if abs(points[i,0]-plane)<=tol];mapping[center]=center
        if not left:continue
        tree=KDTree(len(left))
        for i in left:tree.insert(Vector(points[i]),i)
        tree.balance();pairs=[]
        for i in right:
            if not left:break
            for _,j,distance in tree.find_range(Vector(reflection(points[i],plane)),tol):pairs.append((distance,i,j))
        for distance,i,j in sorted(pairs):
            if mapping[i]<0 and mapping[j]<0:mapping[i]=j;mapping[j]=i
    # Different triangulations may still share mirrored vertices. They can
    # use full solving followed by symmetry, but cannot reuse one-side checks.
    if np.any(mapping<0):
        loose=defaultdict(list)
        for i in np.flatnonzero(mapping<0):loose[membership[i]].append(int(i))
        for ids in loose.values():
            left=[i for i in ids if points[i,0]<plane-tol]
            if not left:continue
            tree=KDTree(len(left))
            for i in left:tree.insert(Vector(points[i]),i)
            tree.balance();pairs=[]
            for i in ids:
                if points[i,0]<=plane+tol or not left:continue
                # Pair small authored asymmetries without requiring the
                # neutral mouth/curves themselves to have stayed symmetric.
                for _,j,d in tree.find_range(Vector(reflection(points[i],plane)),max(tol,rig.info['width']*.015)):pairs.append((d,i,j))
            for d,i,j in sorted(pairs):
                if mapping[i]<0 and mapping[j]<0:mapping[i]=j;mapping[j]=i
    # Curve-based upper/lower or strand classification can differ at one
    # canthus. At coincident mirrored coordinates, use the actual region.
    loose=defaultdict(list)
    for i in np.flatnonzero(mapping<0):loose[labels[i]].append(int(i))
    for ids in loose.values():
        left=[i for i in ids if points[i,0]<plane-tol]
        if not left:continue
        tree=KDTree(len(left))
        for i in left:tree.insert(Vector(points[i]),i)
        tree.balance();pairs=[]
        for i in ids:
            if points[i,0]>plane+tol:
                for _,j,d in tree.find_range(Vector(reflection(points[i],plane)),tol):pairs.append((d,i,j))
        for d,i,j in sorted(pairs):
            if mapping[i]<0 and mapping[j]<0:mapping[i]=j;mapping[j]=i
    rig._symmetry_pairing=(mapping,'')
    return rig._symmetry_pairing


def surface_bindings(rig,kind=None):
    """Use the mirrored surface when opposite tessellations have extra vertices."""
    cache=getattr(rig,'_symmetry_surface_bindings',{})
    if kind in cache:return cache[kind]
    mapping,_=pairing(rig);points=rig.original_points;plane=rig.info['plane']
    tolerance=max(rig.info['width']*1e-5,1e-9);limit=rig.info['width']*.02
    allowed=({f for f,label in enumerate(rig.info['labels']) if label in (3,5,7)} if kind=='_eyes'
             else set(rig.oral_parts[kind]) if kind is not None else None)
    faces=defaultdict(list)
    for tri,f in rig.mesh_triangles:
        if allowed is not None and f not in allowed:continue
        label=rig.info['labels'][f]
        if label<0:continue
        side=1 if points[list(tri),0].mean()>=plane else -1
        faces[label,side].append(list(tri))
    trees={key:BVHTree.FromPolygons([Vector(p) for p in points],value) for key,value in faces.items()}
    bindings={}
    part_ids={i for f in allowed for i in rig.info['faces'][f]} if allowed is not None else set(range(len(points)))
    for i in np.flatnonzero(mapping<0):
        if i not in part_ids:continue
        side=1 if points[i,0]>plane else -1;target=reflection(points[i],plane);candidates=[]
        labels=rig.members[i]-{-1,-2}
        if kind is None and 0 in labels:labels={0}
        for label in labels:
            key=(label,-side);tree=trees.get(key)
            if tree is None:continue
            hit,normal,index,distance=tree.find_nearest(Vector(target))
            if hit is None or distance>limit:continue
            tri=np.asarray(faces[key][index]);cloud=points[tri]
            uv=np.linalg.lstsq(np.column_stack((cloud[1]-cloud[0],cloud[2]-cloud[0])),np.asarray(hit)-cloud[0],rcond=None)[0]
            weights=np.clip(np.r_[1-uv.sum(),uv],0.,1.);weights/=max(float(weights.sum()),1e-12)
            candidates.append((distance,tri,weights))
        if candidates:
            distance,tri,weights=min(candidates,key=lambda item:item[0])
            bindings[int(i)]=(tri,weights,float(distance))
    cache[kind]=bindings;rig._symmetry_surface_bindings=cache
    return bindings


def mirror(rig,delta,shapes,average=False):
    mapping,reason=pairing(rig)
    tolerance=max(rig.info['width']*1e-8,1e-12)
    moving=np.linalg.norm(delta,axis=1)>tolerance
    for shape in shapes.values():moving|=np.linalg.norm(shape,axis=1)>tolerance
    main=surface_bindings(rig);missing=[];surface_used=set()
    def check(values,bindings):
        for i in np.flatnonzero((np.linalg.norm(values,axis=1)>tolerance)&(mapping<0)):
            if i not in bindings:missing.append(int(i))
            else:surface_used.add(int(i))
    check(delta,main)
    shape_bindings={kind:surface_bindings(rig,kind) for kind in shapes}
    for kind,shape in shapes.items():check(shape,shape_bindings[kind])
    if missing:
        missing=sorted(set(missing))
        raise SymmetryError('强制对称无法对应 %d 个活动顶点，且附近没有同分区镜像表面（顶点 %s）；请检查分区与拓扑'%(len(missing),','.join(map(str,missing[:8]))))
    positive=np.flatnonzero((rig.original_points[:,0]>rig.info['plane']+rig.info['width']*1e-5)&(mapping>=0))
    negative=mapping[positive];center=np.flatnonzero(mapping==np.arange(len(mapping)))
    selected=moving[positive]|moving[negative];positive=positive[selected];negative=negative[selected]
    center=center[moving[center]]
    def project(base,values,bindings):
        posed=base+values;source=posed[positive].copy()
        if average:source=(source+reflection(posed[negative],rig.info['plane']))*.5
        result=values.copy();result[positive]=source-base[positive]
        result[negative]=reflection(source,rig.info['plane'])-base[negative]
        result[center,0]=rig.info['plane']-base[center,0]
        for i,(tri,weights,distance) in bindings.items():
            if rig.original_points[i,0]>=rig.info['plane']:continue
            if not moving[i] and not np.any(moving[tri]):continue
            result[i]=reflection(weights@posed[tri],rig.info['plane'])-base[i]
        return result
    result=project(rig.points,delta,main)
    output={}
    for kind,shape in shapes.items():
        base=rig.cavity_points if kind.startswith('mouth_') else rig.original_points
        output[kind]=project(base,shape,shape_bindings[kind])
    from . import procedural_cavity as Cavity
    output=Cavity.reattach(rig,result,output)
    rig.last_symmetry_surface_vertices=len(surface_used)
    note='同分区镜像表面插值补齐 %d 个非一一对应顶点'%len(surface_used) if surface_used else ''
    return result,output,True,note


def eligible(recipe):
    return bool(recipe.get('can_symmetrize',False) and not recipe.get('special') and not recipe.get('relation'))


def half_recipe(rig,recipe):
    # Mouth, jaw and custom fields cross the midline; reuse only independent
    # eye/brow passes. The remaining global constraints still run normally.
    if has_channels(recipe,'mouth','mouth_targets','tongue','jaw','oral','custom_rules'):return None
    if not recipe.get('eyes') and not recipe.get('brows'):return None
    mapping,_=pairing(rig)
    # Vertex correspondence is sufficient: opposite triangulation diagonals
    # must not force a second eye solve. Mouth/custom fields still cross the
    # midline and keep their global solve before final position mirroring.
    relevant=set()
    for side in (-1,1):
        if str(side) in recipe.get('eyes',{}):
            relevant.update(rig.eye_skin.regions.get(side,()))
            relevant.update(i for i,labels in enumerate(rig.members) if 2 in labels
                            and (1 if rig.original_points[i,0]>=rig.info['plane'] else -1)==side)
        if str(side) in recipe.get('brows',{}):
            relevant.update(i for s,kind,ids,entry in rig.accessories if s==side and kind=='BROW' for i in ids)
    if any(mapping[i]<0 for i in relevant):return None
    if any(set(recipe.get(k,{}))!={'1','-1'} for k in ('eyes','brows') if recipe.get(k)):return None
    result=copy.deepcopy(recipe)
    for key in ('eyes','brows'):result[key]={k:v for k,v in result.get(key,{}).items() if k=='1'}
    return result
