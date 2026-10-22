"""Focus each workflow step and restore the scene's original viewport state."""
import json
import bpy
from . import region_blender as A


def layer_collections(root, path=()):
    path=path+(root.collection.name,)
    yield root,path
    for child in root.children:
        yield from layer_collections(child,path)


def begin(context):
    s=context.scene.exprkit_regions
    if s.session_running:return
    s.session_objects.clear();s.session_collections.clear()
    s.session_active=context.view_layer.objects.active
    s.session_layer=context.view_layer.name
    for layer in context.scene.view_layers:
        for ob in context.scene.objects:
            item=s.session_objects.add();item.object=ob;item.layer=layer.name
            item.present=layer.objects.get(ob.name)==ob
            item.hidden=ob.hide_get(view_layer=layer) if item.present else False
            item.viewport=ob.hide_viewport;item.unselectable=ob.hide_select
            item.selected=ob.select_get(view_layer=layer) if item.present else False
        for col,path in layer_collections(layer.layer_collection):
            if col.collection==context.scene.collection:continue
            item=s.session_collections.add();item.collection=col.collection
            item.layer=layer.name;item.path=json.dumps(path)
            item.viewport=col.collection.hide_viewport;item.unselectable=col.collection.hide_select
            item.excluded=col.exclude;item.hidden=col.hide_viewport
    s.session_shading=json.dumps([(screen.name,i,area.spaces.active.shading.color_type)
        for screen in bpy.data.screens for i,area in enumerate(screen.areas) if area.type=='VIEW_3D'])
    s.session_running=True


def remember_new(context):
    s=context.scene.exprkit_regions
    known={(item.object,item.layer) for item in s.session_objects}
    for layer in context.scene.view_layers:
        for ob in context.scene.objects:
            if (ob,layer.name) in known or A.is_working(ob):continue
            item=s.session_objects.add();item.object=ob;item.layer=layer.name
            prior=next((row for row in s.session_objects if row!=item and row.object==ob),None)
            item.present=layer.objects.get(ob.name)==ob
            item.hidden=ob.hide_get(view_layer=layer) if item.present else False
            item.selected=ob.select_get(view_layer=layer) if item.present else False
            item.viewport=prior.viewport if prior else ob.hide_viewport
            item.unselectable=prior.unselectable if prior else ob.hide_select


def focus(context, primary, references=()):
    settings=context.scene.exprkit_regions
    if settings.focus_region and settings.preview not in (primary,*references):settings.focus_region=False
    if primary is None:raise ValueError('当前步骤还没有可操作的对象')
    begin(context);remember_new(context)
    if primary==context.scene.exprkit_regions.fitted:
        primary.display_type='TEXTURED';primary.show_wire=False;primary.show_in_front=False
        for screen in bpy.data.screens:
            for area in screen.areas:
                if area.type=='VIEW_3D':area.spaces.active.shading.color_type='MATERIAL'
    keep={ob for ob in (primary,*references) if ob is not None}
    for ob in tuple(keep):
        keep.update(child for child in ob.children if child.get('ek_rigid_owner')==ob.name)
    from . import region_guides as G
    G.focus_collections(context,keep)
    layer=context.view_layer
    # Only reopen collection branches needed by this step. Their flags were
    # captured before any visibility changes, including layer exclusions.
    def open_branch(node):
        needed=any(ob in keep for ob in node.collection.all_objects)
        for child in node.children:needed=open_branch(child) or needed
        if needed and node.collection!=context.scene.collection:
            node.exclude=False;node.hide_viewport=False
            node.collection.hide_viewport=False;node.collection.hide_select=False
        return needed
    open_branch(layer.layer_collection);layer.update()
    for ob in keep:
        if ob.name not in layer.objects:
            if not A.is_working(ob):raise ValueError('对象不在当前场景中：'+ob.name)
            A.new_collection('ExpressionGen_工作副本').objects.link(ob)
    layer.update()
    preserve_edit=layer.objects.active==primary and primary.mode=='EDIT'
    if context.mode!='OBJECT' and not preserve_edit:bpy.ops.object.mode_set(mode='OBJECT')
    for ob in layer.objects:
        if ob!=primary:ob.select_set(False,view_layer=layer)
        if ob in keep:
            ob.hide_viewport=False;ob.hide_select=False;ob.hide_set(False,view_layer=layer)
        elif 'ek_guide_entry' in ob:
            ob.hide_viewport=False;ob.hide_set(False,view_layer=layer)
        else:ob.hide_set(True,view_layer=layer)
    primary.select_set(True,view_layer=layer);layer.objects.active=primary


