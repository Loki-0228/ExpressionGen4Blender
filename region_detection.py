"""Target geometry evidence; no stored reference mesh or vertex numbering."""
from collections import Counter
import numpy as np
from . import region_core as C,region_contours as O


def components(points,polygons):
    coordinates=np.asarray(points,dtype=float);_,islands=C.topology(polygons);rows=[]
    for island in islands:
        faces=island['faces'];ids=sorted({i for f in faces for i in polygons[f]})
        cloud=coordinates[ids];low=cloud.min(0);high=cloud.max(0)
        edges=Counter(tuple(sorted((a,b))) for f in faces for a,b in zip(polygons[f],polygons[f][1:]+polygons[f][:1]))
        rows.append(dict(faces=faces,ids=ids,low=low,high=high,center=(low+high)*.5,
                         size=high-low,boundary=sum(n==1 for n in edges.values())))
    return rows


def face_host(points,polygons,rows):
    """Find a face shell before using its dimensions to classify accessories.

    A local patch named Face must not hide a larger unnamed shell with a pair
    of eye openings. Boundary geometry supplies independent host evidence;
    material/count fallbacks remain available for faces without open eye holes.
    """
    from mathutils import Vector
    material=[row for row in rows if row['hint']==0 and len(row['faces'])>=20]
    geometric=[row for row in rows if len(row['faces'])>=40
               and row['size'][0]>.35*row['size'][2]
               and row['size'][0]<2*row['size'][2]
               and row['size'][1]<row['size'][0]*1.5
               and (row['hint']<=0 or row['hint_ratio']<.8)]
    candidates=list(material)
    candidates.extend(row for row in geometric if not any(row is item for item in material))
    vectors=[Vector(point) for point in points]
    supported=[]
    for row in candidates:
        faces=[polygons[index] for index in row['faces']]
        holes=O.face_openings(faces,[0]*len(faces),vectors)
        eyes,_=boundary_features(holes,[vectors[index] for index in row['ids']])
        if len(eyes)==2:
            supported.append(row)
    if supported:
        # Frontal coverage is independent of triangulation density. A small,
        # densely triangulated decorative patch must not outvote the shell.
        face=max(supported,key=lambda row:float(row['size'][0]*row['size'][2]))
        method='paired_eye_boundaries'
    elif material:
        face=max(material,key=lambda row:len(row['faces']));method='material_fallback'
    elif geometric:
        face=max(geometric,key=lambda row:len(row['faces']));method='geometry_fallback'
    else:
        return None,dict(method='unresolved')
    return face,dict(method=method,faces=len(face['faces']),vertices=len(face['ids']),
                     material_hint=int(face['hint']),bounds=[face['low'].tolist(),face['high'].tolist()],
                     candidates=len(candidates),supported_candidates=len(supported))


def _projected_depth(samples,face_ids,polygons,coordinates,rearmost=False):
    """Depth of actual triangles at XZ samples; empty projected space is NaN."""
    triangles=[(poly[0],poly[j],poly[j+1]) for f in face_ids
               for poly in [polygons[f]] for j in range(1,len(poly)-1)]
    output=np.full(len(samples),np.nan)
    # Bound temporary arrays on dense imported meshes.
    for start in range(0,len(triangles),256):
        cloud=coordinates[np.asarray(triangles[start:start+256],dtype=int)]
        a=cloud[:,0][:,[0,2]];u=cloud[:,1][:,[0,2]]-a;v=cloud[:,2][:,[0,2]]-a
        determinant=u[:,0]*v[:,1]-u[:,1]*v[:,0]
        scale=np.maximum(np.linalg.norm(u,axis=1)*np.linalg.norm(v,axis=1),1e-30)
        good=abs(determinant)>scale*1e-10
        if not np.any(good):continue
        a,u,v,cloud,determinant=a[good],u[good],v[good],cloud[good],determinant[good]
        delta=samples[:,None]-a[None]
        s=(delta[:,:,0]*v[None,:,1]-delta[:,:,1]*v[None,:,0])/determinant
        t=(u[None,:,0]*delta[:,:,1]-u[None,:,1]*delta[:,:,0])/determinant
        hit=(s>=-1e-8)&(t>=-1e-8)&(s+t<=1+1e-8)
        depth=cloud[None,:,0,1]+s*(cloud[None,:,1,1]-cloud[None,:,0,1])+t*(cloud[None,:,2,1]-cloud[None,:,0,1])
        fill=-np.inf if rearmost else np.inf
        values=(np.max if rearmost else np.min)(np.where(hit,depth,fill),axis=1)
        values[~np.isfinite(values)]=np.nan
        output=(np.fmax if rearmost else np.fmin)(output,values)
    return output


