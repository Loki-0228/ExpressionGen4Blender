"""Texture-card expressions: region planes, a face shell and anchor props.

Three card kinds share one contract:

* ``REGION`` a plane whose silhouette is fitted to one partition (the eye
  shadow partition, 13). It floats a short clearance above the analysed
  surface so it never intersects the skin; on Basis it shrinks into the front
  projection of the face shell.
* ``SHELL``  a transparent curved shell over the whole Face partition, mainly
  for blush. It follows the face surface instead of one small partition.
* ``ANCHOR`` a shape-fitted plane at a user anchor (an Empty named ``EK_J_*``);
  on Basis it retreats into the head shell along its own normal. It covers
  sweat drops and surprise marks.

Cards are separate objects, so the target keeps its vertex-for-vertex shape
keys. Every card carries one shape key per expression: Basis is the hidden
state and each expression key restores the fitted, visible position. A card
key may follow a key on the generated result (tears following a cry).

The PMX side mirrors the layout with vertex morphs plus a material morph that
opens alpha from zero, so this module and the CSScript stay in step.
"""
import json

import bpy
import numpy as np

from . import procedural_texture as T
from . import procedural_card_depth as Depth

TAG='ek_material_expression'
REGION=13
EYEWHITE=7
EYE_LABELS=(3,7)                  # pupil/highlight and eye white
EYE_CARDS=('はぁと','星目')        # cards that live inside the eye
SKIN_EYE_LABELS=(0,3,7)           # skin, pupil and eye white; lashes and brows excluded
SKIN_EYE_CARDS=('涙',)             # cards that run from the eye onto the cheek
# A bare string would iterate character by character and break the path.
REFERENCE=('data/reference_cards.json',)
# Shipped with the addon so a fresh install renders the captured cards instead
# of white planes; users may still point card_texture at their own sheet.
BUNDLED=('data/textures/bq.png',)


def bundled_texture():
    """Path of the texture packed with the addon, or '' when it is missing."""
    from pathlib import Path
    base=Path(__file__).resolve().parent
    for name in BUNDLED:
        path=base/name
        if path.exists():return str(path)
    return ''


def reference_library():
    """Card geometry extracted from the reference model, or None."""
    from pathlib import Path
    base=Path(__file__).resolve().parent
    for name in REFERENCE:
        path=base/name
        if path.exists():return json.loads(path.read_text(encoding='utf8'))
    return None


def head_frame(target):
    """Face-partition frame in world space: centre, width, height.

    Cards are stored relative to this frame, so the same library places on any
    model that has a Face partition (label 0).
    """
    faces=partition(target,0)
    if not faces:raise ValueError('缺少 Face 分区，无法放置参考卡片')
    points=face_points(target)
    ids=sorted({v for i in faces for v in target.data.polygons[i].vertices})
    if not ids:raise ValueError('Face 分区没有顶点')
    cloud=points[ids]
    low,high=cloud.min(axis=0),cloud.max(axis=0)
    return dict(center=(low+high)*.5,width=float(max(high[0]-low[0],1e-6)),
                height=float(max(high[2]-low[2],1e-6)),depth=float(max(high[1]-low[1],1e-6)))


def face_points(ob):
    key=ob.data.shape_keys
    rows=key.reference_key.data if key else ob.data.vertices
    matrix=ob.matrix_world
    return np.array([tuple(matrix@row.co) for row in rows],dtype=float)


def partition(target, label):
    """Polygon indices that belong to one semantic label."""
    from . import region_core as C
    slots={}
    explicit=json.loads(target.get('ek_standard_slot_labels','{}'))
    for index,slot in enumerate(target.material_slots):
        name=slot.material.name if slot.material else ''
        value=C.material_region(name)
        if value is None:value=explicit.get(str(index))
        if value is not None:slots[index]=C.canonical_region(value)
    return [number for number,polygon in enumerate(target.data.polygons)
            if slots.get(int(polygon.material_index))==label]