def restore(context, final=None):
    s=context.scene.exprkit_regions
    if s.focus_region:s.focus_region=False
    if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    if s.session_running:
        # Restore object flags before exclusions, which may remove their bases.
        for item in s.session_objects:
            ob=item.object;layer=context.scene.view_layers.get(item.layer)
            if not ob or not layer:continue
            ob.hide_viewport=item.viewport;ob.hide_select=item.unselectable
            if item.present and layer.objects.get(ob.name)==ob:
                ob.hide_set(item.hidden,view_layer=layer)
                ob.select_set(item.selected,view_layer=layer)
        for item in s.session_collections:
            col=item.collection;layer=context.scene.view_layers.get(item.layer)
            if not col or not layer:continue
            col.hide_viewport=item.viewport;col.hide_select=item.unselectable
            matches=[node for node,path in layer_collections(layer.layer_collection)
                     if node.collection==col and json.dumps(path)==item.path]
            if not matches:
                matches=[node for node,path in layer_collections(layer.layer_collection) if node.collection==col]
            for node in matches:
                node.hide_viewport=item.hidden;node.exclude=item.excluded
        for screen_name,index,color in json.loads(s.session_shading or '[]'):
            screen=bpy.data.screens.get(screen_name)
            if screen and index<len(screen.areas) and screen.areas[index].type=='VIEW_3D':
                screen.areas[index].spaces.active.shading.color_type=color
    # All intermediate copies stay available, but no longer cover the originals.
    for layer in context.scene.view_layers:
        for ob in layer.objects:
            if A.is_working(ob) and not ob.get('ek_committed_rigid') and 'ek_guide_entry' not in ob:
                ob.select_set(False,view_layer=layer);ob.hide_set(True,view_layer=layer)
        from . import region_guides as G
        for collection in context.scene.collection.children_recursive:
            if collection.get('ek_guide_source') and collection.get('ek_guide_target'):
                G.collection_visibility(collection,False,layer)
    if final is not None:
        # The original may have been hidden before an extracted head entered
        # the workflow. Show only the final object's collection path again.
        def reveal(node):
            needed=any(ob==final for ob in node.collection.objects)
            for child in node.children:needed=reveal(child) or needed
            if needed:
                node.exclude=False;node.hide_viewport=False
                node.collection.hide_viewport=False;node.collection.hide_select=False
            return needed
        reveal(context.view_layer.layer_collection);context.view_layer.update()
        final.hide_viewport=False;final.hide_select=False
        if context.view_layer.objects.get(final.name)==final:final.hide_set(False,view_layer=context.view_layer)
    context.view_layer.update()
    active=final if final and final.visible_get(view_layer=context.view_layer) and not final.hide_select else s.session_active
    if active and context.view_layer.objects.get(active.name)==active and active.visible_get(view_layer=context.view_layer):
        if final==active:
            for ob in context.view_layer.objects:ob.select_set(False,view_layer=context.view_layer)
            active.select_set(True,view_layer=context.view_layer)
        context.view_layer.objects.active=active
    s.session_running=False
    s.session_objects.clear();s.session_collections.clear();s.session_shading=''


def guide_focus(context, selected=None, mesh=None):
    s=context.scene.exprkit_regions;collection=s.guide_collection
    reference=collection.get('ek_guide_source') if collection and s.guide_role=='SOURCE' else s.preview
    if collection:
        from . import region_guides as G
        G.show_source_space(collection,s.preview)
    visible=[]
    if collection:
        for ob in list(collection.all_objects):
            from . import region_guides as G
            G.enforce_display(ob,s.preview)
            entry=json.loads(ob.get('ek_guide_entry','{}'))
            if entry.get('role')==s.guide_role and (s.guide_kind=='ALL' or entry.get('kind')==s.guide_kind
                    or (mesh is not None and (ob.visible_get() or ob==s.guide_selected))):
                visible.append(ob)
    primary=mesh or selected or (s.guide_selected if s.guide_selected in visible else next(iter(visible),reference))
    if primary and primary.type=='CURVE':s.guide_selected=primary
    focus(context,primary,[reference,*visible])


def select_mesh_preserving_guides(context,ob):
    """Select a visible marking mesh without replaying workflow display filters."""
    if not ob or not ob.visible_get(view_layer=context.view_layer):
        raise ValueError('请先显示分区网格；曲线显示状态已保留')
    if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    for selected in context.selected_objects:selected.select_set(False)
    ob.hide_select=False;ob.select_set(True);context.view_layer.objects.active=ob