def eye_surface_groups(points,polygons,rows,eyes,width):
    """Protect split sclera shells before testing horizontal accessory strips.

    UV seams can split the back cup and front annulus into separate islands.
    Join only coincident edges, then require the shell to span the iris and
    provide an actual backing across its projected surface. A front lash card,
    a nearby strip, or a shared corner alone supplies none of that evidence.
    """
    from mathutils.kdtree import KDTree
    coordinates=np.asarray(points,dtype=float);protected=[];reports=[]
    tolerance=width*1e-5
    for side,eye in eyes.items():
        extent=np.maximum(eye['size'],width*.005)
        candidates=[]
        for index,row in enumerate(rows):
            if row is eye or row['hint'] not in (-1,-2,7):continue
            if not row.get('hint_labels',{row['hint']})<={-1,-2,7}:continue
            relative=(row['center']-eye['center'])/extent
            if (abs(relative[0])<.9 and abs(relative[2])<.9
                    and row['size'][0]<extent[0]*3 and row['size'][2]<extent[2]*2.5
                    and abs(row['center'][1]-eye['center'][1])<extent[0]*1.5):
                candidates.append((index,row))
        if not candidates:continue
        ids=sorted({v for _,row in candidates for v in row['ids']})
        tree=KDTree(len(ids))
        for v in ids:tree.insert(points[v],v)
        tree.balance()
        parent={v:v for v in ids}
        def root(v):
            while parent[v]!=v:
                parent[v]=parent[parent[v]];v=parent[v]
            return v
        for v in ids:
            for _,other,_ in tree.find_range(points[v],tolerance):
                a,b=root(v),root(other)
                if a!=b:parent[max(a,b)]=min(a,b)
        edges={};neighbors={index:set() for index,_ in candidates}
        for index,row in candidates:
            boundary=Counter(tuple(sorted((a,b))) for f in row['faces'] for poly in [polygons[f]]
                             for a,b in zip(poly,poly[1:]+poly[:1]))
            for (a,b),count in boundary.items():
                if count!=1:continue
                edge=tuple(sorted((root(a),root(b))))
                if edge[0]!=edge[1]:edges.setdefault(edge,set()).add(index)
        for owners in edges.values():
            for index in owners:neighbors[index].update(owners-{index})
        by_id=dict(candidates);remaining=set(by_id)
        # Include coincident iris/highlight layers when the selected reference
        # island is merely the thin outer ring of the iris.
        iris=[r for r in rows if r is eye or (r['hint']==3 and
              np.max(abs(r['center'][[0,2]]-eye['center'][[0,2]])/extent[[0,2]])<.2
              and abs(r['center'][1]-eye['center'][1])<extent[0]*.1
              and np.max(r['size'][[0,2]]/extent[[0,2]])<1.3)]
        x,z=np.meshgrid(np.linspace(eye['low'][0],eye['high'][0],25),
                        np.linspace(eye['low'][2],eye['high'][2],25))
        samples=np.column_stack((x.ravel(),z.ravel()))
        reference=_projected_depth(samples,[f for r in iris for f in r['faces']],polygons,coordinates)
        valid=np.isfinite(reference)
        if np.count_nonzero(valid)<12:continue
        core=valid&(np.linalg.norm((samples-eye['center'][[0,2]])/extent[[0,2]],axis=1)<.25)
        while remaining:
            seed=min(remaining);group=set();queue=[seed]
            while queue:
                index=queue.pop()
                if index in group:continue
                group.add(index);queue.extend(neighbors[index]-group)
            remaining-=group
            members=[by_id[index] for index in sorted(group)]
            low=np.min([r['low'] for r in members],axis=0);high=np.max([r['high'] for r in members],axis=0)
            # The enclosure has to extend on both sides and above/below the
            # iris center. This rejects a long upper or lower accessory band.
            if (high[0]-low[0]<extent[0]*1.15 or
                    np.any(low[[0,2]]>eye['low'][[0,2]]+extent[[0,2]]*.2) or
                    np.any(high[[0,2]]<eye['high'][[0,2]]-extent[[0,2]]*.2)):
                continue
            backing=_projected_depth(samples,[f for r in members for f in r['faces']],
                                     polygons,coordinates,rearmost=True)
            hit=valid&np.isfinite(backing)
            coverage=float(np.count_nonzero(hit)/np.count_nonzero(valid))
            if coverage<.8:continue
            depth=(backing[hit]-reference[hit])/extent[0]
            # Allow only numerical overlap. A foreground transparent card
            # cannot become sclera merely by covering the iris in projection.
            behind=float(np.mean(depth>=-.005))
            if behind<.95 or np.median(depth)<.01 or np.quantile(depth,.95)>1.5:continue
            # A backing can hide a foreground card when taking the rearmost
            # depth. Test members independently in the central iris, allowing
            # a front annulus to graze its rim but not cover its pupil area.
            foreground=[]
            for member in members:
                front=_projected_depth(samples,member['faces'],polygons,coordinates)
                foreground.append(float(np.count_nonzero(core&np.isfinite(front)&
                                  (front<reference-extent[0]*.005))/max(np.count_nonzero(core),1)))
            if max(foreground,default=0)>.15:continue
            protected.extend(members)
            reports.append(dict(side=side,components=sorted(group),faces=sum(len(r['faces']) for r in members),
                                iris_coverage=coverage,behind_fraction=behind,
                                maximum_member_foreground_core=max(foreground,default=0),
                                depth_ratio_quantiles=np.quantile(depth,[.05,.5,.95]).tolist()))
    return protected,reports