def _material(name, texture, tint):
    mat=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat[TAG]=True;mat.diffuse_color=tint
    if hasattr(mat,'blend_method'):mat.blend_method='BLEND'
    if hasattr(mat,'shadow_method'):mat.shadow_method='NONE'
    mat.use_nodes=True
    nodes=mat.node_tree.nodes;links=mat.node_tree.links
    nodes.clear()
    output=nodes.new('ShaderNodeOutputMaterial')
    shader=nodes.new('ShaderNodeBsdfPrincipled')
    links.new(shader.outputs['BSDF'],output.inputs['Surface'])
    shader.inputs['Alpha'].default_value=float(tint[3])
    # A flat tint must not catch a highlight: the eye-shadow card sits in the
    # eye socket and any specular would read as a bright patch, the opposite of
    # a shadow. The reference material is a dark texture for the same reason.
    if 'Roughness' in shader.inputs:shader.inputs['Roughness'].default_value=1.0
    for name in ('Specular IOR Level','Specular'):
        if name in shader.inputs:shader.inputs[name].default_value=0.0
    # The renderer reads Base Color, not diffuse_color, so a textureless card
    # must carry its tint here or it stays the default 0.8 grey.
    shader.inputs['Base Color'].default_value=(float(tint[0]),float(tint[1]),
                                               float(tint[2]),1.0)
    if texture:
        try:
            image=bpy.data.images.load(texture,check_existing=True)
        except (RuntimeError,OSError):
            # A wrong path must not lose the whole card set; the caller turns
            # this into one per-card warning instead.
            raise ValueError('无法读取贴图：'+str(texture))
        node=nodes.new('ShaderNodeTexImage');node.image=image;node.extension='CLIP'
        links.new(node.outputs['Color'],shader.inputs['Base Color'])
        # Linking Alpha replaces default_value, so the tint alpha is folded in
        # with a multiply rather than assigned.
        alpha=tint[3]
        if abs(alpha-1.)>1e-6:
            multiply=nodes.new('ShaderNodeMath');multiply.operation='MULTIPLY'
            multiply.inputs[1].default_value=float(alpha)
            links.new(node.outputs['Alpha'],multiply.inputs[0])
            links.new(multiply.outputs['Value'],shader.inputs['Alpha'])
        else:
            links.new(node.outputs['Alpha'],shader.inputs['Alpha'])
    return mat


def _object(name, vertices, faces, material, collection, uvs=None):
    mesh=bpy.data.meshes.new(name+'_mesh')
    mesh.from_pydata([tuple(row) for row in vertices],[],[tuple(face) for face in faces])
    mesh.update()
    for polygon in mesh.polygons:polygon.use_smooth=True
    mesh.materials.append(material)
    ob=bpy.data.objects.new(name,mesh)
    (collection or bpy.context.scene.collection).objects.link(ob)
    ob[TAG]=True
    if uvs is not None:
        layer=mesh.uv_layers.new(name='UVMap')
        for loop in mesh.loops:
            u,v=uvs[loop.vertex_index]
            layer.data[loop.index].uv=(float(u),float(v))
    return ob


def _planar_uv(points, axes=((0,2),)):
    """Normalised planar UV. Lattice samples are already 2D; mesh points are 3D."""
    cloud=np.asarray(points,dtype=float)
    if cloud.ndim==2 and cloud.shape[1]>len(axes[0]):
        cloud=cloud[:,list(axes[0])]
    lo=cloud.min(axis=0);span=np.maximum(np.ptp(cloud,axis=0),1e-9)
    return (cloud-lo)/span


def _spec_expressions(spec):
    names=[name.strip() for name in str(spec.get('expressions','')).split(',') if name.strip()]
    return names


