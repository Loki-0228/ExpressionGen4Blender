"""One-mesh oral groups: rigid dental jaws and directly lip-attached lining."""
import json
import bpy,bmesh
import numpy as np
from mathutils import Vector,Matrix
from . import region_blender as A
from .region_rigid_parts import drive_channel


def bone_kind(kind,kinds):
    """Use the same jaw owner during solving and in the final armature."""
    tooth=kind.replace('mouth_','teeth_',1)
    return tooth if kind.startswith('mouth_') and tooth in kinds else kind


def key_coordinates(basis,delta,mapping,groups,oral,static_eyes):
    mapping=np.asarray(mapping);coordinates=basis+delta[mapping]
    for kind,ids in groups.items():
        coordinates[ids]=basis[ids]
        if kind in oral:coordinates[ids]+=oral[kind][mapping[ids]]
    coordinates[static_eyes]=basis[static_eyes]
    if '_eyes' in oral:coordinates[static_eyes]+=oral['_eyes'][mapping[static_eyes]]
    return coordinates


def baked_shapes(rig,recipe,shapes):
    """Store the evaluated oral pose in keys, independent of helper bones."""
    from .procedural_cavity import part_pose
    result={kind:value.copy() for kind,value in shapes.items()}
    for kind in rig.oral_parts:
        # Lining already contains its final lip-attached motion. Only teeth
        # store a residual deformation before the rigid jaw pose.
        if not kind.startswith('teeth_'):continue
        ids,center,rotation,translation=part_pose(rig,recipe,kind)
        rest=rig.cavity_points if kind.startswith('mouth_') else rig.original_points
        shape=result.setdefault(kind,np.zeros_like(rig.points))
        cloud=rest[ids]+shape[ids]
        shape[ids]=(cloud-center)@rotation.T+center+translation-rest[ids]
    return result


def geometry(output,rig):
    """Only split shared rim vertices; all faces remain in the same object."""
    eye_faces={i for i,label in enumerate(rig.info['labels']) if label in (3,5,7)}
    split_groups=list(rig.oral_parts.values())+([sorted(eye_faces)] if eye_faces else [])
    bm=bmesh.new()
    try:
        bm.from_mesh(output.data)
        bm.verts.ensure_lookup_table();bm.faces.ensure_lookup_table()
        origin=bm.verts.layers.int.get('ek_vertex_origin') or bm.verts.layers.int.new('ek_vertex_origin')
        face_origin=bm.faces.layers.int.get('ek_face_origin') or bm.faces.layers.int.new('ek_face_origin')
        for i,v in enumerate(bm.verts):v[origin]=i
        for i,f in enumerate(bm.faces):f[face_origin]=i
        original_faces=list(bm.faces)
        for indices in split_groups:
            selected={original_faces[i] for i in indices};vertices={v for f in selected for v in f.verts}
            shared={v for v in vertices if any(f not in selected for f in v.link_faces)}
            # Blender 4.5 copy_from() can invalidate the destination Python
            # handle while copying custom data. Constructor examples copy the
            # data before returning a handle, preserving weights and origins.
            replacements={v:bm.verts.new(v.co,v) for v in shared}
            for f in selected:
                if not any(v in shared for v in f.verts):continue
                new=bm.faces.new([replacements.get(v,v) for v in f.verts],f)
                # Preserve UV/color corner data. Do not reuse a destination
                # loop handle after copy_from(); the face handle stays valid.
                for a,b in zip(new.loops,f.loops):a.copy_from(b)
                bm.faces.remove(f)
        bm.to_mesh(output.data)
    finally:
        bm.free()
    output.data.update();groups={}
    mapping=[row.value for row in output.data.attributes['ek_vertex_origin'].data]
    origins=[row.value for row in output.data.attributes['ek_face_origin'].data]
    for kind,indices in rig.oral_parts.items():
        groups[kind]=sorted({v for f,original in zip(output.data.polygons,origins) if original in indices for v in f.vertices})
    # Face can include a connected eye-pocket backing. Its copy of the rim
    # stays at Basis while the skin copy closes in front of it. Keep the same
    # mesh, UVs and original material mapping; eye keys store ordered retreat.
    output['ek_static_eye_vertices']=json.dumps(sorted({v for f,original in zip(output.data.polygons,origins)
                                                       if original in eye_faces for v in f.vertices}))
    output['ek_oral_groups']=json.dumps(groups)
    output['ek_original_faces']=json.dumps(rig.info['faces'])
    return mapping,groups


