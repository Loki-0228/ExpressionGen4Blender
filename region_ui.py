"""Target material partitions, editable contours and procedural expressions."""
import bpy
import json
from . import region_core, region_blender as A, region_transfer as T, region_guides as G, region_session as S, region_commit as K
from . import generation_progress as GP


def focus_changed(settings,context):
    from . import guide_overlay
    guide_overlay.update_focus(settings,context)


def ensure_working_visible(context, ob):
    if not A.is_working(ob):
        raise ValueError('请选择本插件创建的工作副本')
    # Scripts, scene changes, or undo can leave a working ID without a scene
    # collection. Reattach only our tagged copy, never an original model.
    if ob.name not in context.view_layer.objects:
        col = A.new_collection('ExpressionGen_工作副本')
        col.objects.link(ob)
    for col in ob.users_collection:
        col.hide_viewport = False
    ob.hide_viewport = False
    context.view_layer.update()
    if ob.name not in context.view_layer.objects:
        raise ValueError('工作副本所在集合被当前视图层排除')
    A.set_hidden_if_present(ob,False,context.view_layer)


class EKREG_Material(bpy.types.PropertyGroup):
    slot: bpy.props.IntProperty()
    title: bpy.props.StringProperty()
    faces: bpy.props.IntProperty()
    enabled: bpy.props.BoolProperty(default=False)


class EKREG_ObjectState(bpy.types.PropertyGroup):
    object: bpy.props.PointerProperty(type=bpy.types.Object)
    layer: bpy.props.StringProperty()
    hidden: bpy.props.BoolProperty()
    viewport: bpy.props.BoolProperty()
    unselectable: bpy.props.BoolProperty()
    selected: bpy.props.BoolProperty()
    present: bpy.props.BoolProperty(default=True)


class EKREG_CollectionState(bpy.types.PropertyGroup):
    collection: bpy.props.PointerProperty(type=bpy.types.Collection)
    layer: bpy.props.StringProperty()
    path: bpy.props.StringProperty()
    hidden: bpy.props.BoolProperty()
    viewport: bpy.props.BoolProperty()
    unselectable: bpy.props.BoolProperty()
    excluded: bpy.props.BoolProperty()


_PRESET_ITEMS={}
_PRESET_IDS={}
def standard_preset_items(_self,_context):
    rows=A.standard_presets()
    files=tuple((row['file'],row['name']) for row in rows)
    key=('filename-backed',files)
    if key not in _PRESET_ITEMS:
        # Blender keeps references to dynamic enum strings; retain each list.
        _PRESET_ITEMS[key]=[('__none__','请选择分区预设','选择自行保存的分区标准，或从 JSON 文件加载',0)]+[
            (file,name,'跨工程保存的已修正分区标准',_PRESET_IDS.setdefault(file,len(_PRESET_IDS)+1))
            for file,name in files]
    return _PRESET_ITEMS[key]


def standard_preset_get(settings):
    # Dynamic enums store integer values, while filenames are the stable
    # identity across refreshes, file additions and addon re-registration.
    items=standard_preset_items(settings,None)
    filename=settings.standard_preset_file
    if filename:return next((row[3] for row in items if row[0]==filename),0)
    old=settings.get('standard_preset',0)
    if not isinstance(old,int) or not old:return 0
    import zlib
    return next((row[3] for row in items if row[0]!='__none__'
                 and ((zlib.crc32(row[0].encode('utf-8')) & 0x7fffffff) or 1)==old),0)


def standard_preset_set(settings,value):
    items=standard_preset_items(settings,None)
    filename=next((row[0] for row in items if row[3]==value),None)
    if filename is None:raise ValueError('预设列表已改变，请刷新后重新选择')
    settings.standard_preset_file=filename


def selected_standard_preset(settings):
    return settings.standard_preset_file or settings.standard_preset


