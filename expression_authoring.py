"""Scene library and expression curve copies, separate from correction guides."""
import copy,json,time,uuid
import bpy
import numpy as np
from mathutils import Vector
from . import expression_rules as Rules,expression_runtime as Runtime,region_guides as G,region_blender as A
from . import procedural_generate as P,procedural_rig as R,procedural_atoms as E,procedural_oral as Oral


def library(scene):return json.loads(scene.get('ek_expression_library','[]'))


def save(scene,spec):
    save_many(scene,[spec])


def save_many(scene,specs):
    names={spec['name'] for spec in specs}
    rows=[r for r in library(scene) if r['name'] not in names]+copy.deepcopy(list(specs))
    Rules.validate_library(rows)
    scene['ek_expression_library']=json.dumps(Rules.plain(rows),ensure_ascii=False,allow_nan=False)
    from .procedural_ui import sync_choices
    sync_choices(scene.exprkit_procedural)


def working(context):
    s=context.scene.exprkit_regions
    if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    if not s.target or not s.preview or not s.transferred:raise ValueError('请先生成表情结果')
    output=s.transferred
    if output.get('ek_confirmed_target'):raise ValueError('此结果已应用到模型，请重新生成结果后编辑表情曲线')
    if output.get('ek_procedural_version')!=P.VERSION:raise ValueError('请用当前版本重新生成表情，以保存变形后的曲线')
    collection,snapshot=R.checkpoint(s.preview,s.guide_collection,context.scene.exprkit_procedural.process_lashes)
    s.guide_collection=collection
    if snapshot['hash']!=output.get('ek_procedural_hash') or snapshot['input']!=output.get('ek_procedural_input'):
        raise ValueError('基础分区或校正曲线已修改，请先重新生成结果')
    from .procedural_ui import options_match
    if not options_match(context.scene.exprkit_procedural,output,s.close_neutral_mouth):raise ValueError('生成参数或规则已修改，请先重新生成结果')
    return s,output,snapshot


def create_copies(context,source_name,new_name):
    if source_name=='Basis':source_name=''
    s,output,snapshot=working(context)
    curves=json.loads(output.get('ek_expression_curves','{}'))
    if not curves:raise ValueError('结果缺少变形曲线，请重新生成')
    name=new_name.strip() or source_name.strip()
    if not name or name=='Basis' or len(name.encode('utf-8'))>63:raise ValueError('表情名不能为空或 Basis，且 UTF-8 长度不能超过 63 字节')
    if source_name and source_name not in curves:raise ValueError('所选表情没有曲线记录')
    records=curves[source_name] if source_name else next(iter(curves.values()))
    group=A.new_collection('EK表情曲线_'+name)
    group['ek_expression_owner']=output;group['ek_guide_target']=s.preview
    group['ek_expression_name']=name;group['ek_expression_source']=source_name
    effective=json.loads(output['ek_effective_recipes'])
    group['ek_expression_base_recipe']=json.dumps(effective[source_name] if source_name else dict(eyes={},mouth={},brows={},oral={}),ensure_ascii=False)
    token=uuid.uuid4().hex;objects=[]
    for i,row in enumerate(records):
        entry=copy.deepcopy(row['entry']);original=copy.deepcopy(entry)
        entry.update(key='EXPRESSION:'+token+':'+str(i),points=row['points'] if source_name else row['neutral'])
        entry.pop('fit',None)
        fitted=G.F.fit(entry['points'],entry['kind'])
        if fitted:entry['fit']=fitted
        ob=G.add_curve(group,s.preview,entry);ob.name=name+'_'+G.KINDS[entry['kind']]+'_'+str(entry['side'])
        ob['ek_expression_curve']=True;ob['ek_expression_source_entry']=json.dumps(original,ensure_ascii=False)
        ob['ek_expression_initial']=json.dumps(G.curve_points(ob,s.preview))
        objects.append(ob)
    return group,objects


def spec_from_copies(context,group):
    s,output,snapshot=working(context)
    if group is None or group.get('ek_expression_owner')!=output:raise ValueError('请选择当前结果的表情曲线副本')
    spec=dict(name=group['ek_expression_name'],family='custom',solver='curve_rules_v1',base='',
        base_recipe=json.loads(group['ek_expression_base_recipe']),recognizers=[],rules=[],parameters=[],constraints=list(Rules.CONSTRAINTS))
    for ob in group.all_objects:
        if not ob.get('ek_expression_curve'):continue
        current=Runtime.samples(G.curve_points(ob,s.preview));initial=Runtime.samples(json.loads(ob['ek_expression_initial']))
        if np.allclose(current,initial,rtol=0,atol=1e-9):continue
        entry=json.loads(ob['ek_expression_source_entry']);kind=entry['kind'];side=entry['side']
        candidates=sorted(G.entries_for(snapshot,'TARGET',kind,side),key=lambda e:e['key'])
        index=next((i for i,e in enumerate(candidates) if e['key']==entry['key']),None)
        if index is None:raise ValueError('基础曲线已改变，请重新添加表情曲线副本')
        region=12 if kind=='TONGUE' else 2 if kind in ('BROW','CREASE','LASH','LASH_LINE') else 0
        node='curve_'+str(len(spec['recognizers']))
        spec['recognizers'].append(dict(id=node,mode='GUIDE',kind=kind,side=side,region=region,index=index,criteria=[]))
        # Local curve frame and arc-length scale contain no model vertex IDs.
        normalized=(current-initial)@np.linalg.inv(Runtime.frame(Runtime.samples(entry['points']))).T
        spec['rules'].append(dict(id='rule_'+str(len(spec['rules'])),source=node,target_points=normalized.tolist(),amount=1.,influences=[]))
    Rules.validate(spec)
    return spec,s,output,snapshot


