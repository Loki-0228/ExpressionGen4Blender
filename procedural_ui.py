"""Native target-only expression generation workflow."""
import json,textwrap
import bpy
from bpy_extras.io_utils import ExportHelper
from . import procedural_generate as P,procedural_rig as R,region_blender as A,region_guides as G,region_session as S,region_commit as K


FAMILIES=(('eye','眼睑与睫毛'),('brow','眉毛'),('mouth','嘴型'),('tongue','吐舌与舌宽'),('jaw','下颌'),('custom','自定义表情'))


def recipe_catalog(scene=None):return P.catalog(scene)


class EKPROC_Expression(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='表情名称')
    enabled:bpy.props.BoolProperty(name='生成此表情',default=True)
    family:bpy.props.StringProperty()


def sync_choices(settings):
    rows=recipe_catalog(settings.id_data);catalog=dict(rows)
    for i in reversed(range(len(settings.expressions))):
        if settings.expressions[i].name not in catalog:settings.expressions.remove(i)
    existing={item.name:item for item in settings.expressions}
    for name,family in rows:
        item=existing.get(name)
        if item is None:item=settings.expressions.add();item.name=name
        item.family=family


def options_opened(settings,context):
    if settings.show_options:sync_choices(settings)


def generation_options(settings):
    # Uninitialized settings mean the whole preset, never an empty selection.
    entries={item.name:item for item in settings.expressions}
    selected=[];weights={}
    for name,family in recipe_catalog(settings.id_data):
        item=entries.get(name)
        if item is not None and not item.enabled:continue
        selected.append(name)
        # Generation always uses the full preset action. Saved strengths from
        # earlier versions are deliberately not read from collection items.
        weights[name]=1.
    return dict(selection=selected,recipe_strengths=weights,force_symmetry=settings.force_symmetry,compute_backend=settings.compute_backend,
                lower_lid_scale=settings.lower_lid_participation,
                style_options=dict(smile_arc=settings.smile_arc,smile_preserve=settings.smile_preserve))


def options_match(settings,output,close_mouth):
    saved=json.loads(output.get('ek_procedural_settings','{}'));current=generation_options(settings)
    return (saved.get('strength',1.)==1. and saved.get('force_symmetry',False)==current['force_symmetry'] and saved.get('selection')==current['selection']
            and saved.get('recipe_strengths')==current['recipe_strengths']
            and saved.get('rule_signature')==P.rule_signature(settings.id_data)
            and saved.get('constraint_mode','LEGACY')=='LEGACY'
            and saved.get('lower_lid_scale',1.)==current['lower_lid_scale']
            and saved.get('style_options',{})==current['style_options']
            and saved.get('close_mouth')==close_mouth)