class EKREG_Settings(bpy.types.PropertyGroup):
    show_source_regions: bpy.props.BoolProperty(name='源材质分区详情', default=False)
    show_extract_materials: bpy.props.BoolProperty(name='自定义抽取材质', default=False)
    show_partition_options: bpy.props.BoolProperty(name='分区参数', default=False)
    show_mirror: bpy.props.BoolProperty(name='半脸同步', default=False)
    show_standard: bpy.props.BoolProperty(name='保存与复用标准', default=False)
    show_fit_options: bpy.props.BoolProperty(name='贴合参数', default=False)
    show_transfer_options: bpy.props.BoolProperty(name='映射参数', default=False)
    source: bpy.props.PointerProperty(name='源模型（已有表情）', type=bpy.types.Object,
                                     poll=lambda s, ob: ob.type == 'MESH')
    target: bpy.props.PointerProperty(name='需添加表情的模型', type=bpy.types.Object,
                                     poll=lambda s, ob: ob.type == 'MESH')
    working_source: bpy.props.PointerProperty(type=bpy.types.Object)
    preview: bpy.props.PointerProperty(type=bpy.types.Object)
    standard: bpy.props.PointerProperty(name='已修正分区标准', type=bpy.types.Object,
                                       poll=lambda s, ob: ob.type == 'MESH')
    use_standard: bpy.props.BoolProperty(name='按已修正标准分区', default=False)
    partition_method: bpy.props.EnumProperty(name='自动分区方式',items=[
        ('GEOMETRY','形状与拓扑','结合大小、相对位置、连通结构与材质线索；已有手工标记优先'),
        ('MATERIAL','仅按材质','只按材质名称指定分区，保留手工标记')],default='GEOMETRY')
    standard_preset_file: bpy.props.StringProperty(name='所选分区预设文件',options={'HIDDEN'})
    standard_preset: bpy.props.EnumProperty(name='跨工程预设',items=standard_preset_items,
        get=standard_preset_get,set=standard_preset_set)
    standard_preset_name: bpy.props.StringProperty(name='预设名称',default='面部分区标准')
    fitted: bpy.props.PointerProperty(type=bpy.types.Object)
    transferred: bpy.props.PointerProperty(type=bpy.types.Object)
    guide_collection: bpy.props.PointerProperty(type=bpy.types.Collection)
    guide_selected: bpy.props.PointerProperty(name='检查曲线',type=bpy.types.Object,
        poll=lambda s,ob:ob.type=='CURVE' and 'ek_guide_entry' in ob)
    curve_symmetry:bpy.props.BoolProperty(name='左右对称编辑',default=False,
        description='编辑一侧曲线时镜像至另一侧，保留原始绑定和曲线方向')
    curve_symmetry_message:bpy.props.StringProperty()
    guide_role: bpy.props.EnumProperty(name='检查曲线所属模型',items=[('TARGET','需添加表情的模型','接收表情的模型'),('SOURCE','源模型','提供表情的模型')])
    guide_kind: bpy.props.EnumProperty(name='显示部位',items=[('ALL','全部','')]+
        [(key,value,'') for key,value in G.KINDS.items()])
    lattice_resolution: bpy.props.IntProperty(name='整体晶格分辨率', default=4, min=2, max=8)
    lattice_strength: bpy.props.FloatProperty(name='边界晶格贴合强度', default=0.75, min=0, max=1)
    transfer_neighbors: bpy.props.IntProperty(name='同分区映射邻点数', default=4, min=1, max=16)
    close_neutral_mouth: bpy.props.BoolProperty(name='将结果 Basis 调整为闭嘴',default=True,
        description='按目标原有嘴唇轮廓修正结果 Basis；原始目标仅在确认覆盖后更新')
    transfer_distance: bpy.props.FloatProperty(name='顶点映射距离上限', default=0.08,
        min=0.001, max=0.5, description='占已标记目标面部直径的比例')
    materials: bpy.props.CollectionProperty(type=EKREG_Material)
    materials_source: bpy.props.StringProperty()
    tolerance: bpy.props.FloatProperty(name='形态差异容许范围', default=0.12,
                                      min=0.01, max=0.5, precision=3,
                                      description='距离阈值占源面部包围球直径的比例')
    normal_min: bpy.props.FloatProperty(name='法线相似下限', default=0.15, min=-1, max=1)
    reverse_target: bpy.props.BoolProperty(name='目标法线反向', default=False)
    manual_label: bpy.props.IntProperty(name='手动分区编号', default=-1, min=-1,
                                      options={'HIDDEN'},update=focus_changed)
    manual_number: bpy.props.IntProperty(name='手动分区编号',default=-1,min=-1,max=6,
        description='0 面部，1 眉睫，2 瞳孔与高光，3 眼白，4 口腔，5 牙齿，6 舌头，-1 不参与表情',
        **region_core.region_number_accessors('manual_label'))
    focus_region:bpy.props.BoolProperty(name='优先显示目前分区',default=False,update=focus_changed,
        description='当前编号的分区以 95% 不透明度透过显示；其他分区以 15% 不透明度显示并保留深度遮挡，仅影响工作副本视口')
    focus_object:bpy.props.PointerProperty(type=bpy.types.Object)
    oral_group: bpy.props.EnumProperty(name='口腔部件位置',items=[('AUTO','自动判断',''),('UPPER','上部','程序化生成时作为上口腔或上牙'),('LOWER','下部','程序化生成时作为下口腔或下牙')])
    message: bpy.props.StringProperty(default='选择需添加表情的模型，检查分区和曲线，再生成程序化表情')
    session_running: bpy.props.BoolProperty(default=False)
    session_objects: bpy.props.CollectionProperty(type=EKREG_ObjectState)
    session_collections: bpy.props.CollectionProperty(type=EKREG_CollectionState)
    session_active: bpy.props.PointerProperty(type=bpy.types.Object)
    session_layer: bpy.props.StringProperty()
    session_shading: bpy.props.StringProperty()
    confirmed_result: bpy.props.PointerProperty(type=bpy.types.Object)
    mirror_direction: bpy.props.EnumProperty(name='同步方向', items=[
        ('POSITIVE', '本地 X 正侧 → 负侧', '修正正侧后同步到负侧'),
        ('NEGATIVE', '本地 X 负侧 → 正侧', '修正负侧后同步到正侧')])
    mirror_plane: bpy.props.FloatProperty(name='中线 X（本地坐标）', default=0.0, precision=4)
    mirror_tolerance: bpy.props.FloatProperty(name='镜像匹配容差', default=0.03,
        min=0.001, max=0.2, description='最大匹配距离占目标本地 X 宽度的比例')
    mirror_preserve: bpy.props.BoolProperty(name='保留另一侧手动修正', default=True)


def resolve_curve_target(settings):
    target=A.target_partition(settings.target,settings.preview,settings.id_data)
    if settings.preview!=target:
        settings.preview=target
        settings.guide_collection=G.find(target,target)
        settings.guide_selected=None
    return target


def current_guides(settings):
    from . import procedural_rig as R
    resolve_curve_target(settings)
    settings.guide_role='TARGET'
    options=bpy.context.scene.exprkit_procedural
    settings.guide_collection,snapshot=R.checkpoint(settings.preview,settings.guide_collection,options.process_lashes,
                                                  recover_lashes=True)
    return snapshot