def infer_regions(points,polygons,material_labels):
    """Classify actual islands by relative size, pairing, depth and topology.

    Material names are supporting evidence. This is never called on an
    authoritative marked partition. Unresolved islands remain available for
    manual assignment instead of instantiating missing preset parts.
    """
    rows=components(points,polygons);labels=np.asarray([C.canonical_region(int(v)) for v in material_labels],dtype=int)
    if not rows:return labels.tolist(),dict(method='geometry',warnings=['目标没有可分区的面'])
    for row in rows:
        counts=Counter(int(labels[f]) for f in row['faces']);row['hint']=counts.most_common(1)[0][0]
        row['hint_ratio']=counts[row['hint']]/len(row['faces'])
        row['hint_labels']=set(counts)
    face,host_report=face_host(points,polygons,rows)
    if face is None:return labels.tolist(),dict(method='geometry',warnings=['未找到可靠面部主体，请标记 Face 后继续'])
    width=max(float(face['size'][0]),1e-12)
    height=max(float(face['size'][2]),width*.1);plane=float(face['center'][0]);used={id(face)}
    # Preserve differing material evidence on a connected head, while splitting
    # disconnected accessories sharing one generic Face material geometrically.
    labels[face['faces']]=[int(labels[f]) if labels[f]>=0 else 0 for f in face['faces']]
    for row in rows:
        if row is not face and row['hint']==0:labels[row['faces']]=-1
    def assign(row,label):
        # A mixed connected component must not erase an explicit eye-white
        # face just because its majority is an iris or an accessory strip.
        labels[row['faces']]=[7 if material_labels[f]==7 else label for f in row['faces']]
        used.add(id(row))
    candidates=[]
    for row in rows:
        if row is face:continue
        if row['hint_ratio']>=.8 and row['hint'] in (2,7,8,9,12):continue
        x,y,z=row['size'];center=row['center'];level=(center[2]-face['low'][2])/height
        if (len(row['faces'])>=10 and width*.065<x<width*.48 and height*.055<z<height*.40
                and .3<x/max(z,1e-12)<2.8 and width*.04<abs(center[0]-plane)<width*.48
                and .20<level<.90 and y<max(x,z)):
            candidates.append(row)
    pairs=[]
    for left in candidates:
        if left['center'][0]>=plane:continue
        for right in candidates:
            if right['center'][0]<=plane:continue
            size=np.maximum((left['size']+right['size'])*.5,width*.005)
            difference=abs(left['center']-right['center']);difference[0]=abs(left['center'][0]+right['center'][0]-2*plane)
            if np.max(difference[[0,2]]/size[[0,2]])>.55:continue
            if np.max(abs(left['size'][[0,2]]-right['size'][[0,2]])/size[[0,2]])>.65:continue
            hint=sum(r['hint']==3 for r in (left,right))
            depth=(left['center'][1]+right['center'][1]-2*face['low'][1])/width
            # Both iris and catchlight now have label 3. Prefer the full eye
            # footprint over a smaller, more forward pair of highlights.
            footprint=max(float(size[0]*size[2]/(width*width)),1e-12)
            score=hint*4+2*np.log(footprint)-depth-np.sum(difference[[0,2]]/size[[0,2]])
            pairs.append((score,left,right))
    eyes={}
    if pairs:
        _,left,right=max(pairs,key=lambda r:r[0]);eyes={-1:left,1:right}
        for row in eyes.values():assign(row,3)
    surfaces,surface_report=eye_surface_groups(points,polygons,rows,eyes,width)
    for row in surfaces:assign(row,7)
    for row in rows:
        if id(row) in used:continue
        if row['hint_ratio']>=.8 and row['hint'] in (2,3,7):assign(row,row['hint']);continue
        side=1 if row['center'][0]>=plane else -1;eye=eyes.get(side)
        if eye is None:continue
        extent=np.maximum(eye['size'],width*.005);relative=(row['center']-eye['center'])/extent
        x,y,z=row['size']
        # Thin strips around/above the aperture include both brows and lashes.
        strip=x>z*1.8 and x>width*.09 and abs(relative[0])<1.3 and -.8<relative[2]<2.5
        if strip and abs(relative[1])*extent[1]<width*.18:assign(row,2);continue
    # Individual lash spikes need not be horizontal. Require a slender shape
    # rooted near an already identified strip, rather than calling every small
    # object around the iris a highlight.
    coordinates=np.asarray(points,dtype=float)
    strips=[row for row in rows if id(row) in used and np.all(labels[row['faces']]==2)]
    for row in rows:
        if id(row) in used or row['hint'] in (3,7,8,9,12):continue
        eye=eyes.get(1 if row['center'][0]>=plane else -1)
        if eye is None or max(row['size'])>max(eye['size'])*.65:continue
        cloud=coordinates[row['ids']];singular=np.linalg.svd(cloud-cloud.mean(0),compute_uv=False)
        if len(singular)<2 or singular[0]<singular[1]*2:continue
        nearby=[strip for strip in strips if np.linalg.norm(strip['center']-row['center'])<width*.3]
        if any(np.linalg.norm(cloud[:,None]-coordinates[strip['ids']][None],axis=-1).min()<width*.015 for strip in nearby):
            assign(row,2)
    # Resolve small eye patches only after root-connected lash spikes. A
    # highlight is part of Eyes throughout detection, never a temporary Gaze.
    for row in rows:
        if id(row) in used:continue
        eye=eyes.get(1 if row['center'][0]>=plane else -1)
        if eye is None:continue
        extent=np.maximum(eye['size'],width*.005);relative=(row['center']-eye['center'])/extent
        if abs(relative[0])>=.7 or abs(relative[2])>=.7:continue
        x,y,z=row['size'];area=x*z/max(extent[0]*extent[2],1e-20)
        if area<.3 and row['center'][1]<=eye['center'][1]+width*.005:assign(row,3)
        elif area>1.15 and row['center'][1]>eye['center'][1]:assign(row,7)
        elif .3<=area<=1.15:assign(row,3)
    eye_level=min((r['low'][2] for r in eyes.values()),default=face['low'][2]+height*.5)
    for row in rows:
        if id(row) in used:continue
        x,y,z=row['size'];center=row['center']
        if not (width*.07<x<width*.55 and abs(center[0]-plane)<width*.08
                and face['low'][2]<center[2]<eye_level and row['high'][1]>face['low'][1]):continue
        if row['hint'] in (8,9,12):assign(row,row['hint']);continue
        if row['boundary']==0 and y>x*.45 and z<x*.8:assign(row,12)
        elif row['boundary'] and z<x*.6 and y<x*.8:assign(row,9)
        elif row['boundary'] and y>x*.35:assign(row,8)
    labels=np.array([C.canonical_region(int(v)) for v in labels])
    counts=Counter(int(v) for v in labels)
    return labels.tolist(),dict(method='geometry',present_regions=sorted(k for k,n in counts.items() if k>=0 and n),
                                components=len(rows),geometric_components=len(used),face_host=host_report,
                                eye_surface_groups=surface_report,warnings=[])