class EKPROC_Settings(bpy.types.PropertyGroup):
    target:bpy.props.PointerProperty(name='需添加表情的模型',type=bpy.types.Object,poll=lambda s,o:o.type=='MESH')
    partition:bpy.props.PointerProperty(name='已有分区（可选）',type=bpy.types.Object,poll=lambda s,o:o.type=='MESH')
    partition_method:bpy.props.EnumProperty(name='自动分区方式',items=[('GEOMETRY','形状与拓扑',''),('MATERIAL','仅按材质','')],default='GEOMETRY')
    working:bpy.props.PointerProperty(type=bpy.types.Object)
    collection:bpy.props.PointerProperty(type=bpy.types.Collection)
    output:bpy.props.PointerProperty(type=bpy.types.Object)
    confirmed:bpy.props.PointerProperty(type=bpy.types.Object)
    curve:bpy.props.PointerProperty(name='检查曲线',type=bpy.types.Object,poll=lambda s,o:o.type=='CURVE' and 'ek_guide_entry' in o)
    curve_preview:bpy.props.PointerProperty(type=bpy.types.Object)
    process_lashes:bpy.props.BoolProperty(name='单独处理单根睫毛',default=True,
        description='生成曲线时识别单根睫毛；生成表情时只让当前有曲线标记的单根睫毛独立形变。没有标记或关闭时随整体眼睑移动')
    kind:bpy.props.EnumProperty(name='显示部位',items=[('ALL','全部','')]+[(k,v,'') for k,v in G.KINDS.items()])
    label:bpy.props.EnumProperty(name='所选面分区',items=[('0','0 · 面部',''),('2','1 · 眉毛与睫毛',''),('3','2 · 瞳孔与高光',''),('7','3 · 眼白',''),('8','4 · 口腔（自动上下组）',''),('9','5 · 牙齿（自动上下组）',''),('12','6 · 舌头',''),('-1','-1 · 不参与表情',''),('81','4 · 上口腔',''),('82','4 · 下口腔',''),('91','5 · 上牙',''),('92','5 · 下牙','')])
    force_symmetry:bpy.props.BoolProperty(name='强制左右对称',default=False,
        description='将 X 正侧完成约束后的坐标镜像到负侧；可复用的眼眉仅计算正侧。子表情、组合及特殊表情保持定义；无法配对的活动顶点会阻止该表情输出')
    compute_backend:bpy.props.EnumProperty(name='计算设备',items=[('AUTO','自动 GPU','可用时用 NVIDIA CUDA 加速三角面接触；小任务或不可用时自动回退 CPU'),('CPU','CPU','仅使用 CPU 计算')],default='AUTO')
    expressions:bpy.props.CollectionProperty(type=EKPROC_Expression)
    expression_index:bpy.props.IntProperty(default=0,min=0)
    selection_anchor:bpy.props.IntProperty(default=-1)
    expression_search:bpy.props.StringProperty(name='搜索表情',options={'TEXTEDIT_UPDATE'})
    expression_family:bpy.props.EnumProperty(name='类别',items=[('ALL','全部','')]+[(key,name,'') for key,name in FAMILIES],default='ALL')
    combination:bpy.props.StringProperty(name='组合名称',default='组合表情')
    show_options:bpy.props.BoolProperty(name='表情选择',default=False,update=options_opened)
    show_styles:bpy.props.BoolProperty(name='风格设置',default=False)
    lower_lid_participation:bpy.props.FloatProperty(name='下眼睑参与量',default=1.,min=0.,max=1.,
        description='在允许范围内调整闭合线高度；越小越多由上眼睑完成闭合。闭眼接合与下眼睑移动上限始终生效')
    smile_arc:bpy.props.FloatProperty(name='笑眼弧度',default=1.,min=.15,max=1.,
        description='调整笑闭眼向上拱起的弧度，始终保留向上弧线，并受闭合边界限制')
    smile_preserve:bpy.props.FloatProperty(name='笑眼形态保持',default=.85,min=0.,max=1.,
        description='保留上眼线的整体形态；闭合、贴脸及厚度约束优先于形态保持')
    message:bpy.props.StringProperty(default='只需需添加表情的模型及面部分区，无需源模型')


def style_options(layout,settings):
    layout.prop(settings,'show_styles',text='风格设置',icon='TRIA_DOWN' if settings.show_styles else 'TRIA_RIGHT',emboss=False)
    if settings.show_styles:
        column=layout.column(align=True)
        for name in ('lower_lid_participation','smile_arc','smile_preserve'):column.prop(settings,name,slider=True)


def visible_choices(settings):
    query=settings.expression_search.strip().casefold()
    return [i for i,item in enumerate(settings.expressions)
            if (settings.expression_family=='ALL' or item.family==settings.expression_family)
            and (not query or query in item.name.casefold())]