class EKREG_OT_partition(bpy.types.Operator):
    bl_idname = 'exprkit_regions.partition'
    bl_label = '生成目标面部分区预览'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        s = context.scene.exprkit_regions
        try:
            if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            source = s.standard if s.use_standard else None
            A.check_mesh(s.target)
            if s.use_standard and source is None:
                raise ValueError('请先加载用户分区预设，或选择场景中的已修正分区标准')
            if source is None:
                from . import procedural_generate as P
                S.begin(context)
                try:s.preview=A.target_partition(s.target,s.preview,context.scene)
                except ValueError:
                    s.preview=P.prepare(s.target,allow_unmarked=True,partition_method=s.partition_method)
                    s.preview.name=s.target.name+'_EK_regions'
                    s.preview['ek_target_object']=s.target.name;s.preview['ek_target_reference']=s.target
                A.merge_eye_regions(s.preview)
                S.focus(context,s.preview)
                for screen in bpy.data.screens:
                    for area in screen.areas:
                        if area.type=='VIEW_3D':area.spaces.active.shading.color_type='MATERIAL'
                s.message='目标分区已就绪；检查分区与曲线后生成程序化表情'
                report=json.loads(s.preview.get('ek_partition_detection','{}'))
                backings=report.get('face_backings',{}).get('regions',[])
                if backings:
                    eye_faces=sum(row['faces'] for row in backings if row['label']==7)
                    mouth_faces=sum(row['faces'] for row in backings if row['label']==8)
                    s.message+='；Face 背面识别：眼白 %d 面，口腔 %d 面'%(eye_faces,mouth_faces)
                if report.get('warnings'):s.message+='；'+'；'.join(report['warnings'])
                return {'FINISHED'}
            A.check_mesh(source)
            if source == s.target:
                raise ValueError('源与目标必须是不同物体')
            S.begin(context)
            options = {'tolerance_fraction': s.tolerance, 'normal_min': s.normal_min,
                       'normal_sign': -1 if s.reverse_target else 1}
            if s.preview and s.preview.get('ek_target_object') == s.target.name and \
                    s.preview.get('ek_source_object') == source.name:
                result = A.refresh_preview(source, s.target, s.preview, **options)
            else:
                result = A.evaluate(source, s.target, **options)
                s.preview = A.make_preview(source, s.target, result)
            s.preview.hide_set(False)
            s.preview.hide_viewport = False
            for screen in bpy.data.screens:
                for area in screen.areas:
                    if area.type == 'VIEW_3D':
                        area.spaces.active.shading.color_type = 'MATERIAL'
            counts = result['counts']
            matched = sum(v for k, v in counts.items() if int(k) >= 0)
            s.message = '对应 %d 面；无对应 %d 面；待调整 %d 面' % (
                matched, counts.get(-1, 0), counts.get(-2, 0))
            if not result['depth_guard']:
                s.message += '；源面部无可靠朝向，需检查后侧'
            context.scene['exprkit_region_report'] = json.dumps(result, ensure_ascii=False)
            S.focus(context,s.preview)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class EKREG_OT_generate(bpy.types.Operator):
    bl_idname='exprkit_regions.generate'
    bl_label='按目标曲线生成程序化表情'
    bl_options={'REGISTER','UNDO'}
    def invoke(self,context,event):
        from . import generation_job
        return generation_job.invoke(self,context,'REGIONS')

    def modal(self,context,event):
        from . import generation_job
        return generation_job.modal(self,context,event)

    def cancel(self,context):
        from . import generation_job
        generation_job.cancel(self,context)

    def execute(self,context):
        s=context.scene.exprkit_regions
        try:
            if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            S.begin(context);resolve_curve_target(s)
            from . import procedural_generate as P
            options=context.scene.exprkit_procedural
            from .procedural_ui import generation_options
            choices=generation_options(options)
            if not choices['selection']:raise ValueError('请至少勾选一个表情')
            from .generation_progress import Progress
            with Progress(context) as progress:
                output,s.guide_collection,report=P.generate(s.target,s.preview,s.guide_collection,
                    close_mouth=s.close_neutral_mouth,progress=progress,
                    process_lashes=options.process_lashes,**choices)
            if s.transferred:A.set_hidden_if_present(s.transferred,view_layer=context.view_layer)
            s.transferred=output;s.confirmed_result=None
            options.target=s.target;options.working=s.preview;options.collection=s.guide_collection;options.output=output;options.confirmed=None
            S.focus(context,output)
            s.message='已生成 %d 个程序化表情；跳过 %d 个；耗时 %.1f 秒'%(report['keys'],len(report['skipped']),progress.elapsed)
            if report['neutral_mouth']['changed']:s.message+='；结果 Basis 已闭嘴'
            elif s.close_neutral_mouth:s.message+='；闭嘴状态：'+report['neutral_mouth']['reason']
            limited=[row['name'] for row in report['quality'] if row.get('motion_scale',1.)<.999]
            if limited:s.message+='；%d 个表情因防破面约束收敛幅度'%len(limited)
            if report['unresolved']:s.message+='；需检查局部变形或遮挡：'+'、'.join(report['unresolved'])
            if report['skipped']:s.message+='；'+'；'.join(sorted({row['reason'] for row in report['skipped']}))
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class EKREG_OT_guides(bpy.types.Operator):
    bl_idname='exprkit_regions.guides'
    bl_label='轮廓检查'
    bl_options={'REGISTER','UNDO'}
    action: bpy.props.EnumProperty(items=[('DETECT','生成检查曲线',''),('DETECT_TARGET','生成目标检查曲线',''),('CONFIRM','确认轮廓',''),
        ('SHOW','显示筛选曲线',''),('SELECT','选择曲线',''),('MEMBERS','查看单根睫毛所属面',''),
        ('MANUAL','从所选面指定一根上睫毛',''),('SMOOTH','平滑当前检查曲线','')])
    def execute(self,context):
        s=context.scene.exprkit_regions
        try:
            resolve_curve_target(s)
            source=s.preview
            s.guide_role='TARGET'
            active=context.view_layer.objects.active
            if self.action=='MANUAL':
                expected=source if s.guide_role=='SOURCE' else s.preview
                if active!=expected:raise ValueError('请在目标分区网格中选择一根睫毛的面')
                if active.mode=='EDIT':active.update_from_editmode()
                selected=[p.index for p in active.data.polygons if p.select]
            if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            alignment=source.matrix_world.copy()
            S.begin(context)
            if self.action.startswith('DETECT'):
                resolve_curve_target(s)
                alignment=G.apply_working_transforms(source,s.preview,source)
                from . import procedural_rig as R
                options=context.scene.exprkit_procedural
                s.guide_collection,report=R.detect(s.preview,options.process_lashes)
                s.guide_kind='ALL'
                s.message='校正曲线共 %d 条；新补齐 %d 条；保留删除 %d 条'%(report['curves'],report['created'],report['deleted'])
                if report['warnings']:s.message+='；'+'；'.join(report['warnings'])
            collection=s.guide_collection
            if not collection:raise ValueError('请先生成检查曲线')
            if self.action=='CONFIRM':
                owner=collection.get('ek_guide_source',source)
                snapshot=G.confirm(collection,owner,s.preview,owner.matrix_world)
                s.message='已更新第 %d 版轮廓；下一步直接生成表情' % snapshot['revision']
                S.guide_focus(context)
            elif self.action=='SMOOTH':
                ob=s.guide_selected
                if not ob or ob.name not in collection.all_objects:raise ValueError('请先选择当前检查曲线')
                G.smooth_curve(ob)
                s.message='已平滑曲线，控制点位置保留；下一次生成表情直接生效'
                S.guide_focus(context,ob)
            elif self.action=='MANUAL':
                owner=collection.get('ek_guide_source',source)
                if collection.get('ek_guide_input')!=G.fingerprint(owner,s.preview,owner.matrix_world):
                    raise ValueError('模型或分区已变化，请先重新生成检查曲线')
                s.guide_selected=G.manual_lash(collection,source,s.preview,s.guide_role,selected)
                s.message='已标记单根睫毛；已清空选面，可继续选择下一根'
                for vertex in active.data.vertices:vertex.select=False
                for edge in active.data.edges:edge.select=False
                for face in active.data.polygons:face.select=False
                context.tool_settings.mesh_select_mode=(False,False,True)
                bpy.ops.object.mode_set(mode='EDIT')
            if self.action.startswith('DETECT') or self.action=='SHOW':
                S.guide_focus(context)
            if self.action=='SELECT':
                ob=s.guide_selected
                if not ob or ob.name not in collection.all_objects:raise ValueError('请选取本次检查集合中的曲线')
                S.guide_focus(context,ob)
            if self.action=='MEMBERS':
                guide=s.guide_selected
                if not guide or guide.name not in collection.all_objects:raise ValueError('先选择本次检查中的单根上睫毛曲线')
                entry=json.loads(guide['ek_guide_entry'])
                if entry['kind']!='LASH':raise ValueError('此操作只适用于单根上睫毛')
                owner=collection.get('ek_guide_source',source)
                if collection.get('ek_guide_input')!=G.fingerprint(owner,s.preview,owner.matrix_world):
                    raise ValueError('模型或分区已变化，请先重新生成检查曲线')
                ob=source if entry['role']=='SOURCE' else s.preview
                s.guide_role=entry['role']
                S.select_mesh_preserving_guides(context,ob)
                ids=set(entry['vertices'])
                for vertex in ob.data.vertices:vertex.select=vertex.index in ids
                for edge in ob.data.edges:edge.select=all(i in ids for i in edge.vertices)
                for face in ob.data.polygons:face.select=all(i in ids for i in face.vertices)
                context.tool_settings.mesh_select_mode=(False,False,True)
                bpy.ops.object.mode_set(mode='EDIT')
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class EKREG_OT_tongue(bpy.types.Operator):
    bl_idname='exprkit_regions.tongue'
    bl_label='标记舌头分区'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        s=context.scene.exprkit_regions
        try:
            ob=A.check_mesh(s.preview)
            if not A.is_working(ob) or ob in (s.source,s.target):
                raise ValueError('请先生成独立的分区标记副本')
            active=A.check_mesh(context.view_layer.objects.active)
            if active!=ob or ob.mode!='EDIT':
                raise ValueError('请点击「进入分区副本选面」，选中舌头面后再标记')
            indices=[p.index for p in ob.data.polygons if p.select and not p.hide]
            if not indices:raise ValueError('请先在分区副本中选择舌头面')
            labels=T.mesh_regions(ob)
            indices=[i for i in indices if labels[i]!=12]
            if not indices:
                s.message='所选面已属于舌头分区'
                S.focus(context,ob)
                return {'FINISHED'}
            S.begin(context)
            _,count=T.mark_tongue(ob,face_indices=indices)
            for old in (s.fitted,s.transferred):
                if old:A.set_hidden_if_present(old,view_layer=context.view_layer)
            if s.guide_collection:s.guide_collection['ek_guide_needs_refresh']=True
            s.message='已在分区副本标记 %d 个舌头面；下一次生成表情自动读取最新分区与曲线' % count
            s.fitted=None
            s.transferred=None
            S.focus(context,ob)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}