def boundary_features(holes,skin_points):
    """Localize real Face holes even when no accessory region exists.

    This only supplies contour candidates; it never creates a material region.
    Bilateral eye evidence is required before accepting an unanchored mouth.
    """
    cloud=np.asarray(skin_points,dtype=float);low=cloud.min(0);high=cloud.max(0)
    width=max(float(high[0]-low[0]),1e-12);height=max(float(high[2]-low[2]),1e-12)
    plane=float((low[0]+high[0])*.5)
    candidates=[r for r in holes if width*.08<r['width']<width*.48 and
                .16<r['height']/max(r['width'],1e-12)<1.8 and
                .25<(r['center'][2]-low[2])/height<.88]
    pairs=[]
    for left in candidates:
        if left['center'][0]>=plane-width*.04:continue
        for right in candidates:
            if right['center'][0]<=plane+width*.04:continue
            size=(left['width']+right['width'])*.5
            asymmetry=(abs(left['center'][0]+right['center'][0]-2*plane)+abs(left['center'][2]-right['center'][2]))/size
            shape=abs(left['width']-right['width'])/size
            if asymmetry<.5 and shape<.5:pairs.append((asymmetry+shape,left,right))
    if not pairs:return {},None
    _,left,right=min(pairs,key=lambda row:row[0]);eyes={-1:left['points'],1:right['points']}
    eye_bottom=min(min(p[2] for p in row['points']) for row in (left,right))
    mouths=[r for r in holes if width*.06<r['width']<width*.6 and r['height']<r['width']*.75
            and abs(r['center'][0]-plane)<width*.08 and low[2]+height*.04<r['center'][2]<eye_bottom]
    mouth=min(mouths,key=lambda r:abs(r['center'][0]-plane)/width-r['width']/width) if mouths else None
    return eyes,mouth['points'] if mouth else None


