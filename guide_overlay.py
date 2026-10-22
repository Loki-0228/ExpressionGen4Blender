"""Bright, depth-independent guide overlay in solid and material preview modes."""
import bpy,json
# Preserve the registered handle across importlib.reload so unregister can
# remove the previous callback before installing the updated one.
_handle=globals().get('_handle')
_focus_listener=globals().get('_focus_listener')
_focus_cache={}


def restore_focus(ob):
    if ob is not None and 'ek_focus_display' in ob:
        ob.display_type=ob['ek_focus_display'];ob.show_in_front=bool(ob.get('ek_focus_front',False))
        del ob['ek_focus_display']
        if 'ek_focus_front' in ob:del ob['ek_focus_front']


def update_focus(settings,context):
    _focus_cache.clear()
    old=settings.focus_object;ob=settings.preview if settings.focus_region else None
    if old and old!=ob:restore_focus(old)
    settings.focus_object=ob
    if ob:
        if 'ek_focus_display' not in ob:
            ob['ek_focus_display']=ob.display_type;ob['ek_focus_front']=ob.show_in_front
        # Custom face passes provide per-region opacity in Solid mode too.
        # Changing diffuse alpha alone has no such effect in Solid shading.
        ob.display_type='WIRE';ob.show_in_front=False
    if context and context.screen:
        for area in context.screen.areas:
            if area.type=='VIEW_3D':area.tag_redraw()


@bpy.app.handlers.persistent
def focus_updated(scene,depsgraph):
    from .expression_authoring import sync_symmetry
    sync_symmetry(scene,depsgraph)
    settings=getattr(scene,'exprkit_regions',None)
    if not settings or not settings.focus_region or not settings.preview:return
    ob=settings.preview
    if any(update.id.original in (ob,ob.data) for update in depsgraph.updates):_focus_cache.clear()


def draw_focus(context):
    import gpu
    from gpu_extras.batch import batch_for_shader
    from . import region_transfer as T,region_blender as A
    s=getattr(context.scene,'exprkit_regions',None)
    ob=s.preview if s and s.focus_region else None
    if ob is None or ob not in context.visible_objects:return
    key=(ob.as_pointer(),ob.mode,s.manual_label,tuple(v for row in ob.matrix_world for v in row))
    if key not in _focus_cache:
        by_label={};labels=T.mesh_regions(ob)
        if ob.mode=='EDIT':
            import bmesh
            bm=bmesh.from_edit_mesh(ob.data);bm.faces.index_update()
            for triangle in bm.calc_loop_triangles():
                face=triangle[0].face
                if face.hide:continue
                by_label.setdefault(labels[face.index],[]).extend(ob.matrix_world@loop.vert.co for loop in triangle)
        else:
            ob.data.calc_loop_triangles()
            for triangle in ob.data.loop_triangles:
                if ob.data.polygons[triangle.polygon_index].hide:continue
                by_label.setdefault(labels[triangle.polygon_index],[]).extend(ob.matrix_world@ob.data.vertices[i].co for i in triangle.vertices)
        shader=gpu.shader.from_builtin('UNIFORM_COLOR')
        _focus_cache.clear()
        _focus_cache[key]=(shader,[(label,batch_for_shader(shader,'TRIS',{'pos':points})) for label,points in by_label.items() if points])
    shader,batches=_focus_cache[key]
    depth=gpu.state.depth_test_get();blend=gpu.state.blend_get();mask=gpu.state.depth_mask_get()
    try:
        shader.bind();gpu.state.blend_set('ALPHA');gpu.state.depth_test_set('LESS_EQUAL')
        # Invisible depth prepass: dim regions retain true self-occlusion.
        gpu.state.depth_mask_set(True);shader.uniform_float('color',(0.,0.,0.,0.))
        for label,batch in batches:
            if label!=s.manual_label:batch.draw(shader)
        gpu.state.depth_mask_set(False)
        for label,batch in batches:
            if label==s.manual_label:continue
            shader.uniform_float('color',(*A.region_color(label)[:3],.15));batch.draw(shader)
        gpu.state.depth_test_set('NONE')
        shader.uniform_float('color',(*A.region_color(s.manual_label)[:3],.95))
        for label,batch in batches:
            if label==s.manual_label:batch.draw(shader)
    finally:
        gpu.state.depth_test_set(depth);gpu.state.blend_set(blend);gpu.state.depth_mask_set(mask)


def draw():
    import gpu
    from gpu_extras.batch import batch_for_shader
    from . import region_guides as G
    context=bpy.context
    if not context.space_data or context.space_data.type!='VIEW_3D' or not context.space_data.overlay.show_overlays:return
    draw_focus(context)
    shader=gpu.shader.from_builtin('POLYLINE_UNIFORM_COLOR')
    depth=gpu.state.depth_test_get();blend=gpu.state.blend_get()
    try:
        gpu.state.depth_test_set('NONE');gpu.state.blend_set('ALPHA')
        for ob in context.visible_objects:
            if ob.type!='CURVE' or 'ek_guide_entry' not in ob:continue
            target=next(((c.get('ek_guide_owner') or c).get('ek_guide_target') for c in ob.users_collection
                         if (c.get('ek_guide_owner') or c).get('ek_guide_target')),None)
            if target is None:continue
            to_world=G.reference_transform(ob,target).inverted()
            points=[to_world@__import__('mathutils').Vector(p) for p in G.curve_points(ob,target)]
            color=G.COLORS[json.loads(ob['ek_guide_entry'])['kind']]
            shader.bind();shader.uniform_float('viewportSize',gpu.state.viewport_get()[2:])
            shader.uniform_float('lineWidth',3.5);shader.uniform_float('color',color)
            batch_for_shader(shader,'LINE_STRIP',{'pos':points}).draw(shader)
    finally:
        gpu.state.depth_test_set(depth);gpu.state.blend_set(blend)


def register():
    global _handle,_focus_listener
    unregister()
    if not bpy.app.background:_handle=bpy.types.SpaceView3D.draw_handler_add(draw,(),'WINDOW','POST_VIEW')
    for scene in getattr(bpy.data,'scenes',()):
        settings=getattr(scene,'exprkit_regions',None)
        if settings and settings.focus_region:update_focus(settings,bpy.context)
    _focus_listener=focus_updated;bpy.app.handlers.depsgraph_update_post.append(_focus_listener)


def unregister():
    global _handle,_focus_listener
    if _handle is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handle,'WINDOW');_handle=None
    if _focus_listener in bpy.app.handlers.depsgraph_update_post:bpy.app.handlers.depsgraph_update_post.remove(_focus_listener)
    _focus_listener=None;_focus_cache.clear()
    for ob in getattr(bpy.data,'objects',()):restore_focus(ob)