class EKPROC_OT_choose(bpy.types.Operator):
    bl_idname='exprkit_procedural.choose';bl_label='选择要生成的表情';bl_options={'REGISTER','UNDO'}
    action:bpy.props.EnumProperty(items=[(v,n,'') for v,n in (
        ('INIT','载入表情列表'),('TOGGLE','勾选表情'),('ALL','全选'),('NONE','全不选'),('INVERT','反选'))])
    index:bpy.props.IntProperty(default=-1)
    extend:bpy.props.BoolProperty(default=False,options={'HIDDEN','SKIP_SAVE'})
    only:bpy.props.BoolProperty(default=False,options={'HIDDEN','SKIP_SAVE'})

    @classmethod
    def description(cls,context,properties):
        if properties.action=='TOGGLE':return '勾选此表情；Shift 点击连续勾选，Ctrl 点击仅选此项'
        return '对当前搜索与类别筛选中显示的表情执行操作；隐藏项保持原勾选状态'

    def invoke(self,context,event):
        self.extend=event.shift;self.only=event.ctrl or event.oskey
        return self.execute(context)

    def execute(self,context):
        s=context.scene.exprkit_procedural;sync_choices(s);visible=visible_choices(s)
        if self.action=='TOGGLE':
            if self.index not in visible:return {'CANCELLED'}
            enabled=not s.expressions[self.index].enabled
            if self.only:
                for i,item in enumerate(s.expressions):item.enabled=i==self.index
            elif self.extend and s.selection_anchor in visible:
                a,b=sorted((visible.index(s.selection_anchor),visible.index(self.index)))
                for i in visible[a:b+1]:s.expressions[i].enabled=enabled
            else:s.expressions[self.index].enabled=enabled
            s.expression_index=self.index;s.selection_anchor=self.index
        elif self.action in ('ALL','NONE','INVERT'):
            for i in visible:
                item=s.expressions[i]
                item.enabled=not item.enabled if self.action=='INVERT' else self.action=='ALL'
            s.selection_anchor=-1
        if context.area:context.area.tag_redraw()
        return {'FINISHED'}


class EKPROC_UL_expressions(bpy.types.UIList):
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        row=layout.row(align=True)
        op=row.operator('exprkit_procedural.choose',text='',
            icon='CHECKBOX_HLT' if item.enabled else 'CHECKBOX_DEHLT',emboss=False)
        op.action='TOGGLE';op.index=index
        row.label(text=item.name)

    def filter_items(self,context,data,propname):
        visible=set(visible_choices(data))
        return [self.bitflag_filter_item if i in visible else 0 for i in range(len(getattr(data,propname)))],[]


def expression_options(layout,settings):
    if not settings.expressions and not bpy.app.timers.is_registered(initialize_lists):bpy.app.timers.register(initialize_lists,first_interval=.01)
    layout.prop(settings,'expression_search',text='',icon='VIEWZOOM')
    layout.prop(settings,'expression_family')
    row=layout.row(align=True)
    for action,label in (('ALL','全选'),('NONE','全不选'),('INVERT','反选')):
        row.operator('exprkit_procedural.choose',text=label).action=action
    count=len(generation_options(settings)['selection']);total=len(recipe_catalog())
    layout.label(text='已选 %d / %d'%(count,total))
    layout.template_list('EKPROC_UL_expressions','',settings,'expressions',settings,'expression_index',rows=8)
    layout.label(text='Shift 连选 · Ctrl 仅选此项')
    custom=getattr(bpy.context.scene,'exprkit_rules',None)
    if custom and custom.values:
        box=layout.box();box.label(text='自定义规则参数')
        for value in custom.values:box.prop(value,'value',text=value.name,slider=True)


def initialize_lists():
    if not hasattr(bpy.types.Scene,'exprkit_procedural'):return None
    for scene in bpy.data.scenes:
        sync_choices(scene.exprkit_procedural)
        if hasattr(scene,'exprkit_rules'):
            from .expression_ui import synchronize_values
            synchronize_values(scene)
    for screen in bpy.data.screens:
        for area in screen.areas:
            if area.type=='VIEW_3D':area.tag_redraw()
    return None


