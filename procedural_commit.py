"""Resolve original mesh ownership and merge a reviewed face into that mesh."""
import hashlib
import json
import bmesh
import numpy as np
from . import region_blender as A

LOCAL_BASIS='ek_commit_original_basis_local'


def coordinates(data):
    points=np.empty(len(data)*3,dtype=np.float64)
    data.foreach_get('co',points)
    return points.reshape((-1,3))


def vector_attribute(result,name,count):
    attribute=result.data.attributes.get(name)
    if attribute is None or attribute.domain!='POINT' or attribute.data_type!='FLOAT_VECTOR' or len(attribute.data)!=count:
        raise ValueError('结果缺少有效的原始基型记录，请重新生成')
    points=np.empty(count*3,dtype=np.float64);attribute.data.foreach_get('vector',points)
    points=points.reshape((-1,3))
    if not np.isfinite(points).all():raise ValueError('原始基型记录含无效坐标，请重新生成')
    return points


def basis_alignment(result,target,mapping):
    """Check native Basis before any write, without a float32 inverse round trip."""
    basis=target.data.shape_keys.reference_key.data if target.data.shape_keys else target.data.vertices
    native=coordinates(basis)[mapping]
    original=vector_attribute(result,'ek_neutral_original_basis',len(mapping))
    if not np.isfinite(native).all():raise ValueError('原始 Basis 含无效坐标，请先修正模型')
    if result.get('ek_commit_basis_record')==1:
        recorded=vector_attribute(result,LOCAL_BASIS,len(mapping))
        changed=np.any(native!=recorded,axis=1)
        if changed.any():
            distance=float(np.linalg.norm(native-recorded,axis=1).max())
            raise ValueError('原始 Basis 确实已修改（%d 个对应顶点，最大位移 %.6g），请重新生成'%(np.count_nonzero(changed),distance))
    target_matrix=np.array(target.matrix_world,dtype=np.float64)
    result_matrix=np.array(result.matrix_world,dtype=np.float64)
    if not np.isfinite(target_matrix).all() or not np.isfinite(result_matrix).all():raise ValueError('模型变换含无效数值')
    try:
        forward=np.linalg.solve(result_matrix,target_matrix)
        linear=np.linalg.inv(forward[:3,:3])
    except np.linalg.LinAlgError:raise ValueError('模型含零缩放，无法写回') from None
    expected=native@forward[:3,:3].T+forward[:3,3]
    if np.array_equal(target_matrix,result_matrix):
        tolerance=np.full_like(expected,1e-6)
    else:
        # Mesh.transform stores float32 coordinates. Bound only that forward
        # multiply/add rounding; inverse scaling must not magnify it into a
        # false native-Basis edit. New outputs also have an exact local record.
        absolute=abs(native)@abs(forward[:3,:3]).T+abs(forward[:3,3])
        tolerance=4*np.finfo(np.float32).eps*(absolute+abs(original))+1e-12
    error=abs(expected-original)
    if np.any(error>tolerance):
        raise ValueError('原模型与分区副本的基型或位置不一致（最大坐标偏差 %.6g），请重新创建分区并生成'%float(error.max()))
    return native,original,linear


def topology_stamp(mesh):
    faces=[list(p.vertices) for p in mesh.polygons]
    return hashlib.sha256(json.dumps([len(mesh.vertices),faces],separators=(',',':')).encode()).hexdigest()


def original_binding(target):
    """The explicitly selected target is the receiver, even if it was extracted.

    Copy provenance describes where geometry came from, not authorization to
    overwrite a different object. Never redirect beyond the target field.
    """
    A.check_mesh(target)
    return target,list(range(len(target.data.vertices))),list(range(len(target.data.polygons)))


def basis_signature(ob):
    basis=ob.data.shape_keys.reference_key.data if ob.data.shape_keys else ob.data.vertices
    stamp=hashlib.sha256(coordinates(basis).tobytes())
    stamp.update(np.asarray(ob.matrix_world,dtype=np.float64).tobytes())
    stamp.update(topology_stamp(ob.data).encode())
    return stamp.hexdigest()