def create(output,rig,parts):
    if not parts:return None
    arm=bpy.data.armatures.new(output.name+'_口腔约束')
    ob=bpy.data.objects.new(arm.name,arm);output.users_collection[0].objects.link(ob)
    ob.matrix_world=output.matrix_world.copy();ob.parent=output;ob.matrix_parent_inverse=output.matrix_world.inverted()
    ob[A.TAG]=True;ob['ek_oral_owner']=output;ob.hide_render=True;ob.display_type='WIRE'
    previous=bpy.context.view_layer.objects.active
    if bpy.context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    selected=list(bpy.context.selected_objects)
    for item in selected:item.select_set(False)
    ob.select_set(True);bpy.context.view_layer.objects.active=ob
    bpy.ops.object.mode_set(mode='EDIT')
    groups=json.loads(output['ek_oral_groups'])
    kinds={part.kind for part in parts}
    binding={kind:bone_kind(kind,kinds) for kind in kinds}
    for part in parts:
        if binding[part.kind]!=part.kind:continue
        bone=arm.edit_bones.new('EK_oral_'+part.kind)
        bone.head=output.matrix_world.inverted()@Vector(part.center)
        bone.tail=bone.head+Vector((0,max(part.width*.2,.001),0))
    bpy.ops.object.mode_set(mode='OBJECT')
    for part in parts:
        name='EK_oral_'+binding[part.kind]
        group=output.vertex_groups.get(name) or output.vertex_groups.new(name=name)
        group.remove(list(range(len(output.data.vertices))))
        group.add(groups[part.kind],1.,'REPLACE')
        bone=ob.pose.bones[name];bone.rotation_mode='XYZ'
    ob.select_set(False)
    for item in selected:
        if item.name in bpy.context.view_layer.objects:item.select_set(True)
    bpy.context.view_layer.objects.active=previous
    modifier=output.modifiers.new('EK_口腔刚性约束','ARMATURE');modifier.object=ob
    modifier.use_vertex_groups=True;modifier.use_bone_envelopes=False
    output['ek_oral_armature']=ob
    store={part.kind:{name:[v.tolist() for v in pose] for name,pose in part.poses.items()} for part in parts if binding[part.kind]==part.kind}
    output['ek_oral_bone_groups']=json.dumps(binding)
    output['ek_oral_poses']=json.dumps(store)
    rebuild_drivers(output)
    ob.hide_set(True)
    return ob


def rebuild_drivers(output):
    ob=output.get('ek_oral_armature')
    if not ob:return
    if ob.animation_data:ob.animation_data_clear()
    rotation=np.array(output.matrix_world.to_quaternion().to_matrix())
    scale=np.array(output.matrix_world.to_scale())
    for kind,poses in json.loads(output['ek_oral_poses']).items():
        bone=ob.pose.bones.get('EK_oral_'+kind)
        if bone is None:continue
        local={}
        for name,pose in poses.items():
            translation=rotation.T@np.array(pose[0])/np.maximum(np.abs(scale),1e-9)
            from mathutils import Euler
            world=np.array(Euler(tuple(pose[1]),'XYZ').to_matrix())
            euler=np.array(Matrix((rotation.T@world@rotation).tolist()).to_euler('XYZ'))
            local[name]=(translation,euler)
        for channel,path in enumerate(('location','rotation_euler')):
            full=bone.path_from_id(path)
            for axis in range(3):
                rows=[(name,float(values[channel][axis])) for name,values in local.items() if abs(values[channel][axis])>1e-9]
                if rows:drive_channel(ob,full,axis,rows,output.data.shape_keys)


