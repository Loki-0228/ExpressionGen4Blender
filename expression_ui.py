"""Visual rule authoring, portable IO, pose curve editing and combinations."""
import json
import bpy
import numpy as np
from bpy_extras.io_utils import ImportHelper,ExportHelper
from . import expression_rules as Rules,expression_authoring as Author,expression_runtime as Runtime
from . import region_guides as G,region_session as S,procedural_rig as R
from . import region_core as C


METRICS=[(key,label,'') for key,label in zip(Rules.METRICS,('中心 X 比例','中心 Y 比例','中心 Z 比例','X 尺寸占比','Y 尺寸占比','Z 尺寸占比','弧长占比','宽高比','边界环数量','连通块数量','是否闭合','顶点数量'))]
KINDS=[(key,label,'') for key,label in G.KINDS.items()]


class EKRULE_Node(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='曲线 ID')
    mode:bpy.props.EnumProperty(name='识别方式',items=[('GUIDE','已有校正曲线',''),('BOUNDARY','分区边界',''),('SECTION','分区截面',''),('DERIVED','引用另一曲线','')])
    kind:bpy.props.EnumProperty(name='控制部位',items=KINDS)
    region:bpy.props.IntProperty(name='所属分区',default=0,options={'HIDDEN'})
    region_number:bpy.props.IntProperty(name='所属分区',default=0,min=-1,max=6,
        **C.region_number_accessors('region'))
    side:bpy.props.EnumProperty(name='左右侧',items=[('0','中间',''),('1','X 正侧',''),('-1','X 负侧','')])
    index:bpy.props.IntProperty(name='同类候选序号',default=0,min=0)
    reference:bpy.props.StringProperty(name='引用曲线 ID')
    axis:bpy.props.EnumProperty(name='截面轴',items=[('0','X',''),('1','Y',''),('2','Z','')],default='2')
    position:bpy.props.FloatProperty(name='截面位置比例',default=.5,min=0,max=1)
    offset:bpy.props.FloatVectorProperty(name='相对偏移',size=3,min=-2,max=2)


class EKRULE_Criterion(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='所属曲线 ID')
    metric:bpy.props.EnumProperty(name='特点',items=METRICS)
    reference:bpy.props.StringProperty(name='参照曲线 ID（空为模型）')
    minimum:bpy.props.FloatProperty(name='最小值',default=-1.)
    maximum:bpy.props.FloatProperty(name='最大值',default=1.)


def shift_changed(item,context):
    item.target_points='';item.original_curve=None;item.target_curve=None;item.target_ref='';item.target_rule=''


class EKRULE_Calculation(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='规则 ID')
    source:bpy.props.StringProperty(name='原始识别曲线 ID')
    target_ref:bpy.props.StringProperty(name='目标识别曲线 ID（可选）')
    target_rule:bpy.props.StringProperty(name='目标规则 ID（可选）')
    shift:bpy.props.FloatVectorProperty(name='归一化目标偏移',size=3,min=-2,max=2,update=shift_changed,
        description='设置此值会将当前目标替换为统一偏移；复杂目标可编辑下方的目标曲线')
    target_points:bpy.props.StringProperty(default='')
    original_curve:bpy.props.PointerProperty(name='原始曲线',type=bpy.types.Object,poll=lambda s,o:o.type=='CURVE')
    target_curve:bpy.props.PointerProperty(name='目标曲线',type=bpy.types.Object,poll=lambda s,o:o.type=='CURVE')
    amount:bpy.props.FloatProperty(name='接近目标程度',default=1.,min=0,max=1)
    parameter:bpy.props.StringProperty(name='绑定参数 ID（可选）')


class EKRULE_Influence(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='所属规则 ID')
    curve:bpy.props.StringProperty(name='影响曲线 ID（可选）')
    region:bpy.props.IntProperty(name='影响网格分区',default=0,options={'HIDDEN'})
    region_number:bpy.props.IntProperty(name='影响网格分区',default=0,min=-1,max=6,
        **C.region_number_accessors('region'))
    metric:bpy.props.EnumProperty(name='影响特点',items=METRICS)
    input_min:bpy.props.FloatProperty(name='输入下限',default=0.)
    input_max:bpy.props.FloatProperty(name='输入上限',default=1.)
    output_min:bpy.props.FloatProperty(name='下限对应程度',default=0.,min=0,max=1)
    output_max:bpy.props.FloatProperty(name='上限对应程度',default=1.,min=0,max=1)