class EKREG_OT_standard(bpy.types.Operator):
    bl_idname = 'exprkit_regions.standard'
    bl_label = '采用当前修正分区为标准'
    bl_options = {'REGISTER', 'UNDO'}
    load: bpy.props.BoolProperty(default=False,options={'SKIP_SAVE'})
    save_preset: bpy.props.BoolProperty(default=False,options={'SKIP_SAVE'})
    preset_file: bpy.props.StringProperty(options={'SKIP_SAVE'})
    from_file: bpy.props.BoolProperty(default=False,options={'SKIP_SAVE'})
    filepath: bpy.props.StringProperty(subtype='FILE_PATH',options={'SKIP_SAVE'})
    filter_glob: bpy.props.StringProperty(default='*.json',options={'HIDDEN','SKIP_SAVE'})

    def invoke(self,context,event):
        if self.load and self.from_file and not self.filepath:
            context.window_manager.fileselect_add(self)
            return {'RUNNING_MODAL'}
        return self.execute(context)

    def execute(self, context):
        s = context.scene.exprkit_regions
        try:
            S.begin(context)
            if self.load:
                selected=self.preset_file or selected_standard_preset(s)
                if self.from_file:
                    if not self.filepath:raise ValueError('请选择分区标准 JSON 文件')
                    from pathlib import Path
                    path=Path(bpy.path.abspath(self.filepath))
                else:path=A.standard_preset_path(selected)
                loaded=A.load_standard(path)
                s.standard=loaded
                if not self.from_file:s.standard_preset_file=selected
                else:
                    directory=A.standard_preset_directory()
                    s.standard_preset_file=path.name if directory and path.resolve().parent==directory.resolve() else '__none__'
                s.message='已加载分区标准「%s」（%d 面）；可按当前标准生成分区'%(path.stem,len(loaded.data.polygons))
                s.use_standard=True
            else:
                s.standard,state=A.capture_standard(s.preview,preset_name=s.standard_preset_name)
                s.standard_preset_file=state['preset_file']
                s.message='已保存预设「%s」；文件：%s' % (state['preset_file'][:-5],A.standard_preset_path(state['preset_file']))
            for area in context.screen.areas:area.tag_redraw()
            S.focus(context,s.standard,[s.target]) if self.load else S.focus(context,s.preview)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class EKREG_OT_preset_library(bpy.types.Operator):
    bl_idname='exprkit_regions.preset_library'
    bl_label='分区预设库'
    action:bpy.props.EnumProperty(items=[('REFRESH','刷新预设列表',''),('FOLDER','打开预设文件夹','')])
    def execute(self,context):
        s=context.scene.exprkit_regions
        try:
            if self.action=='FOLDER':
                directory=A.standard_preset_directory(create=True)
                bpy.ops.wm.path_open(filepath=str(directory))
            else:
                rows=A.standard_presets()
                if selected_standard_preset(s) not in {row['file'] for row in rows}:
                    s.standard_preset_file='__none__'
                s.message='预设列表已刷新：%d 个命名预设；位置：%s'%(len(rows),A.standard_preset_directory() or '配置目录不可用')
                for area in context.screen.areas:area.tag_redraw()
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class EKREG_OT_manual(bpy.types.Operator):
    bl_idname = 'exprkit_regions.manual'
    bl_label = '将所选面标记为该分区'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        s = context.scene.exprkit_regions
        try:
            if context.view_layer.objects.active != s.preview:
                raise ValueError('请选中目标预览副本并选择需要调整的面')
            S.begin(context)
            count = A.manual_assign(s.preview, s.manual_label)
            if not count:
                raise ValueError('没有选中的面')
            if count:
                value={'AUTO':0,'UPPER':1,'LOWER':-1}[s.oral_group] if s.manual_label in (8,9) else 0
                if s.preview.mode=='EDIT':
                    import bmesh
                    bm=bmesh.from_edit_mesh(s.preview.data)
                    layer=bm.faces.layers.int.get('ek_procedural_oral_group') or bm.faces.layers.int.new('ek_procedural_oral_group')
                    for face in bm.faces:
                        if face.select:face[layer]=value
                    bmesh.update_edit_mesh(s.preview.data)
                else:
                    attribute=s.preview.data.attributes.get('ek_procedural_oral_group') or s.preview.data.attributes.new('ek_procedural_oral_group','INT','FACE')
                    for face in s.preview.data.polygons:
                        if face.select:attribute.data[face.index].value=value
            s.message = '已手动标记 %d 面，重新分区时保留' % count
            if s.guide_collection:s.guide_collection['ek_guide_needs_refresh']=True
            S.focus(context,s.preview)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class EKREG_OT_colors(bpy.types.Operator):
    bl_idname='exprkit_regions.colors'
    bl_label='更新分区配色'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        try:
            s=context.scene.exprkit_regions
            S.begin(context)
            before=T.mesh_regions(s.preview)
            count=A.recolor_preview(s.preview)
            s.message='已更新目标分区配色；原模型材质不变'
            if before!=T.mesh_regions(s.preview) and s.guide_collection:
                s.guide_collection['ek_guide_needs_refresh']=True
                s.message+='；下一次生成表情自动更新轮廓'
            S.focus(context,s.preview)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc))
            return {'CANCELLED'}