def pocket_openings(points,polygons,labels,region_points,face_width,mouth=False):
    """Trace the front skin entrance, not the widest internal cross-section.

    A connected eye or oral pocket can widen behind its opening. Its entrance
    is the closed fold where adjacent faces change facing along the view's
    Y axis. Retain actual mesh edges and validate the inset surface behind it.
    """
    if len(region_points)<3:return []
    coordinates=np.asarray(points,dtype=float);anchor=np.asarray(region_points,dtype=float)
    low=anchor.min(0);high=anchor.max(0);center=(low+high)*.5
    width=max(float(high[0]-low[0]),face_width*.025)
    edge_faces={};facing={}
    for f,label in enumerate(labels):
        if label!=0:continue
        poly=polygons[f];cloud=coordinates[poly];local=cloud-cloud.mean(0)
        normal=np.cross(local,np.roll(local,-1,axis=0)).sum(0)
        facing[f]=float(normal[1])/max(float(np.linalg.norm(normal)),1e-30)
        for a,b in zip(poly,poly[1:]+poly[:1]):edge_faces.setdefault(tuple(sorted((a,b))),[]).append(f)
    graph={}
    for (a,b),owners in edge_faces.items():
        if len(owners)!=2 or facing[owners[0]]*facing[owners[1]]>=-1e-12:continue
        graph.setdefault(a,set()).add(b);graph.setdefault(b,set()).add(a)
    remaining=set(graph);choices=[]
    while remaining:
        seed=min(remaining);part=set();queue=[seed]
        while queue:
            i=queue.pop()
            if i in part:continue
            part.add(i);queue.extend(graph[i]-part)
        remaining-=part
        if len(part)<6 or any(len(graph[i])!=2 for i in part):continue
        ring=[seed];previous=None;current=seed
        while True:
            following=min(graph[current]-({previous} if previous is not None else set()))
            if following==seed:break
            ring.append(following);previous,current=current,following
        cloud=coordinates[ring];lo=cloud.min(0);hi=cloud.max(0);mid=(lo+hi)*.5
        if not lo[0]<center[0]<hi[0] or abs(mid[0]-center[0])>width*.25:continue
        if not max(width*.35,face_width*.035)<hi[0]-lo[0]<min(width*2.2,face_width*.6):continue
        if mouth:
            if hi[2]-lo[2]>(hi[0]-lo[0])*.85:continue
            if abs(mid[2]-center[2])>max(float(high[2]-low[2]),face_width*.08):continue
        else:
            if not lo[2]<center[2]<hi[2] or hi[2]-lo[2]<float(high[2]-low[2])*.25:continue
        # The entrance lies near/in front of the iris, teeth or tongue. A
        # rear pocket silhouette is not an eyelid/lip regardless of its area.
        front_depth=float(np.median(cloud[:,1]))
        if front_depth>float(np.quantile(anchor[:,1],.35))+width*.12:continue
        try:frame=O.MouthFrame([points[i] for i in ring])
        except ValueError:continue
        row=dict(points=[points[i] for i in ring],vertices=ring,center=frame.center,
                 width=frame.width,height=frame.height,
                 method='mouth_front_fold' if mouth else 'eye_front_fold',front_depth=front_depth)
        row['faces']=pocket_faces(points,polygons,labels,row,edge_faces)
        if row['faces']:choices.append(row)
    # Prefer the foremost validated entrance; neither area nor the size of
    # the backing/accessory determines the aperture separation.
    return sorted(choices,key=lambda row:row['front_depth'])[:1]


def pocket_faces(points,polygons,labels,row,edge_faces):
    """Cut the Face graph at a real rim and retain only its inset disk.

    Flood on the full mesh, not within the detection window: a bounding box
    must never truncate the backing or label the rear of the head as an eye.
    """
    ring=row['vertices'];ring_set=set(ring);rim={tuple(sorted(e)) for e in zip(ring,ring[1:]+ring[:1])}
    if len(ring_set)!=len(ring):return []
    if any(len(edge_faces.get(e,[]))!=2 for e in rim):return []
    seeds=set(edge_faces[next(iter(rim))]);visited=set();candidates=[]
    coordinates=np.asarray(points,dtype=float);cloud=coordinates[ring]
    center=cloud.mean(0);span=np.maximum(np.ptp(cloud[:,[0,2]],axis=0),1e-12)
    mouth=row.get('method')=='mouth_front_fold'
    if mouth:
        # A thin slit must not constrain the internal cavity's height. Fit
        # contact depth along X only; extrapolating its tiny Z range would
        # turn a sloped lip into an arbitrary plane through the whole head.
        x=(cloud[:,0]-center[0])/span[0]
        design=np.column_stack((np.ones(len(ring)),x,x*x))
    else:design=np.column_stack((np.ones(len(ring)),(cloud[:,[0,2]]-center[[0,2]])/span))
    plane=np.linalg.lstsq(design,cloud[:,1],rcond=None)[0]
    face_count=sum(label==0 for label in labels)
    for seed in sorted(seeds):
        if seed in visited:continue
        part=set();queue=[seed]
        while queue:
            f=queue.pop()
            if f in part:continue
            part.add(f);poly=polygons[f]
            for a,b in zip(poly,poly[1:]+poly[:1]):
                edge=tuple(sorted((a,b)))
                if edge not in rim:queue.extend(i for i in edge_faces[edge] if i not in part)
        visited.update(part)
        if not 3<=len(part)<=face_count*.3:continue
        counts=Counter(tuple(sorted((a,b))) for f in part for a,b in zip(polygons[f],polygons[f][1:]+polygons[f][:1]))
        boundary={edge for edge,n in counts.items() if n==1}
        ids=sorted({v for f in part for v in polygons[f]})
        # Exactly one closed ring, manifold disk, no second opening into the
        # head or a nested hole. Reject ambiguous/non-manifold candidates.
        if boundary!=rim or max(counts.values())>2 or len(ids)-len(counts)+len(part)!=1:continue
        inside=coordinates[ids]
        scale=max(span)
        if mouth:
            if np.any(abs(inside[:,[0,2]]-center[[0,2]])>scale*1.5):continue
            parameters=np.clip((inside[:,0]-center[0])/span[0],x.min(),x.max())
            reference=plane[0]+parameters*plane[1]+parameters**2*plane[2]
        else:
            projected=(inside[:,[0,2]]-center[[0,2]])/span
            if np.any(abs(projected)>1.1):continue
            reference=plane[0]+projected@plane[1:]
        depth=inside[:,1]-reference
        interior=[i for i,v in enumerate(ids) if v not in ring_set]
        if not interior:continue
        inset=depth[interior]
        if np.quantile(inset,.65)<scale*.015 or np.quantile(inset,.1)<-scale*.08:continue
        if np.max(inset)>scale*(3. if mouth else 1.5):continue
        candidates.append(sorted(part))
    return candidates[0] if len(candidates)==1 else []


