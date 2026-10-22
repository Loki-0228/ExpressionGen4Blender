"""Generate Vody-derived expressions with no runtime source model."""
import copy,json
from functools import lru_cache
from pathlib import Path
import bpy
import numpy as np
from mathutils import Matrix,Vector
from . import procedural_rig as R,procedural_atoms as E,region_blender as A,region_guides as G,procedural_oral as Oral
from .region_rigid_parts import RigidTeeth
from . import expression_rules as Rules

VERSION=45


@lru_cache(maxsize=8)
def _profile(library_text,values_text):
    from . import expression_rules as Rules
    data=Rules.builtin_profile()
    library=json.loads(library_text);values=json.loads(values_text)
    Rules.validate_library(library)
    for spec in library:
        stored=values.get(spec['name'],{})
        spec['values']={p['id']:float(np.clip(stored.get(p['id'],p['default']),p['min'],p['max'])) for p in spec['parameters']}
    builtin=data['recipes'];names={s['name'] for s in library}
    data['recipes']=[r for r in builtin if r['name'] not in names]+[Rules.runtime_recipe(spec,builtin) for spec in library]
    return data


def profile_state(scene=None):
    scene=scene or getattr(bpy.context,'scene',None)
    return ((scene.get('ek_expression_library','[]'),scene.get('ek_expression_values','{}')) if scene else ('[]','{}'))


def profile(scene=None):return copy.deepcopy(_profile(*profile_state(scene)))


def catalog(scene=None):return tuple((r['name'],r['family']) for r in _profile(*profile_state(scene))['recipes'])


def rule_signature(scene=None):return G.digest(profile_state(scene))


def prepare(target,partition=None,allow_unmarked=False,partition_method='GEOMETRY'):
    A.check_mesh(target);partition=partition or target;A.check_mesh(partition)
    if len(target.data.vertices)!=len(partition.data.vertices) or [list(p.vertices) for p in target.data.polygons]!=[list(p.vertices) for p in partition.data.polygons]:
        raise ValueError('分区网格与原始目标拓扑不同，请选择该目标的分区副本')
    labels=R.mesh_regions(partition)
    marked=partition!=target or bool(partition.get('ek_standard_slot_labels')) or any(
        slot.material and slot.material.name.startswith(('EK_对应_','EK_不参与_')) for slot in partition.material_slots)
    report=dict(method='existing_marks' if marked else 'material',warnings=[])
    if not marked and partition_method=='GEOMETRY':
        points=A.basis_points(partition);faces=[list(p.vertices) for p in partition.data.polygons]
        labels,report=R.D.infer_regions(points,faces,labels)
        labels,backings=R.D.infer_face_backings(points,faces,labels)
        report['face_backings']=backings;report['present_regions']=backings['present_regions'] if 'present_regions' in backings else sorted(set(labels)-{-1,-2})
    if 0 not in labels and not allow_unmarked:raise ValueError('尚无 Face 分区，请先选择已修正分区，或在目标材质中标记 Face')
    ob=partition.copy();ob.data=partition.data.copy();ob.name=target.name+'_EK_regions'
    # A newly created partition has its own role even when its input is an
    # annotated model. Do not inherit a standard/result/source-copy identity.
    for key in ('ek_standard_version','ek_standard_origin','ek_fitted_source','ek_transfer_target','ek_source_partition_markers',
                'ek_commit_basis_record'):
        if key in ob:del ob[key]
    A.new_collection('EK_面部分区').objects.link(ob);ob[A.TAG]=True
    ob['ek_target_reference']=target;ob['ek_target_object']=target.name
    # Preserve the original Basis, regardless of the current key playback value.
    if ob.data.shape_keys:
        coordinates=[p.co.copy() for p in ob.data.shape_keys.reference_key.data];ob.shape_key_clear()
        for p,co in zip(ob.data.vertices,coordinates):p.co=co
    ob.modifiers.clear();ob.data.materials.clear()
    slots={label:i for i,label in enumerate(sorted(set(labels)|{-1}))}
    for label in slots:ob.data.materials.append(A.marker_material(A.marker_name(label),A.region_color(label)))
    for poly,label in zip(ob.data.polygons,labels):poly.material_index=slots[label]
    ob['ek_standard_slot_labels']=json.dumps({str(slot):label for label,slot in slots.items()})
    ob['ek_region_slots']=json.dumps({str(label):slot for label,slot in slots.items()})
    ob['ek_partition_detection']=json.dumps(report,ensure_ascii=False)
    ob['ek_region_labels']=json.dumps(labels)
    ob['ek_original_materials']=json.dumps([p.material_index for p in target.data.polygons])
    ob['ek_manual_overrides']=partition.get('ek_manual_overrides','{}') if marked else '{}'
    ob.display_type='TEXTURED';ob.show_in_front=False
    return ob