def write_copies(context,group,progress=None):
    spec,s,output,snapshot=spec_from_copies(context,group)
    if progress and hasattr(progress,'describe'):progress.describe('表情曲线写回',s.preview,snapshot,expression=spec['name'])
    settings=json.loads(output['ek_procedural_settings']);rig=R.Rig(s.preview,snapshot,settings.get('close_mouth',True));rig.progress=progress
    rig.style_options=settings.get('style_options',{})
    data=P.profile();recipe=Rules.runtime_recipe(spec,Rules.builtin_profile()['recipes'])
    effective=E.merge([recipe],[1.]);effective['name']=spec['name']
    if progress:progress.batch_step('按编辑后的表情曲线重新求解',0,1,spec['name'])
    from .expression_relations import Solver
    delta,effective,oral,quality,curves=Solver(rig,data,settings['lower_lid_scale'],settings.get('force_symmetry',False)).solve(effective)
    if progress:progress('写回表情曲线与形态键')
    mapping=[v.value for v in output.data.attributes['ek_vertex_origin'].data]
    basis=np.array([v.co for v in output.data.shape_keys.reference_key.data])
    coordinates=Oral.key_coordinates(basis,delta,mapping,json.loads(output['ek_oral_groups']),rig.last_oral_deformation,json.loads(output['ek_static_eye_vertices']))
    if not np.isfinite(coordinates).all():raise ValueError('自定义表情出现无效坐标，未写入')
    poses=json.loads(output.get('ek_oral_poses','{}'));bindings=json.loads(output.get('ek_oral_bone_groups','{}'))
    for kind,faces in rig.oral_parts.items():
        if kind not in bindings:continue
        part=P.Part(rig,kind,faces);part.add_recipe(spec['name'],effective)
        poses.setdefault(kind,{})[spec['name']]=[v.tolist() for v in part.poses[spec['name']]]
    keys=output.data.shape_keys.key_blocks;key=keys.get(spec['name'])
    if key:
        backup=output.shape_key_add(name=key.name+'_修改前备份',from_mix=False)
        old=np.empty(len(key.data)*3,dtype=np.float32);key.data.foreach_get('co',old);backup.data.foreach_set('co',old)
        old_poses=json.loads(output.get('ek_oral_poses','{}'))
        for kind,rows in old_poses.items():
            if key.name in rows:poses.setdefault(kind,{})[backup.name]=rows[key.name]
    else:key=output.shape_key_add(name=spec['name'],from_mix=False)
    key.data.foreach_set('co',np.asarray(coordinates,dtype=np.float32).ravel());key.slider_min=0;key.slider_max=1
    output['ek_oral_poses']=json.dumps(poses);Oral.rebuild_drivers(output)
    curves=json.loads(output['ek_expression_curves']);curves[key.name]=rig.last_expression_curves;output['ek_expression_curves']=json.dumps(curves,ensure_ascii=False)
    recipes=json.loads(output['ek_effective_recipes']);recipes[key.name]=Rules.plain(effective);output['ek_effective_recipes']=json.dumps(recipes,ensure_ascii=False)
    output['ek_procedural_recipes']=json.dumps(list(recipes),ensure_ascii=False)
    save(context.scene,spec)
    from .procedural_ui import generation_options
    selected=generation_options(context.scene.exprkit_procedural)
    settings.update(selected);settings['rule_signature']=P.rule_signature(context.scene)
    output['ek_procedural_settings']=json.dumps(settings)
    group['ek_expression_base_recipe']=json.dumps(Rules.plain(effective),ensure_ascii=False)
    solved={r['entry']['key']:r['points'] for r in rig.last_expression_curves}
    for ob in group.all_objects:
        if not ob.get('ek_expression_curve'):continue
        original=json.loads(ob['ek_expression_source_entry']);entry=json.loads(ob['ek_guide_entry'])
        if original['key'] in solved:
            entry['points']=solved[original['key']];entry.pop('fit',None)
            fitted=G.F.fit(entry['points'],entry['kind'])
            if fitted:entry['fit']=fitted
            replace_copy_shape(ob,s.preview,entry)
        ob['ek_expression_initial']=json.dumps(G.curve_points(ob,s.preview))
    for block in keys:block.value=0
    key.value=1;output.active_shape_key_index=list(keys).index(key)
    s.confirmed_result=None;context.scene.exprkit_procedural.confirmed=None
    if progress and hasattr(progress,'result'):progress.result=output
    return key.name,quality


