"""Material extraction and regional correspondence on owned working copies."""
import json
import math
import time
from collections import Counter
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

from . import region_core

TAG = 'ek_region_working'


def is_working(block):
    return bool(block and block.get(TAG))


def check_mesh(ob):
    if ob is None or ob.type != 'MESH':
        raise ValueError('请选择网格物体')
    if ob.mode == 'EDIT':
        ob.update_from_editmode()
    return ob


def basis_points(ob):
    check_mesh(ob)
    key = ob.data.shape_keys
    points = key.reference_key.data if key else ob.data.vertices
    return [ob.matrix_world @ p.co for p in points]


def new_collection(name):
    col = bpy.data.collections.new(name)
    bpy.context.scene.collection.children.link(col)
    col[TAG] = True
    return col


def source_alignment(ob):
    from mathutils import Matrix
    return ob.matrix_world@Matrix(json.loads(ob.get('ek_source_bake',json.dumps([list(r) for r in Matrix.Identity(4)])))) if ob else None


def apply_working_transform(ob,source=False):
    from mathutils import Matrix
    if not is_working(ob):raise ValueError('仅可对工作副本应用变换')
    matrix=ob.matrix_world.copy()
    if np.allclose(np.array(matrix),np.eye(4),atol=1e-9):return matrix
    if abs(matrix.determinant())<1e-12:raise ValueError('工作副本含零缩放，无法应用变换')
    if source:ob['ek_source_bake']=json.dumps([list(r) for r in source_alignment(ob)])
    if ob.data.users>1:ob.data=ob.data.copy()
    ob.data.transform(matrix,shape_keys=True);ob.parent=None;ob.matrix_world=Matrix.Identity(4);ob.data.update()
    return matrix


def result_collection(role):
    root=next((c for c in bpy.context.scene.collection.children if c.get('ek_result_root')),None)
    if root is None:
        root=new_collection('EK_分区贴合与表情迁移');root['ek_result_root']=True
    child=next((c for c in root.children if c.get('ek_result_role')==role),None)
    if child is None:
        child=bpy.data.collections.new('源模型贴合' if role=='SOURCE' else '目标表情结果')
        root.children.link(child);child[TAG]=True;child['ek_result_role']=role
    return child


def set_hidden_if_present(ob, hidden=True, view_layer=None):
    """Old working copies may belong to a different/excluded view layer."""
    layer=view_layer or bpy.context.view_layer
    if ob and layer.objects.get(ob.name)!=ob:
        layer.update()
    if ob and layer.objects.get(ob.name)==ob:
        ob.hide_set(hidden,view_layer=layer)
        for child in ob.children:
            if child.get('ek_rigid_owner')==ob.name:
                set_hidden_if_present(child,hidden,layer)
        return True
    return False


def source_material_rows(source):
    """Read live source regions without changing ID data during panel drawing."""
    if source is None or source.type!='MESH':return []
    if source.mode=='EDIT':
        import bmesh
        faces=bmesh.from_edit_mesh(source.data).faces
    else:faces=source.data.polygons
    counts=Counter(face.material_index for face in faces)
    explicit=json.loads(source.get('ek_standard_slot_labels','{}'))
    rows=[]
    for index,slot in enumerate(source.material_slots):
        if not counts[index]:continue
        title=slot.material.name if slot.material else '空材质槽'
        label=region_core.material_region(title)
        if label is None:label=explicit.get(str(index))
        label=region_core.canonical_region(label)
        rows.append(dict(slot=index,title=title,faces=counts[index],label=label))
    return rows


def default_material_indices(source):
    check_mesh(source)
    return {row['slot'] for row in source_material_rows(source)
            if row['label'] in region_core.DEFAULT_TRANSFER_REGIONS}


