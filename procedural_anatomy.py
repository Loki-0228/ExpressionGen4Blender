"""Recognize volumetric eye geometry and wrap lids around a fixed globe."""
import numpy as np
from . import region_core as C


def sphere(points):
    """Accept a sampled globe/hemisphere, never a nearly planar iris card."""
    p=np.unique(np.asarray(points,dtype=float),axis=0)
    if len(p)<24:return None
    origin=p.mean(0);scale=float(np.ptp(p,axis=0).max())
    if scale<=1e-12:return None
    q=(p-origin)/scale
    design=np.column_stack((2*q,np.ones(len(q))))
    if np.linalg.matrix_rank(design)<4:return None
    fit=np.linalg.lstsq(design,np.sum(q*q,axis=1),rcond=None)[0]
    r2=float(fit[3]+fit[:3]@fit[:3])
    if r2<=0:return None
    center=origin+fit[:3]*scale;radius=np.sqrt(r2)*scale
    residual=np.abs(np.linalg.norm(p-center,axis=1)/radius-1)
    span=np.ptp(p,axis=0)/radius
    if np.quantile(residual,.95)>.06 or min(span[[0,2]])<1.35 or span[1]<.85:return None
    if max(span)>2.3 or p[:,1].max()<center[1]-radius*.35:return None
    return dict(type='convex_globe',center=center.tolist(),radius=float(radius),
                radial_error_95=float(np.quantile(residual,.95)),diameter_coverage=(span/2).tolist())


def detect(points,polygons,labels,plane):
    p=np.asarray(points,dtype=float);result={}
    eye_faces=[i for i,label in enumerate(labels) if label in (3,5,7)]
    faces=[polygons[i] for i in eye_faces]
    for island in C.topology(faces)[1]:
        indices=[eye_faces[i] for i in island['faces']];ids=sorted({i for f in indices for i in polygons[f]})
        fit=sphere(p[ids])
        if fit is None:continue
        side=1 if fit['center'][0]>=plane else -1
        # A single mesh spanning both eyes is not one globe.
        if np.min((p[ids,0]-plane)*side)<=0:continue
        if side not in result or fit['radius']>result[side]['radius']:
            result[side]=dict(fit,vertices=ids,faces=indices)
    return result


def opening(holes,globe,face_width):
    """The visible aperture can be much narrower than the whole eyeball."""
    center=np.asarray(globe['center']);r=globe['radius'];choices=[]
    for row in holes:
        p=np.asarray(row['points']);mid=(p.min(0)+p.max(0))*.5
        if not r*.5<row['width']<min(r*2.5,face_width*.48):continue
        if not .10<row['height']/row['width']<1.5:continue
        distance=float(np.linalg.norm((mid-center)[[0,2]]))/r
        if distance>.6 or abs(mid[1]-center[1])>r*1.5:continue
        choices.append((distance,row))
    return min(choices,key=lambda row:row[0])[1]['points'] if choices else None


def summary(globes):
    return {str(side):{k:v for k,v in globe.items() if k not in ('vertices','faces')}
            for side,globe in globes.items()}


def rotation(a,b):
    """Shortest rotation between radial directions; no transverse scaling."""
    a=a/max(np.linalg.norm(a),1e-12);b=b/max(np.linalg.norm(b),1e-12)
    v=np.cross(a,b);c=float(np.clip(a@b,-1,1))
    if c<-1+1e-8:
        axis=np.cross(a,np.eye(3)[np.argmin(abs(a))]);axis/=np.linalg.norm(axis)
        return 2*np.outer(axis,axis)-np.eye(3)
    k=np.array(((0.,-v[2],v[1]),(v[2],0.,-v[0]),(-v[1],v[0],0.)))
    return np.eye(3)+k+k@k/max(1+c,1e-12)