def retarget_drivers(owner,old_key,new_key):
    """Follow a replaced Key without clearing drivers this apply does not own.

    Only variables whose target id is the old Key are rewritten; unknown
    drivers and unrelated targets stay untouched. Return the changed targets
    so a failed apply can restore the old references.
    """
    if old_key is None or new_key is None:return []
    animation=getattr(owner,'animation_data',None)
    if animation is None:return []
    changed=[]
    for curve in animation.drivers:
        for variable in curve.driver.variables:
            for driver_target in variable.targets:
                if driver_target.id==old_key:
                    driver_target.id=new_key;changed.append(driver_target)
    return changed


def restore_driver_targets(targets,new_key,old_key):
    """Point retargeted variables back before the staged Key is discarded."""
    for driver_target in targets:
        if driver_target.id==new_key:driver_target.id=old_key


def apply(target,result):
    """Write the one-mesh result back, preserving old keys and original materials."""
    from . import procedural_generate as P,procedural_commit as Commit
    if result.get('ek_procedural_version')!=P.VERSION:raise ValueError('结果格式不属于当前版本，请重新生成表情')
    if result.get('ek_transfer_target')!=target:raise ValueError('结果不属于当前目标')
    if result.get('ek_confirmed_target')==target:raise ValueError('该结果已经写入当前目标，无需重复覆盖')
    target,mapping,origins=Commit.validate(result,target);old=target.data
    old_basis=old.shape_keys.reference_key.data if old.shape_keys else old.vertices
    native,original,linear=Commit.basis_alignment(result,target,mapping)
    convert=target.matrix_world.inverted()@result.matrix_world
    if old.shape_keys and not old.shape_keys.use_relative:raise ValueError('不能覆盖绝对形态键')
    if old.shape_keys and old.shape_keys.reference_key.name in [k.name for k in result.data.shape_keys.key_blocks[1:]]:
        raise ValueError('表情名称与原始 Basis 重名，请先重命名')
    staged=target.copy();staged.data=old.copy();arm=None;backup=None;backup_arm=None;new_groups=[];mod=None
    new_key=None;rebound=[]
    previous_arm=target.get('ek_oral_armature');previous_poses=target.get('ek_oral_poses')
    try:
        # Transfer reviewed displacements around the untouched native Basis.
        # Unmoved vertices remain exact even with tiny import scales/offsets.
        incoming=[(k.name,native+(Commit.coordinates(k.data)-original)@linear.T,k.slider_min,k.slider_max)
                  for k in result.data.shape_keys.key_blocks]
        full_origins,result_indices=Commit.stage_geometry(staged,result,mapping,origins)
        full_origins=np.asarray(full_origins,dtype=np.int32)
        basis=(staged.data.shape_keys.reference_key if staged.data.shape_keys
               else staged.shape_key_add(name='Basis',from_mix=False))
        new_key=staged.data.shape_keys
        original_basis=Commit.coordinates(old_basis)[full_origins]
        committed_basis=original_basis.copy()
        committed_basis[result_indices]=incoming[0][1]
        basis.data.foreach_set('co',committed_basis.ravel())
        # Use the stored float32 Basis for relative offsets, while calculating
        # them in float64. A zero shift must leave an old key bit-for-bit intact.
        committed_basis=Commit.coordinates(basis.data)
        neutral_shift=committed_basis-original_basis
        staged.data.vertices.foreach_set('co',committed_basis.ravel())
        if old.shape_keys:
            for key in old.shape_keys.key_blocks[1:]:
                dest=staged.data.shape_keys.key_blocks[key.name]
                dest.data.foreach_set('co',(Commit.coordinates(key.data)[full_origins]+neutral_shift).ravel())
            # Mesh.copy() retains Key settings, drivers, Action slots and NLA,
            # including structures the public API cannot reconstruct. Only
            # self-references must follow the private copy; no id_type writes.
            retarget_drivers(staged.data.shape_keys,old.shape_keys,staged.data.shape_keys)
        for name,coords,minimum,maximum in incoming[1:]:
            key=staged.data.shape_keys.key_blocks.get(name) or staged.shape_key_add(name=name,from_mix=False)
            previous=old.shape_keys.key_blocks.get(name) if old.shape_keys else None
            if previous and previous.relative_key!=old.shape_keys.reference_key:
                residual=Commit.coordinates(previous.data)-Commit.coordinates(previous.relative_key.data)
                key.data.foreach_set('co',(committed_basis+residual[full_origins]).ravel())
            for index,co in zip(result_indices,coords):key.data[index].co=co
            key.relative_key=basis;key.slider_min=minimum;key.slider_max=maximum;key.value=0;key.mute=False;key.vertex_group=''
        if result.get('ek_topology_transfer') and old.shape_keys:
            # Preserve the relative offsets of untouched keys even when their
            # parent was replaced by this batch.
            changed={name for name,_,_,_ in incoming[1:]}
            children={}
            for previous in old.shape_keys.key_blocks[1:]:
                if previous.name not in changed and previous.relative_key!=previous:
                    children.setdefault(previous.relative_key.name,[]).append(previous)
            pending=list(changed)
            while pending:
                parent=pending.pop()
                for child in children.get(parent,[]):
                    parent_points=Commit.coordinates(new_key.key_blocks[parent].data)
                    offset=Commit.coordinates(child.data)-Commit.coordinates(child.relative_key.data)
                    new_key.key_blocks[child.name].data.foreach_set('co',(parent_points+offset[full_origins]).ravel())
                    pending.append(child.name)
        # The full original mesh already carries original materials, UVs and
        # body weights. Only copy generated jaw groups into its vertex range.
        oral_names={'EK_oral_'+name for name in json.loads(result.get('ek_oral_bone_groups','{}')).values()}
        for name in sorted(oral_names):
            source_group=result.vertex_groups.get(name)
            if source_group is None:raise ValueError('结果缺少口腔约束顶点组，请重新生成')
            group=staged.vertex_groups.get(name) or staged.vertex_groups.new(name=name)
            group.remove(result_indices)
            for vertex,index in zip(result.data.vertices,result_indices):
                for weight in vertex.groups:
                    if weight.group==source_group.index:group.add([index],weight.weight,'REPLACE')
        for group in staged.vertex_groups:
            existing=target.vertex_groups.get(group.name)
            if existing is None:existing=target.vertex_groups.new(name=group.name);new_groups.append(existing)
            if existing.index!=group.index:raise ValueError('原模型顶点组顺序已变化，请重新生成')
        original_arm=result.get('ek_oral_armature')
        if original_arm:
            arm=original_arm.copy();arm.data=original_arm.data.copy();arm.animation_data_clear()
            arm.data.transform(convert)
            (target.users_collection[0] if target.users_collection else bpy.context.scene.collection).objects.link(arm)
            arm.parent=target;arm.matrix_parent_inverse=target.matrix_world.inverted();arm.matrix_world=target.matrix_world.copy()
            arm['ek_oral_owner']=target
        backup_collection=A.new_collection('EK_覆盖前备份')
        backup=target.copy();backup.name=target.name+'_EK_覆盖前备份';backup[A.TAG]=True
        backup_collection.objects.link(backup);backup.hide_set(True);backup.hide_render=True
        if previous_arm and not arm:
            # The backup must keep the old driver semantics. Copy the armature
            # before the live one is retargeted, then point the backup's own
            # modifier and owner at the copy: it still reads the old Key.
            backup_arm=previous_arm.copy();backup_arm.data=previous_arm.data.copy()
            backup_arm.name=previous_arm.name+'_EK_覆盖前备份'
            backup_collection.objects.link(backup_arm)
            backup_arm.parent=backup;backup_arm.matrix_parent_inverse=previous_arm.matrix_parent_inverse.copy()
            backup_arm.matrix_world=previous_arm.matrix_world.copy()
            backup_arm['ek_oral_owner']=backup
            backup_arm.hide_set(True);backup_arm.hide_render=True
            for backup_modifier in backup.modifiers:
                if backup_modifier.type=='ARMATURE' and backup_modifier.object==previous_arm:
                    backup_modifier.object=backup_arm
            if backup.get('ek_oral_armature')==previous_arm:backup['ek_oral_armature']=backup_arm
        target.data=staged.data
        if arm:
            mod=target.modifiers.new('EK_口腔刚性约束','ARMATURE');mod.object=arm
            # Deform rigid groups before the target's existing body rig.
            with bpy.context.temp_override(object=target,active_object=target):
                bpy.ops.object.modifier_move_to_index(modifier=mod.name,index=0)
            target['ek_oral_armature']=arm
            # Batches accumulate: keep earlier batches' poses, let this batch override same-named keys.
            merged=json.loads(previous_poses) if previous_poses else {}
            for kind,rows in json.loads(result['ek_oral_poses']).items():merged.setdefault(kind,{}).update(rows)
            target['ek_oral_poses']=json.dumps(merged);rebuild_drivers(target);arm.hide_set(True)
        elif previous_arm:
            # This batch adds no armature. Keep the earlier armature, its poses
            # and its modifier exactly as they were; only its Key references
            # must follow the staged mesh. rebuild_drivers() is deliberately
            # not called here because it would clear unknown drivers.
            rebound+=retarget_drivers(previous_arm,old.shape_keys,new_key)
            rebound+=retarget_drivers(previous_arm.data,old.shape_keys,new_key)
        else:
            for name in ('ek_oral_armature','ek_oral_poses'):
                if name in target:del target[name]
        if arm or not previous_arm:
            for old_mod in list(target.modifiers):
                if old_mod!=mod and old_mod.type=='ARMATURE' and old_mod.object and old_mod.object.get('ek_oral_owner')==target:
                    target.modifiers.remove(old_mod)
        if result.get('ek_topology_transfer'):
            rebound+=retarget_drivers(target,old.shape_keys,new_key)
            for child in target.children:
                if child.get('ek_committed_rigid') or child.get('ek_material_expression'):
                    rebound+=retarget_drivers(child,old.shape_keys,new_key)
                    rebound+=retarget_drivers(child.data.shape_keys if child.type=='MESH' else child.data,old.shape_keys,new_key)
        partition=result.get('ek_procedural_partition')
        if partition:
            from . import region_guides as G
            target.data['ek_regeneration_state']=json.dumps(dict(
                target=Commit.basis_signature(target),
                partition=G.fingerprint(partition,partition,None,include_regions=False)))
        result['ek_confirmed_target']=target;result['ek_confirmation_backup']=backup.name
        target.active_shape_key_index=0;target.show_only_shape_key=False
        return len(incoming)-1,backup,[]
    except Exception:
        target.data=old
        restore_driver_targets(rebound,new_key,old.shape_keys)
        for name,value in (('ek_oral_armature',previous_arm),('ek_oral_poses',previous_poses)):
            if value is not None:target[name]=value
            elif name in target:del target[name]
        if mod:target.modifiers.remove(mod)
        for group in new_groups:target.vertex_groups.remove(group)
        if backup_arm:bpy.data.objects.remove(backup_arm,do_unlink=True)
        if arm:bpy.data.objects.remove(arm,do_unlink=True)
        if backup:bpy.data.objects.remove(backup,do_unlink=True)
        raise
    finally:
        mesh=staged.data;bpy.data.objects.remove(staged,do_unlink=True)
        if not mesh.users:bpy.data.meshes.remove(mesh)