_mirroring=False


def replace_copy_shape(ob,target,entry):
    global _mirroring
    previous=_mirroring;_mirroring=True
    try:G.set_curve_shape(ob,target,entry)
    finally:_mirroring=previous


def owner(ob):
    return next((c.get('ek_guide_owner') or c for c in ob.users_collection
                 if (c.get('ek_guide_owner') or c).get('ek_guide_target')),None)


def mirror_target(source):
    if source is None or source.type!='CURVE' or 'ek_guide_entry' not in source:raise ValueError('请先选择一条左右侧曲线')
    group=owner(source);entry=json.loads(source['ek_guide_entry']);side=entry['side']
    if not group or not side:raise ValueError('这条曲线没有左右侧')
    kind=entry['kind'];target=group['ek_guide_target']
    all_curves=([o for o in group.all_objects if 'ek_guide_entry' in o] if source.get('ek_expression_curve')
                else G.authoritative_objects(group,target,persist=True))
    def same(s):return sorted((o for o in all_curves if (lambda e:e['kind']==kind and e['side']==s)(json.loads(o['ek_guide_entry']))),key=lambda o:json.loads(o['ek_guide_entry'])['key'])
    own,other=same(side),same(-side)
    if len(own)!=len(other):raise ValueError('左右同类曲线数量不同，请先补齐或修正标记')
    destination=other[own.index(source)]
    if destination.mode=='EDIT':raise ValueError('请只进入一侧曲线编辑模式')
    return destination,target


def mirror(context,source,live=False):
    destination,target=mirror_target(source)
    source.update_from_editmode()
    if destination.data.users>1:destination.data=destination.data.copy()
    data=source.data.splines[0]
    transform=target.matrix_world.inverted()@source.matrix_world
    convert=destination.matrix_world.inverted()@target.matrix_world
    plane=context.scene.exprkit_regions.mirror_plane
    def point(p):
        value=transform@p;value.x=2*plane-value.x;return convert@value
    controls=list(data.bezier_points if data.type=='BEZIER' else data.points)
    stored=json.loads(destination['ek_guide_base'])
    co=lambda p:p.co if data.type=='BEZIER' else p.co.xyz
    first=destination.matrix_world@point(co(controls[0]));last=destination.matrix_world@point(co(controls[-1]))
    start=target.matrix_world@Vector(stored[0]);end=target.matrix_world@Vector(stored[-1])
    reverse=(first-end).length_squared+(last-start).length_squared<(first-start).length_squared+(last-end).length_squared
    if reverse:controls.reverse()
    # Mirror only the editable spline. Rest samples/vertex bindings are kept.
    destination.data.splines.clear();spline=destination.data.splines.new(data.type);spline.use_cyclic_u=data.use_cyclic_u
    if data.type=='BEZIER':
        spline.bezier_points.add(len(data.bezier_points)-1)
        for a,b in zip(controls,spline.bezier_points):
            b.co=point(a.co);b.handle_left_type='FREE';b.handle_right_type='FREE'
            b.handle_left=point(a.handle_right if reverse else a.handle_left);b.handle_right=point(a.handle_left if reverse else a.handle_right)
    else:
        spline.points.add(len(data.points)-1)
        spline.order_u=min(data.order_u,len(controls));spline.use_endpoint_u=data.use_endpoint_u
        for a,b in zip(controls,spline.points):b.co=(*point(a.co.xyz),a.co.w)
    destination['ek_curve_edit_time']=time.time()
    destination['ek_curve_change_stamp']=G.digest(G.curve_points(destination,target))
    return destination


def sync_symmetry(scene,depsgraph):
    global _mirroring
    if _mirroring:return
    s=getattr(scene,'exprkit_regions',None);ob=bpy.context.object
    if not s or ob is None or ob.type!='CURVE' or 'ek_guide_entry' not in ob:return
    if not any(update.id.original in (ob,ob.data) for update in depsgraph.updates):return
    _mirroring=True
    try:
        group=owner(ob)
        if not group:return
        ob.update_from_editmode()
        stamp=G.digest(G.curve_points(ob,group['ek_guide_target']))
        if ob.get('ek_curve_change_stamp')==stamp:return
        changed=('ek_curve_change_stamp' in ob or G.edited(ob,group['ek_guide_target']))
        ob['ek_curve_change_stamp']=stamp
        if not changed:return
        ob['ek_curve_edit_time']=time.time()
        if not s.curve_symmetry:return
        mirror(bpy.context,ob,True);ob['ek_symmetry_stamp']=stamp
        s.curve_symmetry_message=''
    except (ValueError,KeyError,RuntimeError) as exc:s.curve_symmetry_message=str(exc)
    finally:_mirroring=False