def infer_face_backings(points,polygons,labels):
    """Relabel existing Face pockets as sclera/cavity, leaving other marks.

    Accessory location proposes a rim; a bounded inset surface connected to
    that rim is mandatory. No preset, new surface, or shape-key evidence.
    """
    result=list(labels);coordinates=np.asarray(points,dtype=float)
    skin=sorted({v for f,label in zip(polygons,labels) if label==0 for v in f})
    report=dict(method='face_backing_topology',regions=[],warnings=[])
    if not skin:return result,report
    low=coordinates[skin].min(0);high=coordinates[skin].max(0)
    width=max(float(high[0]-low[0]),1e-12);plane=float((low[0]+high[0])*.5)
    def cloud(label,side=0):
        ids=sorted({v for f,l in zip(polygons,result) if l==label for v in f
                    if not side or (1 if coordinates[v,0]>=plane else -1)==side})
        return [points[i] for i in ids]
    anchors=[]
    for side in (-1,1):
        if cloud(7,side):continue
        anchor=cloud(3,side) or cloud(5,side)
        if len(anchor)>=3:anchors.append((7,side,anchor,False))
    if not cloud(8):
        anchor=cloud(9)+cloud(12)
        if len(anchor)>=3:anchors.append((8,0,anchor,True))
    for label,side,anchor,mouth in anchors:
        holes=O.face_openings(polygons,result,points)
        # An existing aperture without a backing is valid. Do not reinterpret
        # the head's far surface, or invent a missing eye/cavity region.
        if O.pick_opening(holes,anchor,width,mouth=mouth):continue
        edge_faces={}
        for f,l in enumerate(result):
            if l!=0:continue
            poly=polygons[f]
            for a,b in zip(poly,poly[1:]+poly[:1]):edge_faces.setdefault(tuple(sorted((a,b))),[]).append(f)
        candidates=[]
        for row in pocket_openings(points,polygons,result,anchor,width,mouth=mouth):
            faces=row.get('faces') or pocket_faces(points,polygons,result,row,edge_faces)
            if faces:row['faces']=faces;candidates.append(row)
        chosen=O.pick_opening(candidates,anchor,width,mouth=mouth) if candidates else None
        if chosen is None:continue
        row=next(row for row in candidates if row['points'] is chosen)
        for f in row['faces']:result[f]=label
        report['regions'].append(dict(label=label,side=side,faces=len(row['faces']),rim_vertices=len(row['vertices']),
                                      rim_method=row['method']))
    report['changed_faces']=sum(a!=b for a,b in zip(result,labels))
    report['present_regions']=sorted(set(result)-{-1,-2})
    return result,report


def front_mouth_opening(candidates,points,polygons,labels,cloud,width,details=None):
    """Find a front lip on connected skin, including a separate lower face."""
    local={}
    opening=_front_mouth_on_component(candidates,points,polygons,labels,cloud,width,local)
    if opening is not None:
        if details is not None:details.update(local)
        return opening
    skin=[poly for poly,label in zip(polygons,labels) if label==0]
    _,islands=C.topology(skin)
    if len(islands)<2:return None
    largest=max(islands,key=lambda row:len(row['faces']))
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    coordinates=np.asarray(points,dtype=float);choices=[]
    front=float(coordinates[:,1].min()-width*2)
    length=float(np.ptp(coordinates[:,1])+width*4)
    for island in islands:
        if island is largest:continue
        faces=set(island['faces']);vertices={i for f in faces for i in skin[f]}
        owned=[(score,row) for score,row in candidates if set(row['vertices'])<=vertices]
        if not owned:continue
        # A detached lining must not replace the visible skin in front of it.
        others=[poly for f,poly in enumerate(skin) if f not in faces]
        tree=BVHTree.FromPolygons([Vector(p) for p in points],others) if others else None
        for score,row in owned:
            local={}
            opening=_front_mouth_on_component([(score,row)],points,polygons,labels,row['points'],width,local,faces)
            if opening is None:continue
            p=np.asarray(opening);q=np.roll(p,-1,axis=0)
            weights=np.linalg.norm(q[:,[0,2]]-p[:,[0,2]],axis=1);visible=0.
            for a,b,w in zip(p,q,weights):
                mid=(a+b)*.5
                hit=tree.ray_cast(Vector((mid[0],front,mid[2])),Vector((0,1,0)),length)[0] if tree else None
                if hit is None or hit.y>=mid[1]-row['width']*1e-4:visible+=w
            total=max(float(weights.sum()),1e-20)
            if visible/total<.97:continue
            support=local.get('surface_faces',set())
            surface=[label if i in support else -1 for i,label in enumerate(labels)]
            lip=O.LipRing(opening,surface=(points,polygons,surface))
            sides=lip.surface_sides((lip.chains[True],lip.chains[False]),(points,polygons,surface))
            if sides is None or min(sides)>=-.15 or max(sides)<=.15:continue
            depth=float(np.sum((p[:,1]+q[:,1])*.5*weights)/total)
            local['split_face_component']=True
            choices.append((depth,score,opening,local))
    if not choices:return None
    _,_,opening,local=min(choices,key=lambda row:(row[0],row[1]))
    if details is not None:details.update(local)
    return opening


