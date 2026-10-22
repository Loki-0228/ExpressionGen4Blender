"""Attach the cavity to the lip ring and spread opening over its topology."""
from collections import Counter,defaultdict
import numpy as np
from mathutils import Matrix,Euler,Vector
from mathutils.geometry import tessellate_polygon
from .region_contours import lip_weights,LipRing
from .region_deformation import SkinDisplacementField
from .procedural_oral import bone_kind
from . import procedural_binding as Binding,procedural_surfaces as Surfaces
from .generation_progress import notify


def part_pose(rig,recipe,kind):
    ids=sorted({i for f in rig.oral_parts[kind] for i in rig.info['faces'][f]})
    owner=bone_kind(kind,rig.oral_parts)
    pivot_ids=sorted({i for f in rig.oral_parts[owner] for i in rig.info['faces'][f]})
    center=rig.original_points[pivot_ids].mean(0)
    pose=recipe.get('oral',{}).get(owner,{})
    rotation=np.asarray(pose.get('rotation',np.eye(3)))
    translation=np.asarray(pose.get('translation',np.zeros(3)))*rig.widths['LIP',0]
    return ids,center,rotation,translation


def rotation_at(rotation,t):
    euler=np.asarray(Matrix(rotation).to_euler('XYZ'))
    return np.asarray(Euler(tuple(euler*t),'XYZ').to_matrix())


def tooth_triangles(rig,recipe,t=1.):
    """Evaluate each group's own copy, including originally shared vertices."""
    clouds=[]
    for kind,faces in rig.oral_parts.items():
        if not kind.startswith('teeth_'):continue
        ids,center,rotation,translation=part_pose(rig,recipe,kind)
        cloud=rig.original_points[ids].copy()
        if kind in rig.last_teeth_deformation:cloud+=rig.last_teeth_deformation[kind][ids]*t
        moved=rig.original_points.copy()
        moved[ids]=(cloud-center)@rotation_at(rotation,t).T+center+translation*t
        face_set=set(faces)
        triangles=np.asarray([tri for tri,f in rig.mesh_triangles if f in face_set],dtype=np.int32).reshape((-1,3))
        clouds.append(moved[triangles])
    return np.concatenate(clouds) if clouds else np.empty((0,3,3))


def boundary_loops(neighbors):
    """Separate simple cycles even when two boundary loops touch at a corner."""
    visited=set();loops=[]
    for root in sorted(neighbors):
        if root in visited:continue
        path=[root];active={root:0};visited.add(root)
        stack=[(root,None,iter(sorted(neighbors[root])))]
        while stack:
            vertex,parent,adjacent=stack[-1]
            other=next(adjacent,None)
            if other is None:
                stack.pop();active.pop(vertex);path.pop();continue
            if other==parent:continue
            if other in active:
                cycle=path[active[other]:]
                if len(cycle)>=3:loops.append(cycle.copy())
            elif other not in visited:
                visited.add(other);active[other]=len(path);path.append(other)
                stack.append((other,vertex,iter(sorted(neighbors[other]))))
    return loops