class EKRULE_Parameter(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='参数 ID')
    label:bpy.props.StringProperty(name='界面名称',default='接近程度')
    minimum:bpy.props.FloatProperty(name='最小值',default=0.,min=0,max=1)
    maximum:bpy.props.FloatProperty(name='最大值',default=1.,min=0,max=1)
    default:bpy.props.FloatProperty(name='默认值',default=1.,min=0,max=1)
    exposed:bpy.props.BoolProperty(name='在生成界面显示',default=True)


def value_changed(item,context):
    scene=item.id_data;values=json.loads(scene.get('ek_expression_values','{}'))
    value=max(item.minimum,min(item.maximum,item.value))
    if abs(value-item.value)>1e-7:item.value=value;return
    values.setdefault(item.expression,{})[item.parameter]=value
    scene['ek_expression_values']=json.dumps(values,ensure_ascii=False)


class EKRULE_Value(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty()
    expression:bpy.props.StringProperty()
    parameter:bpy.props.StringProperty()
    minimum:bpy.props.FloatProperty()
    maximum:bpy.props.FloatProperty(default=1.)
    value:bpy.props.FloatProperty(name='参数值',default=1.,min=0,max=1,update=value_changed)


class EKRULE_Mask(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='条件名称')
    region:bpy.props.IntProperty(name='分区编号（-2 为全部）',default=-2,options={'HIDDEN'})
    region_number:bpy.props.IntProperty(name='分区编号（-2 为全部）',default=-2,min=-2,max=6,
        **C.region_number_accessors('region'))
    axis:bpy.props.EnumProperty(name='位置轴',items=[('0','X',''),('1','Y',''),('2','Z','')])
    minimum:bpy.props.FloatProperty(name='位置比例下限',default=0.,min=0,max=1)
    maximum:bpy.props.FloatProperty(name='位置比例上限',default=1.,min=0,max=1)


class EKRULE_Term(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='来源表情名称')
    weight:bpy.props.FloatProperty(name='组合权重',default=1.,min=0,max=1)


class EKRULE_Settings(bpy.types.PropertyGroup):
    name:bpy.props.StringProperty(name='表情名称',default='自定义表情')
    base:bpy.props.StringProperty(name='基础表情（可选）')
    base_recipe:bpy.props.StringProperty(default='')
    mode:bpy.props.EnumProperty(name='定义方式',items=[('CURVES','曲线计算规则',''),('SIDE','取来源的左侧或右侧',''),('FILTER','取满足条件的网格',''),('COMBINATION','组合已有表情','')])
    can_symmetrize:bpy.props.BoolProperty(name='允许强制左右对称',default=False)
    special:bpy.props.BoolProperty(name='特殊表情（不强制对称）',default=False)
    relation_source:bpy.props.StringProperty(name='来源表情')
    relation_side:bpy.props.EnumProperty(name='保留侧',items=[('1','左侧（X 正侧）',''),('-1','右侧（X 负侧）','')])
    conditions:bpy.props.CollectionProperty(type=EKRULE_Mask)
    condition_index:bpy.props.IntProperty(min=0)
    terms:bpy.props.CollectionProperty(type=EKRULE_Term)
    term_index:bpy.props.IntProperty(min=0)
    page:bpy.props.EnumProperty(items=[('RECOGNIZE','识别曲线',''),('COMPUTE','计算规则',''),('PARAMETERS','界面参数','')])
    source_expression:bpy.props.StringProperty(name='已有表情（空为 Basis）')
    curve_name:bpy.props.StringProperty(name='写回表情名',default='自定义表情')
    curve_collection:bpy.props.PointerProperty(type=bpy.types.Collection)
    show_sculpt:bpy.props.BoolProperty(default=False)
    sculpt_object:bpy.props.PointerProperty(type=bpy.types.Object)
    sculpt_scope:bpy.props.EnumProperty(name='转换范围',items=[('VISIBLE','当前组可见曲线',''),('SELECTED','当前组选中曲线','')])
    sculpt_width:bpy.props.FloatProperty(name='面片宽度比例',description='相对于分区模型宽度；只改变雕刻面片宽度，不改变曲线',default=.004,min=.0001,max=.2,precision=4)
    sculpt_along:bpy.props.IntProperty(name='纵向细分',default=64,min=4,max=512)
    sculpt_across:bpy.props.IntProperty(name='横向细分',default=2,min=1,max=16)
    sculpt_fit:bpy.props.IntProperty(name='写回拟合段数',default=8,min=1,max=64)
    nodes:bpy.props.CollectionProperty(type=EKRULE_Node)
    node_index:bpy.props.IntProperty(min=0)
    criteria:bpy.props.CollectionProperty(type=EKRULE_Criterion)
    criterion_index:bpy.props.IntProperty(min=0)
    calculations:bpy.props.CollectionProperty(type=EKRULE_Calculation)
    calculation_index:bpy.props.IntProperty(min=0)
    influences:bpy.props.CollectionProperty(type=EKRULE_Influence)
    influence_index:bpy.props.IntProperty(min=0)
    parameters:bpy.props.CollectionProperty(type=EKRULE_Parameter)
    parameter_index:bpy.props.IntProperty(min=0)
    values:bpy.props.CollectionProperty(type=EKRULE_Value)
    message:bpy.props.StringProperty()


def synchronize_values(scene):
    settings=scene.exprkit_rules;stored=json.loads(scene.get('ek_expression_values','{}'))
    settings.values.clear()
    for spec in Author.library(scene):
        for p in spec['parameters']:
            if not p['exposed']:continue
            item=settings.values.add();item.name=spec['name']+' · '+p.get('label',p['id'])
            item.expression=spec['name'];item.parameter=p['id'];item.minimum=p['min'];item.maximum=p['max']
            item.value=stored.get(spec['name'],{}).get(p['id'],p['default'])


def draft(context,recognize_only=False):
    s=context.scene.exprkit_rules;partition=context.scene.exprkit_regions.preview
    spec=dict(name=s.name.strip(),base=s.base.strip(),family='custom',solver='curve_rules_v1',constraints=list(Rules.CONSTRAINTS),recognizers=[],rules=[],parameters=[],can_symmetrize=s.can_symmetrize,special=s.special)
    if s.mode!='CURVES':
        spec['base']='';spec['can_symmetrize']=False
        spec['relation']=dict(mode=s.mode,source=s.relation_source.strip(),side=int(s.relation_side))
        if s.mode=='FILTER':spec['relation']['conditions']=[dict(region=c.region,axis=int(c.axis),min=c.minimum,max=c.maximum) for c in s.conditions]
        if s.mode=='COMBINATION':spec['relation']['terms']=[dict(source=t.name.strip(),weight=t.weight) for t in s.terms]
        return Rules.validate(spec)
    if s.base_recipe:spec['base_recipe']=json.loads(s.base_recipe)
    if any(c.name not in {n.name for n in s.nodes} for c in s.criteria):raise ValueError('识别条件的所属曲线 ID 不存在')
    for n in s.nodes:
        spec['recognizers'].append(dict(id=n.name,mode=n.mode,kind=n.kind,region=n.region,side=int(n.side),index=n.index,
            reference=n.reference,axis=int(n.axis),position=n.position,offset=list(n.offset),
            criteria=[dict(metric=c.metric,reference=c.reference,min=c.minimum,max=c.maximum) for c in s.criteria if c.name==n.name]))
    if recognize_only:
        if not spec['recognizers']:raise ValueError('请先添加识别曲线')
        spec['rules']=[dict(id='recognition_preview',source=spec['recognizers'][0]['id'],target_points=[[0,0,0],[0,0,0]],amount=0)]
        return Rules.validate(spec)
    if any(f.name not in {r.name for r in s.calculations} for f in s.influences):raise ValueError('影响项的所属规则 ID 不存在')
    for r in s.calculations:
        target_ref=r.target_ref;target_rule=r.target_rule
        points=json.loads(r.target_points) if r.target_points else [list(r.shift),list(r.shift)]
        if r.original_curve and r.target_curve:
            if not partition:raise ValueError('请先选择分区副本')
            original=Runtime.samples(G.curve_points(r.original_curve,partition));target=Runtime.samples(G.curve_points(r.target_curve,partition))
            points=((target-original)@np.linalg.inv(Runtime.frame(original)).T).tolist()
            if (not target_ref and not target_rule) or G.digest(G.curve_points(r.target_curve,partition))!=r.target_curve.get('ek_rule_initial'):
                target_ref='';target_rule=''
        spec['rules'].append(dict(id=r.name,source=r.source,target_curve=target_ref,target_rule=target_rule,target_points=points,
            amount=r.amount,parameter=r.parameter,influences=[dict(curve=f.curve,region=f.region,metric=f.metric,
                input_min=f.input_min,input_max=f.input_max,output_min=f.output_min,output_max=f.output_max) for f in s.influences if f.name==r.name]))
    spec['parameters']=[dict(id=p.name,label=p.label,min=p.minimum,max=p.maximum,default=p.default,exposed=p.exposed) for p in s.parameters]
    return Rules.validate(spec)


def load_draft(scene,spec):
    s=scene.exprkit_rules;s.name=spec['name'];s.base=spec.get('base','');s.base_recipe=json.dumps(spec['base_recipe']) if spec.get('base_recipe') else ''
    relation=spec.get('relation',{});s.mode=relation.get('mode','CURVES')
    s.can_symmetrize=spec.get('can_symmetrize',False);s.special=spec.get('special',False)
    s.relation_source=relation.get('source','');s.relation_side=str(relation.get('side',1))
    s.conditions.clear();s.terms.clear()
    for row in relation.get('conditions',[]):
        c=s.conditions.add();c.name='条件 '+str(len(s.conditions));c.region=row.get('region',-2);c.axis=str(row['axis']);c.minimum=row['min'];c.maximum=row['max']
    for row in relation.get('terms',[]):
        t=s.terms.add();t.name=row['source'];t.weight=row.get('weight',1)
    for key in ('nodes','criteria','calculations','influences','parameters'):getattr(s,key).clear()
    for r in spec['recognizers']:
        n=s.nodes.add();n.name=r['id'];n.mode=r['mode'];n.kind=r['kind'];n.region=r['region'];n.side=str(r['side']);n.index=r.get('index',0)
        n.reference=r.get('reference','');n.axis=str(r.get('axis',2));n.position=r.get('position',.5);n.offset=r.get('offset',[0,0,0])
        for row in r.get('criteria',[]):
            c=s.criteria.add();c.name=n.name;c.metric=row['metric'];c.reference=row.get('reference','');c.minimum=row['min'];c.maximum=row['max']
    for row in spec['rules']:
        r=s.calculations.add();r.name=row['id'];r.source=row['source'];r.target_ref=row.get('target_curve','');r.target_rule=row.get('target_rule','')
        r.target_points=json.dumps(row.get('target_points',[[0,0,0],[0,0,0]]));r.amount=row.get('amount',1);r.parameter=row.get('parameter','')
        for f in row.get('influences',[]):
            item=s.influences.add();item.name=r.name
            for key in ('curve','region','metric','input_min','input_max','output_min','output_max'):
                if key in f:setattr(item,key,f[key])
    for row in spec['parameters']:
        p=s.parameters.add();p.name=row['id'];p.label=row.get('label',p.name);p.minimum=row['min'];p.maximum=row['max'];p.default=row['default'];p.exposed=row['exposed']
    for key in ('node_index','criterion_index','calculation_index','influence_index','parameter_index'):setattr(s,key,0)


class EKRULE_OT_edit(bpy.types.Operator):
    bl_idname='exprkit_rules.edit';bl_label='自定义表情规则操作';bl_options={'REGISTER','UNDO'}
    action:bpy.props.StringProperty()
    field:bpy.props.StringProperty()
    index_field:bpy.props.StringProperty()
    def execute(self,context):
        s=context.scene.exprkit_rules;shared=context.scene.exprkit_regions
        try:
            if self.action=='ADD':
                rows=getattr(s,self.field);item=rows.add();item.name=self.field+'_'+str(len(rows));setattr(s,self.index_field,len(rows)-1)
                if self.field=='criteria' and s.nodes:item.name=s.nodes[min(s.node_index,len(s.nodes)-1)].name
                if self.field=='influences' and s.calculations:item.name=s.calculations[min(s.calculation_index,len(s.calculations)-1)].name
                if self.field=='calculations' and s.nodes:item.source=s.nodes[min(s.node_index,len(s.nodes)-1)].name
            elif self.action=='REMOVE':
                rows=getattr(s,self.field);index=getattr(s,self.index_field)
                if rows:rows.remove(min(index,len(rows)-1));setattr(s,self.index_field,max(0,index-1))
            elif self.action=='SAVE':
                Author.save(context.scene,draft(context));synchronize_values(context.scene);s.message='已保存，可在表情生成列表中勾选'
            elif self.action=='LOAD':
                spec=next((r for r in Author.library(context.scene) if r['name']==s.name),None)
                if spec is None:raise ValueError('没有该名称的已保存自定义规则')
                load_draft(context.scene,spec);s.message='已读取规则'
            elif self.action=='CLEAR':
                for key in ('nodes','criteria','calculations','influences','parameters','conditions','terms'):getattr(s,key).clear()
                s.base='';s.base_recipe='';s.name='自定义表情';s.mode='CURVES';s.can_symmetrize=False;s.special=False;s.relation_source=''
            elif self.action in ('RULE_CURVES','RECOGNIZE'):
                if not shared.preview:raise ValueError('请先创建分区')
                if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
                spec=draft(context,recognize_only=self.action=='RECOGNIZE')
                shared.guide_collection,snapshot=R.checkpoint(shared.preview,shared.guide_collection,context.scene.exprkit_procedural.process_lashes)
                rig=R.Rig(shared.preview,snapshot,shared.close_neutral_mouth);nodes=Runtime.recognize(rig,spec)
                group=bpy.data.collections.new('EK规则曲线_'+s.name);context.scene.collection.children.link(group);group['ek_guide_target']=shared.preview
                if self.action=='RECOGNIZE':
                    objects=[]
                    for node in nodes.values():
                        entry=dict(key='RECOGNITION:'+group.name+':'+node['id'],kind=node['kind'],side=node['side'],role='TARGET',points=node['points'].tolist(),vertices=node['vertices'])
                        ob=G.add_curve(group,shared.preview,entry);ob.name=s.name+'_'+node['id'];ob['ek_expression_curve']=True;objects.append(ob)
                    S.focus(context,objects[0],[shared.preview,*objects]);s.message='已显示识别结果；修改识别条件后可重新显示'
                else:
                    r=s.calculations[min(s.calculation_index,len(s.calculations)-1)];node=nodes[r.source]
                    recipe=Rules.runtime_recipe(spec,Rules.builtin_profile()['recipes']);Runtime.evaluate(rig,recipe)
                    points=Runtime.samples(node['points']);target=rig.custom_rule_targets[spec['name'],r.name]
                    for role,cloud in (('原始',points),('目标',target)):
                        entry=dict(key='RULE:'+group.name+':'+role,kind=node['kind'],side=node['side'],role='TARGET',points=cloud.tolist(),vertices=node['vertices'])
                        ob=G.add_curve(group,shared.preview,entry);ob.name=s.name+'_'+r.name+'_'+role;ob['ek_expression_curve']=True
                        ob['ek_rule_initial']=G.digest(G.curve_points(ob,shared.preview))
                        if role=='原始':r.original_curve=ob
                        else:r.target_curve=ob
                    S.focus(context,r.target_curve,[shared.preview,r.original_curve]);s.message='编辑目标曲线后保存规则'
            elif self.action=='COPIES':
                s.curve_collection,objects=Author.create_copies(context,s.source_expression,s.curve_name)
                S.focus(context,objects[0],[shared.transferred,*objects]);s.message='编辑表情曲线后点击写回'
            elif self.action=='WRITE':
                from .generation_progress import Progress
                with Progress(context) as progress:name,quality=Author.write_copies(context,s.curve_collection,progress)
                synchronize_values(context.scene);S.focus(context,shared.transferred,list(s.curve_collection.all_objects))
                s.message='已写回「'+name+'」并保存可迁移规则；约束冲突 %d'%quality['unresolved']
            elif self.action=='MIRROR':
                source=context.object if context.object and context.object.type=='CURVE' else shared.guide_selected
                destination=Author.mirror(context,source);s.message='已镜像至 '+destination.name
            elif self.action=='SCULPT':
                from . import curve_sculpt
                count=curve_sculpt.create(context);s.message='已将 %d 条曲线合并为雕刻面片，按材质和面组区分'%count
            elif self.action=='SCULPT_WRITE':
                from . import curve_sculpt
                count=curve_sculpt.write(context);s.message='已写回 %d 条曲线并删除编辑面片；重新生成表情即可应用'%count
            elif self.action=='SCULPT_CANCEL':
                from . import curve_sculpt
                edit=curve_sculpt.current(context)
                if not edit:raise ValueError('没有可取消的编辑面片')
                first=edit.get('ek_sculpt_source_0');target=edit.get('ek_sculpt_target')
                curve_sculpt.remove(context,edit)
                if first:S.focus(context,first,[target])
                s.message='已取消面片编辑，曲线保持原样'
            shared.message=s.message
            return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));s.message=str(exc);return {'CANCELLED'}