def _front_mouth_on_component(candidates,points,polygons,labels,cloud,width,details=None,component=None):
    """Find an open lip entrance on the exterior skin, not its rear material seam.

    This path requires a real Face boundary. Inward-facing lip strips may end
    at that boundary while the visible lip lies at a fold in front of it. The
    rear strip may be an annulus or a partial strip; no closed pocket is needed.
    Connected backing detection uses its separate disk-based path unchanged.
    """
    coordinates=np.asarray(points,dtype=float)
    skin_ids=[i for i,label in enumerate(labels) if label==0]
    skin=[polygons[i] for i in skin_ids]
    neighbors,islands=C.topology(skin)
    if not islands:return None
    # A detached cavity sharing the Face material must not supply the lip.
    exterior=set(component) if component is not None else set(max(islands,key=lambda row:len(row['faces']))['faces'])
    exterior_vertices={v for f in exterior for v in skin[f]}
    candidates=[(score,row) for score,row in candidates if set(row['vertices'])<=exterior_vertices]
    if not candidates:return None
    rim_edges={tuple(sorted((a,b))) for _,row in candidates
               for a,b in zip(row['vertices'],row['vertices'][1:]+row['vertices'][:1])}
    rim_ids=sorted({v for edge in rim_edges for v in edge});rim=coordinates[rim_ids]
    lo=rim.min(0);hi=rim.max(0);center=(lo+hi)*.5
    span=max(float(hi[0]-lo[0]),width*.025)
    owners={};facing={};areas={};centers={}
    for f in exterior:
        poly=skin[f];p=coordinates[poly];c=p.mean(0);local=p-c
        normal=np.cross(local,np.roll(local,-1,axis=0)).sum(0)
        area=float(np.linalg.norm(normal));facing[f]=float(normal[1])/max(area,1e-30)
        areas[f]=area;centers[f]=c
        for a,b in zip(poly,poly[1:]+poly[:1]):owners.setdefault(tuple(sorted((a,b))),[]).append(f)
    # Infer winding from the frontmost skin around the opening, so an entirely
    # reversed mesh does not swap exterior and interior. Do not use the cavity
    # center's depth: an independent cavity can be arbitrarily deep or large.
    local=[f for f in exterior if abs(centers[f][0]-center[0])<span*1.25
           and abs(centers[f][2]-center[2])<span*.75 and abs(facing[f])>.15]
    if not local:return None
    front=float(np.quantile([centers[f][1] for f in local],.35))
    sample=[f for f in local if centers[f][1]<=front]
    vote=sum(facing[f]*areas[f] for f in sample)
    weight=sum(abs(facing[f])*areas[f] for f in sample)
    if abs(vote)<weight*.35 or weight<=1e-20:return None
    sign=1. if vote>0 else -1.
    forward={f for f in exterior if sign*facing[f]>=-1e-8}
    front_labels=[-1]*len(polygons)
    for f in forward:front_labels[skin_ids[f]]=0
    front_rows=O.opening_candidates(O.face_openings(polygons,front_labels,points),cloud,width,mouth=True)
    # A fold is accepted only if its inward side reaches the existing oral
    # boundary through a local strip of the same skin. Reject closed dimples,
    # nostrils, and the far side of the head even if their projection is nearby.
    remaining=exterior-forward;linked=set()
    while remaining:
        seed=min(remaining);part={seed};queue=[seed];remaining.remove(seed)
        while queue:
            for f in neighbors[queue.pop()]:
                if f in remaining:remaining.remove(f);part.add(f);queue.append(f)
        if len(part)>len(exterior)*.3:continue
        ids=sorted({v for f in part for v in skin[f]});p=coordinates[ids]
        if np.any(abs(p[:,[0,2]]-center[[0,2]])>span*1.5):continue
        if not any(f in part for edge in rim_edges for f in owners.get(edge,[])):continue
        linked.update(part)
    accepted=[]
    for score,row in front_rows:
        ring=row['vertices'];p=coordinates[ring];mid=(p.min(0)+p.max(0))*.5
        if not span*.4<row['width']<span*1.6 or abs(mid[2]-center[2])>span*.5:continue
        edges=[tuple(sorted((a,b))) for a,b in zip(ring,ring[1:]+ring[:1])]
        if not all(edge in rim_edges or any(f in linked for f in owners.get(edge,[])) for edge in edges):continue
        # Integrate depth along the outline rather than weighting dense vertex
        # patches more heavily. Foremost supported skin wins over cavity size.
        q=np.roll(p,-1,axis=0);lengths=np.linalg.norm(q[:,[0,2]]-p[:,[0,2]],axis=1)
        depth=float(np.sum((q[:,1]+p[:,1])*.5*lengths)/max(float(lengths.sum()),1e-20))
        accepted.append((depth,score,row))
    if not accepted:return None
    if details is not None:details['surface_faces']={skin_ids[f] for f in forward}
    return min(accepted,key=lambda row:(row[0],row[1]))[2]['points']


