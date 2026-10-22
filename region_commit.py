"""Apply reviewed keys to the original target without replacing its mesh layout."""
import json
import bpy
from . import region_blender as A
from .region_rigid_parts import mask_part

PARTS=('teeth','mouth','teeth_upper','teeth_lower','mouth_upper','mouth_lower')


def validate(target, result):
    A.check_mesh(target);A.check_mesh(result)
    if result.get('ek_oral_motion_version',0)<1:
        raise ValueError('口腔表情算法已更新，请重新迁移表情后再确认')
    if target==result or A.is_working(target):
        raise ValueError('覆盖目标必须是需添加表情的模型')
    if target.library or target.data.library:
        raise ValueError('目标来自链接库，请先建立本地覆盖')
    if result.get('ek_transfer_target')!=target:
        raise ValueError('结果不属于当前原始目标，请重新迁移表情')
    a,b=target.data,result.data
    if len(a.vertices)!=len(b.vertices) or [tuple(p.vertices) for p in a.polygons]!=[tuple(p.vertices) for p in b.polygons]:
        raise ValueError('原始目标拓扑已变化，请重新生成分区并迁移')
    keys=b.shape_keys
    if not keys or not keys.use_relative or len(keys.key_blocks)<2:
        raise ValueError('结果中没有可确认的相对表情形态键')
    if a.shape_keys and not a.shape_keys.use_relative:
        raise ValueError('原始目标使用绝对形态键，不能覆盖为相对表情')
    basis=a.shape_keys.reference_key.data if a.shape_keys else a.vertices
    extent=max((v.co.length for v in basis),default=1)
    convert=target.matrix_world.inverted()@result.matrix_world
    original=b.attributes.get('ek_neutral_original_basis') if (result.get('ek_neutral_adjusted') or result.get('ek_neutral_mouth_closed')) else None
    if result.get('ek_neutral_mouth_closed') and (original is None or original.domain!='POINT' or len(original.data)!=len(b.vertices)):
        raise ValueError('闭嘴基型缺少原始目标记录，请重新迁移')
    reference=[row.vector for row in original.data] if original else [row.co for row in keys.reference_key.data]
    if any((v.co-convert@w).length>max(extent*1e-6,1e-7) for v,w in zip(basis,reference)):
        raise ValueError('原始目标的基础形状已变化，请重新生成分区并迁移')
    if a.shape_keys and a.shape_keys.reference_key.name in [key.name for key in keys.key_blocks if key!=keys.reference_key]:
        raise ValueError('迁移表情名称与目标基础形态键重名，请先重命名')
    parts={}
    for kind in PARTS:
        name=result.get('ek_rigid_'+kind,'');part=bpy.data.objects.get(name)
        if name and part is None:raise ValueError('口腔部件已被删除，请重新执行表情迁移')
        if part:
            faces=json.loads(part.get('ek_rigid_faces','[]'))
            vertices=json.loads(part.get('ek_rigid_vertices','[]'))
            if (part.parent!=result or len(faces)!=len(part.data.polygons) or
                    len(vertices)!=len(part.data.vertices) or any(i<0 or i>=len(a.polygons) for i in faces) or
                    any(i<0 or i>=len(a.vertices) for i in vertices)):
                raise ValueError('口腔部件缺少原面对应记录，请重新执行表情迁移')
            parts[kind]=part
    return parts