def region_card(target, spec, collection=None):
    """A plane fitted to one partition, lifted off the skin by one clearance."""
    label=int(spec.get('region',REGION))
    faces=partition(target,label)
    if not faces:raise ValueError('所选分区没有可用的面：'+spec.get('name','目影'))
    # The shadow band covers the top of the pupil as well as the eye white.
    if label==EYEWHITE and 0.<float(spec.get('band',0.))<1.:faces=faces+partition(target,3)
    points=face_points(target)
    rings=[list(target.data.polygons[i].vertices) for i in faces]
    fr=T.frame(points,rings)
    # A band keeps only the upper share of the region. The eye shadow is the
    # top third of the eye white, not the whole sclera, so the card reads as a
    # lid shadow instead of tinting the eyeball.
    band=float(spec.get('band',0.))
    if 0.<band<1.:
        basis=np.column_stack((fr['u'],fr['v'],fr['normal']))
        heights=[]
        for ring in rings:
            centroid=points[list(ring)].mean(axis=0)
            heights.append(float((centroid-fr['center'])@fr['v']))
        heights=np.asarray(heights)
        cut=float(np.quantile(heights,1.-band))
        kept=[ring for ring,height in zip(rings,heights) if height>=cut]
        if len(kept)>=2:rings=kept
    kept_ids=sorted({i for ring in rings for i in ring})
    local_ring=(points[kept_ids]-fr['center'])@np.column_stack((fr['u'],fr['v']))
    ring=T.hull(local_ring)
    # Grow slightly about the centre so the band reaches the lash line instead
    # of stopping inside the sclera.
    expand=float(spec.get('expand',1.))
    if expand>1.:
        centre=ring.mean(axis=0)
        ring=centre+(ring-centre)*expand
    samples,grid=T.lattice(ring,int(spec.get('columns',14)),int(spec.get('rows',4)),
                           float(spec.get('inset',.06)))
    faces_out=T.triangles(grid)
    if 0.<band<1.:
        # A band follows each eye's upper lid instead of one convex blob.
        samples,faces_out=T.upper_bands(fr['local'][:,:2],band,int(spec.get('columns',14)),
                                        int(spec.get('rows',4)),float(spec.get('expand',1.)))
    if not faces_out:raise ValueError('贴图卡片网格过小，请提高行列细分：'+spec.get('name','目影'))
    show=T.fitted(fr,samples,float(spec.get('clearance',T.CLEARANCE)))
    # Closed state must vanish inside the face shell, not only behind the eye
    # shadow rim: take the least-front face depth under this card's footprint.
    skin=[list(target.data.polygons[i].vertices) for i in partition(target,0)] or rings
    behind=float(T.footprint(fr,points,skin).min())
    hide=T.hidden(fr,samples,behind=behind,margin=float(spec.get('margin',T.MARGIN)))
    card=_object('EK_card_'+spec['name'],hide,faces_out,
                 _material('EK_card_'+spec['name'],spec.get('texture'),
                           tuple(spec.get('tint',(1,1,1,1)))),collection,
                 _planar_uv(samples))
    card['ek_card_kind']='REGION'
    card['ek_card_region']=label
    card['ek_card_expressions']=json.dumps(_spec_expressions(spec),ensure_ascii=False)
    card['ek_card_fit']=json.dumps(dict(show=show.tolist(),hide=hide.tolist()),ensure_ascii=False)
    return card,show


def shell_card(target, spec, collection=None):
    """A transparent shell over the whole Face partition, mainly for blush."""
    faces=partition(target,0)
    if not faces:raise ValueError('缺少 Face 分区，无法生成曲面罩')
    points=face_points(target)
    rings=[list(target.data.polygons[i].vertices) for i in faces]
    ids=sorted({i for ring in rings for i in ring})
    index={old:new for new,old in enumerate(ids)}
    remap=[[index[i] for i in ring] for ring in rings]
    cloud=points[ids]
    outer=T.shell(cloud,remap,float(spec.get('offset',T.SHELL_OFFSET)),float(spec.get('scale',1.)))
    # The shell keeps the Face polygons' own winding, so its normals are the Face normals.
    # Sink the closed shell well inside the skin so no part of it shows.
    # The hidden state sinks by the full nominal offset, not the edge-limited one, so it stays behind the skin.
    full=T.shell(cloud,remap,float(spec.get('offset',T.SHELL_OFFSET)),float(spec.get('scale',1.)),limit=False)
    hidden=cloud+(full-cloud)*-(1.0+float(spec.get('margin',T.MARGIN))*64.)
    card=_object('EK_card_'+spec['name'],hidden,remap,
                 _material('EK_card_'+spec['name'],spec.get('texture'),
                           tuple(spec.get('tint',(1,1,1,1)))),collection,
                 _planar_uv(cloud))
    card['ek_card_kind']='SHELL'
    card['ek_card_expressions']=json.dumps(_spec_expressions(spec),ensure_ascii=False)
    card['ek_card_fit']=json.dumps(dict(show=outer.tolist(),hide=hidden.tolist()),ensure_ascii=False)
    return card,outer


