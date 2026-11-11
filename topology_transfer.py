"""Batch and local expression transfer between index-compatible meshes."""
import json
import bpy
import numpy as np

from . import procedural_commit as Commit, region_blender as A, region_session as S
from .region_core import REGION_NAMES, REGION_UI_NUMBERS


def face_signature(mesh):
    def cycle(face):
        indices=list(face.vertices)
        start=indices.index(min(indices))
        ring=tuple(indices[start:]+indices[:start])
        return min(ring,(ring[0],*reversed(ring[1:])))
    return sorted(cycle(face) for face in mesh.polygons)


def same_topology(source,target):
    if (len(source.vertices)!=len(target.vertices) or len(source.edges)!=len(target.edges)
            or len(source.polygons)!=len(target.polygons)):
        return False
    edges=lambda mesh:sorted(tuple(sorted(edge.vertices)) for edge in mesh.edges)
    return face_signature(source)==face_signature(target) and edges(source)==edges(target)


def group_weights(ob,name):
    if not name:return np.ones(len(ob.data.vertices))
    group=ob.vertex_groups.get(name)
    if group is None:raise ValueError(ob.name+' 缺少顶点组「'+name+'」')
    return np.array([next((g.weight for g in v.groups if g.group==group.index),0.)
                     for v in ob.data.vertices])


def region_weights(target,partition,region):
    from .region_transfer import mesh_regions
    mesh=A.check_mesh(partition if partition is not None else target)
    if mesh!=target:
        owner=mesh.get('ek_target_reference')
        if owner is not None and owner!=target:raise ValueError('分区副本不属于接收模型')
        if not same_topology(mesh.data,target.data):
            raise ValueError('分区副本与接收模型的编号拓扑不同')
    weights=np.zeros(len(target.data.vertices))
    for face,label in zip(mesh.data.polygons,mesh_regions(mesh)):
        if label==region:weights[list(face.vertices)]=1.
    return weights


def key_delta(ob,key):
    return (Commit.coordinates(key.data)-Commit.coordinates(key.relative_key.data))*group_weights(ob,key.vertex_group)[:,None]


def transport_frames(source,target,triangles):
    """Fit one global similarity and area-weighted local rest-surface frames."""
    if np.array_equal(source,target):
        return np.broadcast_to(np.eye(3),(len(source),3,3)),np.eye(3),0
    a=source-source.mean(0);b=target-target.mean(0)
    u,s,vh=np.linalg.svd(b.T@a)
    sign=np.linalg.det(u@vh)
    u[:,-1]*=sign;s[-1]*=sign
    scale=float(s.sum()/max(np.sum(a*a),1e-30))
    if scale<=1e-12:raise ValueError('两个基型无法建立可靠的整体对齐')
    global_frame=scale*(u@vh)

    def basis(points):
        p=points[triangles]
        ab,ac=p[:,1]-p[:,0],p[:,2]-p[:,0]
        normal=np.cross(ab,ac);area=np.linalg.norm(normal,axis=1)
        edge=np.maximum(np.linalg.norm(ab,axis=1),np.linalg.norm(ac,axis=1))
        # The third axis scales with the geometric mean of tangent stretches.
        # A surface displacement along the normal then follows model scale.
        frame=np.stack((ab,ac,normal/np.sqrt(np.maximum(area,1e-30))[:,None]),axis=2)
        return frame,area,area>np.maximum(edge*edge*1e-5,1e-28)

    original,areas,valid=basis(source)
    posed,_,usable=basis(target)
    valid&=usable
    ids=triangles[valid];weights=areas[valid]
    local=posed[valid]@np.linalg.inv(original[valid])
    u,s,vh=np.linalg.svd(local)
    local=(u*np.clip(s,scale*.25,scale*4.)[:,None,:])@vh
    frames=np.zeros((len(source),3,3));total=np.zeros(len(source))
    for corner in ids.T:
        np.add.at(frames,corner,local*weights[:,None,None])
        np.add.at(total,corner,weights)
    has_frame=total>0
    frames[has_frame]/=total[has_frame,None,None]
    frames[~has_frame]=global_frame
    return frames,global_frame,int(np.count_nonzero(~has_frame))