class EKREG_OT_mirror(bpy.types.Operator):
    bl_idname = 'exprkit_regions.mirror'
    bl_label = '同步半脸分区'
    bl_options = {'REGISTER', 'UNDO'}
    def execute(self, context):
        s = context.scene.exprkit_regions
        try:
            S.begin(context)
            result = A.mirror_regions(s.preview, s.mirror_direction, s.mirror_plane,
                                      s.mirror_tolerance, s.mirror_preserve)
            if result['changed'] and s.guide_collection:s.guide_collection['ek_guide_needs_refresh']=True
            s.message = '已同步 %d 面；保留手动修正 %d 面；未匹配 %d 面' % (
                result['changed'], result['protected'], result['unmatched'])
            self.report({'INFO'}, s.message)
            S.focus(context,s.preview)
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}


class EKREG_OT_preview(bpy.types.Operator):
    bl_idname = 'exprkit_regions.preview'
    bl_label = '显示工作副本'
    bl_options = {'REGISTER', 'UNDO'}
    restore: bpy.props.BoolProperty(default=False)
    def execute(self, context):
        s = context.scene.exprkit_regions
        if self.restore:
            S.restore(context)
            return {'FINISHED'}
        reference = s.standard if s.use_standard else None
        if not s.preview:
            self.report({'ERROR'}, '请先生成工作副本与分区预览')
            return {'CANCELLED'}
        S.focus(context,s.preview,[reference])
        return {'FINISHED'}