def generation_reference(target,partition):
    """Validate before solving; accept only a proven previous writeback rebase."""
    import bpy
    A.check_mesh(target);A.check_mesh(partition)
    if target==partition or partition.get('ek_target_reference')!=target:
        raise ValueError('分区副本不属于当前目标，请重新选择对应分区')
    if topology_stamp(target.data)!=topology_stamp(partition.data):
        raise ValueError('目标拓扑与旧分区不同，请从当前目标重新创建分区')
    native=coordinates(target.data.shape_keys.reference_key.data if target.data.shape_keys else target.data.vertices)
    original=coordinates(partition.data.shape_keys.reference_key.data if partition.data.shape_keys else partition.data.vertices)
    try:forward=np.linalg.solve(np.asarray(partition.matrix_world),np.asarray(target.matrix_world))
    except np.linalg.LinAlgError:raise ValueError('模型含零缩放，无法生成') from None
    expected=native@forward[:3,:3].T+forward[:3,3]
    magnitude=abs(native)@abs(forward[:3,:3]).T+abs(forward[:3,3])
    tolerance=4*np.finfo(np.float32).eps*(magnitude+abs(original))+1e-6
    if np.all(abs(expected-original)<=tolerance):return original
    from . import region_guides as G
    proof=json.loads(target.data.get('ek_regeneration_state','{}'))
    if (proof.get('target')==basis_signature(target)
            and proof.get('partition')==G.fingerprint(partition,partition,None,include_regions=False)):
        return expected
    # Migrate saved results only after checking their exact committed Basis
    # and unchanged authoring geometry. Actual edits remain a hard rejection.
    for previous in bpy.data.objects:
        if (previous.type!='MESH' or previous.get('ek_confirmed_target')!=target
                or previous.get('ek_procedural_partition')!=partition
                or previous.get('ek_commit_topology')!=topology_stamp(target.data)
                or not previous.data.shape_keys):continue
        ids=json.loads(previous.get('ek_commit_vertices','[]'))
        origin=previous.data.attributes.get('ek_vertex_origin')
        if origin is None:continue
        try:
            mapping=np.asarray([ids[row.value] for row in origin.data],dtype=int)
            if len(set(mapping))!=len(native):continue
            saved=vector_attribute(previous,LOCAL_BASIS,len(mapping))
            reference=vector_attribute(previous,'ek_neutral_original_basis',len(mapping))
            conversion=np.linalg.solve(np.asarray(previous.matrix_world),np.asarray(target.matrix_world))
            committed=saved+(coordinates(previous.data.shape_keys.reference_key.data)-reference)@np.linalg.inv(conversion[:3,:3]).T
            authoring_transform=np.linalg.solve(np.asarray(previous.matrix_world),np.asarray(partition.matrix_world))
            authoring=original[mapping]@authoring_transform[:3,:3].T+authoring_transform[:3,3]
            if (np.array_equal(native[mapping],committed.astype(np.float32))
                    and np.all(abs(authoring-reference)<=tolerance[mapping])):
                return expected
        except (ValueError,KeyError,IndexError,np.linalg.LinAlgError):continue
    raise ValueError('原模型与分区副本的基型或位置不一致，请重新创建分区；未开始表情计算')


def record(result,binding):
    target,vertices,faces=binding
    result['ek_commit_target']=target
    result['ek_commit_vertices']=json.dumps(vertices)
    result['ek_commit_faces']=json.dumps(faces)
    result['ek_commit_topology']=topology_stamp(target.data)
    mapping=[vertices[row.value] for row in result.data.attributes['ek_vertex_origin'].data]
    native,_,_=basis_alignment(result,target,mapping)
    attribute=result.data.attributes.get(LOCAL_BASIS) or result.data.attributes.new(LOCAL_BASIS,'FLOAT_VECTOR','POINT')
    attribute.data.foreach_set('vector',native.ravel())
    result['ek_commit_basis_record']=1