def extract_material_faces(source, material_indices, collection=None, selected_only=False):
    """Extract a new rest-pose source face, preserving all keys and UVs.

    Originals, their rig, materials and shape keys are not modified. The extracted
    working face deliberately has no armature modifier, so its object transform
    can be aligned independently while its copied expression keys remain usable.
    """
    check_mesh(source)
    chosen = set(material_indices)
    faces = [p for p in source.data.polygons
             if (p.select if selected_only else p.material_index in chosen)]
    if not faces:
        raise ValueError('所选材质或面选择没有包含多边形')
    old_vertices = sorted({vi for p in faces for vi in p.vertices})
    remap = {old: i for i, old in enumerate(old_vertices)}
    data = source.data
    coords = data.shape_keys.reference_key.data if data.shape_keys else data.vertices
    mesh = bpy.data.meshes.new(source.name + '_EK_source_mesh')
    mesh.from_pydata([tuple(coords[vi].co) for vi in old_vertices], [],
                     [[remap[vi] for vi in p.vertices] for p in faces])
    for slot in source.material_slots:
        mesh.materials.append(slot.material)
    for new, old in zip(mesh.polygons, faces):
        new.material_index = old.material_index
        new.use_smooth = old.use_smooth
    for layer in data.uv_layers:
        dst = mesh.uv_layers.new(name=layer.name)
        for new, old in zip(mesh.polygons, faces):
            for new_loop, old_loop in zip(new.loop_indices, old.loop_indices):
                dst.data[new_loop].uv = layer.data[old_loop].uv
    mesh.update()
    result = bpy.data.objects.new(source.name + '_EK_source', mesh)
    (collection or new_collection('EK_面部分区')).objects.link(result)
    result.matrix_world = source.matrix_world.copy()
    result[TAG] = True
    result['ek_source_object'] = source.name
    result['ek_source_reference'] = source
    result['ek_source_vertices'] = json.dumps(old_vertices)
    result['ek_source_faces'] = json.dumps([p.index for p in faces])
    explicit=json.loads(source.get('ek_standard_slot_labels','{}'))
    if explicit:
        used={p.material_index for p in faces}
        result['ek_standard_slot_labels']=json.dumps({key:label for key,label in explicit.items() if int(key) in used})
    if data.shape_keys:
        copied = {}
        for key in data.shape_keys.key_blocks:
            new_key = result.shape_key_add(name=key.name, from_mix=False)
            for ni, oi in enumerate(old_vertices):
                new_key.data[ni].co = key.data[oi].co
            new_key.slider_min, new_key.slider_max = key.slider_min, key.slider_max
            new_key.value = 0.0
            copied[key.name] = new_key
        for key in data.shape_keys.key_blocks:
            copied[key.name].relative_key = copied[key.relative_key.name]
        result.data.shape_keys.use_relative = data.shape_keys.use_relative
    for group in source.vertex_groups:
        result.vertex_groups.new(name=group.name)
    for ni, oi in enumerate(old_vertices):
        for weight in data.vertices[oi].groups:
            result.vertex_groups[weight.group].add([ni], weight.weight, 'REPLACE')
    bpy.context.view_layer.update()
    return result


def source_partition(source,working=None,scene=None):
    """Resolve the extracted source by its explicit object reference."""
    check_mesh(source);scene=scene or bpy.context.scene
    def extracted(ob):
        return bool(ob and ob.type=='MESH' and is_working(ob) and 'ek_source_vertices' in ob
                    and 'ek_source_faces' in ob and 'ek_fitted_source' not in ob and 'ek_target_object' not in ob)
    if extracted(source):return source
    def matches(ob):
        if not extracted(ob):return False
        return ob.get('ek_source_reference')==source
    if matches(working):return working
    candidates=[ob for ob in scene.objects if matches(ob)]
    if len(candidates)==1:return candidates[0]
    if candidates:
        raise ValueError('存在多个源抽取副本，请先选择本次使用的源面部副本')
    return None


def geometry(ob):
    from mathutils.bvhtree import BVHTree
    points = basis_points(ob)
    mesh = ob.data
    mesh.calc_loop_triangles()
    tris, mats, face_ids = [], [], []
    semantic = json.loads(ob.get('ek_standard_slot_labels', '{}'))
    for tri in mesh.loop_triangles:
        material = mesh.polygons[tri.polygon_index].material_index
        label = semantic.get(str(material), material)
        if semantic and label < 0:
            continue
        tris.append(tuple(tri.vertices))
        mats.append(label)
        face_ids.append(tri.polygon_index)
    if not tris:
        raise ValueError('网格没有可用于匹配的三角面')
    bvh = BVHTree.FromPolygons(points, tris, all_triangles=True)
    return points, tris, mats, face_ids, bvh