class EKRULE_OT_export(bpy.types.Operator,ExportHelper):
    bl_idname='exprkit_rules.export';bl_label='导出计算规则表格与 JSON'
    filename_ext='.json'
    filter_glob:bpy.props.StringProperty(default='*.json',options={'HIDDEN'})
    def execute(self,context):
        try:
            paths=Rules.write_document(self.filepath,Author.library(context.scene))
            self.report({'INFO'},'已导出 '+paths[0].name+' 与 '+paths[1].name);return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


class EKRULE_OT_import(bpy.types.Operator,ImportHelper):
    bl_idname='exprkit_rules.import_rules';bl_label='读取表情规则 JSON';bl_options={'REGISTER','UNDO'}
    filename_ext='.json'
    filter_glob:bpy.props.StringProperty(default='*.json',options={'HIDDEN'})
    def execute(self,context):
        try:
            from pathlib import Path
            path=Path(self.filepath)
            if path.stat().st_size>32*1024*1024:raise ValueError('规则文件超过 32 MB')
            rows=Rules.read_document(json.loads(path.read_text(encoding='utf-8-sig')))
            Author.save_many(context.scene,rows)
            if rows:load_draft(context.scene,rows[0])
            synchronize_values(context.scene)
            self.report({'INFO'},'已读取内置规则并导入 %d 个自定义表情'%len(rows));return {'FINISHED'}
        except Exception as exc:self.report({'ERROR'},str(exc));return {'CANCELLED'}