def rim_binding(original,faces,rows,width):
    """Store fixed barycentric links to actual lip edges, independent of pose."""
    edges=Counter(tuple(sorted((a,b))) for f in faces for a,b in zip(f,f[1:]+f[:1]))
    neighbors=defaultdict(set);connected=defaultdict(set)
    for (a,b),count in edges.items():
        connected[a].add(b);connected[b].add(a)
        if count==1:neighbors[a].add(b);neighbors[b].add(a)
    components={}
    for root in sorted(connected):
        if root in components:continue
        components[root]=root;queue=[root]
        while queue:
            for i in connected[queue.pop()]:
                if i not in components:components[i]=root;queue.append(i)
    targets={};ambiguous=0
    vectors=[Vector(point) for point in original]
    chains={upper:[i for u,i in sorted({(u,i) for i,u,up in rows if bool(up)==upper or u<1e-7 or u>1-1e-7})]
            for upper in (False,True)}
    lines={upper:Binding.Line(original[chain]) for upper,chain in chains.items()}
    corners=[original[chains[True][end]] for end in (0,-1)]
    lip_owners={i:bool(upper) for i,u,upper in rows if 1e-7<u<1-1e-7}
    lip=np.concatenate([line.points for line in lines.values()]);candidates={}
    for loop in boundary_loops(neighbors):
        cloud=original[loop]
        if np.ptp(cloud[:,0])<width*.35:continue
        distance=np.linalg.norm(cloud[:,None]-lip[None],axis=-1).min(1)
        # Select the nearest front rim of each connected cavity. A deep but
        # detached entrance is still an entrance; do not reject it solely for
        # exceeding a fixed 10% lip-distance threshold or bind its rear hole.
        score=float(np.mean(distance));component=components[loop[0]]
        if component not in candidates or score<candidates[component][0]:
            candidates[component]=(score,loop)
    for score,loop in candidates.values():
        cloud=original[loop]
        left=int(np.argmin(np.linalg.norm(cloud-corners[0],axis=1)))
        loop=loop[left:]+loop[:left]
        right=int(np.argmin(np.linalg.norm(original[loop]-corners[1],axis=1)))
        if right==0:continue
        paths=[loop[:right+1],[loop[0]]+list(reversed(loop[right:]))]
        # Keep known Face ownership across a shared rim. Detached lining uses
        # its connected upper/lower wall, then the checked rest curves. Raw
        # average Z swaps overlapping lips and depends on vertex density.
        votes=[sum(1 if lip_owners[i] else -1 for i in path[1:-1] if i in lip_owners) for path in paths]
        upper_path=None
        if votes[0]!=votes[1]:upper_path=0 if votes[0]>votes[1] else 1
        if upper_path is None:
            index={v:i for i,v in enumerate(loop)};ring_chains=tuple([index[v] for v in path] for path in paths)
            ring=LipRing([vectors[i] for i in loop],branches=ring_chains)
            sides=ring.surface_sides(ring_chains,(vectors,faces,[0]*len(faces)))
            if sides is not None and min(sides)<-.15 and max(sides)>.15:
                upper_path=int(np.argmax(sides))
        if upper_path is None:
            errors={}
            for number,path in enumerate(paths):
                length=np.linalg.norm(np.diff(original[path],axis=0),axis=1)
                weights=np.r_[length,0.]+np.r_[0.,length]
                for upper,line in lines.items():
                    parameters=Binding.ordered_parameters(original[path],line)
                    error=np.sum((original[path]-np.array([line.sample(u) for u in parameters]))**2,axis=1)
                    errors[number,upper]=float(np.sum(weights*error)/max(float(weights.sum()),1e-20))
            direct=errors[0,True]+errors[1,False];reverse=errors[0,False]+errors[1,True]
            if abs(direct-reverse)>width*width*1e-8:upper_path=0 if direct<reverse else 1
        if upper_path is None:
            ambiguous+=1;continue
        for number,path in enumerate(paths):
            upper=number==upper_path;line=lines[upper];chain=chains[upper]
            parameters=Binding.ordered_parameters(original[path],line)
            for i,u in zip(path,parameters):
                edge=min(max(int(np.searchsorted(line.parameters,u,side='right'))-1,0),len(chain)-2)
                t=float(np.clip((u-line.parameters[edge])/max(line.parameters[edge+1]-line.parameters[edge],1e-12),0,1))
                targets.setdefault(i,[]).append(((chain[edge],1-t),(chain[edge+1],t)))
    result={}
    for i,links in targets.items():
        weights=defaultdict(float)
        for link in links:
            for vertex,weight in link:weights[vertex]+=weight/len(links)
        result[i]=list(weights.items())
    return result,ambiguous