def evaluate(source, target, tolerance_fraction=0.10, normal_min=0.15,
             normal_sign=1.0, manual=None):
    """Classify whole target polygons using source rest geometry in world space."""
    check_mesh(source)
    check_mesh(target)
    if source.get('ek_standard_slot_labels'):
        return evaluate_standard(source, target, tolerance_fraction, normal_min,
                                 normal_sign, manual)
    points, tris, materials, face_ids, bvh = geometry(source)
    center_of_source = sum(points, Vector()) / len(points)
    # A world-axis bounding box changes size when rotated. A bounding sphere
    # about the vertex centroid gives a rigid-motion invariant size instead.
    diagonal = 2.0 * max((p - center_of_source).length for p in points)
    if diagonal <= 1e-9:
        raise ValueError('源面部尺寸为零')
    tolerance = diagonal * tolerance_fraction
    outward = Vector()
    source_area = 0.0
    for tri in tris:
        a, b, c = (points[i] for i in tri)
        area_normal = (b - a).cross(c - a)
        outward += area_normal
        source_area += area_normal.length
    # An open face patch provides a net outward direction. A closed shell does
    # not; report that limitation instead of guessing a world axis.
    depth_guard = outward.length > max(1e-9, source_area * 0.03)
    if depth_guard:
        outward.normalize()
        rear_limit = min(p.dot(outward) for p in points) - tolerance * 0.35
    target_points = basis_points(target)
    evidence = []
    for poly in target.data.polygons:
        verts = [target_points[i] for i in poly.vertices]
        center = sum(verts, Vector()) / len(verts)
        behind = bool(depth_guard and center.dot(outward) < rear_limit)
        # Newell normal is well-defined for concave ngons and nonuniform scale.
        normal = Vector()
        for a, b in zip(verts, verts[1:] + verts[:1]):
            normal += a.cross(b)
        area = normal.length * 0.5
        if normal.length:
            normal.normalize()
        normal *= normal_sign
        # Inset vertex samples prevent an exact boundary vertex dominating votes.
        sample_points = [center] + [(center + p * 3.0) / 4.0 for p in verts]
        samples = []
        for q in sample_points:
            hit, hit_normal, triangle, dist = bvh.find_nearest(q)
            samples.append({'distance': float(dist) if dist is not None else math.inf,
                            'normal_dot': float(normal.dot(hit_normal)) if hit is not None and not behind else -1.0,
                            'label': materials[triangle] if triangle is not None else -1})
        evidence.append({'samples': samples, 'area': area, 'normal': tuple(normal)})
    polygons = [list(p.vertices) for p in target.data.polygons]
    adjacency, target_components = region_core.topology(polygons)
    _, source_components = region_core.topology([list(p.vertices) for p in source.data.polygons])
    result = region_core.classify(evidence, adjacency, tolerance,
                                  normal_min=normal_min, manual=manual)
    result.update(source=source.name, target=target.name,
                  source_diagonal=diagonal, tolerance_fraction=tolerance_fraction,
                  target_components=target_components, source_components=source_components,
                  areas=dict(Counter()), normal_sign=normal_sign,
                  parameters={'normal_min': normal_min}, depth_guard=depth_guard,
                  outward=list(outward) if depth_guard else None)
    areas = {}
    for label, row in zip(result['labels'], evidence):
        areas[label] = areas.get(label, 0.0) + row['area']
    result['areas'] = areas
    return result


COLORS = [(0.08, 0.48, 0.95, 1.0), (0.12, 0.80, 0.42, 1.0),
          (0.74, 0.22, 0.85, 1.0), (0.95, 0.25, 0.30, 1.0),
          (0.20, 0.78, 0.82, 1.0)]
REGION_COLORS = {0:(0.04,0.28,1,1), 2:(0.62,0.03,0.95,1),
                 3:(1,0.04,0.04,1),
                 7:(0.95,0.95,0.95,1), 8:(1,0.85,0,1),
                 9:(0.08,0.95,0.12,1), 12:(1,0.24,0.62,1),
                 -1:(0.16,0.18,0.22,1), -2:(1,0.45,0.02,1)}


def region_color(label):
    label=region_core.canonical_region(label)
    return REGION_COLORS.get(label,COLORS[label % len(COLORS)])


def recolor_preview(preview):
    check_mesh(preview)
    if not is_working(preview):
        raise ValueError('只能更新工作副本的分区标记配色')
    count=0
    for slot in preview.material_slots:
        mat=slot.material
        if not is_working(mat):continue
        label=region_core.material_region(mat.name)
        if label is None:continue
        color=region_color(label)
        if all(abs(a-b)<1e-6 for a,b in zip(mat.diffuse_color,color)):continue
        # Preserve any original/other object sharing this material datablock.
        colored=mat.copy();colored.diffuse_color=color
        slot.material=colored
        count+=1
    return count


def marker_material(name, color):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = color
    mat[TAG] = True
    return mat


def marker_name(label):
    label=region_core.canonical_region(label)
    if label<0:return 'EK_不参与_后侧或其他'
    return 'EK_对应_'+region_core.REGION_NAMES[label]


def mark_source_regions(source_copy):
    """Replace materials only on an extracted copy, retaining source provenance."""
    check_mesh(source_copy)
    if not is_working(source_copy) or not source_copy.get('ek_source_object'):
        raise ValueError('请先创建源面部分区副本')
    if source_copy.get('ek_source_partition_markers'):
        return recolor_preview(source_copy)
    rows=source_material_rows(source_copy)
    assignments=[p.material_index for p in source_copy.data.polygons]
    if source_copy.data.users>1:source_copy.data=source_copy.data.copy()
    remap={row['slot']:i for i,row in enumerate(rows)}
    metadata={str(i):dict(slot=row['slot'],name=row['title']) for i,row in enumerate(rows)}
    labels={str(i):row['label'] if row['label'] in region_core.DEFAULT_TRANSFER_REGIONS else -1
            for i,row in enumerate(rows)}
    source_copy.data.materials.clear()
    for i in range(len(rows)):
        label=labels[str(i)]
        source_copy.data.materials.append(marker_material(marker_name(label),region_color(label)))
    for face,old_slot in zip(source_copy.data.polygons,assignments):face.material_index=remap[old_slot]
    source_copy['ek_source_material_slots']=json.dumps(metadata,ensure_ascii=False)
    source_copy['ek_standard_slot_labels']=json.dumps(labels)
    source_copy['ek_source_partition_markers']=True
    source_copy.data.update()
    return len(rows)