def skin_motion(rig,raw,delta,recipe):
    """Interpolate eyelid rotation around the globe before enforcing contact."""
    if not set(map(int,recipe.get('eyes',{})))&set(getattr(rig,'eye_anatomy',{})):return delta
    result=delta.copy();total=np.zeros_like(delta);weights=np.zeros(len(delta))
    for text,eye in recipe.get('eyes',{}).items():
        side=int(text);globe=getattr(rig,'eye_anatomy',{}).get(side)
        if not globe or side not in rig.eye_skin.regions:continue
        center=np.asarray(globe['center']);r=globe['radius'];rest=rig.points
        controls=sorted(rig.eye_skin.controls[side]);target=rest[controls]+raw[controls]
        closure=float(np.clip(eye.get('closure',0),0,1))
        radial=np.sum((target[:,[0,2]]-center[[0,2]])**2,axis=1)
        front=center[1]-np.sqrt(np.maximum(r*r-radial,0))
        use=radial<r*r
        target[use,1]=np.minimum(target[use,1],target[use,1]*(1-closure)+(front[use]-r*.012)*closure)
        def coordinates(points):
            q=points-center;length=np.linalg.norm(q,axis=1)
            return np.column_stack((np.arcsin(np.clip(q[:,0]/np.maximum(length,1e-12),-1,1)),
                np.arctan2(q[:,2],-q[:,1]),length))
        base=coordinates(rest);seed=np.zeros_like(delta)
        seed[controls]=coordinates(target)-base[controls]
        field=rig.eye_skin.fields[side];motion=field.smooth_displacement(seed)
        ids=np.asarray(sorted(rig.eye_skin.regions[side]),dtype=int)
        q=base[ids]+motion[ids];theta,phi,length=q.T
        posed=center+np.column_stack((length*np.sin(theta),-length*np.cos(theta)*np.cos(phi),length*np.cos(theta)*np.sin(phi)))
        weight=rig.eye_skin.falloff[side][ids]
        total[ids]+=(posed-rest[ids])*weight[:,None];weights[ids]+=weight
    ids=np.flatnonzero(weights>0)
    result[ids]=total[ids]/weights[ids,None]
    return result