def anchor_card(target, spec, collection=None):
    """A J-point card; the Empty carries position and orientation."""
    anchor=bpy.data.objects.get(spec.get('anchor',''))
    if anchor is None:raise ValueError('找不到定位空物体：'+str(spec.get('anchor')))
    matrix=anchor.matrix_world
    corners,front=T.anchor(matrix.translation,matrix.to_3x3(),
                           float(spec.get('width',.1)),float(spec.get('height',.1)))
    points=face_points(target)
    depth=float(np.ptp(points[:,1])) if len(points) else .2
    hidden=T.anchor_hidden(corners,front,depth*.5)
    card=_object('EK_card_'+spec['name'],hidden,[(0,1,2),(0,2,3)],
                 _material('EK_card_'+spec['name'],spec.get('texture'),
                           tuple(spec.get('tint',(1,1,1,1)))),collection,
                 np.array(((0,0),(1,0),(1,1),(0,1)),dtype=float))
    card['ek_card_kind']='ANCHOR'
    card['ek_card_anchor']=spec.get('anchor','')
    card['ek_card_expressions']=json.dumps(_spec_expressions(spec),ensure_ascii=False)
    card['ek_card_fit']=json.dumps(dict(show=corners.tolist(),hide=hidden.tolist(),
                                        front=front.tolist()),ensure_ascii=False)
    return card,corners


def build(target, specs, collection=None):
    """Create every card; returns (card, shown vertices) pairs."""
    cards=[]
    for spec in specs:
        kind=spec.get('kind','REGION')
        if kind=='SHELL':cards.append(shell_card(target,spec,collection))
        elif kind=='ANCHOR':cards.append(anchor_card(target,spec,collection))
        else:cards.append(region_card(target,spec,collection))
    return cards


def apply_keys(card, shown, expressions, follow=None):
    """Basis hides the card; each expression key shows it at the fitted spot."""
    if card.data.shape_keys:card.shape_key_clear()
    basis=card.shape_key_add(name='Basis',from_mix=False)
    hidden=np.asarray(json.loads(card['ek_card_fit'])['hide'],dtype=np.float32)
    basis.data.foreach_set('co',hidden.ravel())
    for name in expressions:
        key=card.shape_key_add(name=name,from_mix=False)
        key.data.foreach_set('co',np.asarray(shown,dtype=np.float32).ravel())
        key.slider_min=0.;key.slider_max=1.;key.value=0.
        source=(follow or {}).get(name)
        if source:follow_driver(card,name,source[0],source[1])
    return card


def follow_driver(card, expression, target, source):
    """Make one card key follow a named key on the generated result.

    The source key is located by its stripped name: exports such as the
    reference model keep a trailing space (``星目 ``), and a literal lookup
    would silently leave the card without a driver.
    """
    key=card.data.shape_keys.key_blocks.get(expression)
    if key is None:raise ValueError('卡片缺少表情键：'+expression)
    keys=target.data.shape_keys
    if keys is None:raise ValueError('结果模型没有形态键：'+source)
    wanted=source.strip()
    match=next((block.name for block in keys.key_blocks
                if block.name.strip()==wanted),None)
    if match is None:raise ValueError('结果模型缺少表情键：'+source)
    curve=key.driver_add('value')
    driver=curve.driver;driver.type='AVERAGE'
    variable=driver.variables.new();variable.type='SINGLE_PROP'
    variable.targets[0].id_type='KEY'
    variable.targets[0].id=keys
    # Blender escapes quotes inside the path, so the raw name is used as-is.
    variable.targets[0].data_path='key_blocks["%s"].value'%match.replace('"','\\"')
    driver.expression='var'
    return driver


def recipe_specs(scene):
    """Card specs authored on the scene, plus the two built-in eye cards."""
    from . import procedural_ui as U
    settings=scene.exprkit_procedural
    specs=[dict(name=item.name,kind=item.kind,region=item.region,texture=item.texture,
                anchor=item.anchor,columns=item.columns,rows=item.rows,
                clearance=item.clearance,margin=item.margin,offset=item.offset,
                scale=item.scale,width=item.width,height=item.height,
                tint=tuple(item.tint))
           for item in settings.cards]
    return specs