def button(layout,action,label):layout.operator('exprkit_rules.edit',text=label).action=action


def edit_list(layout,s,field,index_field,fields):
    box=layout.box();row=box.row();row.template_list('UI_UL_list',field,s,field,s,index_field,rows=3)
    col=row.column(align=True)
    for action,icon in (('ADD','ADD'),('REMOVE','REMOVE')):
        op=col.operator('exprkit_rules.edit',text='',icon=icon);op.action=action;op.field=field;op.index_field=index_field
    rows=getattr(s,field)
    if rows:
        item=rows[min(getattr(s,index_field),len(rows)-1)]
        for key in fields:box.prop(item,key)
    return box


class EKRULE_PT_custom(bpy.types.Panel):
    bl_label='自定义表情 · 曲线编辑';bl_idname='EKRULE_PT_custom';bl_parent_id='EKREG_PT_panel'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='ExpressionGen';bl_order=6;bl_options={'DEFAULT_CLOSED'}
    def draw(self,context):
        from .generation_progress import controls
        s=context.scene.exprkit_rules;shared=context.scene.exprkit_regions;l=controls(self.layout,context)
        output=shared.transferred
        if output and output.data.shape_keys:l.prop_search(s,'source_expression',output.data.shape_keys,'key_blocks')
        else:l.prop(s,'source_expression')
        l.prop(s,'curve_name');button(l,'COPIES','添加表情曲线副本')
        l.prop(shared,'curve_symmetry');button(l,'MIRROR','镜像当前侧至另一侧')
        from .curve_sculpt import draw
        draw(l,context)
        row=l.row();row.enabled=bool(s.curve_collection);button(row,'WRITE','按曲线重新计算并写回表情')
        if s.message:
            import textwrap
            for line in textwrap.wrap(s.message,width=24):l.label(text=line)


