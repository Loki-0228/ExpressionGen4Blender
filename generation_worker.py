"""Private Blender worker; only writes files in its supplied job directory."""
import importlib.util
import json
from pathlib import Path
import sys
import time
import traceback


def main():
    import bpy
    folder=Path(sys.argv[sys.argv.index('--')+1]).resolve()
    request=json.loads((folder/'request.json').read_text(encoding='utf8'))
    root=Path(__file__).resolve().parent
    spec=importlib.util.spec_from_file_location('_expressiongen_worker',root/'__init__.py',submodule_search_locations=[str(root)])
    package=importlib.util.module_from_spec(spec);sys.modules[spec.name]=package;spec.loader.exec_module(package)
    package.register()
    bpy.ops.wm.open_mainfile(filepath=str(folder/'input.blend'),load_ui=False,use_scripts=False)
    scene=bpy.context.scene
    for ob in bpy.data.objects:
        if scene.objects.get(ob.name) is None:scene.collection.objects.link(ob)
    collection=bpy.data.collections.get(request['guides'])
    if collection and collection.name not in scene.collection.children:scene.collection.children.link(collection)
    for key,value in request['rules'].items():scene[key]=value
    target=bpy.data.objects[request['target']];partition=bpy.data.objects[request['partition']]
    scene.frame_set(request['frame'],subframe=request['subframe'])
    from mathutils import Matrix
    for ob,key in ((target,'target_matrix'),(partition,'partition_matrix')):
        ob.parent=None;ob.constraints.clear();ob.animation_data_clear()
        ob.matrix_world=Matrix(request[key])
    from _expressiongen_worker import procedural_commit as Commit
    proof=request['rebase_proof']
    if (Commit.basis_signature(target)!=proof['target']
            or package.region_guides.fingerprint(partition,partition,None,include_regions=False)!=proof['partition']):
        raise ValueError('后台输入与已验证的模型不一致')
    target.data['ek_regeneration_state']=json.dumps(proof)

    def write(payload):
        name=('completion.json' if payload['state']=='completed' else
              'failure.json' if payload['state']=='failed' else 'status.json')
        temporary=folder/(name+'.tmp')
        temporary.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf8')
        try:temporary.replace(folder/name)
        except PermissionError:
            # Windows readers can briefly deny file replacement. Progress is
            # disposable; final files are new and read only after process exit.
            if name!='status.json':raise

    from _expressiongen_worker.generation_progress import Progress
    class WorkerProgress(Progress):
        last_write=0.
        def __call__(self,stage=None,current=None,total=None):
            super().__call__(stage,current,total)
            now=time.monotonic()
            if now-self.last_write<.25:return
            self.last_write=now
            write(dict(state='running',stage=self.stage,detail=self.detail,batch=self.batch,
                       index=self.index,total=self.total,name=self.name,elapsed=self.elapsed))

    try:
        with WorkerProgress(bpy.context) as progress:
            output,guides,report=package.procedural_generate.generate(
                target,partition,collection,progress=progress,**request['options'])
        # Export only the new result and guides. External object properties
        # are rebound to the live originals on import, never appended as copies.
        objects={output,*output.children_recursive,*guides.all_objects}
        collections={guides,*guides.children_recursive}
        owned=objects|collections|{ob.data for ob in objects if ob.data}
        references=[]
        for owner in objects|collections:
            for key in list(owner.keys()):
                value=owner.get(key)
                if isinstance(value,bpy.types.ID) and value not in owned:
                    role='target' if value==target else 'partition' if value==partition else None
                    references.append(dict(owner=owner.name,collection=isinstance(owner,bpy.types.Collection),
                                           key=key,role=role,name=value.name))
                    del owner[key]
        (folder/'result.json').write_text(json.dumps(dict(
            output=output.name,guides=guides.name,references=references,report=report,
            timing=progress.report),ensure_ascii=False),encoding='utf8')
        bpy.data.libraries.write(str(folder/'result.blend'),{output,guides},compress=True)
        write(dict(state='completed'))
    except BaseException as exc:
        write(dict(state='failed',error=str(exc),traceback=traceback.format_exc(),
                   timing=getattr(locals().get('progress'), 'report', None)))
        raise


if __name__=='__main__':
    try:main()
    except BaseException as exc:
        folder=Path(sys.argv[sys.argv.index('--')+1]).resolve()
        temporary=folder/'failure.tmp'
        try:payload=json.loads((folder/'failure.json').read_text(encoding='utf8'))
        except (OSError,ValueError):payload={}
        payload.update(state='failed',error=str(exc),traceback=traceback.format_exc())
        temporary.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf8')
        temporary.replace(folder/'failure.json')
        raise