class Part(RigidTeeth):
    def __init__(self,rig,kind,faces):
        self.kind=kind;self.region=9 if kind.startswith('teeth') else 8;self.allow_scale=False
        self.faces=faces;self.target_ids=sorted({i for f in faces for i in rig.info['faces'][f]})
        world=rig.ob.matrix_world
        self.center=np.mean([world@Vector(rig.original_points[i]) for i in self.target_ids],axis=0)
        self.poses={};self.world=world;self.orientation=np.array(world.to_quaternion().to_matrix())
        self.width=rig.widths.get(('LIP',0),rig.info['width']*.1)

    def add_recipe(self,name,recipe):
        pose=recipe.get('oral',{}).get(self.kind)
        if pose:
            rotation=self.orientation@np.array(pose['rotation'])@self.orientation.T
            translation=np.array(self.world.to_3x3()@Vector(np.array(pose['translation'])*self.width))
            euler=np.array(Matrix(rotation.tolist()).to_euler('XYZ'))
        else:translation=np.zeros(3);euler=np.zeros(3)
        self.poses[name]=(translation,euler,np.ones(3))


def generate(target,partition,collection,families=None,strength=1.,lower_lid_scale=1.,selection=None,close_mouth=True,progress=None,
             process_lashes=None,recipe_strengths=None,force_symmetry=False,style_options=None,compute_backend='AUTO'):
    from . import procedural_gpu as GPU
    from . import procedural_commit as Commit
    binding=Commit.original_binding(target)
    if partition.get('ek_target_reference')!=target:
        raise ValueError('分区副本不属于当前需添加表情的模型，请重新选择对应分区或创建目标分区')
    if len(partition.data.vertices)!=len(binding[1]) or [list(p.vertices) for p in partition.data.polygons]!=[list(p.vertices) for p in target.data.polygons]:
        raise ValueError('分区与所选目标的拓扑不一致，请重新创建分区')
    reference=Commit.generation_reference(target,partition)
    GPU.configure(compute_backend)
    if progress:progress('读取分区与检查曲线')
    collection,snapshot=R.checkpoint(partition, collection, process_lashes, recover_lashes=True)
    # Checkpoint may bake the working object's transform before binding.
    reference=Commit.generation_reference(target,partition)
    if progress and hasattr(progress,'describe'):
        progress.describe('生成表情',partition,snapshot,strength=strength,lower_lid_scale=lower_lid_scale,
            close_mouth=close_mouth,selection=sorted(selection) if selection is not None else None,
            families=sorted(families) if families else None,recipe_strengths=recipe_strengths or {},style_options=style_options or {},rule_signature=rule_signature())
    if progress:progress('建立面部与口腔约束')
    rig=R.Rig(partition,snapshot,close_mouth);rig.progress=progress;rig.style_options=dict(style_options or {});data=profile()
    recipes=[r for r in data['recipes'] if (not families or r['family'] in families) and (selection is None or r['name'] in selection)]
    if not recipes:raise ValueError('请至少选择一个表情')
    weights={r['name']:float(np.clip(strength, .05, 1.))*float(np.clip((recipe_strengths or {}).get(r['name'],1.), .0025, 1.)) for r in recipes}
    if not all(np.isfinite(w) for w in weights.values()):raise ValueError('表情幅度必须是有效数字')
    accepted=[];skipped=[];records=[];expression_curves={};effective_recipes={}
    from .expression_relations import Solver
    solver=Solver(rig,data,lower_lid_scale,force_symmetry)
    for number,recipe in enumerate(recipes):
        if progress:progress.batch_step('计算表情',number,len(recipes),recipe['name'])
        family=recipe['family'];reason=None
        if (family in ('mouth','tongue','jaw') or Rules.has_channels(recipe,'mouth','mouth_reference','mouth_targets','tongue','jaw')) and not rig.info['mouth']:reason=rig.incomplete.get(('LIP',0),'缺少可靠的嘴唇边界')
        if any(int(s) not in rig.rings for s in recipe['eyes']):reason='该表情所需的眼部校正曲线不完整，保留未生成状态'
        if recipe.get('brows') and (not rig.brows or any(e['kind']=='BROW' and str(e['side']) in recipe['brows'] for e in snapshot.get('suppressed',[]))):reason='该表情所需的眉毛校正曲线不完整'
        if (family=='tongue' or recipe.get('tongue')) and not rig.tongue:reason='缺少 Tongue 分区或舌头校正曲线'
        if reason:skipped.append(dict(name=recipe['name'],reason=reason));continue
        try:delta,effective,oral,quality,curves=solver.solve(recipe,weights[recipe['name']])
        except ValueError as exc:
            from .procedural_symmetry import SymmetryError
            from .procedural_binding import ClosureStyleError
            if not isinstance(exc,(SymmetryError,ClosureStyleError)) and not recipe.get('custom_rules') and not recipe.get('relation'):raise
            skipped.append(dict(name=recipe['name'],reason=str(exc)));continue
        from .expression_rules import plain
        expression_curves[recipe['name']]=curves
        effective_recipes[recipe['name']]=plain(effective)
        if not np.isfinite(delta).all() or any(not np.isfinite(shape).all() for shape in rig.last_oral_deformation.values()):
            raise ValueError('表情出现无效坐标：'+recipe['name'])
        accepted.append((recipe['name'],delta,effective,oral))
        records.append(dict(name=recipe['name'],**quality))
    if not accepted:raise ValueError('所选表情均已跳过：'+'；'.join(sorted({r['reason'] for r in skipped})))
    if progress:progress.batch_step('创建结果网格',0,0)
    output=partition.copy();output.data=partition.data.copy();output.name=target.name+'_EK_程序化表情'
    A.new_collection('EK_程序化表情').objects.link(output);output.shape_key_clear();output.modifiers.clear()
    try:
        mapping,groups=Oral.geometry(output,rig)
        static_eyes=json.loads(output['ek_static_eye_vertices'])
        basis=rig.points[mapping].copy()
        for kind,ids in groups.items():
            rest=rig.cavity_points if kind.startswith('mouth_') else rig.original_points
            basis[ids]=rest[np.asarray(mapping)[ids]]
        basis[static_eyes]=rig.original_points[np.asarray(mapping)[static_eyes]]
        for vertex,point in zip(output.data.vertices,basis):vertex.co=point
        attribute=output.data.attributes.get('ek_neutral_original_basis') or output.data.attributes.new('ek_neutral_original_basis','FLOAT_VECTOR','POINT')
        for row,point in zip(attribute.data,reference[mapping]):row.vector=point
        output['ek_neutral_adjusted']=not np.allclose(basis,rig.original_points[mapping],atol=1e-10,rtol=0)
        output['ek_neutral_mouth_closed']=bool(rig.neutral_report['changed'])
        output['ek_neutral_tongue_leveled']=bool(rig.tongue_report['changed'])
        output.shape_key_add(name='Basis',from_mix=False)
        for number,(name,delta,recipe,oral) in enumerate(accepted):
            if progress:progress.batch_step('写入形态键',number,len(accepted),name)
            key=output.shape_key_add(name=name,from_mix=False)
            coordinates=Oral.key_coordinates(basis,delta,mapping,groups,Oral.baked_shapes(rig,recipe,oral),static_eyes)
            key.data.foreach_set('co',np.asarray(coordinates,dtype=np.float32).ravel())
            key.slider_min=0;key.slider_max=1
        if progress:progress.batch_step('绑定口腔与牙齿',0,0)
        # The complete oral pose travels with the shape keys, including when
        # copying/exporting them without an auxiliary armature.
        for prop in ('ek_oral_armature','ek_oral_poses','ek_oral_bone_groups'):
            if prop in output:del output[prop]
        output[A.TAG]=True;output['ek_transfer_target']=target;output['ek_oral_motion_version']=3
        Commit.record(output,binding)
    except Exception:
        armature=output.get('ek_oral_armature')
        if armature and armature.get('ek_oral_owner')==output:
            bpy.data.objects.remove(armature,do_unlink=True)
        for child in list(output.children):
            if child.get('ek_rigid_owner')==output.name:bpy.data.objects.remove(child,do_unlink=True)
        mesh=output.data;bpy.data.objects.remove(output,do_unlink=True)
        if not mesh.users:bpy.data.meshes.remove(mesh)
        raise
    output['ek_procedural_version']=VERSION;output['ek_procedural_partition']=partition
    output['ek_procedural_hash']=snapshot['hash'];output['ek_procedural_input']=snapshot['input']
    output['ek_procedural_settings']=json.dumps(dict(strength=strength,lower_lid_scale=lower_lid_scale,close_mouth=close_mouth,
        process_lashes=snapshot.get('process_lashes',True),recipe_weights=weights,style_options=rig.style_options,compute_backend=compute_backend,constraint_mode='LEGACY',
        selection=[r['name'] for r in recipes],recipe_strengths=recipe_strengths or {},force_symmetry=force_symmetry,rule_signature=rule_signature()))
    output['ek_procedural_recipes']=json.dumps([row[0] for row in accepted],ensure_ascii=False)
    output['ek_expression_curves']=json.dumps(expression_curves,ensure_ascii=False)
    output['ek_effective_recipes']=json.dumps(effective_recipes,ensure_ascii=False)
    output['ek_expression_rule_specs']=json.dumps({r['name']:plain(r) for r in recipes},ensure_ascii=False)
    output.display_type='TEXTURED';output.show_wire=False
    output.active_shape_key_index=0;output.show_only_shape_key=False
    report=dict(keys=len(accepted),skipped=skipped,warnings=rig.warnings,quality=records,
        unresolved=[row['name'] for row in records if row['unresolved']],source_required=False,
        oral_parts=list(rig.oral_parts),profile=data['name'],curve_hash=snapshot['hash'],neutral_mouth=rig.neutral_report,
        neutral_tongue=rig.tongue_report,tongue_method='original_reference_sections_and_rigid_mouth_motion',
        cavity_neutral_vertices=int(np.count_nonzero(np.linalg.norm(rig.cavity_points-rig.original_points,axis=1)>1e-10)),
        eyelid_method='single_cubic_bezier_two_anchors_per_branch',lower_lid_max_rise=E.LOWER_LID_MAX_RISE,
        lower_lid_smile_middle_extra=E.LOWER_LID_MIDDLE_EXTRA,
        closed_eye_styles=dict(normal='reflected_current_upper_curvature',smile='upward_arc_with_upper_band_translation_blend',nagomi='straight_seam_and_band'),
        closed_eye_priority='shared_seam_upper_down_lower_rise_cap_with_turn_delimited_canthus',
        curve_completion='fill_never_created_preserve_user_deletions',suppressed_curves=snapshot.get('suppressed',[]),
        individual_lashes=dict(enabled=snapshot.get('process_lashes',True),marked_units=len(rig.lashes)),
        recipe_weights=weights,curve_rule_method='current_controls_fixed_rest_parameters',
        lash_method='band_first_root_attachment_with_fixed_root_zone',
        lash_band_contact_method='band_towards_solved_skin_with_root_burial',
        lash_skin_contact_method='band_only_bounded_eye_and_skin_path_contacts',
        crease_method='final_upper_band_section_translation',commit_method='explicit_selected_target',
        lash_band_method='final_lower_lid_guided_inward_fold',lash_band_max_inward_x_degrees=85.,
        lash_style_method='actual_mesh_section_centres_after_folding',
        lower_corner_method='turn_delimited_y_rotation_z_compression',
        lash_seam_method='common_skin_polygon_with_style_preserving_band_coverage',
        eyelid_depth_method='shared_local_monotone_profile_with_facial_bridge_limit',
        eye_skin_method='connected_smooth_field_without_second_fade',eye_depth_method='triangle_overlap_path_endpoint_bounds',
        eye_backing_method='legacy_layer_retreat',constraint_mode='LEGACY',
        face_fold_method='smoothed_local_area_projection_shared_edge_budget',
        oral_method='fixed_lip_seam_internal_parts_behind_face',
        mouth_skin_method='finite_surface_profile_with_attached_bevel_collar',
        symmetry=dict(enabled=force_symmetry,method='positive_final_positions_mirrored_after_contacts',applied=[r['name'] for r in records if r.get('symmetry_applied')],
            half_reused=[r['name'] for r in records if r.get('symmetry_half_reused')],
            notes={r['name']:r['symmetry_note'] for r in records if r.get('symmetry_note')}),
        lower_lip_method='original_outline_with_connected_xyz_collar',dental_jaw_method='upper_and_lower_lip_travel_then_bounded_flex',
        dental_contact_method='small_rigid_retreat_and_smooth_local_flex',
        auxiliary_shape_keys=0,
        mouth_method='original_vody_face_outlines',lip_binding_method='checked_guide_vertex_chains',
        detection_methods=rig.info['detection_methods'],feedback_revision=data['feedback_revision'])
    from . import procedural_anatomy as Anatomy
    report['eye_anatomy']=Anatomy.summary(rig.eye_anatomy)
    report['compute']=GPU.statistics()
    output['ek_procedural_report']=json.dumps(report,ensure_ascii=False)
    if progress and hasattr(progress,'metadata'):
        progress.metadata.update(generated=len(accepted),skipped=skipped,triangles=len(rig.mesh_triangles),compute=report['compute'])
        progress.result=output
    return output,collection,report