class EKRULE_PT_advanced(bpy.types.Panel):
    bl_label='自定义表情 · 可迁移规则';bl_idname='EKRULE_PT_advanced';bl_parent_id='EKREG_PT_panel'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='ExpressionGen';bl_order=7;bl_options={'DEFAULT_CLOSED'}
    def draw(self,context):
        from .generation_progress import controls
        s=context.scene.exprkit_rules;l=controls(self.layout,context);l.prop(s,'name');l.prop(s,'mode')
        if s.mode=='CURVES':
            l.prop(s,'base');l.prop(s,'can_symmetrize');l.prop(s,'special')
        row=l.row(align=True);button(row,'CLEAR','新建');button(row,'LOAD','读取同名');button(row,'SAVE','保存规则')
        if s.mode!='CURVES':
            if s.mode in ('SIDE','FILTER'):l.prop_search(s,'relation_source',context.scene.exprkit_procedural,'expressions')
            if s.mode=='SIDE':l.prop(s,'relation_side')
            elif s.mode=='FILTER':
                edit_list(l,s,'conditions','condition_index',('name','region_number','axis','minimum','maximum'))
                l.label(text='全部条件同时满足；边界自动平滑')
            else:edit_list(l,s,'terms','term_index',('name','weight'))
            l.label(text='子表情和组合不参与强制对称')
        else:l.prop(s,'page',expand=True)
        if s.mode=='CURVES' and s.page=='RECOGNIZE':
            edit_list(l,s,'nodes','node_index',('name','mode','kind','region_number','side','index','reference','axis','position','offset'))
            l.label(text='位置比例、尺寸占比与拓扑条件')
            edit_list(l,s,'criteria','criterion_index',('name','metric','reference','minimum','maximum'))
            button(l,'RECOGNIZE','显示识别曲线')
        elif s.mode=='CURVES' and s.page=='COMPUTE':
            edit_list(l,s,'calculations','calculation_index',('name','source','target_ref','target_rule','shift','amount','parameter','original_curve','target_curve'))
            button(l,'RULE_CURVES','创建原始与目标曲线供编辑')
            l.label(text='其他曲线或网格特点的影响')
            edit_list(l,s,'influences','influence_index',('name','curve','region_number','metric','input_min','input_max','output_min','output_max'))
        elif s.mode=='CURVES':edit_list(l,s,'parameters','parameter_index',('name','label','minimum','maximum','default','exposed'))
        l.label(text='沿用防穿插、附着和防翻折约束',icon='LOCKED')
        l.operator('exprkit_rules.export',text='导出全部规则表格与 JSON')
        l.operator('exprkit_rules.import_rules',text='读取规则 JSON')


