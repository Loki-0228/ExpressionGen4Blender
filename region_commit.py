"""Apply reviewed keys to the original target without replacing its mesh layout."""
import json
import bpy
from . import region_blender as A
from .region_rigid_parts import mask_part

PARTS=('teeth','mouth','teeth_upper','teeth_lower','mouth_upper','mouth_lower')
TEETH_MASK='牙齿由独立刚体副本显示'
TEETH_GROUP='EK_RigidTeeth_HiddenInSkin'
MOUTH_MASK='口腔由整体变换副本显示'
MOUTH_NODES='EK_口腔面隐藏'
_MISSING=object()


def _mask_category(kind):
    """mask_part hides teeth with a vertex-group mask and oral parts with faces."""
    return 'teeth' if kind=='teeth' else 'mouth'


def _mask_category_of(mask):
    """Match a committed modifier to the branch mask_part used for its kind."""
    if mask is None:return None
    if mask.type=='MASK':
        if mask.name.startswith(TEETH_MASK) or (mask.vertex_group or '').startswith(TEETH_GROUP):return 'teeth'
    elif mask.type=='NODES':
        group=getattr(mask,'node_group',None)
        if mask.name.startswith(MOUTH_MASK) or (group is not None and group.name.startswith(MOUTH_NODES)):return 'mouth'
    return None


def _driver_targets(part):
    if not part.animation_data:return []
    return [target for curve in part.animation_data.drivers
            for variable in curve.driver.variables for target in variable.targets]


def _driver_key_names(part,keys):
    """Key block names followed by a part's drivers; None marks an unresolved path."""
    if keys is None:return []
    paths={block.path_from_id('value'):block.name for block in keys.key_blocks}
    return [paths.get(target.data_path) for target in _driver_targets(part) if target.id==keys]


def _save_props(ob,names):
    return {name:(ob[name] if name in ob else _MISSING) for name in names}


def _restore_props(ob,snapshot):
    for name,value in snapshot.items():
        if value is _MISSING:
            if name in ob:del ob[name]
        else:ob[name]=value


def _save_part(part):
    return dict(parent=part.parent,inverse=part.matrix_parent_inverse.copy(),
                hide_viewport=part.hide_viewport,hide_render=part.hide_render,
                props=_save_props(part,('ek_rigid_owner','ek_committed_rigid')))


def _restore_part(part,state):
    part.parent=state['parent'];part.matrix_parent_inverse=state['inverse']
    part.hide_viewport=state['hide_viewport'];part.hide_render=state['hide_render']
    _restore_props(part,state['props'])


def _key_block_of(old_keys,data_path):
    for block in old_keys.key_blocks:
        if block.path_from_id('value')==data_path:return block
    return None


def _check_key_drivers(part,old_keys,new_keys,kind):
    """Refuse a commit that would silently leave a part driving missing keys."""
    if old_keys is None:return
    if new_keys is None:raise ValueError('「%s」刚体驱动无法合并：形态键缺失'%kind)
    for target in _driver_targets(part):
        if target.id!=old_keys:continue
        block=_key_block_of(old_keys,target.data_path)
        if block is None or new_keys.key_blocks.get(block.name) is None:
            raise ValueError('「%s」刚体驱动引用的形态键不在合并后的形态键中，无法安全合并，请重新迁移口腔表情后再确认'%kind)


def _check_replaced_drivers(kind,old,part,incoming,old_keys):
    """Refuse replacing a kind when this batch drops a key the old part drove."""
    if old is None or not old.get('ek_committed_rigid'):return
    carried={name for name in _driver_key_names(part,incoming) if name is not None}
    batch={block.name for block in incoming.key_blocks}
    lost={name for name in _driver_key_names(old,old_keys) if name is None or name not in batch or name not in carried}
    if lost:
        labels='、'.join(sorted('未识别的形态键' if name is None else name for name in lost))
        raise ValueError('本批没有保留「%s」刚体在上一批的形态键驱动（%s），替换会丢失驱动，请重新生成表情后再确认'%(kind,labels))