def generate(source,target,key_name='',group='',adapt=1.,strength=1.,previous=None,progress=None,
             region=None,partition=None):
    from . import procedural_generate as P, procedural_constraints as Q
    A.check_mesh(source);A.check_mesh(target)
    if source==target:raise ValueError('请选择不同的参考模型和接收模型')
    keys=source.data.shape_keys;old=target.data.shape_keys
    if not keys or not keys.use_relative or len(keys.key_blocks)<2:
        raise ValueError('参考模型需要相对形态键')
    if old and not old.use_relative:raise ValueError('接收模型使用了绝对形态键')
    if not same_topology(source.data,target.data):
        raise ValueError('两个网格的顶点编号或面连接不一致，需要同一顶点顺序的拓扑')
    selection=[k for k in keys.key_blocks if k!=keys.reference_key and (not key_name or k.name==key_name)]
    if not selection:raise ValueError('参考模型没有所选表情')
    basis_name=old.reference_key.name if old else 'Basis'
    if any(k.name==basis_name for k in selection):
        raise ValueError('参考表情名称与接收模型的基型重名')
    local_scope=region is not None or bool(group)
    mask=region_weights(target,partition,region) if region is not None else group_weights(target,group)
    if not np.any(mask>0):raise ValueError('所选分区或顶点组没有可迁移的顶点')
    source_basis=Commit.coordinates(keys.reference_key.data)
    target_basis=Commit.coordinates(old.reference_key.data if old else target.data.vertices)
    if not np.isfinite(source_basis).all() or not np.isfinite(target_basis).all():
        raise ValueError('网格基型含无效坐标')
    stamp=Commit.basis_signature(target)
    if previous and (previous.get('ek_commit_target')!=target or previous.get('ek_confirmed_target') or
                     previous.get('ek_topology_basis')!=stamp or not previous.data.shape_keys):
        raise ValueError('当前检查副本已写入，或目标基型已改变，请开启新一批')
    if previous and not np.array_equal(Commit.coordinates(previous.data.shape_keys.reference_key.data),target_basis):
        raise ValueError('检查副本的基型已修改，请开启新一批')
    source.data.calc_loop_triangles()
    triangles=np.array([tuple(t.vertices) for t in source.data.loop_triangles],dtype=int).reshape((-1,3))
    if progress:progress('分析同编号顶点的局部表面')
    frames,global_frame,fallback=transport_frames(source_basis,target_basis,triangles)
    frames=global_frame+(frames-global_frame)*adapt
    pending={}
    if previous:
        for key in previous.data.shape_keys.key_blocks[1:]:
            pending[key.name]=(key_delta(previous,key),key.slider_min,key.slider_max)
    for i,key in enumerate(selection):
        if progress:progress.batch_step('迁移形态键',i,len(selection),key.name)
        motion=np.einsum('ijk,ik->ij',frames,key_delta(source,key))*strength
        if local_scope:
            if key.name in pending:prior=pending[key.name][0]
            elif old and old.key_blocks.get(key.name):prior=key_delta(target,old.key_blocks[key.name])
            else:prior=np.zeros_like(motion)
            motion=prior+(motion-prior)*mask[:,None]
        if not np.isfinite(motion).all():raise ValueError('表情含无效坐标：'+key.name)
        pending[key.name]=(motion,min(key.slider_min,0.),max(key.slider_max,1.))

    # Stage a fresh review so a bad key cannot partially change an earlier batch.
    result=target.copy();result.data=target.data.copy();result.name=target.name+'_EK_同拓扑迁移'
    try:
        result.animation_data_clear()
        for prop in list(result.keys()):
            if prop.startswith('ek_'):del result[prop]
        A.new_collection('EK_同拓扑迁移').objects.link(result)
        if result.data.shape_keys:result.shape_key_clear()
        result.data.vertices.foreach_set('co',target_basis.ravel())
        result.shape_key_add(name=basis_name,from_mix=False)
        warnings=[]
        for name,(motion,low,high) in pending.items():
            key=result.shape_key_add(name=name,from_mix=False)
            if key.name!=name:raise ValueError('形态键名称与基型重名：'+name)
            key.data.foreach_set('co',(target_basis+motion).ravel())
            key.slider_min=low;key.slider_max=high;key.value=0.
            minimum,rest=Q.minimum_areas(target_basis,motion,triangles)
            flips=int(np.count_nonzero((rest>1e-25)&(minimum< -rest*1e-5)))
            if flips:warnings.append(dict(name=name,orientation_changes=flips))
        result.active_shape_key_index=0;result.show_only_shape_key=False
        result[A.TAG]=True;result['ek_topology_basis']=stamp
        result['ek_transfer_target']=target;result['ek_procedural_version']=P.VERSION
        result['ek_topology_transfer']=True
        result['ek_original_faces']=json.dumps([list(face.vertices) for face in target.data.polygons])
        for name,domain,size in (('ek_vertex_origin','POINT',len(target_basis)),
                                 ('ek_face_origin','FACE',len(target.data.polygons))):
            attr=result.data.attributes.get(name) or result.data.attributes.new(name,'INT',domain)
            attr.data.foreach_set('value',np.arange(size,dtype=np.int32))
        name='ek_neutral_original_basis'
        basis=result.data.attributes.get(name) or result.data.attributes.new(name,'FLOAT_VECTOR','POINT')
        basis.data.foreach_set('vector',target_basis.ravel())
        Commit.record(result,Commit.original_binding(target))
        report=dict(keys=len(pending),updated=len(selection),fallback_vertices=fallback,warnings=warnings)
        result['ek_topology_report']=json.dumps(report,ensure_ascii=False)
        return result,report
    except Exception:
        mesh=result.data;bpy.data.objects.remove(result,do_unlink=True)
        if not mesh.users:bpy.data.meshes.remove(mesh)
        raise