def prepare(rig):
    """Fit only the cavity to the neutral lips, then reuse the same links."""
    rig.cavity_points=rig.original_points.copy();rig.cavity_links={};rig.cavity_ambiguous=0
    kinds=[kind for kind in rig.oral_parts if kind.startswith('mouth_')]
    if not kinds or ('LIP',0) not in rig.rows:return
    original=rig.original_points;width=rig.widths['LIP',0]
    faces=[rig.info['faces'][f] for kind in kinds for f in rig.oral_parts[kind]]
    ids=sorted({i for f in faces for i in f})
    links,rig.cavity_ambiguous=rim_binding(original,faces,rig.rows['LIP',0],width)
    # A welded Face/Mouth seam must stay welded geometrically, including the
    # skin's inner return strip. Never pull that strip toward an external rim.
    links.update({i:[(i,1.)] for i in ids if 0 in rig.members[i]})
    rig.cavity_links=links
    lip_ids=[i for i,u,upper in rig.rows['LIP',0]]
    front=float(np.median(original[lip_ids,1]));back=max(float(original[ids,1].max()),front+width*.02)
    rear={i for i in ids if original[i,1]>=front+.95*(back-front)}-set(links)
    rig.cavity_field=SkinDisplacementField(original,faces,[0]*len(faces),ids,set(links)|rear,fidelity=.025)
    raw=np.zeros_like(original)
    for i,weights in links.items():raw[i]=sum((rig.points[j]*w for j,w in weights),np.zeros(3))-original[i]
    rig.cavity_points+=rig.cavity_field.solve(raw)


def reattach(rig,delta,shapes):
    """Keep independently mirrored surface bindings welded to final Face."""
    if not getattr(rig,'cavity_links',None):return shapes
    skin=rig.points+delta;result=dict(shapes)
    for kind,faces in rig.oral_parts.items():
        if not kind.startswith('mouth_') or kind not in shapes:continue
        ids=sorted({i for f in faces for i in rig.info['faces'][f]});selected=set(ids)
        raw=np.zeros_like(delta);shape=shapes[kind]
        for i,weights in rig.cavity_links.items():
            if i not in selected:continue
            target=sum((skin[j]*w for j,w in weights),np.zeros(3))
            raw[i]=target-rig.cavity_points[i]-shape[i]
        if np.max(abs(raw))<1e-12:continue
        correction=rig.cavity_field.solve(raw)
        result[kind]=shape.copy();result[kind][ids]+=correction[ids]
    return result


def visible_teeth(triangles,outline):
    """Clip tooth obstacles to the actual Face aperture in the XZ plane.

    The lining attached under the lip must not be forced behind teeth already
    covered by Face. Triangulating the opening also supports concave mouths.
    """
    if not len(triangles) or len(outline)<3:return np.empty((0,3,3))
    scale=max(float(np.ptp(outline,axis=0).max()),1e-12);epsilon=scale*1e-9
    ring=[]
    for x,y,z in outline:
        point=Vector((float(x),0.,float(z)))
        if not ring or (point-ring[-1]).length>epsilon:ring.append(point)
    if len(ring)>1 and (ring[0]-ring[-1]).length<=epsilon:ring.pop()
    if len(ring)<3:return np.empty((0,3,3))
    # Blender returns triangle vertex indices, not Vector coordinates.
    indices=np.asarray(tessellate_polygon([ring]),dtype=np.int32).reshape((-1,3))
    tiles=np.asarray(ring,dtype=float)[indices]
    if not len(tiles):return np.empty((0,3,3))
    other=triangles[:,:,[0,2]];lo=other.min(1);hi=other.max(1);result=[]
    for first in range(0,len(tiles),64):
        plane=tiles[first:first+64][:,:,[0,2]]
        ia,ib=np.nonzero(np.all(plane.min(1)[:,None]<=hi,axis=-1)&np.all(plane.max(1)[:,None]>=lo,axis=-1))
        if not len(ia):continue
        _,weights,valid=Surfaces.overlap_vertices(plane[ia],other[ib])
        for index in np.flatnonzero(np.count_nonzero(valid,axis=1)>=3):
            polygon=weights[index,valid[index]]@triangles[ib[index]]
            center=polygon.mean(0);angles=np.arctan2(polygon[:,2]-center[2],polygon[:,0]-center[0])
            polygon=polygon[np.argsort(angles)]
            keep=np.linalg.norm(polygon-np.roll(polygon,1,axis=0),axis=1)>epsilon
            polygon=polygon[keep]
            for k in range(1,len(polygon)-1):
                tri=polygon[[0,k,k+1]]
                if abs(Surfaces.cross2((tri[1]-tri[0])[[0,2]],(tri[2]-tri[0])[[0,2]]))>epsilon*epsilon:
                    result.append(tri)
    return np.asarray(result,dtype=float).reshape((-1,3,3))