def apply_labels(preview, source, result):
    """Only assign labels to a tagged working copy, preserving original materials."""
    if not is_working(preview):
        raise ValueError('只能标记本插件的分区预览副本')
    if len(result['labels']) != len(preview.data.polygons):
        raise ValueError('网格拓扑已改变，请重新生成预览')
    display_labels=[-1 if label==-2 else label for label in result['labels']]
    region_slots = json.loads(preview.get('ek_region_slots', '{}'))
    semantic = json.loads(source.get('ek_standard_slot_labels', '{}'))
    source_labels = set(semantic.values()) if semantic else set(p.material_index for p in source.data.polygons)
    labels = sorted((set(display_labels) | {-1} | source_labels)-{-2})
    for label in labels:
        if str(label) in region_slots:
            index=region_slots[str(label)]
            mat=preview.material_slots[index].material if 0<=index<len(preview.material_slots) else None
            if is_working(mat) and (not semantic or region_core.material_region(mat.name)==label):continue
        if label == -1:
            name, color = 'EK_不参与_后侧或其他', region_color(label)
        else:
            slot = source.material_slots[label] if label < len(source.material_slots) else None
            original=slot.material.name if slot and slot.material else str(label)
            title=region_core.REGION_NAMES.get(label if semantic else region_core.material_region(original))
            name = 'EK_对应_' + (title or original)
            color = region_color(region_core.material_region(name) if region_core.material_region(name) is not None else label)
        preview.data.materials.append(marker_material(name, color))
        region_slots[str(label)] = len(preview.data.materials) - 1
    for poly, label in zip(preview.data.polygons, display_labels):
        poly.material_index = region_slots[str(label)]
    preview['ek_region_slots'] = json.dumps(region_slots)
    preview['ek_region_labels'] = json.dumps(display_labels)
    preview['ek_last_counts'] = json.dumps(result['counts'])
    # Refresh reused marker slots too, exactly as the explicit color action does.
    recolor_preview(preview)
    preview.data.update()


def make_preview(source, target, result, collection=None):
    mesh = target.data.copy()
    preview = bpy.data.objects.new(target.name + '_EK_regions', mesh)
    (collection or new_collection('EK_面部分区')).objects.link(preview)
    preview.matrix_world = target.matrix_world.copy()
    preview[TAG] = True
    preview['ek_target_object'] = target.name
    preview['ek_target_reference'] = target
    preview['ek_source_object'] = source.name
    preview['ek_original_materials'] = json.dumps([p.material_index for p in target.data.polygons])
    preview['ek_manual_overrides'] = '{}'
    apply_labels(preview, source, result)
    return preview


def target_partition(target,preview=None,scene=None):
    """Read the current partition without changing data during panel drawing."""
    if target is None or target.type!='MESH':
        raise ValueError('先在第 1 步选择目标网格')
    scene=scene or bpy.context.scene
    def matches(ob):
        return bool(ob is not None and ob!=target and ob.type=='MESH' and is_working(ob)
                    and scene.objects.get(ob.name)==ob and ob.get('ek_target_reference')==target)
    # The workflow explicitly assigned this copy. Source object properties
    # inherited by Object.copy() must not override that current association.
    if matches(preview):return preview
    excluded=('ek_standard_version','ek_fitted_source','ek_transfer_target','ek_source_partition_markers')
    candidates=[ob for ob in scene.objects if matches(ob) and not any(key in ob for key in excluded)]
    if len(candidates)==1:return candidates[0]
    if len(candidates)>1:
        raise ValueError('存在多个目标分区副本，请重新生成或指定本次已修正分区')
    if preview is not None:
        raise ValueError('当前分区不属于所选目标，请在第 2 步生成目标分区')
    raise ValueError('没有找到该目标的材质分区副本（_EK_regions），请先生成目标面部分区')


def merge_eye_regions(preview):
    """Collapse old Gaze/Eyes marker slots on owned partitions only.

    Reading regions during drawing remains side-effect free. Migration runs
    at explicit partition/detection actions and preserves topology and guides.
    """
    if not is_working(preview) or preview.type!='MESH' or preview.mode=='EDIT':return False
    if not preview.get('ek_standard_slot_labels') and not preview.get('ek_region_slots'):return False
    if preview.get('ek_transfer_target') or preview.get('ek_fitted_source') or preview.get('ek_source_partition_markers'):return False
    explicit=json.loads(preview.get('ek_standard_slot_labels','{}'));labels={}
    for i,slot in enumerate(preview.material_slots):
        name=slot.material.name if slot.material else ''
        label=region_core.material_region(name)
        if label is None:label=region_core.canonical_region(explicit.get(str(i)))
        labels[i]=label
    eyes=[i for i,label in labels.items() if label==3]
    if not eyes:return False
    first=eyes[0]
    if len(eyes)==1 and preview.material_slots[first].material and preview.material_slots[first].material.name.startswith('EK_对应_Eyes') and 5 not in explicit.values():return False
    if preview.data.users>1:preview.data=preview.data.copy()
    materials=[s.material for s in preview.material_slots];assigned=[p.material_index for p in preview.data.polygons]
    keep=[i for i in range(len(materials)) if i not in eyes[1:]];remap={i:j for j,i in enumerate(keep)}
    remap.update({i:remap[first] for i in eyes})
    materials[first]=marker_material(marker_name(3),region_color(3))
    preview.data.materials.clear()
    for i in keep:preview.data.materials.append(materials[i])
    for poly,old in zip(preview.data.polygons,assigned):poly.material_index=remap[old]
    preview['ek_standard_slot_labels']=json.dumps({str(remap[i]):label for i,label in labels.items() if label is not None})
    preview['ek_region_slots']=json.dumps({str(label):remap[i] for i,label in labels.items() if label is not None})
    for name in ('ek_manual_overrides',):
        if name in preview:preview[name]=json.dumps({k:region_core.canonical_region(v) for k,v in json.loads(preview[name]).items()})
    if 'ek_region_labels' in preview:preview['ek_region_labels']=json.dumps([region_core.canonical_region(v) for v in json.loads(preview['ek_region_labels'])])
    if 'ek_last_counts' in preview:
        counts=Counter()
        for k,v in json.loads(preview['ek_last_counts']).items():counts[region_core.canonical_region(int(k))]+=v
        preview['ek_last_counts']=json.dumps(dict(counts))
    preview.data.update()
    return True