class EKREG_OT_finish(bpy.types.Operator):
    bl_idname='exprkit_regions.finish'
    bl_label='确认完成并恢复显示'
    bl_options={'REGISTER','UNDO'}
    def execute(self,context):
        s=context.scene.exprkit_regions
        try:
            output=s.transferred
            if not output:raise ValueError('请先完成表情生成并检查结果')
            if output.get('ek_confirmed_target')==s.target:
                raise ValueError('该结果已经确认，无需重复覆盖')
            from .procedural_generate import VERSION
            if output.get('ek_procedural_version')!=VERSION:
                raise ValueError('结果格式不属于当前版本，请重新生成表情')
            if output.get('ek_transfer_target')!=s.target:
                raise ValueError('结果不属于当前目标，请重新生成表情')
            if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
            guides=current_guides(s)
            if output.get('ek_procedural_hash')!=guides['hash'] or output.get('ek_procedural_input')!=guides['input']:
                raise ValueError('曲线或分区已改变，请重新生成并检查结果后确认')
            from .procedural_ui import options_match
            if not options_match(context.scene.exprkit_procedural,output,s.close_neutral_mouth):
                raise ValueError('生成设置已改变，请重新生成并检查结果后确认')
            count,backup,children=K.apply(s.target,output)
            s.message='已将 %d 个表情写入「%s」，保留原材质；覆盖前备份：%s' % (count,output['ek_confirmed_target'].name,backup.name)
            S.restore(context,final=output.get('ek_confirmed_target'))
            for child in children:
                child.hide_viewport=s.target.hide_viewport
                for layer in context.scene.view_layers:
                    if layer.objects.get(child.name)==child and layer.objects.get(s.target.name)==s.target:
                        child.hide_set(s.target.hide_get(view_layer=layer),view_layer=layer)
            s.confirmed_result=output
            return {'FINISHED'}
        except Exception as exc:
            self.report({'ERROR'},str(exc));return {'CANCELLED'}


class EKREG_OT_select(bpy.types.Operator):
    bl_idname = 'exprkit_regions.select'
    bl_label = '选择工作副本'
    role: bpy.props.EnumProperty(items=[('TARGET', '目标预览', ''),
        ('STANDARD', '已修正分区标准', ''), ('OUTPUT', '程序化结果', '')])
    edit_faces: bpy.props.BoolProperty(default=False,options={'SKIP_SAVE'},
        description='进入分区副本的编辑模式，并启用面选择')
    def execute(self, context):
        s = context.scene.exprkit_regions
        ob = {'SOURCE': s.working_source, 'FULL_SOURCE': s.source, 'TARGET': s.preview, 'STANDARD': s.standard,
              'FITTED': s.fitted, 'OUTPUT': s.transferred}[self.role]
        if not ob:
            return {'CANCELLED'}
        if self.edit_faces and (self.role!='TARGET' or ob in (s.source,s.target) or not A.is_working(ob)):
            self.report({'ERROR'},'只能在独立的分区副本中选面')
            return {'CANCELLED'}
        keep_selection=context.view_layer.objects.active==ob and ob.mode=='EDIT'
        if context.mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        try:
            references=[s.target] if self.role in ('SOURCE','STANDARD') else []
            S.focus(context,ob,references)
        except ValueError as exc:
            self.report({'ERROR'}, str(exc))
            return {'CANCELLED'}
        if self.edit_faces:
            if not keep_selection:
                for vertex in ob.data.vertices:vertex.select=False
                for edge in ob.data.edges:edge.select=False
                for face in ob.data.polygons:face.select=False
            context.tool_settings.mesh_select_mode=(False,False,True)
            bpy.ops.object.mode_set(mode='EDIT')
        return {'FINISHED'}


def disclosure(layout, settings, prop, title):
    box = layout.box()
    box.prop(settings, prop, text=title,
             icon='TRIA_DOWN' if getattr(settings, prop) else 'TRIA_RIGHT', emboss=False)
    return box.column(align=True) if getattr(settings, prop) else None


def select_copy(layout, role, text, obj):
    row = layout.row()
    row.enabled = bool(obj)
    row.operator('exprkit_regions.select', text=text).role = role


def next_step(context):
    """Read the current partition/curve rules; no preview or confirmation gate."""
    s=context.scene.exprkit_regions;options=context.scene.exprkit_procedural
    if not s.target:return '选择需添加表情的模型'
    if not s.preview or s.preview.get('ek_target_reference')!=s.target:return '创建目标分区'
    collection=s.guide_collection
    if not collection:return '检查当前分区，生成校正曲线'
    if s.preview.mode=='EDIT':return '完成分区编辑并生成表情'
    if any(o.mode=='EDIT' for o in collection.all_objects if o.type=='CURVE'):
        return '完成曲线编辑并生成表情'
    if collection.get('ek_guide_needs_refresh') or collection.get('ek_guide_partition_state')!=G.digest(T.mesh_regions(s.preview)):
        return '按当前规则重新生成表情'
    output=s.transferred
    if not output:return '按当前规则生成表情'
    from .procedural_generate import VERSION
    if output.get('ek_procedural_version')!=VERSION or output.get('ek_commit_target')!=s.target:
        return '按当前规则重新生成表情'
    try:changed=output.get('ek_procedural_hash')!=G.state_hash(collection,G.current(collection,s.preview))
    except (ValueError,KeyError,TypeError):return '修正无效的曲线控制点'
    changed|=options.process_lashes!=bool(collection.get('ek_process_individual_lashes',True))
    from .procedural_ui import options_match
    changed|=not options_match(options,output,s.close_neutral_mouth)
    if changed:return '按当前规则重新生成表情'
    if s.confirmed_result==output:return '已完成，可继续编辑'
    return '检查结果形态键，确认后应用'


class EKREG_PT_panel(bpy.types.Panel):
    bl_idname = 'EKREG_PT_panel'
    bl_label = '程序化表情制作'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ExpressionGen'
    bl_order = 0
    def draw(self, context):
        layout=self.layout
        if GP.active(context):
            layout.label(text='正在生成：'+GP.stage_text(context),icon='TIME');return
        layout.label(text='下一步：'+next_step(context), icon='INFO')