def default_specs():
    """The procedural cards: the eye shadow plane and the blush shell.

    Blush stays procedural on purpose -- it is a soft tinted shell, not a
    captured texture -- while every other reference card ships in
    ``data/reference_cards.json``.
    """
    return [dict(name='目影',kind='REGION',region=EYEWHITE,texture='',anchor='',
                 columns=16,rows=3,band=1./3.,clearance=T.CLEARANCE,margin=T.MARGIN,
                 offset=T.SHELL_OFFSET,expand=1.12,scale=1.,width=.1,height=.1,
                 tint=(.06,.05,.07,.30),expressions='目影濃'),
            dict(name='脸红',kind='SHELL',region=0,texture='',anchor='',
                 columns=10,rows=8,clearance=T.CLEARANCE,margin=T.MARGIN,offset=T.SHELL_OFFSET,
                 scale=1.1,width=.1,height=.1,tint=(1.,.75,.8,.35),expressions='脸红,照れ')]


def spec_from_item(item):
    return dict(name=item.name,kind=item.kind,region=int(item.region),texture=item.texture,
                anchor=item.anchor,columns=int(item.columns),rows=int(item.rows),
                clearance=float(item.clearance),margin=float(item.margin),offset=float(item.offset),
                scale=float(item.scale),width=float(item.width),height=float(item.height),
                tint=tuple(item.tint),expressions=item.expressions,expand=float(item.expand),
        band=float(item.band))


def has_marked_eyeshadow(target):
    """True when the model already provides an eye shadow of its own."""
    if partition(target,REGION):return True
    from . import region_core as C
    for slot in target.material_slots:
        if slot.material and C.material_region(slot.material.name)==REGION:return True
    return False


def build_for(output, settings, expressions, collection=None):
    """Build every enabled card on a generated result and bind its keys.

    Runs in the UI process after generation, so anchor Empties and their world
    matrices are available. The reference cards travel with the addon; blush
    (脸红) is generated procedurally as the face shell instead. Returns the
    card objects; an empty list when the user turned the feature off.
    """
    if settings is None or not getattr(settings,'build_cards',True):return []
    existing=[ob for ob in output.children if ob.get(TAG)]
    for ob in existing:bpy.data.objects.remove(ob,do_unlink=True)
    cards=[]
    library=reference_library()
    # An empty field means "use what we ship"; only a real path overrides it.
    texture=settings.card_texture or bundled_texture()
    # Gather the occluding surface once: the same probes serve every card, and
    # rebuilding them per card would rescan the whole face for each one.
    try:
        probes=card_probes(output)
    except ValueError as exc:
        probes=None
        output['ek_card_warnings']=json.dumps(
            json.loads(output.get('ek_card_warnings','[]'))+[str(exc)],ensure_ascii=False)
    for spec in reference_specs(library,skip=('脸红',)):
        try:
            cards.append(reference_card(output,spec['entry'],library,texture,collection,probes))
        except ValueError as exc:
            output['ek_card_warnings']=json.dumps(
                json.loads(output.get('ek_card_warnings','[]'))+[str(exc)],ensure_ascii=False)
    specs=[spec_from_item(item) for item in settings.cards]
    if not specs:specs=default_specs()
    # The shadow belongs to the model when it already carries one; generating a
    # second card would double it up.
    if has_marked_eyeshadow(output):
        specs=[spec for spec in specs if spec.get('name')!='目影']
    for spec in specs:
        try:
            cards.append(_build_one(output,spec,collection))
        except ValueError as exc:
            # One unusable card must not lose a finished expression set.
            output['ek_card_warnings']=json.dumps(
                json.loads(output.get('ek_card_warnings','[]'))+[str(exc)],ensure_ascii=False)
    for card,shown in cards:
        # A declared list means "only these"; an empty list means "every
        # expression". Reference cards declare exactly their own name, so an
        # unselected card stays hidden at Basis instead of opening with all.
        declared=json.loads(card.get('ek_card_expressions','[]'))
        if declared:wanted=[name for name in expressions if name in declared]
        else:wanted=list(expressions)
        apply_keys(card,shown,wanted)
        card.parent=output
        card.matrix_parent_inverse=output.matrix_world.inverted()
        for name in wanted:
            # Compare stripped names: the reference export keeps a trailing
            # space on some keys (``星目 ``), and a literal test skipped them.
            keys=output.data.shape_keys
            if keys is None:continue
            if any(block.name.strip()==name.strip() for block in keys.key_blocks):
                follow_driver(card,name,output,name)
    output['ek_cards']=json.dumps([card.name for card,_ in cards],ensure_ascii=False)
    # Procedural cards carry no texture, so this records what the reference
    # cards actually sampled -- the first thing to check when they look white.
    output['ek_card_texture']=texture or ''
    return [card for card,_ in cards]