def adopt_corrected_regions(preview, authoritative=False):
    """Rebuild semantic metadata from actual materials, never old face indices."""
    check_mesh(preview)
    if not is_working(preview):
        raise ValueError('请选择分区工作副本')
    merge_eye_regions(preview)
    slots, inverse = {}, {}
    for i, slot in enumerate(preview.material_slots):
        label = region_core.material_region(slot.material.name if slot.material else '')
        if label is not None:
            inverse[i] = label
            slots.setdefault(str(label), i)
    used = {p.material_index for p in preview.data.polygons}
    if not any(v >= 0 for v in inverse.values()):
        raise ValueError('分区工作副本缺少可识别的标记材质')
    missing = used - set(inverse)
    if missing:
        raise ValueError('以下材质槽尚未定义标准分区：' + ', '.join(map(str, sorted(missing))))
    labels = [inverse[p.material_index] for p in preview.data.polygons]
    if authoritative and 0 not in labels:
        raise ValueError('标准网格需要包含已标记的 Face 分区')
    old_slots = json.loads(preview.get('ek_region_slots', '{}'))
    old_labels = json.loads(preview.get('ek_region_labels', '[]'))
    invalidated = old_slots != slots or len(old_labels) != len(labels)
    preview['ek_region_slots'] = json.dumps(slots)
    preview['ek_standard_slot_labels'] = json.dumps({str(i):label for i,label in inverse.items()})
    if authoritative or invalidated:
        # Reindexed topology/materials invalidate historical manual face IDs.
        # Retain CURRENT corrections rather than applying old indices to new faces.
        preview['ek_region_labels'] = json.dumps(labels)
        preview['ek_manual_overrides'] = json.dumps({str(i): v for i, v in enumerate(labels)})
    preview['ek_last_counts'] = json.dumps(dict(Counter(labels)))
    return dict(labels=labels, slots=slots, invalidated=invalidated,
                names={str(k): v for k, v in region_core.REGION_NAMES.items() if str(k) in slots})


def standard_preset_directory(create=False):
    config=bpy.utils.user_resource('CONFIG',create=create)
    if not config:
        if create:raise ValueError('无法找到 Blender 用户配置目录')
        return None
    directory=Path(config)/'ExpressionGen'/'region_presets'
    if create:directory.mkdir(parents=True,exist_ok=True)
    return directory


def standard_presets():
    directory=standard_preset_directory()
    if not directory:return []
    legacy=directory.parents[1]/'ExpressionKit'/'region_presets'
    names={path.name for folder in (directory,legacy) if folder.exists()
           for path in folder.iterdir() if path.is_file() and path.suffix.lower()=='.json'}
    return [dict(file=name,name=Path(name).stem) for name in sorted(names,key=str.casefold)]


def standard_preset_path(filename):
    if filename in ('__default__','__none__'):
        raise ValueError('请选择用户保存的分区预设，或使用「从 JSON 加载」；内置默认标准已移除')
    if not filename or Path(filename).name!=filename or '/' in filename or '\\' in filename:
        raise ValueError('请选择有效的已修正分区标准预设')
    if filename not in {row['file'] for row in standard_presets()}:
        raise ValueError('该预设已不存在，请从列表重新选择')
    directory=standard_preset_directory()
    path=directory/filename
    if path.is_file():return path
    return directory.parents[1]/'ExpressionKit'/'region_presets'/filename


def save_standard_preset(value,name):
    import re
    title=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',name.strip()).strip(' .')[:96]
    if not title:raise ValueError('请填写预设名称')
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])',title.split('.')[0]):title='标准_'+title
    directory=standard_preset_directory(create=True)
    content=json.dumps(value,ensure_ascii=False)
    for number in range(1,10000):
        path=directory/(title+('' if number==1 else ' (%d)' % number)+'.json')
        try:file=path.open('x',encoding='utf-8')
        except FileExistsError:continue
        try:
            with file:file.write(content)
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path
    raise ValueError('同名预设过多，请更换预设名称')