class EKRULE_UL_mix(bpy.types.UIList):
    def draw_item(self,context,layout,data,item,icon,active_data,active_propname,index):
        row=layout.row(align=True);row.label(text=item.name,icon='SHAPEKEY_DATA');row.prop(item,'value',text='',slider=True)
    def filter_items(self,context,data,propname):
        output=context.scene.exprkit_regions.transferred;owned=json.loads(output.get('ek_effective_recipes','{}')) if output else {}
        return [self.bitflag_filter_item if item.name in owned else 0 for item in getattr(data,propname)],[]


class EKRULE_PT_mix(bpy.types.Panel):
    bl_label='组合表情';bl_idname='EKRULE_PT_mix';bl_parent_id='EKREG_PT_panel'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='ExpressionGen';bl_order=8;bl_options={'DEFAULT_CLOSED'}
    def draw(self,context):
        from .generation_progress import controls
        output=context.scene.exprkit_regions.transferred;l=controls(self.layout,context);s=context.scene.exprkit_procedural
        if not output or not output.data.shape_keys:l.label(text='先生成表情');return
        l.template_list('EKRULE_UL_mix','',output.data.shape_keys,'key_blocks',output,'active_shape_key_index',rows=8)
        l.prop(s,'combination');l.operator('exprkit_procedural.work',text='一键生成组合表情').action='COMBINE'


CLASSES=(EKRULE_Node,EKRULE_Criterion,EKRULE_Calculation,EKRULE_Influence,EKRULE_Parameter,EKRULE_Value,EKRULE_Mask,EKRULE_Term,EKRULE_Settings,
         EKRULE_OT_edit,EKRULE_OT_export,EKRULE_OT_import,EKRULE_PT_custom,EKRULE_PT_advanced,EKRULE_UL_mix,EKRULE_PT_mix)


def register():
    for cls in CLASSES:bpy.utils.register_class(cls)
    bpy.types.Scene.exprkit_rules=bpy.props.PointerProperty(type=EKRULE_Settings)


def unregister():
    if hasattr(bpy.types.Scene,'exprkit_rules'):del bpy.types.Scene.exprkit_rules
    for cls in reversed(CLASSES):bpy.utils.unregister_class(cls)