class EKREG_PT_details(bpy.types.Panel):
    bl_idname='EKREG_PT_details';bl_label='详细信息';bl_parent_id='EKREG_PT_panel'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='ExpressionGen'
    bl_order=90;bl_options={'DEFAULT_CLOSED'}
    def draw(self,context):
        import textwrap
        layout=GP.controls(self.layout,context)
        if context.scene.get(GP.REPORT_KEY):
            layout.operator('exprkit_procedural.export_timing',icon='EXPORT')
        for line in textwrap.wrap(context.scene.exprkit_regions.message,width=23):layout.label(text=line)


class EKREG_PT_models(bpy.types.Panel):
    bl_idname='EKREG_PT_models'
    bl_label='1 · 选择需添加表情的模型'
    bl_parent_id='EKREG_PT_panel'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='ExpressionGen';bl_order=0
    def draw(self,context):
        GP.controls(self.layout,context).prop(context.scene.exprkit_regions,'target')


class EKREG_PT_partition(bpy.types.Panel):
    bl_idname = 'EKREG_PT_partition'
    bl_label = '2 · 生成目标分区'
    bl_parent_id = 'EKREG_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ExpressionGen'
    bl_order = 2
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        s, layout = context.scene.exprkit_regions, GP.controls(self.layout,context)
        layout.prop(s, 'use_standard')
        if not s.use_standard:layout.prop(s,'partition_method')
        if s.use_standard:
            box = layout.box()
            box.prop(s, 'standard')
            box.prop(s,'standard_preset')
            box.operator('exprkit_regions.standard', text='加载已修正分区标准预设').load = True
            if s.standard:
                select_copy(box, 'STANDARD', '选择已修正分区标准', s.standard)
                box.label(text='按结构与比例对应，无需位置贴合')
        row = layout.row()
        row.enabled = bool(s.target and (not s.use_standard or s.standard))
        row.operator('exprkit_regions.partition', text='生成 / 更新目标分区')
        if s.preview:
            layout.operator('exprkit_regions.preview', text='显示分区与已修正分区标准' if s.use_standard else '显示目标分区副本')


class EKREG_PT_correct(bpy.types.Panel):
    bl_idname = 'EKREG_PT_correct'
    bl_label = '3 · 检查与修正分区'
    bl_parent_id = 'EKREG_PT_panel'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'ExpressionGen'
    bl_order = 3
    bl_options = {'DEFAULT_CLOSED'}
    def draw(self, context):
        s, layout = context.scene.exprkit_regions, GP.controls(self.layout,context)
        if not s.preview:
            layout.label(text='先在第 2 步生成目标分区', icon='INFO')
            return
        select_copy(layout, 'TARGET', '选择目标分区副本', s.preview)
        layout.operator('exprkit_regions.colors')
        layout.label(text='彩色：已对应；灰色：无对应')
        layout.label(text='编辑模式选面后，可修改分区')
        layout.prop(s, 'manual_number')
        layout.prop(s,'focus_region')
        if s.manual_label in (8,9):layout.prop(s,'oral_group')
        layout.label(text='0 面部 · 1 眉睫 · 2 瞳孔与高光')
        layout.label(text='3 眼白 · 4 口腔 · 5 牙齿 · 6 舌头')
        layout.label(text='-1 不参与表情')
        layout.operator('exprkit_regions.manual', text='将所选面标记到此分区')
        mirror = disclosure(layout, s, 'show_mirror', '半脸同步')
        if mirror is not None:
            mirror.prop(s, 'mirror_direction')
            mirror.prop(s, 'mirror_preserve')
            mirror.prop(s, 'mirror_plane')
            mirror.prop(s, 'mirror_tolerance')
            mirror.operator('exprkit_regions.mirror')



class EKREG_PT_presets(bpy.types.Panel):
    bl_idname='EKREG_PT_presets';bl_label='分区预设库（跨工程）'
    bl_parent_id='EKREG_PT_panel'
    bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='ExpressionGen';bl_order=1
    def draw(self,context):
        s=context.scene.exprkit_regions;layout=GP.controls(self.layout,context)
        rows=A.standard_presets()
        layout.label(text='已保存 %d 个命名预设'%len(rows),icon='PRESET')
        if not rows:layout.label(text='尚未保存预设，可从 JSON 文件加载',icon='INFO')
        for preset in rows[:8]:
            op=layout.operator('exprkit_regions.standard',text=preset['name'],icon='CHECKMARK' if s.standard_preset==preset['file'] else 'IMPORT')
            op.load=True;op.preset_file=preset['file']
        if len(rows)>8:layout.label(text='其余 %d 个可从下方完整列表选择'%(len(rows)-8))
        layout.prop(s,'standard_preset',text='完整列表')
        row=layout.row(align=True)
        load=row.row(align=True);load.enabled=selected_standard_preset(s) in {preset['file'] for preset in rows}
        load.operator('exprkit_regions.standard',text='加载所选预设').load=True
        row.operator('exprkit_regions.preset_library',text='',icon='FILE_REFRESH').action='REFRESH'
        op=layout.operator('exprkit_regions.standard',text='从 JSON 加载',icon='IMPORT');op.load=True;op.from_file=True
        layout.operator('exprkit_regions.preset_library',text='打开保存文件夹',icon='FILE_FOLDER').action='FOLDER'
        directory=A.standard_preset_directory()
        import textwrap
        for line in textwrap.wrap(str(directory or '配置目录不可用'),width=40):layout.label(text=line)
        layout.separator();layout.prop(s,'standard_preset_name')
        row=layout.row();row.enabled=bool(s.preview and s.standard_preset_name.strip())
        row.operator('exprkit_regions.standard',text='保存当前修正分区为预设',icon='FILE_TICK').save_preset=True
        layout.label(text='加载后按拓扑、比例与部件关系分区')