def smooth_depth(field,lower,upper):
    """Positive graph solve with contact bounds, without isolated pinned spikes."""
    lower=np.minimum(np.maximum(lower,0.),upper);values=lower.copy()
    for _ in range(180):
        neighbor=np.bincount(field.a,field.w*values[field.b],minlength=field.n)
        neighbor+=np.bincount(field.b,field.w*values[field.a],minlength=field.n)
        target=np.clip(neighbor/np.maximum(field.degree+field.mass,1e-12),lower,upper)
        change=target-values;values+=change*.8
        if float(np.max(abs(change)))<max(float(np.max(upper))*1e-8,1e-12):break
    return values


def deform(rig,delta,recipe):
    kinds=[kind for kind in rig.oral_parts if kind.startswith('mouth_')]
    if not kinds or ('LIP',0) not in rig.rows:
        return {},dict(cavity_rim_vertices=0,cavity_teeth_contacts=0,cavity_depth_limited_vertices=0,cavity_unresolved_overlaps=0,cavity_ambiguous_rims=0)
    width=rig.widths['LIP',0];original=rig.original_points
    rows=rig.rows['LIP',0];branches={};lip_ids={}
    for upper in (False,True):
        weights=[lip_weights(rows,u,upper) for u in np.linspace(0,1,65)]
        rest=np.array([sum((original[i]*w for i,w in row),np.zeros(3)) for row in weights])
        posed=np.array([sum(((rig.points[i]+delta[i])*w for i,w in row),np.zeros(3)) for row in weights])
        branches[upper]=(rest,posed)
        lip_ids[upper]=[i for u,i in sorted({(u,i) for i,u,up in rows if up==upper or u<1e-7 or u>1-1e-7})]
    opening=lip_ids[True]+list(reversed(lip_ids[False][1:-1]))
    faces=[rig.info['faces'][f] for kind in kinds for f in rig.oral_parts[kind]]
    ids=sorted({i for f in faces for i in f})
    skin=rig.points+delta
    rim={i:sum((skin[j]*w for j,w in weights),np.zeros(3)) for i,weights in rig.cavity_links.items()}
    # Eye/brow-only keys still copy any motion at a shared Face seam. With no
    # seam motion the prepared neutral lining is already the correct result.
    if not (recipe.get('mouth') or recipe.get('mouth_targets') or recipe.get('oral') or 'jaw' in recipe):
        raw=np.zeros_like(original)
        for i,target in rim.items():raw[i]=target-rig.cavity_points[i]
        motion=rig.cavity_field.solve(raw)
        shapes={kind:motion for kind in kinds}
        return shapes,dict(cavity_rim_vertices=len(rim),cavity_teeth_contacts=0,cavity_depth_limited_vertices=0,
                           cavity_unresolved_overlaps=0,cavity_ambiguous_rims=rig.cavity_ambiguous)
    lip_depth=float(np.median(np.concatenate([v[0][:,1] for v in branches.values()])))
    back=max(float(original[ids,1].max()),lip_depth+width*.02)
    desired=original.copy();sum_motion=np.zeros_like(original);counts=np.zeros(len(original))
    poses={kind:part_pose(rig,recipe,kind) for kind in kinds}
    for kind,(part_ids,center,rotation,translation) in poses.items():
        cloud=original[part_ids];rigid=(cloud-center)@rotation.T+center+translation
        anchors=[];motions=[]
        for upper in (False,True):
            rest,posed=branches[upper];order=np.argsort(rest[:,0]);rest=rest[order];posed=posed[order]
            anchors.append(np.column_stack([np.interp(cloud[:,0],rest[:,0],rest[:,axis]) for axis in range(3)]))
            motions.append(np.column_stack([np.interp(cloud[:,0],rest[:,0],(posed-rest)[:,axis]) for axis in range(3)]))
        lo,hi=anchors
        height=np.maximum(hi[:,2]-lo[:,2],width*.025);middle=(lo[:,2]+hi[:,2])*.5
        branch=np.clip(.5+(cloud[:,2]-middle)/height,0,1);branch=branch*branch*(3-2*branch)
        movement=motions[0]*(1-branch[:,None])+motions[1]*branch[:,None]
        depth=np.clip((cloud[:,1]-lip_depth)/(back-lip_depth),0,1)
        depth=np.clip((depth-.15)/.85,0,1);follow=1-depth*depth*(3-2*depth)
        posed=rigid+follow[:,None]*(cloud+movement-rigid)
        sum_motion[part_ids]+=posed-cloud;counts[part_ids]+=1
    raw=sum_motion/np.maximum(counts[:,None],1.)
    for i,target in rim.items():raw[i]=target-original[i]
    # Spread the lip displacement over connected lining, including corners.
    # Shared upper/lower vertices get one target and one linear playback path.
    field=rig.cavity_field
    desired+=field.solve(raw)
    # The front neck narrows with the aperture. A translation-only lining
    # kept its original lateral overhang when the lips contracted, exposing
    # small tabs beyond both corners. Shared seam vertices remain exact.
    left=float(skin[opening,0].min());right=float(skin[opening,0].max())
    front_fraction=np.clip((original[:,1]-lip_depth)/max(back-lip_depth,1e-12),0,1)
    fade=np.clip((front_fraction-.35)/.35,0,1)
    follow=1-fade*fade*(3-2*fade)
    free_ids=np.array(sorted(set(ids)-set(rim)),dtype=int)
    if len(free_ids):
        target=np.clip(desired[free_ids,0],left+width*.002,right-width*.002)
        desired[free_ids,0]+=(target-desired[free_ids,0])*follow[free_ids]

    contacts=set();limited=set();weights=np.linspace(1/16,1,16)
    dental=[tooth_triangles(rig,recipe,float(t)) for t in weights]
    unresolved=0
    if any(len(cloud) for cloud in dental):
        back=max(float(cloud[:,:,1].max()) for cloud in dental if len(cloud))
        ceiling=np.maximum(desired[:,1],np.maximum(original[:,1],back))
        obstacles=[]
        for sample,(t,teeth) in enumerate(zip(weights,dental),1):
            notify(rig,'定位可见牙齿',sample,len(weights))
            obstacles.append(visible_teeth(teeth,rig.points[opening]+delta[opening]*t))
        triangles={}
        for kind in kinds:
            face_set=set(rig.oral_parts[kind])
            triangles[kind]=[tri for tri,f in rig.mesh_triangles if f in face_set]
        movable=np.zeros(len(original));movable[ids]=1.;movable[list(rim)]=0.
        def constraints():
            correction=np.zeros(len(original));blocked=0
            for sample,(t,teeth) in enumerate(zip(weights,obstacles),1):
                notify(rig,'口腔与牙齿接触',sample,len(weights))
                if not len(teeth):continue
                # Mouth follows the same linear key path as Face. Jaw motion
                # affects the internal endpoint without rotating the seam.
                posed=rig.cavity_points+(desired-rig.cavity_points)*t
                freedom=movable*(ceiling-desired[:,1]>1e-12)
                for kind in kinds:
                    change,conflicts=Surfaces.depth_bounds(posed,triangles[kind],teeth,freedom,front=False,coherent=True,
                                                          pulse=getattr(rig,'progress',None))
                    blocked+=conflicts
                    correction=np.maximum(correction,change/t)
            return correction,blocked
        for _ in range(4):
            correction,_=constraints();hit=set(np.flatnonzero(correction>1e-12).tolist())
            if not hit:break
            contacts.update(hit)
            room=np.maximum(ceiling-desired[:,1],0.)*movable
            limited.update(np.flatnonzero(correction>room+1e-12).tolist())
            desired[:,1]+=smooth_depth(field,correction,room)
        remaining,blocked=constraints()
        unresolved=int(np.count_nonzero(remaining>width*1e-8))+blocked
    shapes={}
    for kind,(part_ids,center,rotation,translation) in poses.items():
        shape=np.zeros_like(original);shape[part_ids]=desired[part_ids]-rig.cavity_points[part_ids]
        shapes[kind]=shape
    return shapes,dict(cavity_rim_vertices=len(rim),cavity_teeth_contacts=len(contacts),
                       cavity_ambiguous_rims=rig.cavity_ambiguous,
                       cavity_path_samples=16,cavity_depth_limited_vertices=len(limited),cavity_unresolved_overlaps=unresolved)