PRESET_KINDS=(('ALL','整体预设',''),('REGION','分区预设',''),('EXPRESSION','表情预设',''))
REGION_CHOICES=[('ALL','未限定分区','')]+[(str(label),f'{REGION_UI_NUMBERS[label]} · {title}','')
                                       for label,title in REGION_NAMES.items() if label>=0]


class EKTOPO_Preset(bpy.types.PropertyGroup):
    kind:bpy.props.EnumProperty(items=PRESET_KINDS)
    parent_name:bpy.props.StringProperty()
    source:bpy.props.PointerProperty(type=bpy.types.Object)
    key_name:bpy.props.StringProperty()
    group:bpy.props.StringProperty()
    region:bpy.props.EnumProperty(items=REGION_CHOICES)
    adapt:bpy.props.FloatProperty()
    strength:bpy.props.FloatProperty()


class EKTOPO_Settings(bpy.types.PropertyGroup):
    source:bpy.props.PointerProperty(name='参考模型',type=bpy.types.Object,poll=lambda s,o:o.type=='MESH')
    target:bpy.props.PointerProperty(name='接收模型',type=bpy.types.Object,poll=lambda s,o:o.type=='MESH')
    result:bpy.props.PointerProperty(type=bpy.types.Object)
    key_name:bpy.props.StringProperty(name='单个表情',description='留空时分析并迁移全部相对形态键')
    region:bpy.props.EnumProperty(name='插件分区',items=REGION_CHOICES)
    partition:bpy.props.PointerProperty(name='接收模型分区副本',type=bpy.types.Object,poll=lambda s,o:o.type=='MESH')
    group:bpy.props.StringProperty(name='局部顶点组',description='留空时使用整个网格。局部迁移按接收模型的顶点权重混合')
    adapt:bpy.props.FloatProperty(name='局部适配',default=1.,min=0.,max=1.,subtype='FACTOR')
    strength:bpy.props.FloatProperty(name='强度',default=1.,min=0.,max=2.)
    append:bpy.props.BoolProperty(name='累积到本批检查',default=True)
    presets:bpy.props.CollectionProperty(type=EKTOPO_Preset)
    preset_name:bpy.props.StringProperty(name='预设名称')
    preset_parent:bpy.props.StringProperty(name='所属整体预设')
    preset_kind:bpy.props.EnumProperty(name='保存为',items=PRESET_KINDS)
    preset_pick:bpy.props.StringProperty(name='已保存的预设')
    show_report:bpy.props.BoolProperty(name='检查提示',default=False)
    message:bpy.props.StringProperty()