def flush(context):
    if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')


class EKPROC_OT_work(bpy.types.Operator):
    bl_idname='exprkit_procedural.work';bl_label='程序化表情操作';bl_options={'REGISTER','UNDO'}
    action:bpy.props.EnumProperty(items=[(s,s,'') for s in ('USE_CURRENT','PREPARE','SELECT','MARK','GUIDES','CURVE','LASH','CURVE_PREVIEW','GENERATE','COMBINE','RESULT','FINISH','RESTORE')])
    def invoke(self,context,event):
        if self.action=='GENERATE':
            from . import generation_job
            return generation_job.invoke(self,context,'PROCEDURAL')
        return self.execute(context)

    def modal(self,context,event):
        from . import generation_job
        return generation_job.modal(self,context,event)

    def cancel(self,context):
        from . import generation_job
        generation_job.cancel(self,context)

    def execute(self,context):
        s=context.scene.exprkit_procedural
        try:
            if self.action=='USE_CURRENT':
                old=context.scene.exprkit_regions
                if not old.target or not old.preview:raise ValueError('当前尚无目标分区，请直接选择需添加表情的模型')
                s.target=old.target;s.partition=old.preview;s.message='已选用现有目标及修正分区';return {'FINISHED'}
            if self.action=='PREPARE':
                flush(context);S.begin(context)
                s.working=P.prepare(s.target,s.partition,partition_method=s.partition_method);s.collection=None;s.output=None;s.confirmed=None
                S.focus(context,s.working);s.message='检查分区；可直接选面重新标记，再生成检查曲线'
                for screen in bpy.data.screens:
                    for area in screen.areas:
                        if area.type=='VIEW_3D':area.spaces.active.shading.color_type='MATERIAL'
            elif self.action=='SELECT':
                S.focus(context,s.working);context.tool_settings.mesh_select_mode=(False,False,True)
                if context.mode!='EDIT_MESH':bpy.ops.object.mode_set(mode='EDIT')
            elif self.action in ('MARK','LASH'):
                if context.object!=s.working or context.mode!='EDIT_MESH':raise ValueError('请在目标分区副本中进入选面模式')
                flush(context);ids=[p.index for p in s.working.data.polygons if p.select]
                if not ids:raise ValueError('请先选择需要标记的面')
                if self.action=='LASH':
                    if not s.collection:raise ValueError('请先生成检查曲线')
                    G.manual_lash(s.collection,s.working,s.working,'TARGET',ids)
                    for vertex in s.working.data.vertices:vertex.select=False
                    for edge in s.working.data.edges:edge.select=False
                    for face in s.working.data.polygons:face.select=False
                else:
                    value=int(s.label);label=value//10 if value>=80 else value
                    labels=R.mesh_regions(s.working);slot=next((p.material_index for p,l in zip(s.working.data.polygons,labels) if l==label),None)
                    if slot is None:
                        slot=len(s.working.data.materials);s.working.data.materials.append(A.marker_material(A.marker_name(label),A.region_color(label)))
                    mapping=json.loads(s.working.get('ek_standard_slot_labels','{}'));mapping[str(slot)]=label
                    s.working['ek_standard_slot_labels']=json.dumps(mapping)
                    attribute=s.working.data.attributes.get('ek_procedural_oral_group') or s.working.data.attributes.new('ek_procedural_oral_group','INT','FACE')
                    for i in ids:
                        s.working.data.polygons[i].material_index=slot;attribute.data[i].value=(1 if value%10==1 else -1) if value>=80 else 0
                    if s.collection:s.collection['ek_guide_needs_refresh']=True
                bpy.ops.object.mode_set(mode='EDIT');s.message='已标记；后续生成直接读取当前编辑'
            elif self.action in ('GUIDES','CURVE'):
                flush(context)
                if self.action=='GUIDES':
                    s.collection,report=R.detect(s.working,s.process_lashes);s.message='校正曲线共 %d 条；新补齐 %d 条；保留删除 %d 条'%(report['curves'],report['created'],report['deleted'])
                    s.message+='；'+'；'.join(report['warnings']) if report['warnings'] else ''
                if not s.collection:raise ValueError('请先生成检查曲线')
                visible=[o for o in s.collection.all_objects if s.kind=='ALL' or json.loads(o['ek_guide_entry'])['kind']==s.kind]
                primary=s.curve if s.curve in visible else next(iter(visible),s.working)
                for ob in visible:G.enforce_display(ob,s.working)
                if primary.type=='CURVE':s.curve=primary
                S.focus(context,primary,[s.working,*visible])
            elif self.action=='CURVE_PREVIEW':
                shared=context.scene.exprkit_regions
                if shared.target:
                    from .region_ui import resolve_curve_target
                    resolve_curve_target(shared)
                    s.target=shared.target;s.working=shared.preview;s.collection=shared.guide_collection
                flush(context);S.begin(context)
                from .generation_progress import Progress
                with Progress(context) as progress:
                    output,s.collection,quality=P.preview_curves(s.target,s.working,s.collection,s.process_lashes,progress)
                if s.curve_preview:A.set_hidden_if_present(s.curve_preview)
                s.curve_preview=output
                if shared.preview==s.working:shared.guide_collection=s.collection
                guides=[o for o in s.collection.all_objects if 'ek_guide_entry' in o]
                S.focus(context,output,[output,*guides])
                s.message='已更新曲线校正预览；继续编辑后可再次预览，整套表情尚未生成'
                if quality['unresolved']:s.message+='；存在待检查的局部约束冲突'
                shared.message=s.message
            elif self.action=='GENERATE':
                flush(context)
                choices=generation_options(s)
                if not choices['selection']:raise ValueError('请至少勾选一个表情')
                from .generation_progress import Progress
                with Progress(context) as progress:
                    output,s.collection,report=P.generate(s.target,s.working,s.collection,progress=progress,
                        process_lashes=s.process_lashes,**choices)
                if s.output:A.set_hidden_if_present(s.output)
                s.output=output;s.confirmed=None;S.focus(context,output)
                s.message='已生成 %d 个表情，跳过 %d 个；耗时 %.1f 秒'%(report['keys'],len(report['skipped']),progress.elapsed)
                if report.get('eye_anatomy'):s.message+='；球形眼球适配：%d 侧'%len(report['eye_anatomy'])
                compute=report.get('compute',{})
                if compute.get('gpu_calls'):s.message+='；GPU 接触计算：'+compute['device']
                elif compute.get('fallback_reason'):s.message+='；已回退 CPU：'+compute['fallback_reason'][:100]
                if report['skipped']:s.message+='；'+'；'.join(sorted({row['reason'] for row in report['skipped']}))
                if report['unresolved']:s.message+='；部分表情需检查变形或遮挡：'+','.join(report['unresolved'])
            elif self.action=='COMBINE':
                shared=context.scene.exprkit_regions
                if shared.transferred and shared.transferred.get('ek_procedural_version'):
                    s.target=shared.target;s.working=shared.preview;s.collection=shared.guide_collection;s.output=shared.transferred
                flush(context)
                from .generation_progress import Progress
                with Progress(context) as progress:
                    name,quality=P.combine(s.target,s.working,s.collection,s.output,s.combination,progress=progress,
                        process_lashes=s.process_lashes)
                S.focus(context,s.output);s.message='已按当前权重重新求解「'+name+'」，原权重已归零';s.confirmed=None
                if shared.transferred==s.output:shared.confirmed_result=None;shared.message=s.message
            elif self.action=='RESULT':S.focus(context,s.output)
            elif self.action=='FINISH':
                flush(context)
                if not s.output:raise ValueError('请先生成并检查新的结果')
                if s.output.get('ek_confirmed_target')==s.target:
                    raise ValueError('该结果已经确认，无需重复覆盖')
                if s.output.get('ek_procedural_version')!=P.VERSION:
                    raise ValueError('结果格式不属于当前版本，请重新生成表情')
                if s.output.get('ek_commit_target')!=s.target or s.output.get('ek_transfer_target')!=s.target:
                    raise ValueError('结果不属于当前目标，请重新生成表情')
                s.collection,snapshot=R.checkpoint(s.working,s.collection,s.process_lashes,recover_lashes=True)
                if s.output.get('ek_procedural_hash')!=snapshot['hash'] or s.output.get('ek_procedural_input')!=snapshot['input']:
                    raise ValueError('曲线或分区已修改，请重新生成后再确认')
                if not options_match(s,s.output,True):raise ValueError('生成设置已改变，请重新生成后再确认')
                count,backup,children=K.apply(s.target,s.output)
                final=s.output.get('ek_confirmed_target')
                S.restore(context,final=final)
                for child in children:
                    child.hide_viewport=s.target.hide_viewport;child.hide_render=s.target.hide_render
                    if context.view_layer.objects.get(child.name):child.hide_set(s.target.hide_get())
                s.confirmed=s.output;s.message='已确认并恢复原场景显示；已写回「'+final.name+'」并保留原材质及覆盖前备份'
            elif self.action=='RESTORE':S.restore(context)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