def capture_standard(preview, export_path=None, preset_name=None):
    """Capture an explicit corrected standard as an independent working reference."""
    # Validate before writing the user's working-copy metadata.
    state = adopt_corrected_regions(preview, authoritative=True)
    if not state or 0 not in state['labels']:
        raise ValueError('标准网格需要包含已标记的 Face 分区')
    value=dict(version=1,origin=preview.name,
        vertices=[list(v.co) for v in preview.data.vertices],
        polygons=[list(p.vertices) for p in preview.data.polygons],
        labels=[-1 if label==-2 else label for label in state['labels']],names=state['names'],
        matrix=[list(row) for row in preview.matrix_world])
    value['matching']='part_topology_proportions_relations'
    value['names']['-1']=region_core.REGION_NAMES[-1]
    if preset_name is not None:
        path=save_standard_preset(value,preset_name)
        state['preset_file']=path.name
    elif export_path:
        path=Path(export_path);path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
    standard = preview.copy()
    standard.data = preview.data.copy()
    standard.name = 'EK_已修正分区标准'
    new_collection('EK_已修正分区标准').objects.link(standard)
    standard['ek_standard_slot_labels'] = json.dumps({str(i): region_core.material_region(slot.material.name)
        for i, slot in enumerate(standard.material_slots) if slot.material and
        region_core.material_region(slot.material.name) is not None})
    standard['ek_standard_origin'] = preview.name
    standard['ek_standard_version'] = 1
    standard.display_type = 'WIRE'
    standard.show_in_front = True
    set_hidden_if_present(standard,True)
    target = preview.get('ek_target_reference')
    if target and [list(p.vertices) for p in target.data.polygons] == [list(p.vertices) for p in preview.data.polygons]:
        preview['ek_source_object'] = standard.name
    return standard, state


def read_standard(path):
    """Validate user data before creating any Blender datablocks."""
    path=Path(path)
    try:value=json.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:raise ValueError('分区预设文件不存在：'+str(path)) from None
    except (UnicodeError,json.JSONDecodeError) as exc:
        raise ValueError('无法读取分区预设 JSON「%s」：%s'%(path.name,exc)) from exc
    if not isinstance(value,dict) or type(value.get('version')) is not int or value['version']!=1:
        raise ValueError('分区预设需要 version=1 的网格标准文件')
    vertices=value.get('vertices');polygons=value.get('polygons');labels=value.get('labels')
    if not isinstance(vertices,list) or not vertices or not isinstance(polygons,list) or not polygons:
        raise ValueError('分区预设缺少 vertices 或 polygons 网格数据')
    finite=lambda v:type(v) in (int,float) and math.isfinite(v)
    if any(not isinstance(row,list) or len(row)!=3 or not all(finite(v) for v in row) for row in vertices):
        raise ValueError('分区预设的顶点必须是有限数值组成的 XYZ 坐标')
    for index,face in enumerate(polygons):
        if (not isinstance(face,list) or len(face)<3 or any(type(i) is not int or not 0<=i<len(vertices) for i in face)
                or len(set(face))!=len(face)):
            raise ValueError('分区预设第 %d 个面的顶点索引无效'%(index+1))
    if not isinstance(labels,list) or len(labels)!=len(polygons):
        raise ValueError('分区预设的 labels 数量必须与 polygons 一致')
    if any(type(label) is not int or region_core.canonical_region(label) not in region_core.REGION_NAMES for label in labels):
        raise ValueError('预设包含无法识别的分区编号')
    if 0 not in labels:raise ValueError('分区预设需要包含已标记的 Face 分区')
    value['labels']=[-1 if label==-2 else region_core.canonical_region(label) for label in labels]
    matrix=value.get('matrix',[[1.,0.,0.,0.],[0.,1.,0.,0.],[0.,0.,1.,0.],[0.,0.,0.,1.]])
    if (not isinstance(matrix,list) or len(matrix)!=4
            or any(not isinstance(row,list) or len(row)!=4 or not all(finite(v) for v in row) for row in matrix)):
        raise ValueError('分区预设的 matrix 必须是有限数值组成的 4×4 矩阵')
    value['matrix']=matrix
    return value