def apply(target, result):
    if result.get('ek_procedural_version',0)>=4:
        from . import procedural_oral
        return procedural_oral.apply(target,result)
    parts=validate(target,result)
    old_mesh=target.data
    # Prepare everything against a private mesh. Failures before commit cannot
    # mutate keys, materials or shared geometry on the user's original object.
    staged=target.copy();staged.data=old_mesh.copy()
    children={};backup=None;new_groups=[];new_masks=[]
    old_parts={kind:bpy.data.objects.get(target.get('ek_rigid_'+kind,'')) for kind in PARTS}
    old_mask_names=json.loads(target.get('ek_committed_masks','[]'))
    if target.get('ek_committed_mask'):old_mask_names.append(target['ek_committed_mask'])
    old_masks=[target.modifiers.get(name) for name in set(old_mask_names)]
    try:
        if not staged.data.shape_keys:staged.shape_key_add(name='Basis',from_mix=False)
        keys=staged.data.shape_keys;incoming=result.data.shape_keys
        convert=target.matrix_world.inverted()@result.matrix_world
        if result.get('ek_neutral_adjusted') or result.get('ek_neutral_mouth_closed'):
            shifts=[convert@new.co-old.co for old,new in zip(keys.reference_key.data,incoming.reference_key.data)]
            for key in keys.key_blocks:
                for point,shift in zip(key.data,shifts):point.co+=shift
            for point,keypoint in zip(staged.data.vertices,keys.reference_key.data):point.co=keypoint.co
        if keys.animation_data:
            for curve in keys.animation_data.drivers:
                for variable in curve.driver.variables:
                    for driver_target in variable.targets:
                        if driver_target.id==old_mesh.shape_keys:driver_target.id=keys
        mapped={incoming.reference_key.name:keys.reference_key}
        for key in incoming.key_blocks:
            if key==incoming.reference_key:continue
            dest=keys.key_blocks.get(key.name)
            fresh=dest is None
            if fresh:dest=staged.shape_key_add(name=key.name,from_mix=False)
            for a,b in zip(dest.data,key.data):a.co=convert@b.co
            dest.slider_min=key.slider_min;dest.slider_max=key.slider_max
            if fresh:dest.value=0
            mapped[key.name]=dest
        for key in incoming.key_blocks:
            if key!=incoming.reference_key:
                mapped[key.name].relative_key=mapped.get(key.relative_key.name,keys.reference_key)
        for kind,part in parts.items():
            child=part.copy();child.data=part.data.copy();child.name=target.name+'_Rigid'+kind.title()
            children[kind]=child
            child.data.materials.clear()
            for slot in target.material_slots:child.data.materials.append(slot.material)
            for poly,index in zip(child.data.polygons,json.loads(part['ek_rigid_faces'])):
                poly.material_index=old_mesh.polygons[index].material_index
            if child.animation_data:
                for curve in child.animation_data.drivers:
                    for variable in curve.driver.variables:
                        for driver_target in variable.targets:
                            if driver_target.id==incoming:driver_target.id=keys
                            elif driver_target.id==part:driver_target.id=child
            child.parent=target;child.matrix_parent_inverse=target.matrix_world.inverted()
            child['ek_rigid_owner']=target.name;child['ek_committed_rigid']=True
        # Keep an in-file backup, including existing keys and modifier settings.
        backup=target.copy();backup.name=target.name+'_EK_覆盖前备份';backup[A.TAG]=True
        backup['ek_original_backup']=target.name;backup.hide_render=True
        A.new_collection('EK_覆盖前备份').objects.link(backup)
        backup.hide_set(True);backup.hide_viewport=True
        target.data=staged.data
        for kind,child in children.items():
            (target.users_collection[0] if target.users_collection else bpy.context.scene.collection).objects.link(child)
            new_mask,new_group,_=mask_part(target,json.loads(child['ek_rigid_faces']),json.loads(child['ek_rigid_vertices']),kind)
            new_masks.append(new_mask)
            if new_group:new_groups.append(new_group)
            child.hide_viewport=target.hide_viewport;child.hide_render=target.hide_render
        for kind,old_rigid in old_parts.items():
            if old_rigid and old_rigid.get('ek_committed_rigid'):
                old_rigid.hide_viewport=True;old_rigid.hide_render=True
                # Preserve the old part and its old key drivers on the backup.
                inverse=old_rigid.matrix_parent_inverse.copy()
                old_rigid.parent=backup;old_rigid.matrix_parent_inverse=inverse
                old_rigid['ek_rigid_owner']=backup.name;old_rigid['ek_committed_rigid']=False
            if kind in children:target['ek_rigid_'+kind]=children[kind].name
            elif 'ek_rigid_'+kind in target:del target['ek_rigid_'+kind]
        for old_mask in old_masks:
            if old_mask:target.modifiers.remove(old_mask)
        target['ek_committed_masks']=json.dumps([mask.name for mask in new_masks])
        target['ek_rigid_parts']=json.dumps({kind:child.name for kind,child in children.items()})
        if 'ek_committed_mask' in target:del target['ek_committed_mask']
        result['ek_confirmed_target']=target
        result['ek_confirmation_backup']=backup.name
        return len(mapped)-1,backup,list(children.values())
    except Exception:
        target.data=old_mesh
        for mask in new_masks:target.modifiers.remove(mask)
        for group in new_groups:target.vertex_groups.remove(group)
        for child in children.values():
            mesh=child.data;bpy.data.objects.remove(child,do_unlink=True)
            if mesh.users==0:bpy.data.meshes.remove(mesh)
        if backup:bpy.data.objects.remove(backup,do_unlink=True)
        raise
    finally:
        mesh=staged.data;bpy.data.objects.remove(staged,do_unlink=True)
        if mesh.users==0:bpy.data.meshes.remove(mesh)