def button(layout,action,text,enabled=True):
    row=layout.row();row.enabled=enabled;row.operator('exprkit_procedural.work',text=text).action=action


def lash_options(layout,settings,collection,context=None):
    from .generation_progress import cached_labels
    context=context or bpy.context
    box=layout.box();box.label(text='单根睫毛')
    box.prop(settings,'process_lashes')
    def labels():
        units=[json.loads(o['ek_guide_entry']) for o in collection.all_objects
               if 'ek_guide_entry' in o and G.is_active(o)] if collection else []
        count=sum(e['kind']=='LASH' for e in units)
        return [(('已标记 %d 根'%count) if count else '无单根标记，不生成独立形变','INFO')]
    cached_labels(box,context,('lashes',collection.as_pointer() if collection else 0),labels)
    if not settings.process_lashes:box.label(text='睫毛片随整体眼睑移动')


def curve_feedback(layout,collection,target,context=None):
    if not collection or not target:return
    from .generation_progress import cached_labels
    context=context or bpy.context
    def labels():
        result=[]
        try:
            rows=G.current(collection,target);changed=sum(G.edited(o,target) for o in collection.all_objects if 'ek_guide_entry' in o)
            _,deleted=G.deleted_keys(collection,persist=False)
            result.append(('已校正 %d 条；已删除 %d 条'%(changed,len(deleted)),'CURVE_DATA'))
            stamp=G.state_hash(collection,rows);previous=collection.get('ek_guide_preview_hash')
            options=context.scene.exprkit_procedural
            settings_changed=options.process_lashes!=bool(collection.get('ek_process_individual_lashes',True))
            if any(o.mode=='EDIT' for o in collection.all_objects if o.type=='CURVE'):
                result.append(('正在编辑生成规则，完成后直接生成','EDITMODE_HLT'))
            elif settings_changed:result.append(('睫毛规则已改变，直接重新生成表情','INFO'))
            elif changed:result.append(('当前曲线直接决定生成规则','INFO'))
            if previous and previous!=stamp:result.append(('预览副本未更新，不影响直接生成','INFO'))
            if deleted:result.append(('已删必要曲线对应的表情将跳过','INFO'))
        except (ValueError,KeyError,TypeError) as exc:
            result.append((str(exc),'ERROR'))
        return result
    cached_labels(layout,context,('curves',collection.as_pointer(),target.as_pointer()),labels)