def validate(result,target):
    A.check_mesh(target)
    if target==result or result.get('ek_commit_target')!=target or result.get('ek_transfer_target')!=target:
        raise ValueError('结果的写入对象与当前需添加表情的模型不一致，请为当前目标重新生成表情')
    if target.library or target.data.library:raise ValueError('请先为链接模型建立本地覆盖')
    if topology_stamp(target.data)!=result.get('ek_commit_topology'):
        raise ValueError('原模型拓扑已变化，请重新生成分区和表情')
    vertices=json.loads(result['ek_commit_vertices']);faces=json.loads(result['ek_commit_faces'])
    if (len(set(vertices))!=len(vertices) or len(set(faces))!=len(faces)
            or any(i<0 or i>=len(target.data.vertices) for i in vertices)
            or any(i<0 or i>=len(target.data.polygons) for i in faces)):
        raise ValueError('结果的原模型索引无效，请重新生成')
    original_faces=json.loads(result['ek_original_faces'])
    if len(original_faces)!=len(faces):raise ValueError('结果面数与原模型对应不完整，请重新生成')
    for polygon,index in zip(original_faces,faces):
        if [vertices[i] for i in polygon]!=list(target.data.polygons[index].vertices):
            raise ValueError('结果的面对应已失效，请重新生成')
    vertex_attr=result.data.attributes.get('ek_vertex_origin');face_attr=result.data.attributes.get('ek_face_origin')
    if not vertex_attr or not face_attr:raise ValueError('结果缺少顶点及面对应，请重新生成')
    if (vertex_attr.domain!='POINT' or face_attr.domain!='FACE'
            or any(row.value<0 or row.value>=len(vertices) for row in vertex_attr.data)
            or any(row.value<0 or row.value>=len(faces) for row in face_attr.data)):
        raise ValueError('结果的顶点或面索引越界，请重新生成')
    mapping=[vertices[row.value] for row in vertex_attr.data]
    origins=[faces[row.value] for row in face_attr.data]
    if len(origins)!=len(faces) or set(origins)!=set(faces):raise ValueError('结果面对应重复或缺失，请重新生成')
    for polygon,index in zip(result.data.polygons,origins):
        if [mapping[i] for i in polygon.vertices]!=list(target.data.polygons[index].vertices):
            raise ValueError('结果拓扑不是原面对应的共享边界拆分，请重新生成')
    return target,mapping,origins


def stage_geometry(staged,result,mapping,origins):
    """Keep the full original mesh; only duplicate the result's shared rim IDs.

    Original face/loop data, materials, weights and non-head geometry stay on
    the staged mesh. Keep its copied Key datablock and animation: BMesh copies
    the shape layers onto split vertices, and apply() restores their coordinates
    by origin. Return full-mesh origins and result-to-full vertex IDs.
    """
    bm=bmesh.new()
    try:
        bm.from_mesh(staged.data);bm.verts.ensure_lookup_table();bm.faces.ensure_lookup_table()
        source_vertices=list(bm.verts);source_faces=list(bm.faces)
        base_ids={v:i for i,v in enumerate(source_vertices)};used=set();mapped=[]
        for index in mapping:
            vertex=source_vertices[index]
            if index in used:vertex=bm.verts.new(vertex.co,vertex);base_ids[vertex]=index
            used.add(index);mapped.append(vertex)
        for polygon,index in zip(result.data.polygons,origins):
            old=source_faces[index];vertices=[mapped[i] for i in polygon.vertices]
            if vertices==list(old.verts):continue
            new=bm.faces.new(vertices,old)
            for dst,src in zip(new.loops,old.loops):dst.copy_from(src)
            bm.faces.remove(old)
        bm.verts.index_update()
        full_origins=[base_ids[v] for v in bm.verts]
        result_indices=[v.index for v in mapped]
        bm.to_mesh(staged.data)
    finally:bm.free()
    staged.data.update()
    return full_origins,result_indices
