"""Shrink each eye aperture and its layers about its own centre.

A local radial falloff carries nearby Face vertices. Lashes shrink uniformly,
while the split eye layers converge behind the skin without visible triangles.
"""
import numpy as np
import json
from pathlib import Path
from functools import lru_cache

@lru_cache(maxsize=1)
def _reference_skin():
    path=Path(__file__).parent/"data/reference_recipes.json"
    return json.loads(path.read_text(encoding="utf-8")).get("socket_skin",{})


SKIN_TRANSITION=.65    # falloff width in local aperture radii
COLLAPSE=.001          # contracted aperture span, as a fraction of the rim span
FACE=0
LASH=2
EYE=(3,5,7,13)         # eyeball, iris, sclera/highlight, eye shadow
STATIC_EYE=(3,5,7)     # the writer reads these through shapes['_eyes']


def _labels(value):
    if isinstance(value,(set,frozenset)):return value
    if isinstance(value,np.ndarray):return {int(item) for item in value.reshape(-1)}
    if isinstance(value,(list,tuple)):return set(value)
    try:return set(value)
    except TypeError:return {value}


def _copy_shapes(shapes):
    result={}
    for key,value in dict(shapes or {}).items():
        result[key]=value.copy() if isinstance(value,np.ndarray) else value
    return result


def _report(method,weight,**values):
    result=dict(method=method,socket_weight=float(weight))
    result.update(values)
    return result


def _weight(value):
    try:number=float(value)
    except (TypeError,ValueError):raise ValueError('眼孔收缩权重不是有效数字')
    if not np.isfinite(number):raise ValueError('眼孔收缩权重不是有效数字')
    return float(np.clip(number,0.,1.))


def _unchanged(delta,shapes,weight,reason):
    return delta.copy(),_copy_shapes(shapes),_report('skipped',weight,reason=reason)


def _eye_sides(rig):
    rows=getattr(rig,'rows',None) or {}
    sides={int(key[1]) for key,value in rows.items()
           if isinstance(key,tuple) and len(key)==2 and str(key[0])=='EYE' and len(value)}
    if sides:return sorted(sides)
    return sorted(int(side) for side in (getattr(rig,'rings',None) or {}))


def _rim_ids(rig,side,size):
    rows=getattr(rig,'rows',None) or {}
    key=('EYE',int(side))
    if key not in rows:
        key=next((name for name in rows if isinstance(name,tuple) and len(name)==2
                  and str(name[0])=='EYE' and int(name[1])==int(side)),None)
    if key is None:return None
    ids=np.asarray(sorted({int(row[0]) for row in rows[key]}),dtype=np.int64)
    if not ids.size:return None
    if int(ids.min())<0 or int(ids.max())>=size:raise ValueError('眼缘控制点引用了不存在的顶点')
    return ids


def _controls(eye_skin,side):
    controls=getattr(eye_skin,'controls',None)
    if not isinstance(controls,dict):return None
    ids=controls.get(int(side))
    if ids is None:
        for key,value in controls.items():
            if int(key)==int(side):ids=value;break
    if ids is None:return None
    return np.asarray(sorted({int(i) for i in ids}),dtype=np.int64)


def _hidden_groups(rig):
    """Split the eye stack, eye shadow and lash/brow strips away from Face.

    The writer splits eye layer vertices shared with Face. The skin copy stays
    on the skin path, and the eye copy must receive the separate eye pose.
    """
    members=getattr(rig,'members',None) or []
    eye=[];eye_static=[];lash=[]
    for index,value in enumerate(members):
        labels=_labels(value)
        if labels.intersection(STATIC_EYE):
            eye.append(index)
            eye_static.append(index)
        elif FACE in labels:continue
        elif labels.intersection(EYE):eye.append(index)
        elif LASH in labels:lash.append(index)
    return (np.asarray(sorted(eye),dtype=np.int64),
            np.asarray(sorted(eye_static),dtype=np.int64),
            np.asarray(sorted(lash),dtype=np.int64))