def _build_one(output, spec, collection):
    kind=spec.get('kind','REGION')
    if kind=='SHELL':return shell_card(output,spec,collection)
    if kind=='ANCHOR':return anchor_card(output,spec,collection)
    return region_card(output,spec,collection)


def _key_points(block):
    flat=np.empty(len(block.data)*3,dtype=np.float32);block.data.foreach_get('co',flat)
    return flat.reshape(-1,3).astype(float)


def embed(output):
    """Fold the reviewed cards into the result mesh.

    One object then carries every expression key, so a single slider moves the
    face and its cards together (Blender cannot edit key values on several
    objects at once). Card geometry is appended after the original vertices and
    faces; unembed() removes exactly that tail before any step that needs the
    vertex-origin correspondence. The standalone child cards stay hidden as the
    source for writing cards back onto the target.
    """
    import bmesh
    if output.get('ek_card_embedded'):return 0
    mesh=output.data;keys=mesh.shape_keys
    # A card with only Basis never shows; embedding it would just add dead vertices.
    cards=[ob for ob in output.children if ob.get(TAG) and ob.type=='MESH'
           and ob.data.shape_keys and len(ob.data.shape_keys.key_blocks)>1]
    if keys is None or not cards:return 0
    first_v=len(mesh.vertices);first_f=len(mesh.polygons);first_m=len(mesh.materials)
    inverse=np.array(output.matrix_world.inverted(),dtype=float)
    pieces=[];face_uvs=[]
    for card in cards:
        matrix=inverse@np.array(card.matrix_world,dtype=float)
        def local(points,matrix=matrix):return points@matrix[:3,:3].T+matrix[:3,3]
        shape=card.data.shape_keys
        rest=local(_key_points(shape.reference_key))
        posed={block.name:local(_key_points(block)) for block in shape.key_blocks}
        layer=card.data.uv_layers[0] if card.data.uv_layers else None
        faces=[]
        for polygon in card.data.polygons:
            faces.append(list(polygon.vertices))
            face_uvs.append([tuple(layer.data[i].uv) if layer else (0.,0.) for i in polygon.loop_indices])
        pieces.append(dict(card=card,rest=rest,keys=posed,faces=faces,count=len(rest)))
    bm=bmesh.new()
    try:
        bm.from_mesh(mesh)
        slot=first_m
        for piece in pieces:
            made=[bm.verts.new(tuple(point)) for point in piece['rest']]
            bm.verts.ensure_lookup_table()
            for ring in piece['faces']:
                face=bm.faces.new([made[i] for i in ring]);face.material_index=slot;face.smooth=True
            slot+=1
        bm.to_mesh(mesh)
    finally:bm.free()
    for piece in pieces:mesh.materials.append(piece['card'].data.materials[0] if piece['card'].data.materials else None)
    total=len(mesh.vertices)
    for block in mesh.shape_keys.key_blocks:
        points=_key_points(block)
        cursor=first_v
        for piece in pieces:
            points[cursor:cursor+piece['count']]=piece['keys'].get(block.name,piece['rest']);cursor+=piece['count']
        block.data.foreach_set('co',points.ravel().astype(np.float32))
    for layer in mesh.uv_layers:
        for offset,uvs in enumerate(face_uvs):
            polygon=mesh.polygons[first_f+offset]
            for loop,uv in zip(polygon.loop_indices,uvs):layer.data[loop].uv=uv
    mesh.update()
    for piece in pieces:
        piece['card'].hide_viewport=True;piece['card'].hide_render=True
    output['ek_card_embedded']=json.dumps(dict(vertices=first_v,faces=first_f,materials=first_m,
        cards=[piece['card'].name for piece in pieces]),ensure_ascii=False)
    return total-first_v