def load_standard(path):
    from mathutils import Matrix
    path=Path(path);value=read_standard(path)
    mesh=source=collection=None
    try:
        mesh=bpy.data.meshes.new('EK_standard_mesh')
        mesh.from_pydata(value['vertices'],[],value['polygons']);mesh.update()
        mapping={}
        for label in sorted(set(value['labels'])):
            mapping[str(len(mesh.materials))]=label
            mesh.materials.append(marker_material(marker_name(label),region_color(label)))
        slots={label:int(slot) for slot,label in mapping.items()}
        for face,label in zip(mesh.polygons,value['labels']):face.material_index=slots[label]
        source=bpy.data.objects.new('EK_已修正分区标准',mesh)
        source[TAG]=True;source.matrix_world=Matrix(value['matrix'])
        source['ek_standard_slot_labels']=json.dumps(mapping)
        source['ek_region_slots']=json.dumps({str(label):slot for label,slot in slots.items()})
        source['ek_region_labels']=json.dumps(value['labels'])
        source['ek_standard_version']=1
        source['ek_standard_origin']=str(value.get('origin',path.stem))
        source['ek_standard_file']=str(path.resolve())
        source.display_type='WIRE';source.show_in_front=True
        collection=new_collection('EK_已修正分区标准');collection.objects.link(source)
        # Linking an object does not immediately add its base to a view layer.
        # Update first; excluded layers may legitimately have no object base.
        set_hidden_if_present(source,True)
        return source
    except Exception:
        if source is not None:bpy.data.objects.remove(source,do_unlink=True)
        if mesh is not None and mesh.users==0:bpy.data.meshes.remove(mesh)
        if collection is not None:bpy.data.collections.remove(collection)
        raise


def evaluate_standard(standard, target, tolerance_fraction=0.10, normal_min=0.15,
                      normal_sign=1.0, manual=None):
    """Match part topology, relative size and relationships in local frames."""
    from . import region_preset as Preset
    from .region_transfer import mesh_regions
    check_mesh(standard);check_mesh(target)
    source_polys=[list(p.vertices) for p in standard.data.polygons]
    target_polys=[list(p.vertices) for p in target.data.polygons]
    result=Preset.match([list(v.co) for v in standard.data.vertices],source_polys,mesh_regions(standard),
        [list(v.co) for v in target.data.vertices],target_polys,
        [p.material_index for p in target.data.polygons],manual)
    return dict(result,source=standard.name,target=target.name)


def manual_assign(preview, label):
    label=region_core.canonical_region(label)
    """Selected polygons override automatic labels. Kept on reclassification."""
    check_mesh(preview)
    if not is_working(preview):
        raise ValueError('请选择本插件的分区预览副本')
    if label==-2:label=-1  # Read older saved operator settings as unassigned.
    adopt_corrected_regions(preview)
    slots = json.loads(preview['ek_region_slots'])
    if str(label) not in slots:
        if label not in region_core.REGION_NAMES or label==-2:raise ValueError('请选择有效的分区编号')
        slots[str(label)]=len(preview.data.materials)
        preview.data.materials.append(marker_material(marker_name(label),region_color(label)))
        preview['ek_region_slots']=json.dumps(slots)
        mapping=json.loads(preview.get('ek_standard_slot_labels','{}'))
        mapping[str(slots[str(label)])]=label;preview['ek_standard_slot_labels']=json.dumps(mapping)
    manual = json.loads(preview.get('ek_manual_overrides', '{}'))
    count = 0
    if preview.mode == 'EDIT':
        import bmesh
        bm = bmesh.from_edit_mesh(preview.data)
        bm.faces.ensure_lookup_table()
        for face in bm.faces:
            if face.select:
                manual[str(face.index)] = label
                face.material_index = slots[str(label)]
                count += 1
        bmesh.update_edit_mesh(preview.data)
    else:
        for face in preview.data.polygons:
            if face.select:
                manual[str(face.index)] = label
                face.material_index = slots[str(label)]
                count += 1
    preview['ek_manual_overrides'] = json.dumps(manual)
    return count


