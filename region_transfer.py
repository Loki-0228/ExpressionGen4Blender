"""Fit a partitioned source, then transfer key deltas within semantic regions."""
import json
from collections import Counter, defaultdict
from math import exp
import bpy
import numpy as np
from mathutils import Vector, Matrix
from . import region_core as C, region_blender as A
from . import region_contours as O
from . import region_guides as G, region_lashes as L
from .region_deformation import SkinDisplacementField
from .region_eye_motion import EyeMotion
from .region_rigid_parts import RigidTeeth, RigidMouth


def is_tongue_key(name):
    return any(word in name.casefold() for word in ('tongue','舌','ぺろ','べー','あっかん'))


def mark_tongue(source_or_preview, copy_source=False, face_indices=None):
    """Explicit tongue annotation; source edits go on a new partition copy."""
    A.check_mesh(source_or_preview)
    selected=list(face_indices) if face_indices is not None else [p.index for p in source_or_preview.data.polygons if p.select]
    if not selected:
        raise ValueError('请先选择舌头的面')
    selected=sorted(set(selected))
    if any(i<0 or i>=len(source_or_preview.data.polygons) for i in selected):
        raise ValueError('舌头面选择已失效，请在分区副本中重新选面')
    if copy_source:
        ob=source_or_preview.copy()
        ob.data=source_or_preview.data.copy()
        ob.name=source_or_preview.name+'_EK_tongue_partition'
        A.new_collection('EK_舌头分区工作副本').objects.link(ob)
        ob[A.TAG]=True
        ob['ek_partition_source_origin']=source_or_preview.name
    else:
        if not A.is_working(source_or_preview):
            raise ValueError('目标舌头只能在已修正的分区副本上标记')
        ob=source_or_preview
        selected_set=set(selected)
        if not any(label==0 and i not in selected_set for i,label in enumerate(mesh_regions(ob))):
            raise ValueError('请仅选择舌头面，保留其余 Face 面部分区')
        # Check the partition before appending materials or changing any face.
        A.adopt_corrected_regions(ob)
    slot=next((i for i,s in enumerate(ob.material_slots) if s.material and C.material_region(s.material.name)==12),None)
    if slot is None:
        material=A.marker_material('EK_对应_Tongue',A.region_color(12))
        ob.data.materials.append(material)
        slot=len(ob.data.materials)-1
    if ob.mode=='EDIT' and not copy_source:
        import bmesh
        bm=bmesh.from_edit_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        for i in selected:
            bm.faces[i].material_index=slot
        bmesh.update_edit_mesh(ob.data)
        ob.update_from_editmode()
    else:
        for i in selected:
            ob.data.polygons[i].material_index=slot
    if not copy_source:
        A.adopt_corrected_regions(ob,authoritative=True)
    return ob,len(selected)


class BoundaryLattice:
    """Trilinear cage solved from corresponding region-edge samples.

    Data constraints and six-neighbor smoothing share deformation between
    regions. This is a global warp, not independently scaled facial pieces.
    """
    def __init__(self, lo, hi, anchors, resolution=4, strength=0.75):
        self.lo, self.hi = lo.copy(), hi.copy()
        self.n = resolution
        self.extent = hi-lo
        self.offsets = [Vector() for _ in range(resolution**3)]
        support = [0.0] * len(self.offsets)
        sums = [Vector() for _ in self.offsets]
        region_counts = Counter(label for _,_,label in anchors)
        for point, delta, label in anchors:
            for index, weight in self.weights(point):
                weight /= region_counts[label]
                support[index] += weight
                sums[index] += delta*weight
        data = [total/weight if weight else Vector() for total,weight in zip(sums,support)]
        mean_support = max(sum(support)/len(support), 1e-12)
        self.offsets = [v.copy() for v in data]
        grid_neighbors = []
        n = self.n
        for z in range(n):
            for y in range(n):
                for x in range(n):
                    grid_neighbors.append([xx+n*yy+n*n*zz for xx,yy,zz in
                        ((x-1,y,z),(x+1,y,z),(x,y-1,z),(x,y+1,z),(x,y,z-1),(x,y,z+1))
                        if 0<=xx<n and 0<=yy<n and 0<=zz<n])
        for _ in range(40):
            updated = []
            for i, adjacent in enumerate(grid_neighbors):
                smooth = sum((self.offsets[j] for j in adjacent),Vector())/len(adjacent)
                fidelity = min(support[i]/mean_support,3)
                updated.append((data[i]*fidelity+smooth*0.5)/(fidelity+0.5))
            self.offsets = updated
        self.offsets = [v*strength for v in self.offsets]

    def weights(self, point):
        n = self.n
        cells, fractions = [], []
        for axis in range(3):
            u = (point[axis]-self.lo[axis])/self.extent[axis] if self.extent[axis]>1e-9 else 0.5
            q = min(max(u,0),1)*(n-1)
            cell = min(int(q),n-2)
            cells.append(cell)
            fractions.append(q-cell)
        result=[]
        for z in (0,1):
            for y in (0,1):
                for x in (0,1):
                    weight=1.0
                    for axis,bit in enumerate((x,y,z)):
                        weight *= fractions[axis] if bit else 1-fractions[axis]
                    index=(cells[0]+x)+n*(cells[1]+y)+n*n*(cells[2]+z)
                    result.append((index,weight))
        return result

    def warp(self, point):
        return point + sum((self.offsets[i]*w for i,w in self.weights(point)),Vector())

    def make_object(self, target, collection):
        from mathutils import Matrix
        data = bpy.data.lattices.new('EK_边界约束晶格')
        data.points_u=data.points_v=data.points_w=self.n
        data.interpolation_type_u=data.interpolation_type_v=data.interpolation_type_w='KEY_LINEAR'
        lattice=bpy.data.objects.new('EK_整体边界贴合晶格',data)
        collection.objects.link(lattice)
        # Blender's rest lattice has unit-spaced controls: four points span
        # [-1.5, 1.5], not [-0.5, 0.5]. Match the computed cage envelope.
        scale=Vector(tuple(max(v,1e-6)/(self.n-1) for v in self.extent))
        lattice.matrix_world=target.matrix_world @ Matrix.Translation((self.lo+self.hi)/2) @ Matrix.Diagonal((*scale,1))
        for point,offset in zip(data.points,self.offsets):
            point.co_deform=point.co + Vector(tuple(offset[a]/scale[a] for a in range(3)))
        lattice[A.TAG]=True
        lattice['ek_boundary_lattice']=True
        lattice.display_type='WIRE'
        lattice.hide_set(True)
        return lattice


def region_edge_vertices(ob, labels, allowed):
    edges=defaultdict(list)
    for poly,label in zip(ob.data.polygons,labels):
        if label not in allowed:
            continue
        indices=list(poly.vertices)
        for a,b in zip(indices,indices[1:]+indices[:1]):
            edges[tuple(sorted((a,b)))].append(label)
    result=defaultdict(set)
    for (a,b), owners in edges.items():
        if len(owners)==1 or len(set(owners))>1:
            for label in owners:
                result[label].update((a,b))
    # Closed islands have no open contour: use distributed surface vertices.
    for poly,label in zip(ob.data.polygons,labels):
        if label in allowed and label not in result:
            result[label]=set()
    for label in allowed:
        if not result[label]:
            result[label]={v for p,l in zip(ob.data.polygons,labels) if l==label for v in p.vertices}
    return result


def mesh_regions(ob):
    """Use actual polygon materials; material-slot order is never a region ID."""
    A.check_mesh(ob)
    explicit = json.loads(ob.get('ek_standard_slot_labels', '{}'))
    slots = {}
    for i, slot in enumerate(ob.material_slots):
        name=slot.material.name if slot.material else ''
        # Current visible marker materials win over a saved slot-index map.
        # Reordering/replacing slots must not silently change the meaning of
        # the faces the artist sees in the viewport.
        label=C.material_region(name)
        if label is None:label = explicit.get(str(i))
        if label is not None:
            slots[i] = C.canonical_region(label)
    if ob.mode=='EDIT':
        import bmesh
        return [slots.get(face.material_index,-1) for face in bmesh.from_edit_mesh(ob.data).faces]
    indices=np.empty(len(ob.data.polygons),dtype=np.int32)
    ob.data.polygons.foreach_get('material_index',indices)
    return [slots.get(int(index),-1) for index in indices]


def memberships(ob, labels):
    result = [set() for _ in ob.data.vertices]
    for poly, label in zip(ob.data.polygons, labels):
        for v in poly.vertices:
            result[v].add(label)
    return result