def marked_mouth_opening(holes,points,polygons,labels,width,details=None):
    """Use the already marked, connected cavity to identify its front entrance.

    A cavity's centre/maximum radius can be far behind and above the lip. Its
    shared Face interface provides topology, not a new material assignment.
    The exterior fold still wins over a deep material seam.
    """
    interfaces=[row for row in holes if row.get('oral_boundary') and width*.025<row['width']<width*.65
                and row['height']<row['width']*.85]
    if not interfaces:return None
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    coordinates=np.asarray(points,dtype=float)
    skin=[f for f,label in enumerate(labels) if label==0]
    tree=BVHTree.FromPolygons([Vector(p) for p in points],[polygons[f] for f in skin])
    front=float(coordinates[:,1].min()-width*2);length=float(np.ptp(coordinates[:,1])+width*4)
    owners={}
    for f in skin:
        poly=polygons[f]
        for a,b in zip(poly,poly[1:]+poly[:1]):owners.setdefault(tuple(sorted((a,b))),[]).append(f)
    choices=[]
    for row in interfaces:
        # Localize from the seam itself; deep tongue/back-wall extents are not
        # a reason to discard a correctly labelled connected mouth.
        local={};candidate=front_mouth_opening([(0.,row)],points,polygons,labels,row['points'],width,local)
        if candidate is not None:
            p=np.asarray(candidate);q=np.roll(p,-1,axis=0);weights=np.linalg.norm(q[:,[0,2]]-p[:,[0,2]],axis=1)
            depth=float(np.sum((p[:,1]+q[:,1])*.5*weights)/max(float(weights.sum()),1e-20))
            choices.append((depth,candidate,local));continue
        ring=row['vertices'];p=coordinates[ring];q=np.roll(p,-1,axis=0)
        weights=np.linalg.norm(q[:,[0,2]]-p[:,[0,2]],axis=1);visible=0.;supported=0.
        rim=set(ring)
        for a,b,w in zip(ring,ring[1:]+ring[:1],weights):
            midpoint=(coordinates[a]+coordinates[b])*.5
            hit,_,_,_=tree.ray_cast(Vector((midpoint[0],front,midpoint[2])),Vector((0,1,0)),length)
            if hit is None or hit.y>=midpoint[1]-row['width']*1e-4:visible+=w
            for f in owners.get(tuple(sorted((a,b))),[]):
                outside=[v for v in polygons[f] if v not in rim]
                if not outside:continue
                offset=coordinates[outside].mean(0)-midpoint
                # Exterior skin runs outward in XZ. A depth-only lining wall
                # is not a valid fallback for a rejected deep mouth boundary.
                planar=float(np.linalg.norm(offset[[0,2]]))
                if planar>abs(float(offset[1]))*.5 and offset[1]<row['width']*.08:
                    supported+=w;break
        total=max(float(weights.sum()),1e-20)
        if visible/total<.97 or supported/total<.8:continue
        lip=O.LipRing(row['points'],surface=(points,polygons,labels))
        scores=lip.surface_sides((lip.chains[True],lip.chains[False]),(points,polygons,labels))
        if scores is None or min(scores)>=-.15 or max(scores)<=.15:continue
        depth=float(np.sum((p[:,1]+q[:,1])*.5*weights)/total)
        choices.append((depth,row['points'],dict(surface_faces=set(skin))))
    if not choices:return None
    _,opening,local=min(choices,key=lambda row:row[0])
    if details is not None:details.update(local)
    return opening


def opening_for_region(holes,points,polygons,labels,cloud,width,mouth=False,details=None):
    if mouth:
        connected=marked_mouth_opening(holes,points,polygons,labels,width,details)
        if connected is not None:return connected,'marked_mouth_front_interface'
        candidates=O.opening_candidates(holes,cloud,width,mouth=True)
        if candidates:
            local={} if details is None else details
            opening=front_mouth_opening(candidates,points,polygons,labels,cloud,width,local)
            # Never silently fall back to a deep boundary after rejecting it.
            if opening is None:return None,'unreliable_open_mouth'
            method='split_face_mouth_front_skin' if local.get('split_face_component') else 'open_mouth_front_skin'
            return opening,method
    opening=O.pick_opening(holes,cloud,width,mouth=mouth) if len(cloud)>=3 else None
    if opening:return opening,'boundary'
    candidates=pocket_openings(points,polygons,labels,cloud,width,mouth=mouth)
    opening=O.pick_opening(candidates,cloud,width,mouth=mouth) if candidates else None
    method=next((row['method'] for row in candidates if row['points'] is opening),None)
    return opening,method
