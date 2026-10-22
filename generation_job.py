"""Run expensive generation outside the UI process; import verified results."""
import json
import atexit
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import bpy

_active=None


def shutdown():
    if _active is not None:_active.close()


def signature(target,partition,guides,options):
    from . import region_guides as G,procedural_commit as C,procedural_generate as P
    return dict(target=C.basis_signature(target),partition=G.fingerprint(partition,partition,None),
                guides=G.state_hash(guides,G.current(guides,partition)) if guides else None,
                options=options,rules=P.profile_state())


class Job:
    def __init__(self,context,flow):
        from . import region_ui,region_session as S,procedural_ui as U,procedural_commit as C,procedural_rig as R
        if _active is not None:raise ValueError('已有表情正在生成，请等待完成或按 Esc 取消')
        self.context=context;self.flow=flow;self.process=None;self.log=None;self.folder=None
        self.timer=None;self.progress=None;self.closed=False;self.started=time.monotonic()
        settings=context.scene.exprkit_procedural;shared=context.scene.exprkit_regions
        if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
        if flow=='REGIONS':
            S.begin(context);region_ui.resolve_curve_target(shared)
            self.target,self.partition,self.guides=shared.target,shared.preview,shared.guide_collection
            close_mouth=shared.close_neutral_mouth
        else:
            S.begin(context)
            self.target,self.partition,self.guides=settings.target,settings.working,settings.collection
            close_mouth=True
        self.options=dict(U.generation_options(settings),close_mouth=close_mouth,process_lashes=settings.process_lashes)
        if not self.options['selection']:raise ValueError('请至少勾选一个表情')
        C.generation_reference(self.target,self.partition)
        # Existing previews are already normalized. Only transform baking must
        # occur before export; ordinary curve reconciliation stays in worker.
        from mathutils import Matrix
        from . import region_blender as A
        A.merge_eye_regions(self.partition)
        if self.partition.matrix_world!=Matrix.Identity(4):
            self.guides,_=R.checkpoint(self.partition,self.guides,settings.process_lashes)
            if flow=='REGIONS':shared.guide_collection=self.guides
            else:settings.collection=self.guides
        self.original_signature=signature(self.target,self.partition,self.guides,self.options)

    def start(self):
        global _active
        from .generation_progress import Progress
        from . import procedural_generate as P
        from . import region_guides as G
        self.folder=Path(tempfile.mkdtemp(prefix='expressiongen-generation-')).resolve()
        self.progress=Progress(self.context);self.progress.cooperative=True
        self.progress.__enter__();_active=self
        try:
            request=dict(target=self.target.name,partition=self.partition.name,
                guides=self.guides.name if self.guides else '',options=self.options,
                rules=dict(zip(('ek_expression_library','ek_expression_values'),P.profile_state())),
                frame=self.context.scene.frame_current,subframe=self.context.scene.frame_subframe,
                target_matrix=[list(row) for row in self.target.matrix_world],
                partition_matrix=[list(row) for row in self.partition.matrix_world],
                rebase_proof=dict(target=self.original_signature['target'],
                    partition=G.fingerprint(self.partition,self.partition,None,include_regions=False)))
            (self.folder/'request.json').write_text(json.dumps(request,ensure_ascii=False),encoding='utf8')
            blocks={self.target,self.partition}
            if self.guides:blocks.add(self.guides)
            bpy.data.libraries.write(str(self.folder/'input.blend'),blocks,compress=True)
            self.log=(self.folder/'worker.log').open('wb')
            flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
            self.process=subprocess.Popen([bpy.app.binary_path,'--background','--factory-startup',
                '--disable-autoexec','--python-exit-code','1','--python',
                str(Path(__file__).with_name('generation_worker.py')),'--',str(self.folder)],
                stdout=self.log,stderr=subprocess.STDOUT,creationflags=flags)
            self.progress('后台生成表情')
        except BaseException:
            self.close()
            raise
        return self

    def poll(self):
        if self.closed:raise ValueError('生成任务已结束')
        status={}
        try:status=json.loads((self.folder/'status.json').read_text(encoding='utf8'))
        except (OSError,ValueError):pass
        if status.get('state')=='running':
            self.progress.batch=status.get('batch','生成表情')
            self.progress.index=status.get('index',0);self.progress.total=status.get('total',0)
            self.progress.name=status.get('name','')
            self.progress(status.get('stage'),None,None)
        code=self.process.poll()
        if code is None:return None
        # The worker can finish between the first read and poll().
        final=self.folder/('completion.json' if code==0 else 'failure.json')
        try:status=json.loads(final.read_text(encoding='utf8'))
        except (OSError,ValueError):pass
        if status.get('state')!='completed' or code:
            if status.get('timing'):
                from .generation_progress import REPORT_KEY
                self.context.scene[REPORT_KEY]=json.dumps(status['timing'],ensure_ascii=False)
            raise ValueError(status.get('error') or '后台生成进程已退出；原预览保留')
        return json.loads((self.folder/'result.json').read_text(encoding='utf8'))

    def collect(self,result):
        from . import region_guides as G,region_blender as A,region_session as S,procedural_ui as U
        shared=self.context.scene.exprkit_regions;settings=self.context.scene.exprkit_procedural
        target,partition,guides=self.target,self.partition,self.guides
        current_options=dict(U.generation_options(settings),
            close_mouth=shared.close_neutral_mouth if self.flow=='REGIONS' else True,
            process_lashes=settings.process_lashes)
        selected=(shared.target,shared.preview,shared.guide_collection) if self.flow=='REGIONS' else (
            settings.target,settings.working,settings.collection)
        if selected!=(target,partition,guides) or signature(target,partition,guides,current_options)!=self.original_signature:
            raise ValueError('生成期间模型、分区、曲线或设置已改变，请重新生成；原预览保留')
        with bpy.data.libraries.load(str(self.folder/'result.blend'),link=False) as (available,loaded):
            loaded.objects=[result['output']]
            loaded.collections=[result['guides']]
        output=loaded.objects[0];new_guides=loaded.collections[0]
        try:
            owners={ob.name:ob for ob in [output,*output.children_recursive,*new_guides.all_objects]}
            # Library append may suffix names; map original names using the
            # stable guide keys and the explicitly requested root identities.
            original_objects={result['output']:output}
            for ob in new_guides.all_objects:
                original_objects.setdefault(ob.name,ob)
            collections={c.name:c for c in [new_guides,*new_guides.children_recursive]}
            collections[result['guides']]=new_guides
            for reference in result['references']:
                if reference['collection']:
                    owner=collections.get(reference['owner'])
                    if owner is None:
                        owner=next((c for c in new_guides.children_recursive
                                    if c.name.startswith(reference['owner']+'.')),None)
                else:
                    owner=original_objects.get(reference['owner'])
                    if owner is None:
                        owner=next((ob for ob in owners.values()
                                    if ob.name.startswith(reference['owner']+'.')),None)
                if owner is None:raise ValueError('后台结果缺少部件，请重新生成')
                value=target if reference['role']=='target' else partition if reference['role']=='partition' else bpy.data.objects.get(reference['name'])
                if value is not None:owner[reference['key']]=value
            output['ek_transfer_target']=target;output['ek_commit_target']=target
            output['ek_target_reference']=target;output['ek_procedural_partition']=partition
            new_guides['ek_guide_source']=partition;new_guides['ek_guide_target']=partition
            new_guides['ek_guide_generation']=max((c.get('ek_guide_generation',0) for c in bpy.data.collections
                if c!=new_guides and c.get('ek_guide_target')==partition),default=0)+1
            # Rebuilt curves may have a changed display transform. Evaluate
            # appended objects in the scene before reading their world points.
            self.context.scene.collection.children.link(new_guides)
            self.context.view_layer.update()
            if G.state_hash(new_guides,G.current(new_guides,partition))!=output['ek_procedural_hash']:
                raise ValueError('后台结果与校正曲线不一致，请重新生成')
            collection=A.new_collection('EK_程序化表情')
            collection.objects.link(output)
            for child in output.children_recursive:
                if self.context.scene.objects.get(child.name) is None:collection.objects.link(child)
        except BaseException:
            for ob in {output,*output.children_recursive,*new_guides.all_objects}:
                bpy.data.objects.remove(ob,do_unlink=True)
            for c in reversed([new_guides,*new_guides.children_recursive]):
                if c.name in bpy.data.collections:bpy.data.collections.remove(c)
            raise
        old=shared.transferred if self.flow=='REGIONS' else settings.output
        if old:A.set_hidden_if_present(old,view_layer=self.context.view_layer)
        if guides:G.collection_visibility(guides,False)
        shared.target=target;shared.preview=partition;shared.guide_collection=new_guides
        shared.transferred=output;shared.confirmed_result=None
        settings.target=target;settings.working=partition;settings.collection=new_guides
        settings.output=output;settings.confirmed=None
        report=result['report']
        message='已生成 %d 个表情；跳过 %d 个；耗时 %.1f 秒'%(report['keys'],len(report['skipped']),time.monotonic()-self.started)
        if report['unresolved']:message+='；需检查局部变形或遮挡：'+'、'.join(report['unresolved'])
        shared.message=message;settings.message=message
        self.close()
        if result.get('timing'):
            from .generation_progress import REPORT_KEY
            payload=json.dumps(result['timing'],ensure_ascii=False)
            self.context.scene[REPORT_KEY]=payload;output[REPORT_KEY]=payload
        S.focus(self.context,output)
        return output

    def close(self):
        global _active
        if self.closed:return
        self.closed=True
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=2)
        if self.log:self.log.close()
        if self.timer:
            self.context.window_manager.event_timer_remove(self.timer);self.timer=None
        if self.progress:self.progress.close()
        if self.folder:
            temporary=Path(tempfile.gettempdir()).resolve()
            if self.folder.parent==temporary and self.folder.name.startswith('expressiongen-generation-'):
                shutil.rmtree(self.folder,ignore_errors=True)
        if _active is self:_active=None