def unembed(output):
    """Remove the cards embed() appended; the original mesh and keys are untouched."""
    import bmesh
    info=json.loads(output.get('ek_card_embedded') or 'null')
    if not info:return 0
    mesh=output.data
    bm=bmesh.new()
    try:
        bm.from_mesh(mesh);bm.verts.ensure_lookup_table()
        tail=list(bm.verts)[info['vertices']:]
        bmesh.ops.delete(bm,geom=tail,context='VERTS')
        bm.to_mesh(mesh)
    finally:bm.free()
    while len(mesh.materials)>info['materials']:mesh.materials.pop(index=len(mesh.materials)-1)
    mesh.update()
    for name in info.get('cards',[]):
        card=bpy.data.objects.get(name)
        if card is not None:card.hide_viewport=False;card.hide_render=False
    del output['ek_card_embedded']
    return len(tail)


def cleanup():
    """Remove card objects this addon owns; safe to call on reload."""
    for ob in list(bpy.data.objects):
        if ob.get(TAG):bpy.data.objects.remove(ob,do_unlink=True)
    for mesh in list(bpy.data.meshes):
        if mesh.users==0 and mesh.name.startswith('EK_card_'):bpy.data.meshes.remove(mesh)


def card_probes(target, labels=(0,2,3,5,7)):
    """Vertices that a card must stay in front of.

    Cards in the reference sit on the eyeball (starlight, tears) or float just
    off the cheek (symbols), so both surfaces count as the occluder. The lash
    and brow partition is included because a tear card hugs the lid edge and
    would otherwise disappear behind the lash band.
    """
    ids=set()
    for label in labels:
        for index in partition(target,label):
            ids.update(target.data.polygons[index].vertices)
    if not ids:raise ValueError('缺少面部或眼部分区，无法确定卡片深度')
    return face_points(target)[sorted(ids)]


def clear_posed_face(target, name, posed, faces, width):
    """Lift the entire card against the actual expression's facial triangles."""
    keys=target.data.shape_keys
    key=keys.key_blocks.get(name) if keys else None
    if key is None:return posed
    from mathutils import Vector
    from mathutils.bvhtree import BVHTree
    selected=set(partition(target,0))
    target.data.calc_loop_triangles()
    triangles=[tuple(t.vertices) for t in target.data.loop_triangles if t.polygon_index in selected]
    if not triangles:return posed
    points=[target.matrix_world@row.co for row in key.data]
    tree=BVHTree.FromPolygons(points,triangles,all_triangles=True)
    samples=list(posed)
    for face in faces:
        for k in range(1,len(face)-1):
            a,b,c=posed[[face[0],face[k],face[k+1]]]
            for u in range(5):
                for v in range(5-u):
                    samples.append(a+(b-a)*(u/4.)+(c-a)*(v/4.))
    front=min(p.y for p in points)-width
    shift=0.;margin=max(T.CLEARANCE,.008)*width
    for point in samples:
        hit,_,_,_=tree.ray_cast(Vector((point[0],front,point[2])),Vector((0.,1.,0.)))
        if hit is not None:shift=max(shift,float(point[1]-hit.y)+margin)
    # Replacement eyes need a small extra gap for the curved card surface
    # and views slightly above the facial front direction.
    if name in ("はぅ","はちゅ目"):shift+=width*.02
    result=posed.copy();result[:,1]-=shift
    return result


