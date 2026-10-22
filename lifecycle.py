"""Register the addon and preserve current settings across RNA reloads."""
import bpy

SETTINGS=('exprkit_regions','exprkit_procedural','exprkit_rules')


def plain(value):
    if isinstance(value,bpy.types.ID):return value
    if hasattr(value,'keys'):return {key:plain(value[key]) for key in value.keys()}
    if hasattr(value,'to_list'):return value.to_list()
    return value


def capture():
    saved=[]
    for scene in bpy.data.scenes:
        values={}
        for name in SETTINGS:
            settings=getattr(scene,name,None)
            if settings is None:
                # Native ID properties survive initial RNA registration.
                # Untyped nested pointer storage is not a Python ID and must
                # not be replayed as a dict into PointerProperty setters.
                continue
            row={}
            for prop in settings.bl_rna.properties:
                key=prop.identifier
                if key=='rna_type' or (prop.is_readonly and prop.type!='COLLECTION'):continue
                value=getattr(settings,key)
                if prop.type=='COLLECTION':
                    value=[{p.identifier:(tuple(getattr(item,p.identifier)) if getattr(p,'is_array',False) else getattr(item,p.identifier)) for p in item.bl_rna.properties
                        if p.identifier!='rna_type' and not p.is_readonly} for item in value]
                elif getattr(prop,'is_array',False):value=tuple(value)
                row[key]=value
            values[name]=row
        saved.append((scene,values))
    return saved


def restore(saved):
    for scene,values in saved:
        for name,row in values.items():
            settings=getattr(scene,name)
            for key,value in row.items():
                prop=settings.bl_rna.properties.get(key)
                if prop is None:continue
                if name=='exprkit_regions' and key=='standard_preset':
                    # The removed builtin default is not a valid new enum
                    # item. Preserve user selections by filename on reload.
                    if row.get('standard_preset_file'):continue
                    from .region_ui import standard_preset_items
                    items=standard_preset_items(settings,None)
                    if isinstance(value,int):
                        import zlib
                        value=next((item[0] for item in items if item[0]!='__none__'
                            and ((zlib.crc32(item[0].encode('utf-8')) & 0x7fffffff) or 1)==value),'__none__')
                    settings.standard_preset_file=value if value in {item[0] for item in items} else '__none__'
                    continue
                if prop.type=='COLLECTION':
                    collection=getattr(settings,key);collection.clear()
                    entries=value.values() if isinstance(value,dict) else value
                    for entry in entries:
                        item=collection.add()
                        for field,content in sorted(entry.items(),key=lambda row:row[0]!='shift'):
                            if hasattr(item,field):setattr(item,field,content)
                elif prop.type=='ENUM' and isinstance(value,int):
                    choice=next((item.identifier for item in prop.enum_items if item.value==value),None)
                    if choice is not None:setattr(settings,key,choice)
                else:
                    setattr(settings,key,value)


def unregister_classes(modules):
    for name in SETTINGS:
        if hasattr(bpy.types.Scene,name):delattr(bpy.types.Scene,name)
    for module in reversed(modules):
        for cls in reversed(module.CLASSES):
            base=next((base for base in (bpy.types.Panel,bpy.types.Operator,bpy.types.UIList,bpy.types.PropertyGroup)
                       if issubclass(cls,base)),None)
            identifier=cls.__name__
            if base==bpy.types.Operator:
                namespace,name=cls.bl_idname.split('.',1)
                identifier=namespace.upper()+'_OT_'+name
            old=base.bl_rna_get_subclass_py(identifier,None) if base else None
            old=old or getattr(bpy.types,cls.__name__,None)
            if old is not None:bpy.utils.unregister_class(old)


def register(modules):
    from . import guide_overlay,generation_progress,generation_job
    generation_job.shutdown()
    generation_job.install()
    generation_progress.reset()
    guide_overlay.unregister()
    # Blender's Add-ons UI temporarily restricts scene data during register().
    # Native ID properties survive RNA re-registration; only unrestricted
    # in-process reloads need an explicit snapshot of the typed settings.
    unrestricted=hasattr(bpy.data,'scenes')
    saved=capture() if unrestricted else []
    unregister_classes(modules)
    for module in modules:module.register()
    restore(saved)
    guide_overlay.register()


def unregister(modules):
    from . import guide_overlay,generation_progress,generation_job
    generation_job.remove()
    generation_progress.reset()
    guide_overlay.unregister()
    unregister_classes(modules)