def mirror_regions(preview, direction='POSITIVE', plane=0.0,
                   tolerance_fraction=0.03, preserve_manual=True):
    """Synchronize actual labels with mirrored geometry AND topology.

    Local coordinates keep object alignment transforms independent. Normal and
    distance gates reject unrelated nearby surfaces. Connectivity profiles and
    neighboring correspondences distinguish overlapping islands and patches.
    Central crossing polygons
    are left alone. Destination annotations become persistent manual overrides.
    """
    from mathutils.kdtree import KDTree
    check_mesh(preview)
    if not is_working(preview) or not preview.get('ek_region_slots'):
        raise ValueError('请选择已生成分区的目标预览副本')
    adopt_corrected_regions(preview)
    if direction not in ('POSITIVE', 'NEGATIVE'):
        raise ValueError('无效的同步方向')
    if not 0 < tolerance_fraction <= 0.2:
        raise ValueError('镜像匹配容差须在 0 到 0.2 之间')
    slots = json.loads(preview['ek_region_slots'])
    inverse = {int(slot): int(label) for label, slot in slots.items()}
    mesh = preview.data
    if not mesh.vertices:
        raise ValueError('预览网格为空')
    coords = [v.co.copy() for v in mesh.vertices]
    width = max(v.x for v in coords) - min(v.x for v in coords)
    tolerance = width * tolerance_fraction
    if width <= 1e-9:
        raise ValueError('预览的本地 X 宽度为零')
    sign = 1 if direction == 'POSITIVE' else -1
    source, target, rows = [], [], {}
    for face in mesh.polygons:
        verts = [coords[i] for i in face.vertices]
        side = [sign * (v.x - plane) for v in verts]
        center = sum(verts, Vector()) / len(verts)
        normal = Vector()
        for a, b in zip(verts, verts[1:] + verts[:1]):
            normal += a.cross(b)
        if normal.length:
            normal.normalize()
        rows[face.index] = (center, normal)
        if min(side) >= -width * 1e-7 and max(side) > width * 1e-7:
            if face.material_index in inverse:
                source.append(face.index)
        elif max(side) <= width * 1e-7 and min(side) < -width * 1e-7:
            target.append(face.index)
    if not source or not target:
        raise ValueError('中线两侧没有可同步的完整面，请检查本地 X 中线')
    tree = KDTree(len(source))
    for index in source:
        center, _ = rows[index]
        reflected = center.copy()
        reflected.x = 2 * plane - reflected.x
        tree.insert(reflected, index)
    tree.balance()
    manual = json.loads(preview.get('ek_manual_overrides', '{}'))
    baseline = json.loads(preview.get('ek_region_labels', '[]'))
    neighbors, profiles = region_core.topology_profiles([list(p.vertices) for p in mesh.polygons])
    candidates_by_face = {}
    topology_rejected = 0
    source_labels = {i: inverse[mesh.polygons[i].material_index] for i in source}
    # Include protected target faces in correspondence: their topology still
    # anchors nearby uncorrected faces, while their labels remain untouched.
    for index in target:
        center, normal = rows[index]
        candidates = []
        for _, match, distance in tree.find_range(center, tolerance * 2):
            _, source_normal = rows[match]
            reflected_normal = source_normal.copy()
            reflected_normal.x *= -1
            dot = normal.dot(reflected_normal)
            if dot < 0.5:
                continue
            cost = region_core.topology_cost(profiles[index], profiles[match])
            if cost is None or cost > 0.55:
                topology_rejected += 1
                continue
            candidates.append((match, distance / (2 * tolerance), cost, 1 - dot))
        # Favor connectivity but bound work on very dense overlapping surfaces.
        candidates.sort(key=lambda r: (0.25 * r[1] + 0.65 * r[2] + 0.10 * r[3], r[0]))
        candidates_by_face[index] = candidates[:16]
    mapping, topology_report = region_core.topology_correspondence(
        candidates_by_face, neighbors, source_labels)
    updates = {}
    protected = unmatched = 0
    for index in target:
        face = mesh.polygons[index]
        label = inverse.get(face.material_index)
        # Native material-slot edits also count as corrections, even when they
        # were made without the plugin's manual assignment button.
        corrected = str(index) in manual or (
            len(baseline) == len(mesh.polygons) and label != baseline[index])
        if preserve_manual and corrected:
            protected += 1
            continue
        if index not in mapping:
            unmatched += 1
            continue
        match = mapping[index]
        new_label = inverse[mesh.polygons[match].material_index]
        if label != new_label:
            updates[index] = new_label
    # Capture native corrections so reclassification preserves both halves.
    for face in mesh.polygons:
        label = inverse.get(face.material_index)
        if label is not None and len(baseline) == len(mesh.polygons) and label != baseline[face.index]:
            manual[str(face.index)] = label
    if preview.mode == 'EDIT':
        import bmesh
        bm = bmesh.from_edit_mesh(mesh)
        bm.faces.ensure_lookup_table()
        for index, label in updates.items():
            bm.faces[index].material_index = slots[str(label)]
        bmesh.update_edit_mesh(mesh)
        preview.update_from_editmode()
    else:
        for index, label in updates.items():
            mesh.polygons[index].material_index = slots[str(label)]
        mesh.update()
    manual.update({str(index): label for index, label in updates.items()})
    preview['ek_manual_overrides'] = json.dumps(manual)
    report = dict(changed=len(updates), protected=protected, unmatched=unmatched,
                  source_faces=len(source), target_faces=len(target), direction=direction,
                  plane=plane, tolerance=tolerance, method='geometry_and_topology',
                  topology_rejected_candidates=topology_rejected, **topology_report)
    preview['ek_mirror_report'] = json.dumps(report)
    preview['ek_last_counts'] = json.dumps(dict(Counter(
        inverse.get(p.material_index, -2) for p in mesh.polygons)))
    return report


def refresh_preview(source, target, preview, **options):
    manual = {int(i): label for i, label in json.loads(
        preview.get('ek_manual_overrides', '{}')).items()}
    if [list(p.vertices) for p in preview.data.polygons] != [list(p.vertices) for p in target.data.polygons]:
        raise ValueError('预览或目标拓扑已改变；面编号不再可靠，请新建预览')
    from .region_transfer import mesh_regions
    current=mesh_regions(preview);baseline=json.loads(preview.get('ek_region_labels','[]'))
    if len(baseline)==len(current):
        for i,label in enumerate(current):
            if i in manual or label!=(-1 if baseline[i]==-2 else baseline[i]):manual[i]=label
    preview['ek_manual_overrides']=json.dumps({str(i):label for i,label in manual.items()})
    result = evaluate(source, target, manual=manual, **options)
    apply_labels(preview, source, result)
    return result