def follow_attachments(rig,delta,recipe):
    """Transport lash cards and detached orbital overlays with the true rim.

    The globe radius defines rotation, while the final skin rim supplies the
    anchor. Cards retain their cross section instead of being flattened into
    the closure seam. Face components attached to the main head stay in the
    skin solver; only small disconnected patches around the orbit follow.
    """
    active=set(map(int,recipe.get('eyes',{})))&set(getattr(rig,'eye_anatomy',{}))
    if not active:return delta,dict(globe_attachment_vertices=0,globe_attachment_mode=None)
    from . import procedural_binding as B
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    from mathutils.geometry import barycentric_transform
    result=delta.copy();count=0;overlay_count=0
    face_polys=[f for f,label in zip(rig.info['faces'],rig.info['labels']) if label==0]
    patches=[sorted({i for j in island['faces'] for i in face_polys[j]}) for island in C.topology(face_polys)[1]]
    lash_polys=[f for f,label in zip(rig.info['faces'],rig.info['labels']) if label==2]
    lash_patches=[sorted({i for j in island['faces'] for i in lash_polys[j]}) for island in C.topology(lash_polys)[1]]
    for text in recipe.get('eyes',{}):
        side=int(text);globe=getattr(rig,'eye_anatomy',{}).get(side)
        if not globe or side not in rig.rings:continue
        center=np.asarray(globe['center']);radius=globe['radius'];rows=rig.rows['EYE',side]
        chains={up:[i for u,i in sorted({(u,i) for i,u,upper in rows if upper==up or u<1e-7 or u>1-1e-7})] for up in (False,True)}
        lines={up:B.Line(rig.points[ids]) for up,ids in chains.items()}
        ids={i for i,labels in enumerate(rig.members) if 2 in labels and i not in rig.brows and
             (rig.points[i,0]-rig.info['plane'])*side>0}
        rim={i for i,u,up in rows};overlays=set();aperture_overlays=set()
        mid=(rig.points[sorted(rim)].min(0)+rig.points[sorted(rim)].max(0))*.5
        for patch in patches+lash_patches:
            cloud=rig.points[patch]
            if set(patch)&rim or np.ptp(cloud,axis=0).max()>radius*2.8:continue
            if np.linalg.norm(cloud.mean(0)-center)>radius*1.6:continue
            if np.min((cloud[:,0]-rig.info['plane'])*side)<=0:continue
            covers_aperture=(np.ptp(cloud[:,0])<radius*2.05 and cloud[:,2].min()<mid[2]<cloud[:,2].max()
                             and cloud[:,0].min()<mid[0]<cloud[:,0].max() and np.ptp(cloud[:,1])<radius*.8)
            if covers_aperture:aperture_overlays.update(patch)
            elif patch in patches:overlays.update(patch)
        ids-=aperture_overlays
        ids-=overlays
        for i in sorted(aperture_overlays):
            point=rig.points[i];old=[];movement=[]
            for up in (False,True):
                chain=chains[up];order=np.argsort(rig.points[chain,0]);chain=np.asarray(chain)[order]
                x=rig.points[chain,0]
                old.append(float(np.interp(point[0],x,rig.points[chain,2])))
                movement.append(np.array([np.interp(point[0],x,delta[chain,axis]) for axis in range(3)]))
            weight=float(np.clip((point[2]-old[0])/max(old[1]-old[0],radius*.02),0,1))
            result[i]=movement[0]*(1-weight)+movement[1]*weight;count+=1;overlay_count+=1
        skin_ids=set().union(*(set(patch) for patch in patches if set(patch)&rim))
        triangles=[list(t) for t,f in rig.mesh_triangles if rig.info['labels'][f]==0 and set(t)<=skin_ids]
        if overlays and triangles:
            tree=BVHTree.FromPolygons([Vector(p) for p in rig.points],triangles,all_triangles=True)
            for i in sorted(overlays):
                hit,normal,index,distance=tree.find_nearest(Vector(rig.points[i]))
                if index is None:continue
                tri=triangles[index];old=rig.points[tri];new=old+delta[tri]
                anchor=np.array(barycentric_transform(hit,*map(Vector,old),*map(Vector,new)))
                result[i]=anchor-np.array(hit);count+=1;overlay_count+=1
        for i in sorted(ids):
            point=rig.points[i]
            options=[(up,*line.project(point)) for up,line in lines.items()]
            owned=rig.lash_upper.get(i) if 2 in rig.members[i] else None
            if owned is not None:options=[row for row in options if row[0]==owned]
            up,u,distance=min(options,key=lambda row:row[2]);line=lines[up]
            anchor=line.sample(u);posed=rig.points[chains[up]]+result[chains[up]]
            target=np.array([np.interp(u,line.parameters,posed[:,axis]) for axis in range(3)])
            frame=rotation(anchor-center,target-center)
            offset=point-anchor
            if owned and side in rig.lash_lines:
                base,current=rig.lash_lines[side];v=base.project(point)[0]
                offset=offset+current.sample(v)-base.sample(v)
            # Keep edits to existing lash/crease curves effective.
            for s,kind,vertices,entry in rig.accessories:
                if s==side and i in vertices:offset=offset+B.edit_offset(entry,point)
            for unit in rig.lashes:
                if unit['side']!=side or i not in unit['vertices'] or i in unit.get('band_vertices',[]):continue
                root,tip=np.asarray(unit['base']);edited=np.asarray(unit['points'])
                axis=tip-root;t=float(np.clip((point-root)@axis/max(axis@axis,1e-12),0,1))
                offset+=(edited[0]-root)*(1-t)+(edited[-1]-tip)*t
            result[i]=target+frame@offset-point;count+=1
    return result,dict(globe_attachment_vertices=count,globe_overlay_vertices=overlay_count,globe_attachment_mode='radial_rim_transport')