def apply(rig,delta,shapes,weight=1.):
    """Blend a per-eye uniform collapse and local surrounding skin motion."""
    weight=_weight(weight)
    points=getattr(rig,'points',None)
    points=np.asarray(delta if points is None else points,dtype=np.float64)
    delta=np.asarray(delta,dtype=np.float64)
    if points.ndim!=2 or points.shape[1]!=3 or delta.shape!=points.shape:
        raise ValueError('眼孔收缩需要 N×3 的顶点坐标与位移')
    if weight<=0.:return _unchanged(delta,shapes,weight,'weight_zero')
    sides=_eye_sides(rig)
    if not sides:return _unchanged(delta,shapes,weight,'no_eye_rings')
    members=getattr(rig,'members',None) or []
    if len(members)!=len(points):raise ValueError('顶点分区数量与网格不一致')
    face_ids=np.asarray([i for i,value in enumerate(members) if FACE in _labels(value)],dtype=np.int64)
    if not face_ids.size:return _unchanged(delta,shapes,weight,'no_face_region')
    if not np.isfinite(points).all() or not np.isfinite(delta).all():raise ValueError('眼孔收缩输入含无效坐标')
    posed=points+delta
    rims={}
    for side in sides:
        ids=_rim_ids(rig,side,len(points))
        if ids is None or len(ids)<3:continue
        cloud=posed[ids][:,[0,2]]
        lower=cloud.min(axis=0);upper=cloud.max(axis=0)
        centre=np.array(((lower[0]+upper[0])*.5,float(posed[ids,1].mean()),(lower[1]+upper[1])*.5))
        rims[side]=dict(ids=ids,centre=centre,span=upper-lower)
    if not rims:return _unchanged(delta,shapes,weight,'no_eye_rings')
    # Rim target: both image axes contract to a dot at the side's own range
    # centre, depth meets the rim average. Keep the helper independent of any
    # named blink or closure rule.
    raw=np.zeros_like(posed)
    for row in rims.values():
        ids=row['ids'];centre=row['centre'];target=posed[ids].copy()
        target[:,0]=centre[0]+COLLAPSE*(target[:,0]-centre[0])
        target[:,1]=centre[1]+COLLAPSE*(target[:,1]-centre[1])
        target[:,2]=centre[2]+COLLAPSE*(target[:,2]-centre[2])
        raw[ids]=target-posed[ids]
    # A local radial scale remains monotone around each aperture. Unlike the
    # ordinary eyelid field it does not extrapolate a blink into a collapsed hole.
    smooth=np.zeros_like(posed)
    info=getattr(rig,'info',{}) or {}
    plane=float(info.get('plane',0.))
    for side,row in rims.items():
        ids=face_ids[np.where(posed[face_ids,0]>=plane,1,-1)==side]
        centre=row['centre'];radius=np.maximum(row['span']*.5,1e-9)
        # Measure distance from the actual rim, not its bounding rectangle.
        # A periodic radial contour avoids dragging the rectangle's corners.
        contour=(posed[row['ids']][:,[0,2]]-centre[[0,2]])/radius
        angles=np.arctan2(contour[:,1],contour[:,0]);order=np.argsort(angles)
        angles=angles[order];lengths=np.linalg.norm(contour[order],axis=1)
        cloud=(posed[ids][:,[0,2]]-centre[[0,2]])/radius
        theta=np.arctan2(cloud[:,1],cloud[:,0])
        boundary=np.interp(theta,np.r_[angles[-1]-2*np.pi,angles,angles[0]+2*np.pi],
                           np.r_[lengths[-1],lengths,lengths[0]])
        rho=np.linalg.norm(cloud,axis=1)/np.maximum(boundary,1e-9)
        t=np.clip((rho-1.)/SKIN_TRANSITION,0.,1.)
        # Quintic falloff has zero first/second derivatives at both ends.
        influence=1.-t*t*t*(10.-15.*t+6.*t*t)
        # Projection alone also selects the back of the head. Keep its shell
        # out of the socket deformation instead of pulling it through the face.
        depth_t=np.clip((posed[ids,1]-centre[1]-row['span'][0]*.10)/
                        max(row['span'][0]*.25,1e-9),0.,1.)
        influence*=1.-depth_t*depth_t*(3.-2.*depth_t)
        smooth[ids]=(centre-posed[ids])*((1.-COLLAPSE)*influence[:,None])
        smooth[row['ids']]=(centre-posed[row['ids']])*(1.-COLLAPSE)
    skin_method='local_radial_scale'
    reference=_reference_skin() if hasattr(rig,'ob') else {}
    if reference:
        # Transfer the authored skin field in each eye's local frame. This
        # retains its depth and limited support instead of a spherical sink.
        for side,row in rims.items():
            samples=reference.get(str(side))
            if not samples:continue
            ids=face_ids[np.where(posed[face_ids,0]>=plane,1,-1)==side]
            scale=np.array([row['span'][0],row['span'][0],row['span'][1]])
            scale=np.maximum(scale,1e-9)
            query=(points[ids]-row['centre'])/scale
            source=np.asarray(samples['points']);movement=np.asarray(samples['delta'])
            for start in range(0,len(ids),256):
                q=query[start:start+256]
                distance=np.sum((q[:,None]-source[None])**2,axis=2)
                near=np.argsort(distance,axis=1)[:,:4]
                d=np.take_along_axis(distance,near,axis=1)
                weights=1./np.maximum(d,1e-16);weights/=weights.sum(1)[:,None]
                offset=np.einsum('ij,ijk->ik',weights,movement[near])*scale
                # Unrepresented distant geometry must not inherit eye motion.
                offset[d[:,0]>.25**2]=0.
                smooth[ids[start:start+256]]=offset
        skin_method='reference_eye_local_skin_field'

    eye_ids,eye_static,eye_ids_lash=_hidden_groups(rig)
    hidden=np.zeros_like(posed)
    hidden_all=np.asarray(sorted(set(eye_ids.tolist())|set(eye_ids_lash.tolist())),dtype=np.int64)
    for side,row in rims.items():
        ids=hidden_all[np.where(posed[hidden_all,0]>=plane,1,-1)==side]
        # Lashes and shadow shrink without twist or tip fitting.
        hidden[ids]=(row['centre']-posed[ids])*(1.-COLLAPSE)
        # At full weight even the small residual aperture must not show a
        # white pixel. Collapse every eye triangle to one point behind its rim.
        eye_side=eye_static[np.where(posed[eye_static,0]>=plane,1,-1)==side]
        retreat=row['span'][0]*.10
        hidden[ids,1]+=retreat
        eye_target=row['centre']+np.array([0.,retreat,0.])
        hidden[eye_side]=eye_target-posed[eye_side]
    result=delta+weight*smooth
    if eye_ids_lash.size:result[eye_ids_lash]+=weight*hidden[eye_ids_lash]
    original=getattr(rig,'original_points',None)
    original=points if original is None else np.asarray(original,dtype=np.float64)
    if original.shape!=points.shape:raise ValueError('原始网格尺寸与当前网格不一致')
    static_delta=eye_ids[np.isin(eye_ids,eye_static)]
    remaining=eye_ids[np.isin(eye_ids,eye_static,invert=True)]
    if static_delta.size:
        old=shapes.get('_eyes') if isinstance(shapes,dict) else None
        if old is None:old=np.zeros_like(points)
        else:
            old=np.asarray(old,dtype=np.float64)
            if old.shape!=points.shape:raise ValueError('眼部形态键与网格尺寸不一致')
        base=original[static_delta]+old[static_delta]
        target=posed[static_delta]+hidden[static_delta]
        updated=old.copy()
        updated[static_delta]=old[static_delta]+weight*(target-base)
        shapes=_copy_shapes(shapes)
        shapes['_eyes']=updated
    else:shapes=_copy_shapes(shapes)
    if remaining.size:result[remaining]+=weight*hidden[remaining]
    # All Face layers already received the same spatial scale above. Reapplying
    # a displacement-only follower here preserves the old layer offsets and
    # reopens detached eyelid collars after their host aperture has collapsed.
    follower_count=0
    if not np.isfinite(result).all():raise ValueError('眼孔收缩产生无效坐标')
    if '_eyes' in shapes and not np.isfinite(np.asarray(shapes['_eyes'],dtype=np.float64)).all():
        raise ValueError('眼孔收缩产生无效形态键')
    rim_vertices=len(set().union(*(set(row['ids'].tolist()) for row in rims.values())))
    quality=_report('per_eye_uniform_scale_with_local_falloff',weight,
        socket_rim_sides=[int(side) for side in sorted(rims)],
        socket_rim_vertices=int(rim_vertices),
        socket_contracted_vertices=int(np.count_nonzero(np.any(raw!=0.,axis=1))),
        socket_skin_vertices=int(np.count_nonzero(np.any(smooth!=0.,axis=1))),
        socket_hidden_vertices=int(hidden_all.size),
        socket_hidden_moved_vertices=int(np.count_nonzero(np.any(hidden!=0.,axis=1))),
        socket_hidden_eye_vertices=int(eye_ids.size),
        socket_hidden_eye_static_vertices=int(static_delta.size),
        socket_hidden_eye_delta_vertices=int(remaining.size),
        socket_hidden_lash_vertices=int(eye_ids_lash.size),
        socket_face_vertices=int(face_ids.size),
        socket_skin_method=skin_method,
        socket_follower_vertices=follower_count)
    return result,shapes,quality