def selected_partition(context,s):
    if s.partition is not None:return s.partition
    for candidate in (context.scene.exprkit_procedural.working,context.scene.exprkit_regions.preview):
        if candidate is not None and candidate.get('ek_target_reference')==s.target:return candidate
    return None


def save_preset(s):
    kind=s.preset_kind
    if kind=='ALL':
        if s.source is None:raise ValueError('请选择参考模型')
        parent=''
    else:
        parent=s.preset_parent
        root=s.presets.get(parent)
        if root is None or root.kind!='ALL':raise ValueError('请选择所属的整体预设')
        if s.source!=root.source:raise ValueError('请先加载整体预设，再保存其子预设')
        if kind=='REGION' and s.region=='ALL' and not s.group:raise ValueError('分区预设需要插件分区或局部顶点组')
        if s.region=='ALL' and s.group:group_weights(A.check_mesh(s.target),s.group)
        if kind=='EXPRESSION':
            keys=s.source.data.shape_keys if s.source else None
            key=keys.key_blocks.get(s.key_name) if keys else None
            if key is None or key==keys.reference_key:raise ValueError('表情预设需要指定单个形态键')
    title=s.preset_name.strip()
    if not title:raise ValueError('请输入预设名称')
    name=f'{parent} / {title}' if parent else title
    preset=s.presets.get(name)
    if preset and (preset.kind!=kind or preset.parent_name!=parent):
        raise ValueError('此名称已用于另一层级或另一整体预设')
    if preset is None:preset=s.presets.add()
    preset.name=name;preset.kind=kind;preset.parent_name=parent
    preset.source=s.source if kind=='ALL' else None
    preset.key_name=s.key_name if kind=='EXPRESSION' else ''
    preset.region=s.region if kind!='ALL' else 'ALL'
    preset.group=s.group if kind!='ALL' and s.region=='ALL' else ''
    preset.adapt=s.adapt;preset.strength=s.strength
    s.preset_pick=name
    if kind=='ALL':s.preset_parent=name


def load_preset(s):
    preset=s.presets.get(s.preset_pick)
    if preset is None:raise ValueError('请选择已保存的预设')
    root=preset if preset.kind=='ALL' else s.presets.get(preset.parent_name)
    if root is None or root.source is None:raise ValueError('整体预设的参考模型已不存在')
    s.source=root.source;s.preset_parent=root.name
    s.key_name=preset.key_name;s.group=preset.group;s.region=preset.region
    s.adapt=preset.adapt;s.strength=preset.strength
    s.preset_kind=preset.kind;s.preset_name=preset.name.removeprefix(f'{preset.parent_name} / ')


