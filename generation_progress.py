"""Visible generation stages with throttled repaint on Blender's main thread."""
import time
import json
import platform
import traceback as traceback_module
from datetime import datetime, timezone
import bpy

_active=None
_ui_cache={}
REPORT_KEY='ek_generation_timing'


def active(context):
    return _active is not None and context.scene==_active.scene


def stage_text(context):
    if not active(context):return ''
    return _active.stage+(' '+_active.detail if _active.detail else '')


def controls(layout,context):
    """Keep panel contents in place while temporarily disabling edits."""
    column=layout.column();column.enabled=not active(context)
    return column


def cached_labels(layout,context,key,read):
    """Reuse the last idle feedback without resampling curves during repaint."""
    cache_key=(context.scene.as_pointer(),key)
    if not active(context):_ui_cache[cache_key]=tuple(read())
    for text,icon in _ui_cache.get(cache_key,()):layout.label(text=text,icon=icon)


def stable_value(context,key,value):
    """Hold layout conditions while generation refreshes its input curves."""
    cache_key=(context.scene.as_pointer(),key)
    if not active(context) or cache_key not in _ui_cache:_ui_cache[cache_key]=value
    return _ui_cache[cache_key]


def _redraw(wm):
    try:
        for window in wm.windows:
            if window.screen:
                for area in window.screen.areas:area.tag_redraw()
    except (ReferenceError,RuntimeError):pass


def reset():
    """Discard transient UI state when unregistering the addon."""
    if _active is not None:_active.close()
    _ui_cache.clear()


def count(callback,**values):
    """Optional integer work counters; ordinary progress callbacks still work."""
    recorder=getattr(callback,'count',None)
    if recorder:recorder(**values)


def notify(rig,stage=None,current=None,total=None):
    callback=getattr(rig,'progress',None)
    if callback:callback(stage,current,total)