def preview_curves(target,partition,collection,process_lashes=None,progress=None):
    """Evaluate one corrected rest pose on a separate, reversible mesh copy."""
    if partition.get('ek_target_reference')!=target:raise ValueError('请先选择当前目标的分区副本')
    if progress:progress('读取校正曲线')
    collection,snapshot=R.checkpoint(partition,collection,process_lashes)
    if progress and hasattr(progress,'describe'):progress.describe('曲线校正预览',partition,snapshot)
    rig=R.Rig(partition,snapshot,False);rig.progress=progress
    zeros=np.zeros((17,3)).tolist()
    recipe=dict(name='曲线校正预览',eyes={},mouth={},brows={},oral={},guide_preview=True)
    for side in rig.rings:
        recipe['eyes'][str(side)]=dict(upper=zeros,lower=zeros,closure=0.,blink=0.,smile=0.,flat=0.,lower_share=0.,lash_pitch=0.)
    if rig.info['mouth']:recipe['mouth']=dict(upper=zeros,lower=zeros)
    for side,kind,ids,entry in rig.accessories:
        if kind=='BROW':recipe['brows'][str(side)]=[[0.,0.,0.]]
    delta,quality=E.solve(rig,recipe,profile())
    output=partition.copy();output.data=partition.data.copy();output.name=target.name+'_EK_曲线校正预览'
    A.new_collection('EK_曲线校正预览').objects.link(output);output.shape_key_clear();output.modifiers.clear()
    try:
        mapping,groups=Oral.geometry(output,rig);mapping=np.asarray(mapping)
        basis=rig.points[mapping].copy();static=json.loads(output['ek_static_eye_vertices'])
        for kind,ids in groups.items():basis[ids]=(rig.cavity_points if kind.startswith('mouth_') else rig.original_points)[mapping[ids]]
        basis[static]=rig.original_points[mapping[static]]
        coordinates=Oral.key_coordinates(basis,delta,mapping,groups,Oral.baked_shapes(rig,recipe,rig.last_oral_deformation),static)
        if not np.isfinite(coordinates).all():raise ValueError('曲线校正预览出现无效坐标，请检查控制点')
        output.data.vertices.foreach_set('co',np.asarray(coordinates,dtype=np.float32).ravel());output.data.update()
    except Exception:
        mesh=output.data;bpy.data.objects.remove(output,do_unlink=True)
        if not mesh.users:bpy.data.meshes.remove(mesh)
        raise
    output['ek_curve_preview_owner']=partition;output['ek_curve_preview_hash']=snapshot['hash']
    output[A.TAG]=True;output.show_wire=False
    collection['ek_guide_preview_hash']=snapshot['hash']
    if progress and hasattr(progress,'result'):progress.result=output
    return output,collection,quality