def wrap(rig,delta,recipe):
    """Keep the moving lid in front of its fixed globe, preserving rest skin.

    A linear shape key follows a chord, not a spherical arc. Bound depth at
    intermediate weights too. Existing buried rim allowance fades to zero as
    the lid closes, so a rear aperture edge cannot leave the globe exposed.
    """
    result=delta.copy();count=0;maximum=0.
    for text,eye in recipe.get('eyes',{}).items():
        side=int(text);globe=getattr(rig,'eye_anatomy',{}).get(side)
        if not globe or side not in rig.eye_skin.regions:continue
        center=np.asarray(globe['center']);radius=globe['radius']
        ids=np.array(sorted(rig.eye_skin.regions[side]-rig.creases),dtype=int)
        if not len(ids):continue
        rest=rig.points[ids];motion=result[ids]
        moved=np.linalg.norm(motion,axis=1)>radius*1e-8
        if not np.any(moved):continue
        def front(p):
            radial=np.sum((p[:,[0,2]]-center[[0,2]])**2,axis=1)
            return center[1]-np.sqrt(np.maximum(radius**2-radial,0)),radial<radius**2
        old,inside=front(rest)
        allowance=np.maximum(rest[:,1]-old,0.)
        closure=float(np.clip(eye.get('closure',0),0,1))
        goal=motion[:,1].copy()
        for t in np.linspace(1/32,1,32):
            posed=rest+motion*t;surface,within=front(posed)
            # Small shell margin only grows with actual motion, never at Basis.
            bound=(surface+allowance*(1-t*closure)-rest[:,1])/t-radius*.012
            use=within&moved
            goal[use]=np.minimum(goal[use],bound[use])
        correction=np.zeros_like(delta);correction[ids,1]=goal-motion[:,1]
        # A coarse eyelid triangle can cut the globe even when its vertices
        # clear it. Sample the material face too, with the same rest allowance.
        region=set(ids.tolist())
        triangles=np.array([tri for tri in rig.field.triangles if set(tri)<=region],dtype=int).reshape((-1,3))
        if len(triangles):
            branches={up:rig.points[sorted({i for i,u,upper in rig.rows['EYE',side] if upper==up or u<1e-7 or u>1-1e-7})] for up in (False,True)}
            branches={up:line[np.argsort(line[:,0])] for up,line in branches.items()}
            bary=np.array(((.5,.5,0),(.5,0,.5),(0,.5,.5),(1/3,1/3,1/3)))
            old=np.einsum('bj,tjk->tbk',bary,rig.points[triangles]).reshape((-1,3))
            change=np.einsum('bj,tjk->tbk',bary,(result+correction)[triangles]).reshape((-1,3))
            old_front,_=front(old);allow=np.maximum(old[:,1]-old_front,0.)
            required=np.zeros(len(old))
            for t in (.25,.5,.75,1.):
                posed=old+change*t;surface,within=front(posed)
                lower=np.interp(posed[:,0],branches[False][:,0],branches[False][:,2])
                upper=np.interp(posed[:,0],branches[True][:,0],branches[True][:,2])
                within&=(posed[:,2]>=lower)&(posed[:,2]<=upper)&(np.linalg.norm(change,axis=1)>radius*1e-8)
                bound=(surface+allow*(1-t*closure)-posed[:,1])/t-radius*.006
                required[within]=np.minimum(required[within],bound[within])
            required=required.reshape((-1,len(bary))).min(1)
            extra=np.zeros(len(delta))
            np.minimum.at(extra,triangles.ravel(),np.repeat(required,3))
            correction[:,1]+=extra
        goal=motion[:,1]+correction[ids,1]
        contacts=set(ids[goal<motion[:,1]-radius*1e-8].tolist())
        if contacts:
            correction=rig.eye_skin.depth_correction(correction,contacts,[side])
            result+=correction;count+=len(contacts);maximum=max(maximum,float(np.max(abs(correction[:,1]))))
    return result,dict(globe_lid_vertices=count,globe_lid_depth_correction=maximum)