class EKREG_PT_guides(bpy.types.Panel):
    bl_idname='EKREG_PT_guides'
    bl_label='4 · 轮廓校正'
    bl_parent_id='EKREG_PT_panel'
    bl_space_type='VIEW_3D'
    bl_region_type='UI'
    bl_category='ExpressionGen'
    bl_order=4
    def draw(self,context):
        s,layout=context.scene.exprkit_regions,GP.controls(self.layout,context)
        reason=''
        try:partition=A.target_partition(s.target,s.preview,context.scene)
        except ValueError as exc:partition=None;reason=str(exc)
        if partition:layout.label(text='目标分区：'+partition.name,icon='MESH_DATA')
        from .procedural_ui import lash_options,curve_feedback
        lash_options(layout,context.scene.exprkit_procedural,s.guide_collection,context)
        row=layout.row();row.enabled=bool(partition)
        row.operator('exprkit_regions.guides',text='生成 / 补齐校正曲线').action='DETECT_TARGET'
        if reason:
            import textwrap
            for line in textwrap.wrap(reason,width=23):layout.label(text=line,icon='INFO')
            return
        if not s.guide_collection:
            layout.label(text='完成分区后，检查眼睑、嘴唇与单根睫毛')
            return
        if GP.stable_value(context,'guides.refresh',bool(s.guide_collection.get('ek_guide_needs_refresh'))):
            layout.label(text='分区已改变，下一次生成自动更新',icon='INFO')
        layout.prop(s,'guide_kind')
        layout.operator('exprkit_regions.guides',text='显示所选部位').action='SHOW'
        layout.prop(s,'guide_selected')
        layout.prop(s,'curve_symmetry')
        layout.operator('exprkit_rules.edit',text='镜像当前侧至另一侧').action='MIRROR'
        if s.curve_symmetry:layout.prop(s,'mirror_plane')
        message=GP.stable_value(context,'guides.symmetry_message',s.curve_symmetry_message)
        if message:layout.label(text=message,icon='INFO')
        layout.operator('exprkit_regions.guides',text='选择曲线，Tab 编辑').action='SELECT'
        if GP.stable_value(context,'guides.selected',bool(s.guide_selected)):
            layout.operator('exprkit_regions.guides',text='平滑当前曲线（保留控制点）').action='SMOOTH'
            layout.operator('exprkit_regions.guides',text='查看这根睫毛所属面').action='MEMBERS'
        layout.label(text='单根睫毛：起点为根部，终点为尖端')
        layout.label(text='漏检时，在对应网格中选一根睫毛的面')
        layout.operator('exprkit_regions.guides',text='从所选面指定一根上睫毛').action='MANUAL'
        from .curve_sculpt import draw
        draw(layout,context)
        curve_feedback(layout,s.guide_collection,partition,context)


class EKREG_PT_generate(bpy.types.Panel):
    bl_idname='EKREG_PT_generate';bl_label='5 · 生成表情与确认'
    bl_parent_id='EKREG_PT_panel';bl_space_type='VIEW_3D';bl_region_type='UI';bl_category='ExpressionGen';bl_order=5
    def draw(self,context):
        s,layout=context.scene.exprkit_regions,GP.controls(self.layout,context)
        options=context.scene.exprkit_procedural
        settings=disclosure(layout,options,'show_options','表情选择')
        if settings is not None:
            from .procedural_ui import expression_options
            expression_options(settings,options)
        layout.prop(options,'force_symmetry')
        from .procedural_ui import style_options
        style_options(layout,options)
        layout.prop(s,'close_neutral_mouth')
        # Use identical containers before, during and after generation. Adding
        # a busy-only box starts a panel alignment animation that cannot finish
        # inside the synchronous calculation loop.
        row=self.layout.row()
        if not GP.draw(row,context):
            row.enabled=bool(s.preview)
            row.operator('exprkit_regions.generate',text='按目标曲线生成表情')
        layout=GP.controls(self.layout,context)
        output=s.transferred if s.transferred and s.transferred.get('ek_procedural_version') else None
        select_copy(layout,'OUTPUT','选择结果并检查形态键',output)
        applied=bool(output and s.target and output.get('ek_confirmed_target')==s.target)
        if applied:layout.label(text='表情已写入需添加表情的模型',icon='CHECKMARK')
        if s.target:layout.label(text='写入目标：'+s.target.name)
        matches=bool(output and output.get('ek_commit_target')==s.target)
        if output and not matches:layout.label(text='目标已改变，请重新生成表情',icon='ERROR')
        layout.label(text='确认后写回表情，并保留覆盖前备份')
        row=layout.row();row.enabled=matches and not applied
        row.operator('exprkit_regions.finish',text='写入目标并恢复显示')
        layout.operator('exprkit_regions.preview',text='暂时恢复原场景显示').restore=True


CLASSES = (EKREG_Material, EKREG_ObjectState, EKREG_CollectionState, EKREG_Settings,
           EKREG_OT_partition, EKREG_OT_guides, EKREG_OT_generate, EKREG_OT_tongue, EKREG_OT_standard, EKREG_OT_preset_library,
           EKREG_OT_manual, EKREG_OT_colors, EKREG_OT_mirror, EKREG_OT_preview, EKREG_OT_finish,
           EKREG_OT_select, EKREG_PT_panel, EKREG_PT_models,
           EKREG_PT_presets, EKREG_PT_partition, EKREG_PT_correct, EKREG_PT_guides, EKREG_PT_generate,EKREG_PT_details)


def register():
    # Allow this module's registrations to be refreshed during development.
    if hasattr(bpy.types.Scene, 'exprkit_regions'):
        del bpy.types.Scene.exprkit_regions
    for cls in reversed(CLASSES):
        old = getattr(bpy.types, cls.__name__, None)
        if old:
            bpy.utils.unregister_class(old)
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.exprkit_regions = bpy.props.PointerProperty(type=EKREG_Settings)


def unregister():
    if hasattr(bpy.types.Scene, 'exprkit_regions'):
        del bpy.types.Scene.exprkit_regions
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)


if __name__ == '__main__':
    register()