class EKPROC_OT_export_timing(bpy.types.Operator,ExportHelper):
    bl_idname='exprkit_procedural.export_timing';bl_label='导出最近一次耗时报告'
    filename_ext='.json'
    filter_glob:bpy.props.StringProperty(default='*.json',options={'HIDDEN'})

    @classmethod
    def poll(cls,context):
        from .generation_progress import active,REPORT_KEY
        return not active(context) and bool(context.scene.get(REPORT_KEY))

    def execute(self,context):
        from pathlib import Path
        from .generation_progress import REPORT_KEY
        try:
            report=json.loads(context.scene[REPORT_KEY])
            Path(self.filepath).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        except (OSError,ValueError,KeyError) as exc:
            self.report({'ERROR'},'耗时报告导出失败：'+str(exc));return {'CANCELLED'}
        self.report({'INFO'},'已导出阶段、表情、界面刷新耗时和约束工作量');return {'FINISHED'}


class EKPROC_PT_panel(bpy.types.Panel):
    bl_idname='EKPROC_PT_panel';bl_label='程序化表情';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='ExpressionGen';bl_order=1
    def draw(self,context):
        from .generation_progress import controls,draw
        s=context.scene.exprkit_procedural;l=controls(self.layout,context)
        for line in textwrap.wrap(s.message,width=23):l.label(text=line)
        l.separator();l.label(text='1 · 目标与分区')
        l.prop(s,'target');l.prop(s,'partition');l.prop(s,'partition_method');button(l,'USE_CURRENT','使用当前修正分区')
        button(l,'PREPARE','创建目标分区副本',bool(s.target))
        if s.working:
            button(l,'SELECT','选中分区副本并选面');l.prop(s,'label');button(l,'MARK','标记所选面')
        l.separator();l.label(text='2 · 轮廓校正')
        lash_options(l,s,s.collection)
        button(l,'GUIDES','生成 / 补齐校正曲线',bool(s.working))
        if s.collection:
            l.prop(s,'kind');l.prop(s,'curve');button(l,'CURVE','显示并选中检查曲线')
            button(l,'LASH','将所选面指定为单根睫毛')
            curve_feedback(l,s.collection,s.working)
        l.separator();l.label(text='3 · 生成与检查')
        l.prop(s,'show_options',icon='TRIA_DOWN' if s.show_options else 'TRIA_RIGHT',emboss=False)
        if s.show_options:
            expression_options(l,s)
        l.prop(s,'force_symmetry')
        l.prop(s,'compute_backend')
        style_options(l,s)
        row=self.layout.row()
        if not draw(row,context):
            row.enabled=bool(s.working)
            row.operator('exprkit_procedural.work',text='生成目标表情副本').action='GENERATE'
        l=controls(self.layout,context)
        if s.output:
            button(l,'RESULT','选中结果并检查形态键');l.prop(s,'combination')
            button(l,'COMBINE','按当前形态键权重合成')
            l.label(text='组合会重新求解轮廓，避免重复闭合')
            l.separator();l.label(text='4 · 确认完成')
            applied=bool(s.target and s.output.get('ek_confirmed_target')==s.target)
            if s.target:l.label(text='写入目标：'+s.target.name)
            matches=s.output.get('ek_commit_target')==s.target
            if not matches:l.label(text='目标已改变，请重新生成表情',icon='ERROR')
            elif applied:l.label(text='表情已写入需添加表情的模型',icon='CHECKMARK')
            button(l,'FINISH','写入目标并恢复显示',matches and not applied)
        button(l,'RESTORE','暂时恢复原场景显示',context.scene.exprkit_regions.session_running)


CLASSES=(EKPROC_Expression,EKPROC_Settings,EKPROC_OT_choose,EKPROC_UL_expressions,EKPROC_OT_work,EKPROC_OT_export_timing)
def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.exprkit_procedural=bpy.props.PointerProperty(type=EKPROC_Settings)
def unregister():
    if hasattr(bpy.types.Scene,'exprkit_procedural'):del bpy.types.Scene.exprkit_procedural
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