class Progress:
    def __init__(self,context):
        self.context=context;self.start=time.monotonic();self.end=None
        self.scene=context.scene;self.wm=context.window_manager;self._begun=False
        self.workspace=getattr(context,'workspace',None);self._status_set=False
        self.stage='准备生成';self.stage_start=self.start;self.detail=''
        self.batch='准备';self.name='';self.index=0;self.total=0
        self.last_draw=0.;self.last_log=0.
        self._clock=self.start;self._rows={};self._drawing=False
        self.metadata={};self.result=None;self.report=None
        self.started_at=datetime.now(timezone.utc).isoformat()

    def _row(self):
        key=(self.batch,self.name,self.stage)
        if key not in self._rows:
            self._rows[key]=dict(batch=self.batch,expression=self.name,stage=self.stage,
                work_seconds=0.,redraw_seconds=0.,redraws=0,counters={})
        return self._rows[key]

    def _account(self,now):
        self._row()['work_seconds']+=now-self._clock;self._clock=now

    def count(self,**values):
        counters=self._row()['counters']
        for key,value in values.items():counters[key]=counters.get(key,0)+int(value)

    def describe(self,operation,partition,snapshot=None,**settings):
        self.metadata.update(operation=operation,model=partition.name,
            vertices=len(partition.data.vertices),polygons=len(partition.data.polygons),settings=settings)
        if snapshot is not None:
            self.metadata.update(curve_hash=snapshot.get('hash'),input_signature=snapshot.get('input'),
                curves=len(snapshot.get('entries',[])),process_lashes=snapshot.get('process_lashes',True))

    def _save_report(self,kind,value,traceback=None):
        from . import bl_info
        rows=list(self._rows.values());batches={};stages={};counts={}
        for row in rows:
            for table,key,labels in ((stages,row['stage'],dict(stage=row['stage'])),
                    (batches,(row['batch'],row['expression']),dict(batch=row['batch'],expression=row['expression']))):
                entry=table.setdefault(key,dict(labels,work_seconds=0.,redraw_seconds=0.,redraws=0))
                for field in ('work_seconds','redraw_seconds','redraws'):entry[field]+=row[field]
            for key,number in row['counters'].items():counts[key]=counts.get(key,0)+number
        sort=lambda values:sorted(values,key=lambda row:row['work_seconds']+row['redraw_seconds'],reverse=True)
        self.report=dict(format='ExpressionGen.generation_timing',schema_version=1,
            addon_version='.'.join(map(str,bl_info['version'])),blender_version=bpy.app.version_string,
            python_version=platform.python_version(),platform=platform.platform(),started_at=self.started_at,
            status='failed' if kind else 'completed',error=str(value) if kind else None,
            error_type=kind.__name__ if kind else None,
            traceback=''.join(traceback_module.format_exception(kind,value,traceback)) if kind else None,
            failure_context=dict(batch=self.batch,expression=self.name,stage=self.stage,detail=self.detail) if kind else None,
            elapsed_seconds=self.elapsed,work_seconds=sum(r['work_seconds'] for r in rows),
            redraw_seconds=sum(r['redraw_seconds'] for r in rows),redraws=sum(r['redraws'] for r in rows),
            metadata=self.metadata,counters=counts,stages=sort(stages.values()),batches=sort(batches.values()),rows=rows,
            timing_scope='Elapsed intervals between stage markers; synchronous UI redraw excluded from work. Report serialization excluded.')
        payload=json.dumps(self.report,ensure_ascii=False)
        self.scene[REPORT_KEY]=payload
        if self.result is not None:self.result[REPORT_KEY]=payload
        for row in self.report['stages'][:5]:
            print('[ExpressionGen 耗时] %s | 计算 %.2fs | 界面 %.2fs'%(row['stage'],row['work_seconds'],row['redraw_seconds']),flush=True)

    @property
    def elapsed(self):return (self.end or time.monotonic())-self.start

    def _status(self):
        if bpy.app.background or self.workspace is None:return
        batch='%s %d / %d'%(self.batch,self.index,self.total) if self.total else self.batch
        parts=['ExpressionGen',batch]
        if self.name:parts.append(self.name)
        parts.append(self.stage+(' '+self.detail if self.detail else ''))
        parts.append('已用 %.0f 秒 · 当前阶段 %.0f 秒'%(self.elapsed,time.monotonic()-self.stage_start))
        try:
            self.workspace.status_text_set(' | '.join(parts));self._status_set=True
        except (ReferenceError,RuntimeError):pass

    def __enter__(self):
        global _active
        if _active is not None:raise ValueError('表情正在生成，请等待本次完成')
        _active=self
        try:
            self.wm.progress_begin(0,100);self._begun=True
            self('准备生成')
        except BaseException:
            self.close()
            raise
        return self

    def batch_step(self,batch,index,total,name=''):
        self._account(time.monotonic())
        self.batch=batch;self.index=index;self.total=total;self.name=name
        self(batch)

    def __call__(self,stage=None,current=None,total=None):
        if self._drawing:return
        now=time.monotonic()
        if stage is not None:
            if stage!=self.stage:
                self._account(now);self.stage_start=now
            self.stage=stage;self.detail=('%d / %d'%(current,total)) if total else ''
        if now-self.last_draw<.35:return
        self.last_draw=now
        self._account(now);row=self._row();self._drawing=True
        try:
            wm=self.wm
            wm.progress_update(100*self.index/max(self.total,1))
            self._status()
            if now-self.last_log>=5.:
                print('[ExpressionGen] %s %d/%d %s | %s %s | %.1fs'%(
                    self.batch,self.index,self.total,self.name,self.stage,self.detail,self.elapsed),flush=True)
                self.last_log=now
            _redraw(wm)
            # Blender data stays on the main thread. Account for synchronous
            # repaint separately, including panels, overlays and GPU waits.
            if not getattr(self,'cooperative',False) and not bpy.app.background and self.context.window:
                try:
                    if bpy.ops.wm.redraw_timer.poll():bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP',iterations=1)
                except RuntimeError:pass
        finally:
            finished=time.monotonic();row['redraw_seconds']+=finished-now;row['redraws']+=1
            # A slow repaint must not immediately consume the next interval.
            self.last_draw=finished;self._clock=finished;self._drawing=False

    def close(self):
        """Release the busy state even when the window was closed or replaced."""
        global _active
        if _active is self:_active=None
        if self._status_set:
            self._status_set=False
            try:self.workspace.status_text_set(None)
            except (ReferenceError,RuntimeError):pass
        if self._begun:
            self._begun=False
            try:self.wm.progress_end()
            except (ReferenceError,RuntimeError):pass
        _redraw(self.wm)

    def __exit__(self,kind,value,traceback):
        self.end=time.monotonic()
        try:self._account(self.end)
        finally:self.close()
        try:self._save_report(kind,value,traceback)
        except Exception as exc:print('[ExpressionGen] 耗时报告保存失败：'+str(exc),flush=True)
        print('[ExpressionGen] %s | %.1fs'%('失败：'+str(value) if kind else '完成',self.elapsed),flush=True)
        if kind:
            print('[ExpressionGen] 失败位置：%s / %s / %s'%(self.batch,self.name,self.stage),flush=True)
            traceback_module.print_exception(kind,value,traceback)


def draw(layout,context):
    """Replace one button with one progress widget; never grow a busy panel.

    Blender animates panel realignment via TIMER events. Synchronous redraws
    cannot finish that animation while generation owns the main thread.
    """
    progress=_active
    if not active(context):return False
    text='%d / %d · %s'%(progress.index,progress.total,progress.name or progress.batch) if progress.total else progress.stage
    layout.progress(factor=min(1.,max(0.,progress.index/max(progress.total,1))),type='BAR',text=text)
    return True