class ProjectedSurfaceDepth:
    """Sample the target lash surface in X/Z without collapsing its outline."""
    def __init__(self,points,triangles):
        from mathutils.bvhtree import BVHTree
        self.points=points;self.triangles=triangles
        self.tree=BVHTree.FromPolygons([Vector((p.x,0,p.z)) for p in points],triangles,all_triangles=True)

    def warp(self,point):
        hit,normal,index,distance=self.tree.find_nearest(Vector((point.x,0,point.z)))
        if hit is None:return point.copy()
        a,b,c=[self.points[i] for i in self.triangles[index]]
        bx,bz=b.x-a.x,b.z-a.z;cx,cz=c.x-a.x,c.z-a.z
        px,pz=hit.x-a.x,hit.z-a.z;det=bx*cz-bz*cx
        if abs(det)<1e-16:return point.copy()
        u=(px*cz-pz*cx)/det;v=(bx*pz-bz*px)/det
        return Vector((point.x,(1-u-v)*a.y+u*b.y+v*c.y,point.z))


def fit_source(source, partitioned_target, alignment=None,
               lattice_resolution=4, lattice_strength=0.75, guides=None, detect_only=False,guide_role=None):
    """New, decoupled working mesh in target space; originals remain untouched.

    A global affine envelope and a boundary-constrained lattice establish the
    target proportions. Per-region projection adapts the rest surface. Key
    deltas follow the nonlinear lattice; projection changes only the rest pose.
    """
    from mathutils.bvhtree import BVHTree
    A.check_mesh(source)
    A.check_mesh(partitioned_target)
    if guides is None and not detect_only:
        checkpoint=G.find(source,partitioned_target)
        if checkpoint:guides=G.checkpoint(checkpoint,source,partitioned_target,alignment)
    if source == partitioned_target:
        raise ValueError('源与目标必须是不同网格')
    if not 2 <= lattice_resolution <= 8 or not 0 <= lattice_strength <= 1:
        raise ValueError('晶格分辨率须为 2 至 8，贴合强度须为 0 至 1')
    keys = source.data.shape_keys
    if not keys or len(keys.key_blocks) < 2:
        raise ValueError('源模型需要包含基型及表情形态键')
    if not keys.use_relative:
        raise ValueError('当前分区迁移支持相对形态键')
    source_labels, target_labels = mesh_regions(source), mesh_regions(partitioned_target)
    common = {v for v in source_labels if v >= 0} & {v for v in target_labels if v >= 0}
    if not common:
        raise ValueError('源与目标没有同名面部分区，请先完成材质分区')
    # This reads the completed target as an annotation, not a geometry destination.
    target_mesh = partitioned_target.data
    target_points = [v.co.copy() for v in (target_mesh.shape_keys.reference_key.data
                     if target_mesh.shape_keys else target_mesh.vertices)]
    to_target = partitioned_target.matrix_world.inverted() @ (alignment or source.matrix_world)
    source_points = [to_target @ v.co for v in keys.reference_key.data]
    source_vertices = sorted({v for p, label in zip(source.data.polygons, source_labels)
                              if label in common for v in p.vertices})
    target_vertices = sorted({v for p, label in zip(target_mesh.polygons, target_labels)
                              if label in common for v in p.vertices})
    def bounds(points, indices):
        lo = Vector(tuple(min(points[i][axis] for i in indices) for axis in range(3)))
        hi = Vector(tuple(max(points[i][axis] for i in indices) for axis in range(3)))
        return lo, hi
    # Oral depth or a protruding tongue must not determine the whole face scale.
    body_labels=common-O.ORAL_REGIONS
    src_body=sorted({v for p,l in zip(source.data.polygons,source_labels)
                     if l in body_labels for v in p.vertices})
    dst_body=sorted({v for p,l in zip(target_mesh.polygons,target_labels)
                     if l in body_labels for v in p.vertices})
    src_lo, src_hi = bounds(source_points, src_body or source_vertices)
    dst_lo, dst_hi = bounds(target_points, dst_body or target_vertices)
    gains = Vector(tuple((dst_hi[a]-dst_lo[a])/(src_hi[a]-src_lo[a])
                         if src_hi[a]-src_lo[a] > 1e-9 else 1 for a in range(3)))
    center_src, center_dst = (src_lo+src_hi)/2, (dst_lo+dst_hi)/2
    def scaled(delta):
        return Vector(tuple(delta[a]*gains[a] for a in range(3)))
    def placed(co):
        return center_dst + scaled(co-center_src)
    from mathutils.kdtree import KDTree
    src_edges=region_edge_vertices(source,source_labels,common)
    dst_edges=region_edge_vertices(partitioned_target,target_labels,common)
    for label in common & O.EYE_REGIONS:
        # Use the projected overall envelope even when every lash is a separate
        # island. An internal tessellation edge must never become a fit anchor.
        src_all=sorted({v for p,l in zip(source.data.polygons,source_labels) if l==label for v in p.vertices})
        dst_all=sorted({v for p,l in zip(target_mesh.polygons,target_labels) if l==label for v in p.vertices})
        src_hull=set(O.hull([placed(source_points[v]) for v in src_all]))
        dst_hull=set(O.hull([target_points[v] for v in dst_all]))
        src_edges[label]={v for v in src_all if (float(placed(source_points[v]).x),float(placed(source_points[v]).z)) in src_hull}
        dst_edges[label]={v for v in dst_all if (float(target_points[v].x),float(target_points[v].z)) in dst_hull}
    anchors=[]
    for label in sorted(common):
        if label in O.ORAL_REGIONS:
            continue  # Oral components use their opening's affine transform.
        indices=sorted(dst_edges[label])
        tree=KDTree(len(indices))
        for index in indices:
            tree.insert(target_points[index],index)
        tree.balance()
        samples=sorted(src_edges[label])
        stride=max(1,len(samples)//128)
        for index in samples[::stride]:
            point=placed(source_points[index])
            hit,_,distance=tree.find(point)
            delta=hit-point
            cap=(dst_hi-dst_lo).length*0.2
            if distance>cap and distance>1e-9:
                delta*=cap/distance
            anchors.append((point,delta,label))
    lattice=BoundaryLattice(dst_lo,dst_hi,anchors,lattice_resolution,lattice_strength)
    prefit=[placed(p) for p in source_points]
    warped=[lattice.warp(p) for p in prefit]
    source_members=memberships(source,source_labels)
    target_members=memberships(partitioned_target,target_labels)
    source_plane=(min(p.x for p in warped)+max(p.x for p in warped))/2
    target_plane=(min(target_points[i].x for i in target_vertices)+max(target_points[i].x for i in target_vertices))/2
    eye_warps={}
    contour_frames={}
    brow_splits={}
    source_eye_parts=[0]*len(source_points)
    target_eye_parts=[0]*len(target_points)
    source_lash_polys=[list(p.vertices) for p,l in zip(source.data.polygons,source_labels) if l==2]
    target_lash_polys=[list(p.vertices) for p,l in zip(target_mesh.polygons,target_labels) if l==2]
    for label in sorted(common & O.EYE_REGIONS):
        for side in (-1,1):
            src=[p for i,p in enumerate(warped) if label in source_members[i] and (1 if p.x>=source_plane else -1)==side]
            dst=[p for i,p in enumerate(target_points) if label in target_members[i] and (1 if p.x>=target_plane else -1)==side]
            parts=[(0,src,dst)]
            if label==2:
                src_eye=[p for i,p in enumerate(warped) if 3 in source_members[i] and (1 if p.x>=source_plane else -1)==side]
                dst_eye=[p for i,p in enumerate(target_points) if 3 in target_members[i] and (1 if p.x>=target_plane else -1)==side]
                src_split=O.brow_lash_split(src,src_eye)
                dst_split=O.brow_lash_split(dst,dst_eye)
                if src_split is not None and dst_split is not None:
                    brow_splits[str(side)]=dst_split
                    src_parts=O.brow_lash_parts(warped,source_lash_polys,src_split,source_plane,side)
                    dst_parts=O.brow_lash_parts(target_points,target_lash_polys,dst_split,target_plane,side)
                    for i,part in src_parts.items():source_eye_parts[i]=part
                    for i,part in dst_parts.items():target_eye_parts[i]=part
                    parts=[(part,[warped[i] for i,p in src_parts.items() if p==part],
                                 [target_points[i] for i,p in dst_parts.items() if p==part]) for part in (1,2)]
            for part,src,dst in parts:
                if len(src)<3 or len(dst)<3:
                    continue
                try:
                    eye_warps[(label,side,part)]=O.OutlineWarp(src,dst)
                    contour_frames['%d:%d:%d'%(label,side,part)] = dict(
                        source_outline=len(eye_warps[(label,side,part)].source.outline),
                        target_outline=len(eye_warps[(label,side,part)].target.outline))
                except ValueError:
                    pass
    source_polygons=[list(p.vertices) for p in source.data.polygons]
    target_polygons=[list(p.vertices) for p in target_mesh.polygons]
    # Small Face strips above the aperture are accessory eyelid lines. They
    # follow lashes with a retained offset; never project onto brows/skin.
    eyelid_followers={}
    face_polygons=[p for p,l in zip(source_polygons,source_labels) if l==0]
    _,face_components=C.topology(face_polygons)
    for component in face_components:
        indices={i for f in component['faces'] for i in face_polygons[f]}
        cloud=[warped[i] for i in indices]
        centroid=sum(cloud,Vector())/len(cloud)
        side=1 if centroid.x>=source_plane else -1
        eye=[p for i,p in enumerate(warped) if 3 in source_members[i] and
             (1 if p.x>=source_plane else -1)==side]
        if len(eye)<3 or (2,side,1) not in eye_warps:continue
        frame=O.OutlineFrame(eye)
        width=max(p.x for p in cloud)-min(p.x for p in cloud)
        height=max(p.z for p in cloud)-min(p.z for p in cloud)
        if (width<=frame.width*1.4 and height<=frame.height*.5 and
            abs(centroid.x-frame.center.x)<frame.width*.8 and
            frame.center.z+frame.height*.2<centroid.z<frame.center.z+frame.height*1.1):
            for i in indices:eyelid_followers[i]=side
    source_holes=O.face_openings(source_polygons,source_labels,prefit)
    target_holes=O.face_openings(target_polygons,target_labels,target_points)
    # Locate the lip opening from the mouth body, never a tongue-out silhouette.
    oral_source=[p for i,p in enumerate(prefit) if 8 in source_members[i]]
    oral_target=[p for i,p in enumerate(target_points) if 8 in target_members[i]]
    if not oral_source:
        oral_source=[p for i,p in enumerate(prefit) if 9 in source_members[i]]
    if not oral_target:
        oral_target=[p for i,p in enumerate(target_points) if 9 in target_members[i]]
    source_mouth_hole=O.pick_opening(source_holes,oral_source,dst_hi.x-dst_lo.x,mouth=True)
    target_mouth_hole=O.pick_opening(target_holes,oral_target,dst_hi.x-dst_lo.x,mouth=True)
    source_mouth_reference=G.adjust_ring(source_mouth_hole,'SOURCE','LIP',0,guides) if source_mouth_hole else None
    target_mouth_reference=G.adjust_ring(target_mouth_hole,'TARGET','LIP',0,guides) if target_mouth_hole else None
    mouth_warp=None
    face_hole_warps=[]
    lip_controls={}
    target_lip_controls=[]
    if common & O.ORAL_REGIONS:
        if source_mouth_hole is None or target_mouth_hole is None:
            raise ValueError('无法识别源或目标的口部边界环；请检查 Face 与 Mouth 分区。闭口环可用，但不能用口腔包围盒代替口洞')
        original_hole=[center_src+Vector(tuple((p[a]-center_dst[a])/gains[a]
                         if abs(gains[a])>1e-9 else 0 for a in range(3)))
                       for p in source_mouth_reference]
        mouth_warp=O.MouthOpeningTransform(original_hole,target_mouth_reference,
            src_hi.x-src_lo.x,dst_hi.x-dst_lo.x)
        after_lattice=[lattice.warp(p) for p in source_mouth_hole]
        face_hole_warps.append(O.MouthOpeningTransform(after_lattice,target_mouth_reference,
            dst_hi.x-dst_lo.x,dst_hi.x-dst_lo.x))
        src_ring,dst_ring=O.LipRing(source_mouth_reference),O.LipRing(target_mouth_reference)
        src_indices={id(p):i for i,p in enumerate(prefit)}
        dst_indices={id(p):i for i,p in enumerate(target_points)}
        for i,p in enumerate(source_mouth_hole):
            u,upper=src_ring.parameter(i)
            lip_controls[src_indices[id(p)]]=(u,upper,dst_ring.sample(u,upper))
        for i,p in enumerate(target_mouth_hole):
            u,upper=dst_ring.parameter(i)
            target_lip_controls.append((dst_indices[id(p)],u,upper))
    # Face eye openings follow the same overall outlines, without matching loops
    # vertex by vertex or assuming lashes share the skin's connectivity.
    eye_apertures={}
    ocular_frames={}
    lash_outlines={}
    lash_depths={}
    lash_outline_reports={}
    eye_controls={}
    eye_followers={}
    target_eye_controls=[]
    source_eye_rings={};target_eye_rings={}
    src_indices={id(p):i for i,p in enumerate(prefit)}
    dst_indices={id(p):i for i,p in enumerate(target_points)}
    target_mesh.calc_loop_triangles()
    for side in (-1,1):
        src=[p for i,p in enumerate(prefit) if 3 in source_members[i] and (1 if p.x>=source_plane else -1)==side]
        dst=[p for i,p in enumerate(target_points) if 3 in target_members[i] and (1 if p.x>=target_plane else -1)==side]
        if len(src)<3 or len(dst)<3:
            continue
        a=O.pick_opening(source_holes,src,dst_hi.x-dst_lo.x)
        b=O.pick_opening(target_holes,dst,dst_hi.x-dst_lo.x)
        if a and b:
            source_eye_rings[side]=O.EyeRing(a);target_eye_rings[side]=O.EyeRing(b)
            a_reference=G.adjust_ring(a,'SOURCE','EYE',side,guides)
            b_reference=G.adjust_ring(b,'TARGET','EYE',side,guides)
            original=[center_src+Vector(tuple((p[axis]-center_dst[axis])/gains[axis]
                if abs(gains[axis])>1e-9 else 0 for axis in range(3))) for p in a_reference]
            aperture=O.EyeApertureWarp(original,b_reference)
            eye_apertures[side]=aperture
            ocular_frames[side]=O.EyeFrameTransform(aperture)
            source_lashes=[source_points[i] for i,part in enumerate(source_eye_parts)
                if part==1 and (1 if prefit[i].x>=source_plane else -1)==side]
            target_lashes=[target_points[i] for i,part in enumerate(target_eye_parts)
                if part==1 and (1 if target_points[i].x>=target_plane else -1)==side]
            target_branches={i:aperture.target.locate(target_points[i])[1] for i,part in enumerate(target_eye_parts)
                if part==1 and (1 if target_points[i].x>=target_plane else -1)==side}
            for upper in (True,False):
                src_cloud=[p for p in source_lashes if aperture.source.locate(p)[1]==upper]
                dst_cloud=[p for p in target_lashes if aperture.target.locate(p)[1]==upper]
                try:
                    contour=O.OutlineWarp(src_cloud,dst_cloud)
                except ValueError:
                    continue
                lash_outlines[side,upper]=contour
                depth_triangles=[tuple(tri.vertices) for tri in target_mesh.loop_triangles
                    if target_labels[tri.polygon_index]==2 and
                    all(v in target_branches for v in tri.vertices) and
                    sum(target_branches[v]==upper for v in tri.vertices)>=2]
                if depth_triangles:
                    lash_depths[side,upper]=ProjectedSurfaceDepth(target_points,depth_triangles)
                lash_outline_reports['%d:%s'%(side,'upper' if upper else 'lower')]=dict(
                    source_vertices=len(src_cloud),target_vertices=len(dst_cloud),
                    target_bounds=[[min(p[a] for p in dst_cloud),max(p[a] for p in dst_cloud)] for a in range(3)])
            for j,p in enumerate(a):
                index=src_indices[id(p)];u,upper=aperture.source.parameter(j)
                eye_controls[index]=(side,u,upper,aperture.target.sample(u,upper))
            for j,p in enumerate(b):
                u,upper=aperture.target.parameter(j)
                target_eye_controls.append((dst_indices[id(p)],side,u,upper))
            for i,p in enumerate(source_points):
                follows=(2 in source_members[i] and source_eye_parts[i]==1) or i in eyelid_followers
                if follows and (1 if prefit[i].x>=source_plane else -1)==side:
                    u,upper=aperture.source.locate(p)
                    hit=aperture.warp(p,u,upper)
                    contour=lash_outlines.get((side,True if i in eyelid_followers else upper))
                    if contour:
                        if i in eyelid_followers:
                            hit=contour.follow_outline(p)
                        else:
                            # Fit the actual upper/lower lash envelope instead
                            # of keeping the old model's gap above the eye.
                            # Both transforms join at the canthus to avoid a
                            # split through a connected lash corner.
                            t=min(min(u,1-u)/.06,1);t=t*t*(3-2*t)
                            hit=hit+(contour.warp(p)-hit)*t
                            depth=lash_depths.get((side,upper))
                            if depth:hit.y+=(depth.warp(hit).y-hit.y)*t
                    eye_followers[i]=(side,u,upper,hit)
            # The skin around the rim still follows a continuous local warp.
            face_hole_warps.append(O.OutlineWarp([lattice.warp(p) for p in a],b_reference))
    source_guide_parts=list(source_eye_parts)
    for i in eyelid_followers:source_guide_parts[i]=2
    entries,lash_units=G.detection_entries(prefit,target_points,source_polygons,target_polygons,
        source_guide_parts,target_eye_parts,source_plane,target_plane,source_eye_rings,target_eye_rings,
        source_mouth_hole,target_mouth_hole,None,source_labels,target_labels)
    if detect_only:
        from mathutils import Matrix
        affine=Matrix.Diagonal((*gains,1.0));affine.translation=center_dst-scaled(center_src)
        if guide_role:entries=[entry for entry in entries if entry['role']==guide_role]
        return G.capture(source,partitioned_target,alignment,entries,affine@to_target)
    source_lash_units=G.units(guides,'SOURCE',lash_units['SOURCE'],prefit,source_eye_rings)
    target_lash_units=G.units(guides,'TARGET',lash_units['TARGET'],target_points,target_eye_rings)
    source_strands={i for unit in source_lash_units for i in unit['vertices'] if i not in unit.get('band_vertices',[])}
    target_strands={i for unit in target_lash_units for i in unit['vertices'] if i not in unit.get('band_vertices',[])}
    band_hits={};band_frames={}
    for side,aperture in eye_apertures.items():
        guide_rows=(guides or {}).get('entries',entries)
        trends={}
        for upper in (True,False):
            src=[i for i,(s,u,branch,hit) in eye_followers.items() if s==side and branch==upper and source_eye_parts[i]==1]
            dst=[i for i,part in enumerate(target_eye_parts) if part==1 and
                 (1 if target_points[i].x>=target_plane else -1)==side and aperture.target.locate(target_points[i])[1]==upper]
            body_src=[source_points[i] for i in src if i not in source_strands]
            body_dst=[target_points[i] for i in dst if i not in target_strands]
            edits={}
            if upper:
                for role in ('SOURCE','TARGET'):
                    line=next((e for e in guide_rows if e['role']==role and e['kind']=='LASH_LINE' and e['side']==side and e.get('enabled',True)),None)
                    if line and 'base' in line:
                        change=np.array([G.sample(line['points'],u)-G.sample(line['base'],u) for u in np.linspace(0,1,33)])
                        edits[role]=change/np.array(gains) if role=='SOURCE' else change
            # The actual eye aperture determines width, height and branch
            # placement. A detected lash strip must not replace that frame.
            trends[upper]=L.CurveSimilarity(aperture.source,aperture.target,body_src,body_dst,upper,
                edits.get('SOURCE'),edits.get('TARGET'))
        coherent_faces=[face for face in source_lash_polys if all(source_eye_parts[i]==1 and
            (1 if prefit[i].x>=source_plane else -1)==side for i in face)]
        _,components=C.topology(coherent_faces)
        for component in components:
            ids={i for f in component['faces'] for i in coherent_faces[f]}
            upper=sum(aperture.source.locate(source_points[i])[1] for i in ids)>=len(ids)/2
            trend=trends[upper]
            for i in ids:band_hits[i]=trend.warp(source_points[i]);band_frames[i]=trend
    # Strand identities drive expression rotation, not separate Basis warps
    # inside a connected card. The whole card shares the band transform.
    accessory_frames={}
    working_entries=(guides or {}).get('entries',entries)
    for source_entry in working_entries:
        if source_entry['role']!='SOURCE' or source_entry['kind'] not in ('BROW','CREASE') or not source_entry.get('enabled',True):continue
        candidates=[e for e in working_entries if e['role']=='TARGET' and e['kind']==source_entry['kind'] and
                    e['side']==source_entry['side'] and e.get('enabled',True)]
        if not candidates:continue
        center=np.mean(source_entry['points'],axis=0)
        destination=min(candidates,key=lambda e:np.linalg.norm(np.mean(e['points'],axis=0)-center))
        frame=L.PolylineSimilarity(source_entry['points'],destination['points'])
        for i in source_entry.get('vertices',[]):accessory_frames[i]=frame
    accessory_edits={}
    accessory_roles={i:e['kind'] for e in entries if e['role']=='SOURCE' and e['kind'] in ('CREASE','BROW')
                     for i in e['vertices']}
    for entry in (guides or {}).get('entries',[]):
        if not entry.get('enabled',True) or entry['kind'] not in ('CREASE','BROW'):continue
        if entry['role']=='SOURCE':
            for index in entry['vertices']:
                nearest=min(range(33),key=lambda k:(G.sample(entry['base'],k/32)-prefit[index]).length_squared)/32
                accessory_edits[index]=G.sample(entry['base'],nearest)-G.sample(entry['points'],nearest)
    def region_warp(label,point,side,part=0,follower=False):
        if label in O.ORAL_REGIONS and mouth_warp:
            return mouth_warp.warp(point,shape=False)  # Only translation/rotation/scale.
        value=lattice.warp(point)
        if follower:
            return eye_warps[(2,side,1)].follow_outline(value)
        if label in O.EYE_REGIONS:
            contour=eye_warps.get((label,side,part))
            if contour:
                return contour.warp(value)
        if label==0:
            for contour in face_hole_warps:
                value=contour.local_face_warp(value)
        return value
    target_mesh.calc_loop_triangles()
    triangles = defaultdict(list)
    for tri in target_mesh.loop_triangles:
        label = target_labels[tri.polygon_index]
        if label in common:
            triangles[label].append(tuple(tri.vertices))
    trees = {label: BVHTree.FromPolygons(target_points, rows, all_triangles=True)
             for label, rows in triangles.items()}
    lookup, pairs, fitted_points, faces, old_faces, vertex_sides = {}, [], [], [], [], []
    for poly, label in zip(source.data.polygons, source_labels):
        if label not in trees:
            continue
        face = []
        for index in poly.vertices:
            token = (label, index)
            if token not in lookup:
                side=1 if warped[index].x>=source_plane else -1
                guess = region_warp(label,source_points[index] if label in O.ORAL_REGIONS
                                    else prefit[index],side,source_eye_parts[index] if label==2 else 0,
                                    label==0 and index in eyelid_followers)
                if label in (0,2) and index in accessory_frames:
                    hit=accessory_frames[index].warp(prefit[index])
                elif label==2 and index in band_hits:
                    hit=band_hits[index]
                elif label==0 and index in lip_controls:
                    hit=lip_controls[index][2]
                elif label==0 and index in eye_controls:
                    hit=eye_controls[index][3]
                elif (label==2 or label==0) and index in eye_followers:
                    hit=band_hits.get(index,eye_followers[index][3]) if label==2 else eye_followers[index][3]
                elif label in O.OCULAR_REGIONS and side in ocular_frames:
                    hit=ocular_frames[side].warp(source_points[index])
                elif label in O.EYE_REGIONS or label in O.ORAL_REGIONS or (label==0 and index in eyelid_followers):
                    hit=guess  # Keep coherent pieces; do not collapse vertices onto planes.
                else:
                    hit, _, _, _ = trees[label].find_nearest(guess)
                if hit is None:
                    raise ValueError('分区没有可贴合的有效表面：' + C.REGION_NAMES[label])
                if label in (0,2) and index in accessory_edits and index not in accessory_frames:hit=hit+accessory_edits[index]
                if label in (0,2) and index in accessory_roles and guides and index not in accessory_frames:
                    candidates=[e for e in guides['entries'] if e['role']=='TARGET' and e['kind']==accessory_roles[index]
                        and e['side']==side and e.get('enabled',True)]
                    if candidates:
                        _,entry,u=min((((G.sample(e['base'],k/16)-hit).length_squared,e,k/16)
                            for e in candidates for k in range(17)),key=lambda row:row[0])
                        hit=hit+G.sample(entry['points'],u)-G.sample(entry['base'],u)
                lookup[token] = len(pairs)
                pairs.append(token)
                vertex_sides.append(side if label in O.EYE_REGIONS else 0)
                fitted_points.append(hit)
            face.append(lookup[token])
        faces.append(face)
        old_faces.append(poly)
    # Smooth the Face displacement itself before baking Basis. This prevents
    # adjacent lip vertices jumping between opposite nearest target surfaces.
    rest=np.array([prefit[index] for label,index in pairs])
    skin_pins={i for i,(label,index) in enumerate(pairs) if label==0 and
               (index in lip_controls or index in eye_controls or index in accessory_frames)}
    skin_ids={i for i,(label,index) in enumerate(pairs) if label==0}
    rest_field=SkinDisplacementField(rest,faces,[source_labels[p.index] for p in old_faces],skin_ids,skin_pins,fidelity=.25)
    rest_delta=rest_field.solve(np.array(fitted_points)-rest)
    fitted_points=[Vector(p) for p in rest+rest_delta]
    mesh = bpy.data.meshes.new(source.name + '_EK_fitted_mesh')
    mesh.from_pydata(fitted_points, [], faces)
    for slot in source.material_slots:
        mesh.materials.append(slot.material)
    for new, old in zip(mesh.polygons, old_faces):
        new.material_index, new.use_smooth = old.material_index, old.use_smooth
    for layer in source.data.uv_layers:
        dst = mesh.uv_layers.new(name=layer.name)
        for new, old in zip(mesh.polygons, old_faces):
            for nl, ol in zip(new.loop_indices, old.loop_indices):
                dst.data[nl].uv = layer.data[ol].uv
    fitted = bpy.data.objects.new(source.name + '_EK_fitted', mesh)
    collection=A.result_collection('SOURCE')
    collection.objects.link(fitted)
    fitted.matrix_world = partitioned_target.matrix_world.copy()
    fitted[A.TAG] = True
    fitted['ek_fitted_source'] = source.name
    fitted['ek_fitted_target'] = partitioned_target.name
    fitted['ek_vertex_regions'] = json.dumps([label for label, index in pairs])
    fitted['ek_vertex_sides'] = json.dumps(vertex_sides)
    fitted['ek_target_eye_plane'] = target_plane
    fitted['ek_vertex_eye_parts']=json.dumps([source_eye_parts[index] if label==2 else 0 for label,index in pairs])
    fitted['ek_target_brow_splits']=json.dumps(brow_splits)
    fitted['ek_target_eye_parts']=json.dumps(target_eye_parts)
    fitted['ek_brow_fit_version']=2
    fitted['ek_lash_fit_version']=5
    fitted['ek_upper_lash_band']=json.dumps([i for i,(label,index) in enumerate(pairs)
        if label==2 and index in band_hits])
    fitted['ek_lip_fit_version']=3
    fitted['ek_lip_controls']=json.dumps([(i,*lip_controls[index][:2]) for i,(label,index) in enumerate(pairs)
                                          if label==0 and index in lip_controls])
    fitted['ek_target_lip_controls']=json.dumps(target_lip_controls)
    fitted['ek_eye_fit_version']=2
    fitted['ek_eye_rim_controls']=json.dumps([(i,*eye_controls[index][:3]) for i,(label,index) in enumerate(pairs)
        if label==0 and index in eye_controls])
    fitted['ek_eye_lash_controls']=json.dumps([(i,*eye_followers[index][:3]) for i,(label,index) in enumerate(pairs)
        if label==2 and index in eye_followers])
    fitted['ek_target_eye_controls']=json.dumps(target_eye_controls)
    fitted['ek_eye_outline_parts'] = json.dumps(contour_frames)
    fitted['ek_source_vertices'] = json.dumps([index for label, index in pairs])
    remapped_lashes=[]
    for unit in source_lash_units:
        row=dict(unit)
        for group in ('vertices','roots','tips','band_vertices'):
            row[group]=[lookup[2,i] for i in unit.get(group,[]) if (2,i) in lookup]
        if not all(row[g] for g in ('vertices','roots','tips')):continue
        row['points']=[np.mean([fitted_points[i] for i in row[g]],axis=0).tolist() for g in ('roots','tips')]
        remapped_lashes.append(row)
    fitted['ek_source_lash_units']=json.dumps(remapped_lashes)
    fitted['ek_target_lash_units']=json.dumps(target_lash_units)
    if guides:
        fitted['ek_guides_snapshot']=G.dumps(guides)
        fitted['ek_guides_alignment']=G.dumps([list(r) for r in (alignment if alignment is not None else source.matrix_world)])
    fitted['ek_source_faces'] = json.dumps([p.index for p in old_faces])
    fitted['ek_fit_gains'] = json.dumps(list(gains))
    fitted['ek_mouth_fit_version'] = 2
    linear = to_target.to_3x3()
    copied = {}
    for key in keys.key_blocks:
        new = fitted.shape_key_add(name=key.name, from_mix=False)
        for i, (label, index) in enumerate(pairs):
            base=source_points[index] if label in O.ORAL_REGIONS else placed(source_points[index])
            raw=linear @ (key.data[index].co - keys.reference_key.data[index].co)
            if label not in O.ORAL_REGIONS:
                raw=scaled(raw)
            side=1 if warped[index].x>=source_plane else -1
            part=source_eye_parts[index] if label==2 else 0
            if raw.length_squared<1e-20:
                delta=Vector()
            elif label in (0,2) and index in accessory_frames:
                delta=accessory_frames[index].delta(raw)
            elif label==0 and index in lip_controls and mouth_warp:
                oral_base=source_points[index]
                oral_raw=linear @ (key.data[index].co - keys.reference_key.data[index].co)
                delta=mouth_warp.warp(oral_base+oral_raw)-mouth_warp.warp(oral_base)
            elif label==2 and index in band_frames:
                delta=band_frames[index].delta(linear@(key.data[index].co-keys.reference_key.data[index].co))
            elif (label==0 and index in eye_controls) or ((label==0 or label==2) and index in eye_followers):
                side,u,upper,hit=eye_controls[index] if label==0 and index in eye_controls else eye_followers[index]
                eye_raw=linear @ (key.data[index].co-keys.reference_key.data[index].co)
                delta=eye_apertures[side].delta(eye_raw,u)
            elif label in O.OCULAR_REGIONS and side in ocular_frames:
                delta=ocular_frames[side].delta(linear @ (key.data[index].co-keys.reference_key.data[index].co))
            else:
                follower=label==0 and index in eyelid_followers
                delta = region_warp(label,base+raw,side,part,follower)-region_warp(label,base,side,part,follower)
            new.data[i].co = fitted_points[i] + delta
        new.slider_min, new.slider_max = key.slider_min, key.slider_max
        copied[key.name] = new
    for key in keys.key_blocks:
        copied[key.name].relative_key = copied[key.relative_key.name]
    fitted.data.shape_keys.use_relative = keys.use_relative
    fitted.display_type = 'TEXTURED'
    fitted.show_wire = False
    fitted.show_in_front = False
    cage=lattice.make_object(partitioned_target,collection)
    fitted['ek_fit_lattice']=cage.name
    bpy.context.view_layer.update()
    report = dict(regions={C.REGION_NAMES[label]: dict(
        source_faces=source_labels.count(label), target_faces=target_labels.count(label))
        for label in sorted(common)}, gains=list(gains),
        vertices=len(pairs), keys=len(keys.key_blocks), method='boundary_lattice_then_region_surface_fit',
        lattice_controls=lattice_resolution**3,boundary_samples=len(anchors),
        lattice_strength=lattice_strength,max_cage_displacement=max(v.length for v in lattice.offsets),
        eye_method='overall_outline_per_side_no_surface_projection',eye_outline_parts=contour_frames,
        brow_lash_method='separate_eye_guided_envelopes',brow_lash_split_sides=sorted(brow_splits),
        eyelid_line_method='follow_lashes_preserve_offset_no_projection',eyelid_line_vertices=len(eyelid_followers),
        eye_rim_method='independent_upper_lower_aperture_curves',eye_rim_controls=len(eye_controls),
        ocular_method='iris_and_highlight_share_aperture_frame',
        ocular_gains={str(side):list(frame.gains) for side,frame in ocular_frames.items()},
        lash_fit_method='independent_upper_lower_target_lash_envelopes',lash_outline_parts=lash_outline_reports,
        lip_method='continuous_upper_lower_ring_interpolation',lip_controls=len(lip_controls),
        mouth_method='topology_ring_uniform_srt_no_height_division' if mouth_warp else 'unavailable',
        mouth_scale=mouth_warp.scale if mouth_warp else None,
        source_mouth_hole=bool(source_mouth_hole),target_mouth_hole=bool(target_mouth_hole),
        mouth_locator='oral_region_assisted_face_boundary_ring',
        mouth_contact_vertices={role:next((row['contact_vertices'] for row in holes
            if row['points'] is picked),0) for role,holes,picked in (
                ('source',source_holes,source_mouth_hole),('target',target_holes,target_mouth_hole))},
        face_opening_controls=len(face_hole_warps))
    report['individual_upper_lashes']={'source':len(remapped_lashes),'target':len(target_lash_units)}
    report['upper_lash_band_method']='aperture_anchored_upper_lower_component_similarity'
    report['upper_lash_band_vertices']=len(json.loads(fitted['ek_upper_lash_band']))
    report['guide_revision']=(guides or {}).get('revision')
    fitted['ek_fit_report'] = json.dumps(report, ensure_ascii=False)
    return fitted, report


def build_vertex_mapping(fitted, partitioned_target, neighbors=1,
                         max_distance_fraction=0.08, freeze_outside_boundary=True):
    """Nearest vertices/RBF strictly inside the same semantic region."""
    from mathutils.kdtree import KDTree
    A.check_mesh(fitted)
    A.check_mesh(partitioned_target)
    labels = json.loads(fitted.get('ek_vertex_regions', '[]'))
    if len(labels) != len(fitted.data.vertices) or not fitted.data.shape_keys:
        raise ValueError('请先创建有效的分区贴合源副本')
    if set(labels) & O.ORAL_REGIONS and fitted.get('ek_mouth_fit_version',0)<2:
        raise ValueError('此副本使用旧版口腔变形，请重新创建贴合源副本后再迁移')
    if 2 in labels and fitted.get('ek_brow_fit_version',0)<2:
        raise ValueError('眉睫贴合算法已更新，请重新创建贴合源副本后再迁移')
    if 0 in labels and 3 in labels and fitted.get('ek_eye_fit_version',0)<2:
        raise ValueError('上下眼睑算法已更新，请重新创建贴合源副本后再迁移')
    if 0 in labels and set(labels) & O.ORAL_REGIONS and fitted.get('ek_lip_fit_version',0)<3:
        raise ValueError('嘴唇边界算法已更新，请重新创建贴合源副本后再迁移')
    if neighbors < 1 or max_distance_fraction <= 0:
        raise ValueError('映射邻点数和距离上限必须大于零')
    source_to_target = partitioned_target.matrix_world.inverted() @ fitted.matrix_world
    source_points = [source_to_target @ v.co for v in fitted.data.shape_keys.reference_key.data]
    target_points = [v.co.copy() for v in (partitioned_target.data.shape_keys.reference_key.data
        if partitioned_target.data.shape_keys else partitioned_target.data.vertices)]
    target_labels = mesh_regions(partitioned_target)
    groups = memberships(partitioned_target, target_labels)
    annotated = [i for i, row in enumerate(groups) if any(label >= 0 for label in row)]
    if not annotated:
        raise ValueError('目标没有已确认的面部分区')
    center = sum((target_points[i] for i in annotated), Vector()) / len(annotated)
    diagonal = max((target_points[i]-center).length for i in annotated)*2
    limit = diagonal * max_distance_fraction
    by_region = defaultdict(list)
    sides=json.loads(fitted.get('ek_vertex_sides','[]'))
    if len(sides)!=len(labels):
        sides=[0]*len(labels)
    eye_plane=float(fitted.get('ek_target_eye_plane',0))
    parts=json.loads(fitted.get('ek_vertex_eye_parts','[]'))
    if len(parts)!=len(labels):parts=[0]*len(labels)
    splits=json.loads(fitted.get('ek_target_brow_splits','{}'))
    target_parts=json.loads(fitted.get('ek_target_eye_parts','[]'))
    target_point_indices={id(p):i for i,p in enumerate(target_points)}
    lip_rows=json.loads(fitted.get('ek_lip_controls','[]'))
    target_lips=defaultdict(list)
    target_lip_rows=json.loads(fitted.get('ek_target_lip_controls','[]'))
    for i,u,upper in target_lip_rows:
        target_lips[i].append((u,upper))
    lip_band={}
    lip_ring=None
    if lip_rows and target_lip_rows:
        import heapq
        lip_ring=O.LipRing([target_points[i] for i,u,upper in target_lip_rows])
        radius=lip_ring.frame.width*.3
        adjacency=defaultdict(set)
        for poly,label in zip(partitioned_target.data.polygons,target_labels):
            if label!=0:continue
            vertices=list(poly.vertices)
            for a,b in zip(vertices,vertices[1:]+vertices[:1]):
                adjacency[a].add(b);adjacency[b].add(a)
        queue=[(0.0,i,i) for i in target_lips];heapq.heapify(queue)
        while queue:
            distance,i,seed=heapq.heappop(queue)
            if i in lip_band or distance>radius:continue
            lip_band[i]=(distance,seed)
            for j in adjacency[i]:
                if j not in lip_band:
                    heapq.heappush(queue,(distance+(target_points[i]-target_points[j]).length,j,seed))
    def lip_override(index):
        if index not in lip_band:return [],0
        distance,seed=lip_band[index]
        controls=target_lips[index] if index in target_lips else target_lips[seed]
        combined=defaultdict(float)
        for seed_u,upper in controls:
            u=seed_u if index in target_lips else lip_ring.locate(target_points[index],upper)[0]
            for vertex,weight in O.lip_weights(lip_rows,u,upper):
                combined[vertex]+=weight/len(controls)
        if any((source_points[v]-target_points[index]).length>limit for v in combined):
            return [],0
        return list(combined.items()),(1-distance/(lip_ring.frame.width*.3))**2
    eye_rows=defaultdict(list)
    lash_rows=defaultdict(list)
    target_eyes=defaultdict(list)
    eye_rings={}
    eye_band={}
    for index,side,u,upper in json.loads(fitted.get('ek_eye_rim_controls','[]')):
        for branch in ((True,False) if u<1e-7 or u>1-1e-7 else (upper,)):
            eye_rows[side].append((index,u,branch))
    for index,side,u,upper in json.loads(fitted.get('ek_eye_lash_controls','[]')):
        lash_rows[side].append((index,u,upper))
    target_eye_rows=json.loads(fitted.get('ek_target_eye_controls','[]'))
    for index,side,u,upper in target_eye_rows:
        target_eyes[index].append((side,u,upper))
    if target_eye_rows:
        import heapq
        adjacency=defaultdict(set)
        for poly,label in zip(partitioned_target.data.polygons,target_labels):
            if label!=0:continue
            vertices=list(poly.vertices)
            for a,b in zip(vertices,vertices[1:]+vertices[:1]):
                adjacency[a].add(b);adjacency[b].add(a)
        for side in (-1,1):
            rows=[r for r in target_eye_rows if r[1]==side]
            if not rows:continue
            ring=O.EyeRing([target_points[i] for i,side,u,upper in rows])
            eye_rings[side]=ring
            queue=[(0.0,i,i) for i,side,u,upper in rows];heapq.heapify(queue)
            visited=set()
            while queue:
                distance,i,seed=heapq.heappop(queue)
                if i in visited or distance>ring.frame.width*.35:continue
                visited.add(i)
                if i not in eye_band or distance<eye_band[i][1]:eye_band[i]=(side,distance,seed)
                for j in adjacency[i]:
                    if j not in visited:
                        heapq.heappush(queue,(distance+(target_points[i]-target_points[j]).length,j,seed))
    def eye_override(index,lash=False):
        if lash:
            side=1 if target_points[index].x>=eye_plane else -1
            ring=eye_rings.get(side)
            if ring is None:return [],0
            u,upper=ring.locate(target_points[index])
            rows=O.contour_weights(lash_rows[side],u,upper)
            if rows and min((source_points[v]-target_points[index]).length for v,w in rows)>limit:
                rows=[]
            rim=O.lip_weights(eye_rows[side],u,upper)
            if rim and min((source_points[v]-target_points[index]).length for v,w in rim)>limit:
                rim=[]
            # A model may have no lower-lash fragment at this corner. The
            # aperture is still a valid control; do not fall back to an
            # unrelated nearest upper lash and introduce a discontinuity.
            if not rows:return rim,1.0 if rim else 0
            if not rim:return rows,1.0
            # Lash roots and skin must have the SAME motion. Retain a smooth
            # source-lash contribution at distant tips, fading it out at the
            # root and both canthi to prevent a seam through one lash strip.
            anchor=ring.sample(u,upper);offset=target_points[index]-anchor
            distance=(offset.x*offset.x+offset.z*offset.z)**.5
            t=min(max((distance/ring.frame.width-.05)/.2,0),1)
            t=min(t,min(min(u,1-u)/.12,1));t=t*t*(3-2*t)
            if t<1:
                if rim:
                    combined=defaultdict(float)
                    for v,w in rows:combined[v]+=w*t
                    for v,w in rim:combined[v]+=w*(1-t)
                    rows=list(combined.items())
            return rows,1.0
        if index not in eye_band:return [],0
        side,distance,seed=eye_band[index];ring=eye_rings[side]
        constraints=target_eyes.get(index,target_eyes[seed])
        combined=defaultdict(float)
        for side,seed_u,upper in constraints:
            u=seed_u if index in target_eyes else ring.locate(target_points[index],upper)[0]
            for vertex,weight in O.lip_weights(eye_rows[side],u,upper):
                combined[vertex]+=weight/len(constraints)
        if not combined or min((source_points[v]-target_points[index]).length for v in combined)>limit:
            return [],0
        # Keep the first skin rows attached to their own eyelid, then fade
        # through connected Face edges. Do not jump across the open eye.
        t=min(max((1-distance/(ring.frame.width*.35))/.7,0),1)
        return list(combined.items()),t*t*(3-2*t)
    def target_part(label,side,point):
        if label==2 and len(target_parts)==len(target_points):
            return target_parts[target_point_indices[id(point)]]
        threshold=splits.get(str(side)) if label==2 else None
        return (2 if point.z>=threshold else 1) if threshold is not None else 0
    outline_frames={}
    for label in O.EYE_REGIONS:
        for side in (-1,1):
            cloud=[p for i,p in enumerate(target_points) if label in groups[i] and
                   (1 if p.x>=eye_plane else -1)==side]
            grouped=[(part,[p for p in cloud if target_part(label,side,p)==part])
                     for part in ((1,2) if label==2 and str(side) in splits else (0,))]
            for part,cloud in grouped:
                if len(cloud)<3:continue
                try:
                    outline_frames[(label,side,part)]=O.OutlineFrame(cloud)
                except ValueError:
                    pass
    for i, label in enumerate(labels):
        token=(label,sides[i],parts[i]) if label in O.EYE_REGIONS and sides[i] else (label,0,0)
        by_region[token].append(i)
    trees = {}
    def metric(point,token):
        frame=outline_frames.get(token)
        return frame.normalized(point) if frame else point
    for token, indices in by_region.items():
        tree = KDTree(len(indices))
        for i in indices:
            tree.insert(metric(source_points[i],token), i)
        tree.balance()
        trees[token] = tree
    mapping = {}
    rejected = Counter()
    mapped_regions = Counter()
    constrained_lips=0
    constrained_eyes=0
    continuous_lashes=0
    constrained_shared_outside=0
    for i, row in enumerate(groups):
        semantic = {label for label in row if label >= 0}
        if not semantic:
            rejected['outside_or_uncertain'] += 1
            continue
        # The visible mouth rim is a geometric constraint, including vertices
        # shared with the cavity material. Averaging a nearest cavity sample
        # here can give the upper lip a lower-lip displacement and tear the rim.
        if i in target_lips and 0 in semantic and semantic <= ({0} | O.ORAL_REGIONS):
            lip_weighted,lip_blend=lip_override(i)
            if lip_weighted:
                mapping[i]=sorted(lip_weighted)
                for label in semantic:mapped_regions[label]+=1
                constrained_lips+=1
                constrained_shared_outside+=int(any(label<0 for label in row))
                continue
        if i in target_eyes and 0 in semantic and semantic<={0,2}:
            weighted,blend=eye_override(i)
            if weighted:
                mapping[i]=sorted(weighted)
                for label in semantic:mapped_regions[label]+=1
                constrained_eyes+=1
                constrained_shared_outside+=int(any(label<0 for label in row))
                continue
        if semantic=={2}:
            side=1 if target_points[i].x>=eye_plane else -1
            if target_part(2,side,target_points[i])==1:
                weighted,blend=eye_override(i,lash=True)
                if weighted:
                    mapping[i]=sorted(weighted);mapped_regions[2]+=1;continuous_lashes+=1
                    constrained_shared_outside+=int(any(label<0 for label in row))
                    continue
        # Only a positively identified aperture can override a shared outside
        # edge: freezing isolated vertices ON the lid creates spikes on blink.
        # Other outside boundaries, including the rear head, remain unchanged.
        if freeze_outside_boundary and any(label < 0 for label in row):
            # Shared skin vertices adjacent to an aperture must be allowed to
            # follow its connected displacement field. Pinning one of these
            # while its lip neighbour moves creates a needle-shaped triangle.
            # Pure outside vertices and boundaries distant from apertures stay
            # frozen; material assignments are never changed.
            nearby_skin=0 in semantic and (i in lip_band or i in eye_band)
            if not nearby_skin:
                rejected['outside_boundary'] += 1
                continue
            constrained_shared_outside+=1
        matches = []
        # A shared semantic boundary blends group deltas at the same target
        # vertex, preserving target topology instead of splitting the mesh.
        for label in sorted(semantic):
            lip_weighted,lip_blend=lip_override(i) if label==0 else ([],0)
            if label==0 and not lip_weighted:
                lip_weighted,lip_blend=eye_override(i)
            if label==2:
                side=1 if target_points[i].x>=eye_plane else -1
                if target_part(label,side,target_points[i])==1:
                    weighted,blend=eye_override(i,lash=True)
                    if weighted:
                        matches.append((label,weighted));continuous_lashes+=1
                        continue
            if lip_weighted and lip_blend>=1-1e-8:
                    matches.append((label,lip_weighted))
                    continue
            side=(1 if target_points[i].x>=eye_plane else -1) if label in O.EYE_REGIONS else 0
            token=(label,side,target_part(label,side,target_points[i]))
            tree = trees.get(token)
            if tree is None:
                continue
            found = [r for r in tree.find_n(metric(target_points[i],token), min(neighbors,len(by_region[token])))
                     if (source_points[r[1]]-target_points[i]).length<=limit]
            if not found:
                if lip_weighted:matches.append((label,lip_weighted))
                continue
            exact = [r for r in found if r[2] < max(diagonal*1e-8, 1e-10)]
            if exact:
                weighted = [(r[1], 1/len(exact)) for r in exact]
            else:
                metric_limit=2.0 if token in outline_frames else limit
                raw = [(r[1], exp(-((r[2]/metric_limit)**2)) / max(r[2],1e-9)) for r in found]
                total = sum(w for _, w in raw)
                weighted = [(idx, w/total) for idx, w in raw]
            if lip_weighted:
                combined=defaultdict(float)
                for index,weight in weighted:combined[index]+=weight*(1-lip_blend)
                for index,weight in lip_weighted:combined[index]+=weight*lip_blend
                weighted=list(combined.items())
            matches.append((label, weighted))
        if not matches:
            rejected['missing_region_or_distance'] += 1
            continue
        # Do not silently substitute a different group at a multi-region vertex.
        if len(matches) != len(semantic):
            rejected['incomplete_boundary_regions'] += 1
            continue
        weights = defaultdict(float)
        for label, rows in matches:
            mapped_regions[label] += 1
            for index, weight in rows:
                weights[index] += weight/len(matches)
        mapping[i] = sorted(weights.items())
    return mapping, dict(mapped=len(mapping), total=len(groups), rejected=dict(rejected),
        regions={C.REGION_NAMES.get(k,str(k)):v for k,v in mapped_regions.items()},
        max_distance=limit, neighbors=neighbors, method='region_vertex_distance',
        eye_method='separate_lid_curves_and_continuous_lash_field',
        eye_boundary_constraints=constrained_eyes,continuous_lash_targets=continuous_lashes,
        aperture_shared_outside_constraints=constrained_shared_outside,
        lip_boundary_targets=sum(i in mapping for i in target_lips),
        lip_boundary_constraints=constrained_lips,
        lip_band_targets=sum(i in mapping for i in lip_band))


def transfer_to_copy(fitted, partitioned_target, **options):
    """Bake all relative expressions onto a NEW target, keeping unmapped vertices."""
    direct=options.pop('direct',None)
    snapshot=json.loads(fitted.get('ek_guides_snapshot','{}'))
    if snapshot and direct is None:
        source=bpy.data.objects.get(fitted.get('ek_fitted_source',''))
        collection=G.find(source,partitioned_target) if source else None
        if collection:
            alignment=Matrix(json.loads(fitted['ek_guides_alignment']))
            current=G.confirmed(collection,source,partitioned_target,alignment)
            if current['hash']!=snapshot['hash'] or current['input']!=snapshot['input']:
                raise ValueError('曲线或分区已变化，请重新贴合后再迁移')
    keys = fitted.data.shape_keys
    if not keys or not keys.use_relative:
        raise ValueError('当前分区迁移支持相对形态键')
    mapping, report = (direct.mapping,dict(direct.report)) if direct else build_vertex_mapping(fitted, partitioned_target, **options)
    if not mapping:
        raise ValueError('没有有效的同分区顶点对应，请检查贴合结果或距离上限')
    output = partitioned_target.copy()
    output.data = partitioned_target.data.copy()
    output.name = partitioned_target.name + '_EK_transfer'
    A.result_collection('TARGET').objects.link(output)
    # Existing target expressions are kept intact on the user's original.
    # The result is a neutral copy with a fresh transferred key set.
    output.shape_key_clear()
    target_keys = partitioned_target.data.shape_keys
    if target_keys:
        for new, old in zip(output.data.vertices, target_keys.reference_key.data):
            new.co = old.co
    if direct:
        if direct.neutral_report['changed']:
            attribute=output.data.attributes.get('ek_neutral_original_basis') or output.data.attributes.new('ek_neutral_original_basis','FLOAT_VECTOR','POINT')
            for row,point in zip(attribute.data,direct.target_points):row.vector=point
            output['ek_neutral_mouth_closed']=True
        for vertex,point in zip(output.data.vertices,direct.neutral):vertex.co=point
    basis = output.shape_key_add(name='Basis', from_mix=False)
    linear = (output.matrix_world.inverted() @ fitted.matrix_world).to_3x3()
    copied = {keys.reference_key.name: basis}
    confirmed_tongue=12 in json.loads(fitted['ek_vertex_regions']) and 12 in mesh_regions(partitioned_target)
    skipped=[]
    source_basis=[p.co.copy() for p in keys.reference_key.data]
    pins={row[0] for name in ('ek_target_lip_controls','ek_target_eye_controls')
          for row in json.loads(fitted.get(name,'[]'))}
    field=SkinDisplacementField([list(p.co) for p in basis.data],
        [list(p.vertices) for p in output.data.polygons],mesh_regions(partitioned_target),mapping,pins)
    output.data.calc_loop_triangles()
    target_labels=mesh_regions(partitioned_target)
    corner_controls={i for i,u,upper in json.loads(fitted.get('ek_target_lip_controls','[]'))
                     if u<.15 or u>.85}
    eye_targets=json.loads(fitted.get('ek_target_eye_controls','[]'))
    # Some target lids contain thin triangular notches with three rim vertices.
    # Treat the eye curve as a strong soft constraint during unfolding, or no
    # surrounding skin vertex can repair these all-rim triangles. Upper/lower
    # correspondence and the fitted Basis remain unchanged.
    corner_controls.update(i for i,side,u,upper in eye_targets)
    corner_controls.intersection_update(mapping)
    field.set_triangles([tuple(t.vertices) for t in output.data.loop_triangles if target_labels[t.polygon_index]==0],corner_controls)
    # Lash roots inherit any small corner correction made by the triangle
    # constraints, so the skin and lash do not separate on a strong blink.
    eye_rows=defaultdict(list)
    for i,side,u,upper in eye_targets:eye_rows[side].append((i,u,upper))
    eye_rings={side:O.EyeRing([basis.data[i].co.copy() for i,u,upper in rows]) for side,rows in eye_rows.items()}
    target_parts=json.loads(fitted.get('ek_target_eye_parts','[]'))
    target_groups=memberships(partitioned_target,target_labels)
    eye_motion=EyeMotion(fitted,partitioned_target,[list(p.co) for p in basis.data],target_groups,
                         source_points=direct.points if direct else None)
    rigid_teeth=RigidTeeth(fitted,partitioned_target,target_groups)
    rigid_mouth=RigidMouth(fitted,partitioned_target,target_groups)
    if direct:
        direct.configure_oral(rigid_teeth);direct.configure_oral(rigid_mouth)
    eye_motion_reports={}
    eye_plane=float(fitted.get('ek_target_eye_plane',0))
    lash_corrections={}
    for i in mapping:
        if set(target_groups[i])!={2} or len(target_parts)!=len(basis.data) or target_parts[i]!=1:continue
        point=basis.data[i].co;side=1 if point.x>=eye_plane else -1
        ring=eye_rings.get(side)
        if ring is None:continue
        u,upper=ring.locate(point);anchor=ring.sample(u,upper);offset=point-anchor
        distance=(offset.x*offset.x+offset.z*offset.z)**.5
        t=min(max((distance/ring.frame.width-.05)/.2,0),1)
        t=min(t,min(min(u,1-u)/.12,1));t=t*t*(3-2*t)
        lash_corrections[i]=[(j,w*(1-t)) for j,w in O.lip_weights(eye_rows[side],u,upper)]
    triangle_checks={}
    for key in keys.key_blocks:
        if key == keys.reference_key:
            continue
        if is_tongue_key(key.name) and not confirmed_tongue:
            skipped.append(key.name)
            continue
        new = output.shape_key_add(name=key.name, from_mix=False)
        source_deltas=[p.co-base for p,base in zip(key.data,source_basis)]
        for i in range(len(basis.data)):
            new.data[i].co = basis.data[i].co
        deltas=[Vector() for _ in basis.data]
        for dest_index, rows in mapping.items():
            delta = sum((source_deltas[index]*weight
                         for index, weight in rows), Vector())
            deltas[dest_index]=linear @ delta
        if direct:deltas=direct.deltas(source_deltas)
        deltas,closing=eye_motion.apply(np.asarray(deltas),direct.pose(key) if direct else [list(p.co) for p in key.data],source_basis)
        deltas=field.solve(deltas)
        unconstrained=deltas
        deltas,quality=field.constrain_triangles(deltas)
        quality['max_corner_correction']=max((float(sum((deltas[i]-unconstrained[i])**2)**.5) for i in corner_controls),default=0.0)
        correction=deltas-unconstrained
        lash_correction=np.zeros_like(deltas)
        for i,rows in lash_corrections.items():
            for j,w in rows:lash_correction[i]+=correction[j]*w
            if i not in eye_motion.lashes.ids:deltas[i]+=lash_correction[i]
        deltas=eye_motion.lashes.correct_roots(deltas,lash_correction)
        deltas,visibility=eye_motion.keep_visible(deltas)
        if any(closing.values()) or visibility:
            eye_motion_reports[key.name]={'closure':closing,'accessory_front_shift':visibility}
        rigid_teeth.add_pose(key)
        deltas[rigid_teeth.target_ids]=0
        rigid_mouth.add_pose(key)
        # The mouth interior uses a single driven transform. Shared skin-rim
        # vertices keep their lip motion; only the oral faces are masked later.
        deltas[[i for i in rigid_mouth.target_ids if 0 not in target_groups[i]]]=0
        if quality['corrected']:triangle_checks[key.name]=quality
        for dest_index in mapping:
            new.data[dest_index].co=basis.data[dest_index].co+Vector(deltas[dest_index])
        new.slider_min, new.slider_max = key.slider_min, key.slider_max
        copied[key.name] = new
    for key in keys.key_blocks:
        if key != keys.reference_key and key.name in copied:
            if key.relative_key.name not in copied:
                # Relative dependencies were skipped: rebase onto the neutral
                # key using the transferred absolute key coordinates.
                copied[key.name].relative_key=basis
                continue
            copied[key.name].relative_key = copied[key.relative_key.name]
    output[A.TAG] = True
    output['ek_transfer_source'] = fitted.name
    teeth=rigid_teeth.create(output,basis_points=direct.target_points if direct else None)
    mouth=rigid_mouth.create(output,basis_points=direct.target_points if direct else None)
    if direct:
        output['ek_direct_transfer_version']=1
        output['ek_guides_snapshot']=G.dumps(direct.snapshot)
    report['keys'] = len(copied)-1
    report['tongue_confirmed']=confirmed_tongue
    report['skipped_tongue_keys']=skipped
    report['skin_field']='topology_constrained_displacement'
    report['skin_field_vertices']=field.count
    report['eye_closure_method']='shared_lower_lid_curve_ten_percent_rise'
    report['eye_motion']=eye_motion_reports
    report['individual_upper_lashes']=dict(source=len(eye_motion.lashes.source_units),target=len(eye_motion.lashes.units),
        method='per_lash_source_key_root_tip_rotation_no_shared_closure_template')
    report['eye_accessory_groups']=[dict(side=s,role=role,vertices=len(ids)) for s,role,ids in eye_motion.groups]
    report['teeth_method']='rigid_object_transform_driven_by_keys' if teeth else 'no_teeth'
    report['rigid_teeth_object']=teeth.name if teeth else None
    report['mouth_method']='whole_similarity_transform_driven_by_keys' if mouth else 'no_mouth'
    report['rigid_mouth_object']=mouth.name if mouth else None
    output['ek_oral_motion_version']=1
    report['skin_triangle_checks']=triangle_checks
    report['skin_unresolved_keys']=[name for name,row in triangle_checks.items() if row['unresolved']]
    output['ek_deformation_version']=2
    output['ek_triangle_unresolved']=len(report['skin_unresolved_keys'])
    output['ek_transfer_report'] = json.dumps(report, ensure_ascii=False)
    output['ek_transfer_mapping'] = json.dumps(mapping)
    output.data.update()
    return output, report