def combine(target,partition,collection,output,name='组合表情',progress=None,process_lashes=None):
    if output.get('ek_procedural_version')!=VERSION:raise ValueError('结果格式不属于当前版本，请重新生成表情')
    if output.get('ek_commit_target')!=target or output.get('ek_transfer_target')!=target:
        raise ValueError('结果不属于当前需添加表情的模型，请重新生成表情')
    if progress:progress('读取组合表情与当前曲线')
    settings=json.loads(output['ek_procedural_settings'])
    if settings.get('constraint_mode','LEGACY')!='LEGACY':raise ValueError('该结果来自已移除的实验分支，请按原始预设重新生成表情')
    collection,snapshot=R.checkpoint(partition,collection,process_lashes,recover_lashes=True)
    if output.get('ek_procedural_hash')!=snapshot['hash'] or output.get('ek_procedural_input')!=snapshot['input']:
        raise ValueError('曲线或分区已修改，请重新生成后再组合')
    data=profile();lookup=json.loads(output['ek_effective_recipes']);keys=output.data.shape_keys.key_blocks
    selected=[(lookup[key.name],key.value) for key in keys if key.name in lookup and key.value>0]
    if not selected:raise ValueError('先在结果形态键中设置需要组合的表情权重')
    settings=json.loads(output['ek_procedural_settings'])
    from . import procedural_gpu as GPU
    GPU.configure(settings.get('compute_backend','AUTO'))
    rig=R.Rig(partition,snapshot,settings.get('close_mouth',False))
    rig.style_options=settings.get('style_options',{})
    if progress and hasattr(progress,'describe'):
        progress.describe('组合表情',partition,snapshot,components=[dict(name=r['name'],weight=w) for r,w in selected],**settings)
    rig.progress=progress
    if progress:progress.batch_step('计算组合表情',0,1,name)
    from .expression_relations import Solver
    recipe=dict(name=name,family='custom',eyes={},mouth={},brows={},oral={},can_symmetrize=False,
                relation=dict(mode='COMBINATION',terms=[dict(source=r['name'],weight=w) for r,w in selected]),
                relation_recipes={r['name']:r for r,w in selected})
    delta,recipe,oral,quality,curves=Solver(rig,data,settings['lower_lid_scale']).solve(recipe)
    if progress:progress.batch_step('写入组合形态键',0,1,name)
    mapping=[v.value for v in output.data.attributes['ek_vertex_origin'].data]
    basis=np.array([v.co for v in output.data.shape_keys.reference_key.data])
    coordinates=Oral.key_coordinates(basis,delta,mapping,json.loads(output['ek_oral_groups']),Oral.baked_shapes(rig,recipe,rig.last_oral_deformation),
                                     json.loads(output['ek_static_eye_vertices']))
    key=output.shape_key_add(name=name,from_mix=False)
    key.data.foreach_set('co',np.asarray(coordinates,dtype=np.float32).ravel())
    stored=json.loads(output.get('ek_oral_poses','{}'))
    bindings=json.loads(output.get('ek_oral_bone_groups','{}'))
    for part_kind,faces in rig.oral_parts.items():
        if part_kind not in bindings:continue
        part=Part(rig,part_kind,faces);part.add_recipe(key.name,recipe)
        stored.setdefault(part_kind,{})[key.name]=[v.tolist() for v in part.poses[key.name]]
    output['ek_oral_poses']=json.dumps(stored);Oral.rebuild_drivers(output)
    curves=json.loads(output.get('ek_expression_curves','{}'));curves[key.name]=rig.last_expression_curves
    output['ek_expression_curves']=json.dumps(curves,ensure_ascii=False)
    from .expression_rules import plain
    effective=json.loads(output.get('ek_effective_recipes','{}'));effective[key.name]=plain(recipe)
    output['ek_effective_recipes']=json.dumps(effective,ensure_ascii=False)
    for old in keys:old.value=0
    key.value=1;output.active_shape_key_index=list(keys).index(key)
    if progress and hasattr(progress,'result'):progress.result=output
    return key.name,quality