def reference_card(target, entry, library, texture, collection=None, probes=None):
    """Rebuild one card captured from the reference model.

    The library stores rest/posed corners relative to the reference head
    frame, so the same card places on any target: multiply by this model's
    face width and add its face centre. Rest is the hidden state and posed is
    the expression state, matching the procedural cards.

    Depths do not transfer: the reference card may sit on its eyeball while
    this model's face is a little forward or back. The visible state is
    therefore pushed in front of the measured skin/eye surface, keeping the
    card's shape and its X/Z position.
    """
    frame=head_frame(target)
    centre=np.asarray(frame['center'],dtype=float)
    width=max(float(frame['width']),1e-9)
    # Callers may pass '' when the scene field is unset; fall back here too so
    # a direct call still gets the packed sheet.
    texture=texture or bundled_texture()

    def place(rows):
        return centre+np.asarray(rows,dtype=float)*width

    rest=place(entry['rest'])
    posed=place(entry['posed'])
    if probes is None:probes=card_probes(target)
    if entry['name'] in EYE_CARDS:
        # Inside the eye a card only has to clear the pupil and eye white;
        # lashes and lids may cover it, so they are not probed.
        try:probes=card_probes(target,EYE_LABELS)
        except ValueError:pass
    elif entry['name'] in SKIN_EYE_CARDS:
        # A tear starts at the eye and runs over the cheek, so the skin must
        # still be cleared; lashes and brows may cover it.
        try:probes=card_probes(target,SKIN_EYE_LABELS)
        except ValueError:pass
    posed=Depth.push_front(posed,probes,margin=T.CLEARANCE,scale=width)
    # The hidden state must stay behind the same surface it was hidden by.
    rest=Depth.push_behind(rest,probes,margin=T.MARGIN*.5,scale=width)
    faces=[tuple(loop['index'] for loop in face) for face in entry['faces']]
    uvs=[np.array([loop['uv'] for loop in face],dtype=float) for face in entry['faces']]
    if not faces:raise ValueError('参考卡片缺少面：'+entry['name'])
    name=entry['name']
    posed=clear_posed_face(target,name,posed,faces,width)
    card=_object('EK_card_'+name,rest,faces,
                 _material('EK_card_'+name,texture,tuple(entry.get('tint',(1,1,1,1)))),collection)
    layer=card.data.uv_layers.new(name='UVMap')
    for polygon,uv in zip(card.data.polygons,uvs):
        if len(polygon.loop_indices)!=len(uv):
            raise ValueError('参考卡片面与 UV 数量不一致：'+name)
        for loop_index,(u,v) in zip(polygon.loop_indices,uv):
            layer.data[loop_index].uv=(float(u),float(v))
    card['ek_card_kind']='REFERENCE'
    card['ek_card_source']=entry.get('material','')
    card['ek_card_expressions']=json.dumps([name],ensure_ascii=False)
    card['ek_card_fit']=json.dumps(dict(show=posed.tolist(),hide=rest.tolist()),ensure_ascii=False)
    return card,posed


def reference_specs(library, skip=()):
    """Entries for every packaged card, minus the procedural ones."""
    if not library:return []
    return [dict(name=entry['name'],entry=entry)
            for entry in library['cards'] if entry['name'] not in set(skip)]


def commit(target, output):
    """Copy reviewed cards onto the original target and rebind their drivers.

    Batches accumulate: a card the new batch did not select (Basis only) leaves
    the earlier committed copy alone; a selected card replaces that copy.
    """
    copies=[]
    current=target.data.shape_keys
    earlier=[ob for ob in bpy.data.objects if ob.get(TAG) and ob.get('ek_card_owner')==target.name and ob.parent==target]
    for card in [ob for ob in output.children if ob.get(TAG)]:
        shown=card.data.shape_keys
        if not shown or len(shown.key_blocks)<2:continue
        base=card.name+'_写入'
        for old in [ob for ob in earlier if ob.name==base or ob.name.startswith(base+'.')]:
            earlier.remove(old);bpy.data.objects.remove(old,do_unlink=True)
        copy=card.copy();copy.data=card.data.copy();copy.name=base
        (target.users_collection[0] if target.users_collection else bpy.context.scene.collection).objects.link(copy)
        copy.parent=target
        # Cards were authored in world space; keep their placement when the
        # result and the target have different transforms.
        copy.matrix_parent_inverse=target.matrix_world.inverted()
        copy['ek_card_owner']=target.name
        keys=copy.data.shape_keys
        if keys and keys.animation_data:
            for curve in keys.animation_data.drivers:
                for variable in curve.driver.variables:
                    for driver_target in variable.targets:
                        if driver_target.id==output.data.shape_keys:
                            driver_target.id=target.data.shape_keys
        copies.append(copy)
    # Earlier cards still drive from the key block of the mesh that was replaced.
    if current:
        for old in earlier:
            old_keys=old.data.shape_keys
            if not old_keys or not old_keys.animation_data:continue
            for curve in old_keys.animation_data.drivers:
                for variable in curve.driver.variables:
                    for driver_target in variable.targets:
                        if isinstance(driver_target.id,bpy.types.Key) and driver_target.id!=current:
                            driver_target.id=current
    return copies