def _rebind_drivers(part,old,new):
    if old is None:return 0
    changed=0
    for target in _driver_targets(part):
        if target.id==old:target.id=new;changed+=1
    return changed


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
    children={};backup=None;backup_collection=None;backup_copies={};retired=[]
    new_groups=[];new_masks=[];keys=None
    prop_names=tuple('ek_rigid_'+kind for kind in PARTS)+('ek_rigid_parts','ek_committed_masks','ek_committed_mask','ek_committed_mask_kinds')
    saved_props=_save_props(target,prop_names)
    saved_result=_save_props(result,('ek_confirmed_target','ek_confirmation_backup'))
    old_parts={kind:bpy.data.objects.get(target.get('ek_rigid_'+kind,'')) for kind in PARTS}
    # A batch only replaces the kinds it carries. Committed parts it does not
    # mention stay on the target together with their own masks and key drivers.
    retained={kind:part for kind,part in old_parts.items()
              if kind not in parts and part and part.get('ek_committed_rigid')}
    old_mask_names=json.loads(target.get('ek_committed_masks') or '[]')
    if target.get('ek_committed_mask'):old_mask_names.append(target['ek_committed_mask'])
    old_masks=[target.modifiers.get(name) for name in dict.fromkeys(old_mask_names)]
    try:old_mask_kinds=json.loads(target.get('ek_committed_mask_kinds') or '{}')
    except Exception:old_mask_kinds={}
    if not isinstance(old_mask_kinds,dict):old_mask_kinds={}
    old_mask_kinds={name:kind for name,kind in old_mask_kinds.items() if kind in PARTS}
    retained_categories={_mask_category(kind) for kind in retained}
    kept_masks=[];removed_masks=[]
    for old_mask in old_masks:
        if old_mask is None:continue
        # New records know the exact kind; older targets fall back to the branch
        # mask_part used for teeth versus oral kinds.
        kind=old_mask_kinds.get(old_mask.name)
        if kind is not None:
            (kept_masks if kind in retained else removed_masks).append(old_mask)
            continue
        category=_mask_category_of(old_mask)
        if category is not None and category not in retained_categories:removed_masks.append(old_mask)
        else:kept_masks.append(old_mask)
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
        # These refusals happen before the target data or any old part changes.
        for kind,part in retained.items():
            if part.parent!=target:
                raise ValueError('旧批次「%s」刚体部件已脱离原模型，无法安全保留，请重新迁移口腔表情后再确认'%kind)
            _check_key_drivers(part,old_mesh.shape_keys,keys,kind)
        for kind,part in parts.items():
            _check_replaced_drivers(kind,old_parts.get(kind),part,incoming,old_mesh.shape_keys)
        for kind,part in parts.items():
            child=part.copy();child.data=part.data.copy();child.name=target.name+'_Rigid'+kind.title()
            children[kind]=child
            # The new part must still find every key it drives on the merged keys.
            _check_key_drivers(child,incoming,keys,kind)
            child.data.materials.clear()
            for slot in target.material_slots:child.data.materials.append(slot.material)
            for poly,index in zip(child.data.polygons,json.loads(part['ek_rigid_faces'])):
                poly.material_index=old_mesh.polygons[index].material_index
            if child.animation_data:
                for curve in child.animation_data.drivers:
                    for variable in curve.driver.variables:
                        for driver_target in variable.targets:
                            if driver_target.id==part:driver_target.id=child
            _rebind_drivers(child,incoming,keys)
            child.parent=target;child.matrix_parent_inverse=target.matrix_world.inverted()
            child['ek_rigid_owner']=target.name;child['ek_committed_rigid']=True
        # Keep an in-file backup, including existing keys and modifier settings.
        backup=target.copy();backup.name=target.name+'_EK_覆盖前备份';backup[A.TAG]=True
        backup['ek_original_backup']=target.name;backup.hide_render=True
        backup_collection=A.new_collection('EK_覆盖前备份')
        backup_collection.objects.link(backup)
        backup.hide_set(True);backup.hide_viewport=True
        target.data=staged.data
        for kind,child in children.items():
            (target.users_collection[0] if target.users_collection else bpy.context.scene.collection).objects.link(child)
            new_mask,new_group,_=mask_part(target,json.loads(child['ek_rigid_faces']),json.loads(child['ek_rigid_vertices']),kind)
            new_masks.append(new_mask)
            if new_group:new_groups.append(new_group)
            child.hide_viewport=target.hide_viewport;child.hide_render=target.hide_render
        for kind,old_rigid in old_parts.items():
            if kind in retained:
                # The live part keeps its identity. The backup gets an independent
                # copy that still follows the pre-commit keys.
                part=retained[kind]
                duplicate=part.copy();backup_copies[kind]=duplicate
                duplicate.data=part.data.copy();duplicate.name=part.name+'_覆盖前备份'
                backup_collection.objects.link(duplicate)
                _rebind_drivers(duplicate,part,duplicate)
                inverse=part.matrix_parent_inverse.copy()
                duplicate.parent=backup;duplicate.matrix_parent_inverse=inverse
                duplicate['ek_rigid_owner']=backup.name;duplicate['ek_committed_rigid']=False
                duplicate.hide_viewport=True;duplicate.hide_render=True
                target['ek_rigid_'+kind]=part.name
                continue
            if old_rigid and old_rigid.get('ek_committed_rigid'):
                retired.append((old_rigid,_save_part(old_rigid)))
                old_rigid.hide_viewport=True;old_rigid.hide_render=True
                # Preserve the old part and its old key drivers on the backup.
                inverse=old_rigid.matrix_parent_inverse.copy()
                old_rigid.parent=backup;old_rigid.matrix_parent_inverse=inverse
                old_rigid['ek_rigid_owner']=backup.name;old_rigid['ek_committed_rigid']=False
            if kind in children:target['ek_rigid_'+kind]=children[kind].name
            elif 'ek_rigid_'+kind in target:del target['ek_rigid_'+kind]
        backup_parts=json.loads(backup.get('ek_rigid_parts') or '{}')
        for kind in PARTS:
            if kind in backup_copies:
                backup['ek_rigid_'+kind]=backup_copies[kind].name
                backup_parts[kind]=backup_copies[kind].name
            elif old_parts.get(kind) and old_parts[kind].get('ek_committed_rigid'):
                backup['ek_rigid_'+kind]=old_parts[kind].name
                backup_parts[kind]=old_parts[kind].name
        backup['ek_rigid_parts']=json.dumps(backup_parts)
        # Kept parts now follow the merged key set, not the retired one.
        for part in retained.values():_rebind_drivers(part,old_mesh.shape_keys,keys)
        kept_names=[mask.name for mask in kept_masks]
        target['ek_committed_masks']=json.dumps(kept_names+[mask.name for mask in new_masks if mask.name not in kept_names])
        mask_kinds={}
        for mask in kept_masks:
            kind=old_mask_kinds.get(mask.name)
            if kind is None:
                category=_mask_category_of(mask)
                committed=[name for name in PARTS if old_parts.get(name) and old_parts[name].get('ek_committed_rigid')]
                matches=[name for name in committed if category is not None and _mask_category(name)==category]
                if len(matches)==1:kind=matches[0]
            if kind is not None:mask_kinds[mask.name]=kind
        for kind,mask in zip(children,new_masks):mask_kinds[mask.name]=kind
        target['ek_committed_mask_kinds']=json.dumps(mask_kinds)
        merged_parts={}
        for kind in PARTS:
            if kind in children:merged_parts[kind]=children[kind].name
            elif kind in retained:merged_parts[kind]=retained[kind].name
        target['ek_rigid_parts']=json.dumps(merged_parts)
        if 'ek_committed_mask' in target:del target['ek_committed_mask']
        result['ek_confirmed_target']=target
        result['ek_confirmation_backup']=backup.name
        # Only the replaced kinds lose this batch's masks; do it last so a
        # failed commit can still restore every modifier and property above.
        for old_mask in removed_masks:target.modifiers.remove(old_mask)
        return len(mapped)-1,backup,list(children.values())
    except Exception:
        for duplicate in backup_copies.values():
            mesh=duplicate.data;bpy.data.objects.remove(duplicate,do_unlink=True)
            if mesh.users==0:bpy.data.meshes.remove(mesh)
        backup_copies.clear()
        for part,state in retired:_restore_part(part,state)
        if keys is not None:
            for part in retained.values():_rebind_drivers(part,keys,old_mesh.shape_keys)
        _restore_props(target,saved_props)
        _restore_props(result,saved_result)
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