class EKTOPO_OT_work(bpy.types.Operator):
    bl_idname='exprkit_topology.work'
    bl_label='同拓扑迁移'
    bl_options={'REGISTER','UNDO'}
    action:bpy.props.EnumProperty(items=[(a,a,'') for a in ('GENERATE','REVIEW','APPLY','RESTORE','SAVE','LOAD')])

    def execute(self,context):
        from . import region_commit, generation_progress
        s=context.scene.exprkit_topology
        try:
            if self.action=='SAVE':save_preset(s);s.message='已保存预设「'+s.preset_pick+'」'
            elif self.action=='LOAD':load_preset(s);s.message='已载入预设「'+s.preset_pick+'」'
            elif self.action=='REVIEW':S.focus(context,s.result)
            elif self.action=='RESTORE':S.restore(context)
            else:
                if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
                if self.action=='GENERATE':
                    previous=s.result if s.append and s.result and not s.result.get('ek_confirmed_target') else None
                    with generation_progress.Progress(context) as progress:
                        region=int(s.region) if s.region!='ALL' else None
                        result,report=generate(s.source,s.target,s.key_name,s.group,s.adapt,s.strength,previous,progress,
                                               region=region,partition=selected_partition(context,s))
                    if s.result:A.set_hidden_if_present(s.result)
                    s.result=result;S.focus(context,result)
                    s.message='本次迁移 %d 个，本批共 %d 个。%d 个表情需要检查面朝向。'%(
                        report['updated'],report['keys'],len(report['warnings']))
                else:
                    if not s.result or not s.result.get('ek_topology_transfer'):raise ValueError('请先生成检查副本')
                    count,_,_=region_commit.apply(s.target,s.result)
                    S.restore(context,final=s.target)
                    s.message='已写入 %d 个形态键，原模型已备份'%count
            return {'FINISHED'}
        except (ValueError,RuntimeError,np.linalg.LinAlgError) as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class EKTOPO_PT_panel(bpy.types.Panel):
    bl_idname='EKTOPO_PT_panel'
    bl_label='同拓扑表情迁移'
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='ExpressionGen'
    bl_order=2
    bl_options={'DEFAULT_CLOSED'}

    def draw(self,context):
        from .generation_progress import controls
        s=context.scene.exprkit_topology
        layout=controls(self.layout,context)
        layout.prop(s,'source');layout.prop(s,'target')
        keys=s.source.data.shape_keys if s.source else None
        if keys:layout.prop_search(s,'key_name',keys,'key_blocks')
        if s.target:
            layout.prop(s,'region')
            if s.region=='ALL':layout.prop_search(s,'group',s.target,'vertex_groups')
            else:layout.prop(s,'partition')
        layout.prop(s,'adapt',slider=True);layout.prop(s,'strength',slider=True)
        layout.prop(s,'append')
        layout.operator('exprkit_topology.work',text='生成迁移检查副本').action='GENERATE'
        if s.result:
            layout.operator('exprkit_topology.work',text='查看检查副本').action='REVIEW'
            row=layout.row();row.enabled=s.result.get('ek_commit_target')==s.target and not s.result.get('ek_confirmed_target')
            row.operator('exprkit_topology.work',text='确认写入接收模型').action='APPLY'
            layout.prop(s,'show_report')
            if s.show_report:
                report=json.loads(s.result.get('ek_topology_report','{}'))
                box=layout.box()
                if report.get('fallback_vertices'):
                    box.label(text='整体适配顶点 %d 个'%report['fallback_vertices'])
                for warning in report.get('warnings',[]):
                    box.label(text=f"{warning['name']} · {warning['orientation_changes']} 面",icon='INFO')
                if not report.get('warnings'):box.label(text='形态键 0 到 1 之间无面朝向变化')
        if context.scene.exprkit_regions.session_running:
            layout.operator('exprkit_topology.work',text='恢复原场景显示').action='RESTORE'
        if s.message:
            import textwrap
            for line in textwrap.wrap(s.message,width=22):layout.label(text=line)
        box=layout.box();box.label(text='迁移预设')
        box.prop_search(s,'preset_pick',s,'presets')
        chosen=s.presets.get(s.preset_pick)
        if chosen:
            kind=next(title for key,title,_ in PRESET_KINDS if key==chosen.kind)
            box.label(text=kind if not chosen.parent_name else f'{chosen.parent_name} → {kind}')
        box.operator('exprkit_topology.work',text='载入预设').action='LOAD'
        box.prop(s,'preset_kind');box.prop(s,'preset_name')
        if s.preset_kind!='ALL':box.prop_search(s,'preset_parent',s,'presets')
        box.operator('exprkit_topology.work',text='保存预设').action='SAVE'


CLASSES=(EKTOPO_Preset,EKTOPO_Settings,EKTOPO_OT_work,EKTOPO_PT_panel)


def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.exprkit_topology=bpy.props.PointerProperty(type=EKTOPO_Settings)