def invoke(operator,context,flow):
    try:
        operator._generation_job=Job(context,flow).start()
        operator._generation_job.timer=context.window_manager.event_timer_add(.25,window=context.window)
        context.window_manager.modal_handler_add(operator)
        return {'RUNNING_MODAL'}
    except Exception as exc:
        operator.report({'ERROR'},str(exc));return {'CANCELLED'}


def modal(operator,context,event):
    job=getattr(operator,'_generation_job',None)
    if job is None or job.closed:return {'CANCELLED'}
    if event.type=='ESC':
        job.close();context.scene.exprkit_regions.message='已取消生成；原预览保留'
        return {'CANCELLED'}
    if event.type!='TIMER':return {'PASS_THROUGH'}
    try:
        result=job.poll()
        if result is None:return {'RUNNING_MODAL'}
        job.collect(result)
        return {'FINISHED'}
    except Exception as exc:
        job.close();operator.report({'ERROR'},str(exc));return {'CANCELLED'}


def cancel(operator,context):
    job=getattr(operator,'_generation_job',None)
    if job is not None:job.close()


@bpy.app.handlers.persistent
def before_load(_):
    shutdown()


before_load._expressiongen_generation_job=True


def install():
    remove()
    bpy.app.handlers.load_pre.append(before_load)


def remove():
    shutdown()
    for handler in list(bpy.app.handlers.load_pre):
        if getattr(handler,'_expressiongen_generation_job',False):
            bpy.app.handlers.load_pre.remove(handler)


atexit.register(shutdown)
