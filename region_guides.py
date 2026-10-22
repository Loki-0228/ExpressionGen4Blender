"""Editable native curves and immutable, explicitly confirmed fit checkpoints."""
import hashlib
import json
import bpy
import numpy as np
from mathutils import Vector, Matrix
from mathutils.geometry import interpolate_bezier
from . import region_blender as A, region_contours as O, region_lashes as L, region_curve_fit as F

KINDS={'EYE_UPPER':'上眼睑轮廓','EYE_LOWER':'下眼睑轮廓',
       'LIP_UPPER':'上嘴唇','LIP_LOWER':'下嘴唇','BROW':'眉毛',
       'CREASE':'双眼皮线','LASH':'单根上睫毛','TONGUE':'舌头中心线','LASH_LINE':'上睫毛整带中线'}
KINDS['CUSTOM']='自定义识别曲线'
COLORS={'EYE_UPPER':(0,1,1,1),'EYE_LOWER':(1,1,1,1),
        'LIP_UPPER':(1,.05,.55,1),'LIP_LOWER':(.2,1,.15,1),
        'BROW':(1,1,0,1),'CREASE':(1,.4,.02,1),'LASH':(.65,1,0,1),'TONGUE':(1,.2,.5,1),'LASH_LINE':(.3,.65,1,1)}
COLORS['CUSTOM']=(1.,.55,.15,1.)


def dumps(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(dumps(value).encode()).hexdigest()


def deleted_keys(collection,persist=True):
    """An absent curve is intentional only if this collection created it."""
    known=json.loads(collection.get('ek_guide_generated_keys','{}'))
    present={ob.get('ek_guide_key') for ob in collection.all_objects if 'ek_guide_entry' in ob}
    deleted=set(json.loads(collection.get('ek_guide_deleted_keys','[]')))
    deleted.update(set(known)-present);deleted-=present
    if persist:collection['ek_guide_deleted_keys']=dumps(sorted(deleted))
    return known,deleted


def state_hash(collection,rows):
    _,deleted=deleted_keys(collection,persist=False)
    state=dict(entries=rows,deleted=sorted(deleted),
               process_lashes=bool(collection.get('ek_process_individual_lashes',True)))
    # Do not change hashes or implicitly opt old files into new ownership.
    if 'ek_accessory_policy' in collection:
        state['accessory_policy']=json.loads(collection['ek_accessory_policy'])
    return digest(state)


def organize_collection(collection, reset_visibility=True):
    """Organize generated guides under role/kind collections."""
    rows=[ob for ob in collection.all_objects if 'ek_guide_entry' in ob]
    for ob in rows:
        entry=json.loads(ob['ek_guide_entry']);role=entry['role'];kind=entry['kind']
        parent=next((c for c in collection.children if c.get('ek_guide_role')==role),None)
        if parent is None:
            parent=bpy.data.collections.new('源检查曲线' if role=='SOURCE' else '目标检查曲线')
            collection.children.link(parent);parent['ek_guide_role']=role;parent['ek_guide_owner']=collection
        child=next((c for c in parent.children if c.get('ek_guide_kind')==kind),None)
        if child is None:
            child=bpy.data.collections.new(KINDS[kind]);parent.children.link(child)
            child['ek_guide_kind']=kind;child['ek_guide_owner']=collection
        if ob.name not in child.objects:child.objects.link(ob)
        for previous in tuple(ob.users_collection):
            if previous!=child and (previous==collection or previous.get('ek_guide_owner')==collection):
                previous.objects.unlink(ob)
        if reset_visibility:
            ob.hide_viewport=False
            for layer in bpy.context.scene.view_layers:
                if layer.objects.get(ob.name)==ob:ob.hide_set(False,view_layer=layer)
    collection['ek_guide_visibility_version']=1
    return rows


def collection_visibility(collection,visible,view_layer=None,keep=None):
    """Use the collection eye switch; never hide its curve objects."""
    organize_collection(collection)
    layer=view_layer or bpy.context.view_layer
    def visit(node,inside=False):
        inside=inside or node.collection==collection
        if inside:
            node.exclude=False;node.collection.hide_viewport=False
            if node.collection==collection:node.hide_viewport=not visible
            else:node.hide_viewport=bool(visible and keep is not None and not any(ob in keep for ob in node.collection.all_objects))
        for child in node.children:visit(child,inside)
    visit(layer.layer_collection);layer.update()
    for ob in list(collection.all_objects):
        if 'ek_guide_entry' in ob and layer.objects.get(ob.name)==ob:ob.hide_set(False,view_layer=layer)


def focus_collections(context,keep):
    roots=[c for c in context.scene.collection.children_recursive if c.get('ek_guide_source') and c.get('ek_guide_target')]
    for collection in roots:
        rows=organize_collection(collection)
        wanted={ob for ob in rows if ob in keep}
        # A category is one visibility unit even when one curve is selected.
        for ob in tuple(wanted):
            for group in ob.users_collection:
                if group.get('ek_guide_owner')==collection:wanted.update(group.all_objects)
        keep.update(wanted)
        collection_visibility(collection,bool(wanted),context.view_layer,wanted)


def enforce_display(ob,target=None):
    if ob.type!='CURVE' or 'ek_guide_entry' not in ob:return
    kind=json.loads(ob['ek_guide_entry'])['kind'];color=COLORS[kind]
    ob.show_in_front=True;ob.hide_render=True;ob.color=color;ob.display_type='SOLID'
    if target:
        width=max((v.co.x for v in target.data.vertices),default=1)-min((v.co.x for v in target.data.vertices),default=0)
        ob.data.bevel_depth=max(width*.0025,1e-5);ob.data.bevel_resolution=2
    name='EK检查_高亮_'+kind
    material=bpy.data.materials.get(name) or bpy.data.materials.new(name)
    material.diffuse_color=color;material.use_nodes=True
    nodes=material.node_tree.nodes;shader=nodes.get('Emission')
    if shader is None:
        nodes.clear();shader=nodes.new('ShaderNodeEmission');output=nodes.new('ShaderNodeOutputMaterial')
        material.node_tree.links.new(shader.outputs[0],output.inputs['Surface'])
    shader.inputs['Color'].default_value=color;shader.inputs['Strength'].default_value=2.
    ob.data.materials.clear();ob.data.materials.append(material)


def apply_working_transforms(source,target,working_source=None):
    collection=find(source,target)
    source_bake=A.apply_working_transform(working_source,source=True) if working_source else Matrix.Identity(4)
    transform=A.apply_working_transform(target)
    alignment=source.matrix_world.copy() if source==working_source else A.source_alignment(working_source)
    changed_source=source==working_source and not np.allclose(np.array(source_bake),np.eye(4),atol=1e-9)
    changed_target=not np.allclose(np.array(transform),np.eye(4),atol=1e-9)
    if collection and (changed_source or changed_target):
        def converted(points):return [list(transform@Vector(p)) for p in points]
        for ob in list(collection.all_objects):
            if 'ek_guide_entry' not in ob:continue
            entry=json.loads(ob['ek_guide_entry']);entry['points']=converted(entry['points'])
            if entry.get('fit'):
                for name in ('points','left','right'):entry['fit'][name]=converted(entry['fit'][name])
            ob['ek_guide_entry']=dumps(entry)
            for name in ('ek_guide_base','ek_guide_generated','ek_eye_corner_previous'):
                if name in ob:ob[name]=dumps(converted(json.loads(ob[name])))
            enforce_display(ob,target)
        source_transform=transform@Matrix(json.loads(collection['ek_source_transform']))
        if changed_source:source_transform=source_transform@source_bake.inverted()
        collection['ek_source_transform']=dumps([list(r) for r in source_transform])
        collection['ek_guide_input']=fingerprint(source,target,alignment)
        collection['ek_guide_geometry']=fingerprint(source,target,alignment,include_regions=False)
        if 'ek_guide_snapshot' in collection:del collection['ek_guide_snapshot']
    return alignment


def fingerprint(source,target,alignment,include_regions=True):
    from .region_transfer import mesh_regions
    rows=[]
    for ob in (source,target):
        points=ob.data.shape_keys.reference_key.data if ob.data.shape_keys else ob.data.vertices
        rows.append(dict(points=[list(v.co) for v in points],
            faces=[list(p.vertices) for p in ob.data.polygons],
            labels=mesh_regions(ob) if include_regions else [],matrix=[list(r) for r in ob.matrix_world]))
    rows.append([list(r) for r in (alignment if alignment is not None else source.matrix_world)])
    return digest(rows)


def find(source,target):
    candidates=[c for c in bpy.data.collections if c.get('ek_guide_source')==source
                and c.get('ek_guide_target')==target]
    return max(candidates,key=lambda c:c.get('ek_guide_generation',0),default=None)


def guide_owner(ob):
    return next((c.get('ek_guide_owner') or c for c in ob.users_collection
                 if (c.get('ek_guide_owner') or c).get('ek_guide_source')),None)


def reference_transform(ob,target):
    """Displayed world coordinates to the shared fitting coordinate system."""
    collection=guide_owner(ob)
    if ob.get('ek_guide_source_space') and collection:
        return Matrix(json.loads(collection['ek_source_transform']))@collection['ek_guide_source'].matrix_world.inverted()
    return target.matrix_world.inverted()


def show_source_space(collection,target):
    source=collection.get('ek_guide_source')
    if not source:return
    fitted_to_world=source.matrix_world@Matrix(json.loads(collection['ek_source_transform'])).inverted()
    for ob in list(collection.all_objects):
        if json.loads(ob.get('ek_guide_entry','{}')).get('role')!='SOURCE' or ob.get('ek_guide_source_space'):continue
        # Move only the display frame; fitting samples stay exactly unchanged.
        ob.matrix_world=fitted_to_world@target.matrix_world.inverted()@ob.matrix_world
        ob['ek_guide_source_space']=True
    bpy.context.view_layer.update()


def curve_points(ob,target):
    if ob.type!='CURVE' or len(ob.data.splines)!=1:
        raise ValueError('检查曲线必须保留一条样条：'+ob.name)
    spline=ob.data.splines[0];transform=reference_transform(ob,target)@ob.matrix_world
    if spline.use_cyclic_u:raise ValueError('上下轮廓和单根睫毛须为开放曲线：'+ob.name)
    if spline.type=='BEZIER':
        pts=spline.bezier_points;values=[]
        for a,b in zip(pts,pts[1:]):
            values.extend(interpolate_bezier(a.co,a.handle_right,b.handle_left,b.co,9)[:-1])
        if pts:values.append(pts[-1].co)
    elif spline.type=='POLY':values=[Vector(p.co[:3]) for p in spline.points]
    else:raise ValueError('检查曲线支持贝塞尔或多段线，请转换后确认：'+ob.name)
    values=[list(transform@p) for p in values]
    if len(values)<2 or not np.isfinite(values).all() or np.linalg.norm(np.diff(values,axis=0),axis=1).sum()<1e-10:
        raise ValueError('曲线需要至少两个不同的有效控制点：'+ob.name)
    return values


def sample(points,u):
    points=np.asarray(points);lengths=np.r_[0,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
    t=float(np.clip(u,0,1))*lengths[-1]
    k=min(max(int(np.searchsorted(lengths,t,side='right'))-1,0),len(points)-2)
    return Vector(points[k]+(points[k+1]-points[k])*((t-lengths[k])/max(lengths[k+1]-lengths[k],1e-15)))


def smooth_curve(ob):
    if ob.type!='CURVE' or len(ob.data.splines)!=1 or ob.data.splines[0].type!='BEZIER':
        raise ValueError('平滑功能需要一条贝塞尔检查曲线')
    spline=ob.data.splines[0]
    for point in spline.bezier_points:
        point.handle_left_type='AUTO';point.handle_right_type='AUTO'
    spline.resolution_u=24;ob.data.resolution_u=24
    ob.show_in_front=True;ob['ek_smooth_version']=1
    bpy.context.view_layer.update()


def set_curve_shape(ob,target,entry):
    ob.data.splines.clear()
    spline=ob.data.splines.new('BEZIER');spline.bezier_points.add(len(entry['points'])-1)
    for point,co in zip(spline.bezier_points,entry['points']):
        point.co=co;point.handle_left_type='VECTOR';point.handle_right_type='VECTOR'
    ob.matrix_world=target.matrix_world.copy();ob['ek_guide_source_space']=False;ob['ek_guide_entry']=dumps(entry)
    bpy.context.view_layer.update()
    ob['ek_guide_base']=dumps(curve_points(ob,target))
    fit=entry.get('fit')
    if fit:
        ob.data.splines.clear();spline=ob.data.splines.new('BEZIER')
        spline.bezier_points.add(len(fit['points'])-1)
        for p,co,left,right in zip(spline.bezier_points,fit['points'],fit['left'],fit['right']):
            p.co=co;p.handle_left_type='FREE';p.handle_right_type='FREE'
            p.handle_left=left;p.handle_right=right
        spline.resolution_u=24;ob.data.resolution_u=24
        ob['ek_curve_fit_version']=F.VERSION;ob['ek_smooth_version']=1;ob.show_in_front=True
        bpy.context.view_layer.update()
    else:smooth_curve(ob)
    ob['ek_guide_generated']=dumps(curve_points(ob,target))


def edited(ob,target):
    generated=json.loads(ob['ek_guide_generated'])
    points=curve_points(ob,target)
    return len(generated)!=len(points) or not np.allclose(generated,points,atol=1e-8,rtol=0)


def add_curve(collection,target,entry):
    role='源' if entry['role']=='SOURCE' else '目标'
    side=('X正侧' if entry['side']>0 else 'X负侧') if entry['side'] else ''
    name='EK检查_%s_%s_%s_%s'%(role,side,KINDS[entry['kind']],entry['key'].split(':')[-1])
    data=bpy.data.curves.new(name,'CURVE');data.dimensions='3D';data.resolution_u=8
    ob=bpy.data.objects.new(name,data);collection.objects.link(ob);ob.matrix_world=target.matrix_world.copy()
    ob[A.TAG]=True;ob['ek_guide_key']=entry['key'];ob['ek_guide_entry']=dumps(entry)
    ob.show_in_front=True;ob.hide_render=True;ob.color=COLORS[entry['kind']]
    data.bevel_depth=max(collection.get('ek_guide_width',.1)*.001,1e-6);data.bevel_resolution=0
    material=bpy.data.materials.get('EK检查_'+entry['kind']) or bpy.data.materials.new('EK检查_'+entry['kind'])
    material.diffuse_color=ob.color;data.materials.append(material)
    set_curve_shape(ob,target,entry)
    enforce_display(ob,target)
    return ob


def capture(source,target,alignment,entries,source_transform,retire_lashes=False,preserve_shapes=False):
    stamp=fingerprint(source,target,alignment);collection=find(source,target)
    geometry=fingerprint(source,target,alignment,include_regions=False)
    refresh=collection is not None and collection.get('ek_guide_input')!=stamp
    keep_edits=refresh and collection.get('ek_guide_geometry')==geometry
    if collection is None or (refresh and not keep_edits):
        generation=collection.get('ek_guide_generation',0)+1 if collection else 1
        if collection:
            collection_visibility(collection,False)
        collection=bpy.data.collections.new('EK_轮廓检查');bpy.context.scene.collection.children.link(collection)
        collection['ek_guide_source']=source;collection['ek_guide_target']=target
        collection['ek_guide_generation']=generation;collection['ek_guide_input']=stamp
        collection['ek_source_transform']=dumps([list(r) for r in source_transform])
        collection['ek_guide_width']=max((v.co.x for v in target.data.vertices),default=1)-min((v.co.x for v in target.data.vertices),default=0)
    collection['ek_guide_input']=stamp;collection['ek_guide_geometry']=geometry
    from .region_transfer import mesh_regions
    collection['ek_guide_partition_state']=digest(mesh_regions(target))
    existing={json.loads(ob['ek_guide_entry'])['key']:ob for ob in authoritative_objects(collection,target)}
    known,deleted=deleted_keys(collection)
    accessory_kinds={'LASH','BROW','CREASE'}
    if retire_lashes or preserve_shapes:
        # Edited curves describe an artist's ownership decision. Keep that
        # decision when automatic classification changes on the same surface.
        authored=[json.loads(ob['ek_guide_entry']) for ob in existing.values()
                  if is_active(ob) and (json.loads(ob['ek_guide_entry']).get('manual') or edited(ob,target))]
        refreshed=[]
        for entry in entries:
            if entry['kind'] in accessory_kinds|{'LASH_LINE'}:
                kind='LASH' if entry['kind']=='LASH_LINE' else entry['kind']
                vertices=set(entry.get('vertices',[]))
                # A strand may be re-enumerated or gain/lose a few vertices.
                # It still cannot share ownership with an authored strand.
                # The band's ordinary overlap with its own strands is valid.
                protected={i for old in authored if old['role']==entry['role']
                           and old['kind'] in accessory_kinds
                           and (old['kind']!=kind or
                                (entry['kind']!='LASH_LINE' and
                                 not (old['key']==entry['key'] and
                                      set(old.get('vertices',[]))==vertices)))
                           for i in old.get('vertices',[])}
                if protected & vertices:
                    if kind=='LASH' and entry['kind']!='LASH_LINE':continue
                    entry=dict(entry,vertices=[i for i in entry['vertices'] if i not in protected])
                if entry['kind']=='LASH_LINE':
                    entry=dict(entry,lower_vertices=[i for i in entry.get('lower_vertices',[]) if i not in protected])
                if not entry.get('vertices') and not entry.get('lower_vertices'):continue
            refreshed.append(entry)
        entries=refreshed
        # Component enumeration can reuse a key for a different mesh island.
        # Preserve an edited old island under its own identity, never apply
        # its old control points to the new island merely because keys match.
        for entry in entries:
            key=entry['key'];ob=existing.get(key)
            if ob is None or entry['kind'] not in accessory_kinds:continue
            previous=json.loads(ob['ek_guide_entry'])
            if set(previous.get('vertices',[]))==set(entry.get('vertices',[])):continue
            if previous.get('manual') or edited(ob,target):
                retained=key+':retained:'+digest(previous.get('vertices',[]))[:12]
                previous['key']=retained
                ob['ek_guide_key']=retained;ob['ek_guide_entry']=dumps(previous)
                existing[retained]=existing.pop(key);known.pop(key,None)
    incoming_keys={entry['key'] for entry in entries}
    if retire_lashes:
        for key,ob in existing.items():
            previous=json.loads(ob.get('ek_guide_entry','{}'))
            if previous.get('kind') not in accessory_kinds or previous.get('manual') or ':manual' in str(key):continue
            if key not in incoming_keys and is_active(ob) and not edited(ob,target):
                ob['ek_auto_inactive']=True
            elif key in incoming_keys and ob.get('ek_auto_inactive'):
                del ob['ek_auto_inactive']
    created=[]
    for entry in entries:
        if entry['key'] in deleted:continue
        if entry['key'] not in existing:
            # Geometric reclassification may move a strip from brow to crease.
            # Keep the user's geometry and enabled state, with one guide per strip.
            same=None
            if entry['kind'] in accessory_kinds and entry.get('vertices'):
                for old_key,candidate in list(existing.items()):
                    if old_key in incoming_keys:continue
                    previous=json.loads(candidate.get('ek_guide_entry','{}'))
                    compatible=(previous.get('kind')==entry['kind'] or
                                {previous.get('kind'),entry['kind']}<={'BROW','CREASE'})
                    if (previous.get('role')==entry['role'] and compatible
                            and set(previous.get('vertices',[]))==set(entry['vertices'])):
                        same=candidate;break
            if same:
                changed=edited(same,target)
                if same.get('ek_auto_inactive'):del same['ek_auto_inactive']
                if preserve_shapes:
                    previous=json.loads(same['ek_guide_entry'])
                    entry=dict(previous,**{k:entry[k] for k in ('key','kind','side','vertices')})
                same['ek_guide_key']=entry['key'];same['ek_guide_entry']=dumps(entry)
                if entry['kind'] in ('BROW','CREASE'):
                    same.name=same.name.replace(KINDS['BROW' if entry['kind']=='CREASE' else 'CREASE'],KINDS[entry['kind']])
                same.color=COLORS[entry['kind']]
                if not changed and not preserve_shapes:set_curve_shape(same,target,entry)
                known.pop(old_key,None)
                existing[entry['key']]=same
            else:created.append(add_curve(collection,target,entry))
        else:
            ob=existing[entry['key']]
            previous=json.loads(ob.get('ek_guide_entry','{}'))
            changed=edited(ob,target)
            if preserve_shapes:
                # Generation consumes the current control points as rules.
                # Detection may refresh ownership, never replace their shape.
                for key in ('vertices','lower_vertices','band_vertices','binding'):
                    if key in entry:previous[key]=entry[key]
                ob['ek_guide_entry']=dumps(previous)
            elif not changed and (keep_edits or previous!=entry):set_curve_shape(ob,target,entry)
            elif changed and entry['kind'] in ('LIP_UPPER','LIP_LOWER'):
                # Explicit redetection updates mesh ownership while retaining
                # the artist's curve shape. Generation consumes these IDs.
                for key in ('vertices','binding'):previous[key]=entry[key]
                ob['ek_guide_entry']=dumps(previous)
            elif (changed and entry['kind']=='LASH' and
                  set(previous.get('vertices',[]))==set(entry.get('vertices',[]))):
                # Refresh membership after partition edits; retain edited endpoints.
                previous['band_vertices']=entry.get('band_vertices',[])
                ob['ek_guide_entry']=dumps(previous)
            elif changed and entry['kind']=='LASH_LINE':
                previous['vertices']=entry.get('vertices',[])
                previous['lower_vertices']=entry.get('lower_vertices',[])
                ob['ek_guide_entry']=dumps(previous)
    for ob in collection.all_objects:
        if 'ek_guide_entry' not in ob:continue
        entry=json.loads(ob['ek_guide_entry'])
        known[entry['key']]={key:entry[key] for key in ('key','role','kind','side')}
    collection['ek_guide_generated_keys']=dumps(known)
    collection['ek_guide_deleted_keys']=dumps(sorted(deleted))
    bpy.context.view_layer.update()
    for ob in list(collection.all_objects):
        if ob.type!='CURVE' or 'ek_guide_entry' not in ob:continue
        enforce_display(ob,target)
    collection['ek_guide_required']=dumps([e['key'] for e in (json.loads(o['ek_guide_entry']) for o in collection.all_objects if 'ek_guide_entry' in o)
                                         if e['kind'].startswith(('EYE_','LIP_'))])
    collection['ek_curve_fit_version']=F.VERSION
    sync_eye_corners(collection,target,{e['role'] for e in entries})
    organize_collection(collection)
    show_source_space(collection,target)
    if 'ek_guide_needs_refresh' in collection:del collection['ek_guide_needs_refresh']
    return collection,dict(curves=len(collection.all_objects),created=len(created),deleted=len(deleted),
        source_curves=sum(json.loads(ob['ek_guide_entry'])['role']=='SOURCE' for ob in collection.all_objects if 'ek_guide_entry' in ob),
        target_curves=sum(json.loads(ob['ek_guide_entry'])['role']=='TARGET' for ob in collection.all_objects if 'ek_guide_entry' in ob),
        individual_lashes=sum(json.loads(ob['ek_guide_entry'])['kind']=='LASH' for ob in collection.all_objects if 'ek_guide_entry' in ob))


def is_active(ob):
    # Authored correction curves always participate. Only obsolete automatic
    # strands or marks explicitly superseded by a manual strand are excluded.
    return not (ob.get('ek_auto_inactive',False) or ob.get('ek_superseded',False))


def authoritative_objects(collection,target,persist=False):
    groups={}
    active=getattr(bpy.context,'object',None)
    settings=getattr(getattr(bpy.context,'scene',None),'exprkit_regions',None)
    selected=settings.guide_selected if settings else None
    for ob in collection.all_objects:
        if 'ek_guide_entry' not in ob or ob.get('ek_expression_curve'):continue
        entry=json.loads(ob['ek_guide_entry']);groups.setdefault(entry['key'],[]).append(ob)
    remembered=json.loads(collection.get('ek_guide_authority','{}'))
    def priority(ob):
        try:changed=edited(ob,target)
        except (KeyError,ValueError):changed=False
        return (is_active(ob),float(ob.get('ek_curve_edit_time',0)),changed,
                ob.name==remembered.get(json.loads(ob['ek_guide_entry'])['key']),
                ob==active,ob==selected,-len(ob.name),ob.name)
    chosen=[max(objects,key=priority) for key,objects in sorted(groups.items())]
    if persist:
        collection['ek_guide_authority']=dumps({json.loads(ob['ek_guide_entry'])['key']:ob.name for ob in chosen})
    return chosen


def current(collection,target):
    rows=[]
    for ob in authoritative_objects(collection,target):
        if 'ek_guide_entry' not in ob:continue
        entry=json.loads(ob['ek_guide_entry']);entry['enabled']=is_active(ob)
        entry['points']=curve_points(ob,target);entry['base']=json.loads(ob['ek_guide_base'])
        rows.append(entry)
    return sorted(rows,key=lambda row:row['key'])


def sync_eye_corners(collection,target,roles=None):
    """Join upper/lower guides at two shared corners without changing the arc.

    Use the endpoint edited since the last synchronization. If both endpoints
    were moved, meet halfway. Stored positions are in target-local space.
    """
    groups={}
    for ob in authoritative_objects(collection,target):
        entry=json.loads(ob.get('ek_guide_entry','{}'))
        if entry.get('kind') not in ('EYE_UPPER','EYE_LOWER') or not is_active(ob):continue
        if roles is not None and entry.get('role') not in roles:continue
        groups.setdefault((entry['role'],entry['side']),{}).setdefault(entry['kind'],[]).append(ob)
    changed=False
    for group in groups.values():
        if any(len(group.get(kind,[]))!=1 for kind in ('EYE_UPPER','EYE_LOWER')):continue
        objects=[group[kind][0] for kind in ('EYE_UPPER','EYE_LOWER')]
        ends=[];previous=[]
        for ob in objects:
            points=curve_points(ob,target);ends.append(np.array([points[0],points[-1]]))
            baseline=json.loads(ob.get('ek_eye_corner_previous',ob['ek_guide_generated']))
            previous.append(np.array([baseline[0],baseline[-1]]))
        joint=[]
        for end in (0,1):
            moved=[not np.allclose(ends[k][end],previous[k][end],atol=1e-8,rtol=0) for k in (0,1)]
            p=ends[0][end] if moved==[True,False] else ends[1][end] if moved==[False,True] else (ends[0][end]+ends[1][end])/2
            joint.append(p.tolist())
            for k,ob in enumerate(objects):
                if np.allclose(ends[k][end],p,atol=1e-9,rtol=0):continue
                spline=ob.data.splines[0];index=0 if end==0 else -1
                co=(reference_transform(ob,target)@ob.matrix_world).inverted()@Vector(p)
                if spline.type=='BEZIER':
                    point=spline.bezier_points[index];delta=co-point.co
                    left=point.handle_left+delta;right=point.handle_right+delta
                    point.co=co;point.handle_left=left;point.handle_right=right
                else:
                    point=spline.points[index];point.co=(*co,point.co.w)
                changed=True
        for ob in objects:ob['ek_eye_corner_previous']=dumps(joint)
    if changed:bpy.context.view_layer.update()
    return changed


def confirm(collection,source,target,alignment):
    if not collection or collection.get('ek_guide_input')!=fingerprint(source,target,alignment):
        raise ValueError('模型、分区或对齐已变化，请重新生成检查曲线；旧曲线会保留')
    authoritative_objects(collection,target,persist=True)
    sync_eye_corners(collection,target)
    rows=current(collection,target);active={e['key'] for e in rows if e['enabled']}
    for entry in rows:
        if entry['kind']=='LASH' and entry['enabled'] and np.linalg.norm(np.subtract(entry['points'][0],entry['points'][-1]))<1e-10:
            raise ValueError('单根睫毛的根部和尖端不能重合：'+entry['key'])
    known,deleted=deleted_keys(collection)
    suppressed=[known[key] for key in sorted(deleted) if key in known]
    suppressed.extend({key:e[key] for key in ('key','role','kind','side')} for e in rows if not e['enabled'])
    snapshot=dict(entries=rows,suppressed=suppressed,input=collection['ek_guide_input'],revision=collection.get('ek_guide_revision',0)+1,
                  process_lashes=bool(collection.get('ek_process_individual_lashes',True)))
    if 'ek_accessory_policy' in collection:
        snapshot['accessory_policy']=json.loads(collection['ek_accessory_policy'])
    snapshot['hash']=state_hash(collection,rows);collection['ek_guide_snapshot']=dumps(snapshot)
    collection['ek_guide_revision']=snapshot['revision']
    if 'ek_guide_needs_refresh' in collection:del collection['ek_guide_needs_refresh']
    return snapshot


def confirmed(collection,source,target,alignment):
    if not collection or 'ek_guide_snapshot' not in collection:raise ValueError('请先生成检查曲线并执行贴合')
    snapshot=json.loads(collection['ek_guide_snapshot'])
    if snapshot['input']!=fingerprint(source,target,alignment):raise ValueError('模型或分区已变化，下一次贴合会自动更新')
    if snapshot['hash']!=state_hash(collection,current(collection,target)):raise ValueError('曲线已修改，下一次贴合或迁移会自动读取')
    return snapshot


def checkpoint(collection,source,target,alignment):
    """Capture current edits in memory; no separate user save action is needed."""
    if not collection or collection.get('ek_guide_input')!=fingerprint(source,target,alignment):
        raise ValueError('模型或分区已变化，请更新检查曲线')
    sync_eye_corners(collection,target)
    snapshot=json.loads(collection.get('ek_guide_snapshot','{}'))
    if snapshot.get('hash')==state_hash(collection,current(collection,target)) and snapshot.get('input')==collection['ek_guide_input']:
        return snapshot
    return confirm(collection,source,target,alignment)


def entries_for(snapshot,role,kind,side):
    return [e for e in (snapshot or {}).get('entries',[]) if e.get('enabled',True)
            and e['role']==role and e['kind']==kind and e['side']==side]


def adjust_ring(points,role,kind,side,snapshot):
    if not snapshot:return points
    ring=O.EyeRing(points) if kind=='EYE' else O.LipRing(points)
    result=[]
    for j,p in enumerate(points):
        u,upper=ring.parameter(j);entries=entries_for(snapshot,role,kind+('_UPPER' if upper else '_LOWER'),side)
        delta=Vector()
        if entries:
            entry=entries[0];delta=sample(entry['points'],u)-sample(entry['base'],u)
        result.append(p+delta)
    return result


def supported_band_vertices(entries,ownership):
    """Keep an unedited, seam-connected piece of a covering card in its band.

    Ownership components weld shared edges, never isolated coincident tips.
    A manual strand control still wins as soon as its curve is edited.
    """
    bands=[set(r['vertices']) for r in ownership['components']
           if r.get('reason')=='eyelid_surface_support' and r.get('surface_upper')]
    result=set()
    for e in entries:
        if e.get('kind')!='LASH' or not e.get('manual') or not e.get('enabled',True):continue
        if e.get('_edited',False):continue
        if 'base' in e and (np.shape(e['base'])!=np.shape(e['points']) or
                not np.allclose(e['base'],e['points'],atol=1e-8,rtol=0)):continue
        ids=set(e['vertices'])
        if any(ids<band and len(band-ids)>=3 for band in bands):result.update(ids)
    return result


def units(snapshot,role,default,points=None,rings=None):
    if not snapshot:return default
    result=[]
    for entry in snapshot['entries']:
        if entry['role']!=role or entry['kind']!='LASH' or not entry.get('enabled',True):continue
        unit={key:entry[key] for key in ('side','u','vertices','roots','tips','connected')}
        unit['band_vertices']=entry.get('band_vertices',[])
        unit['points']=[entry['points'][0],entry['points'][-1]]
        unit['base']=[entry['base'][0],entry['base'][-1]]
        if points is not None and not np.allclose(unit['points'],[entry['base'][0],entry['base'][-1]],atol=1e-7,rtol=0):
            count=max(1,len(unit['vertices'])//5)
            for group,p in zip(('roots','tips'),unit['points']):
                unit[group]=sorted(unit['vertices'],key=lambda i:(Vector(points[i])-Vector(p)).length_squared)[:count]
            if rings and unit['side'] in rings:unit['u']=rings[unit['side']].locate(Vector(unit['points'][0]),True)[0]
        result.append(unit)
    return result


def detection_entries(prefit,target_points,source_polygons,target_polygons,source_parts,target_parts,
                      source_plane,target_plane,source_eye_rings,target_eye_rings,source_mouth,target_mouth,source_motion=None,
                      source_labels=None,target_labels=None,detect_lashes=True,marked_lashes=None,
                      source_ownership=None,target_ownership=None):
    entries=[];lash_units={}
    for role,points,polygons,parts,plane,eyes,mouth in (
        ('SOURCE',prefit,source_polygons,source_parts,source_plane,source_eye_rings,source_mouth),
        ('TARGET',target_points,target_polygons,target_parts,target_plane,target_eye_rings,target_mouth)):
        # Identical geometric accessory detection on source and target.
        from . import region_core as C
        parts=list(parts);labels=source_labels if role=='SOURCE' else target_labels
        skin=[face for face,label in zip(polygons,labels or []) if label==0];skin_creases=set()
        _,islands=C.topology(skin)
        biggest=max((len(c['faces']) for c in islands),default=0)
        for island in islands:
            if len(island['faces'])>=max(biggest*.2,20):continue
            ids=sorted({i for f in island['faces'] for i in skin[f]});cloud=np.array([points[i] for i in ids]);center=cloud.mean(0)
            side=1 if center[0]>=plane else -1;eye=eyes.get(side)
            if eye is None:continue
            offset=center[2]-eye.sample(eye.locate(Vector(center),True)[0],True).z
            if np.ptp(cloud[:,0])<eye.frame.width*1.4 and np.ptp(cloud[:,2])<eye.frame.height*.5 and 0<offset<eye.frame.height*.6:
                for i in ids:parts[i]=2
                skin_creases.update(ids)
        from . import region_accessories as Accessories
        ownership=source_ownership if role=='SOURCE' else target_ownership
        if ownership is None:
            candidates=polygons if labels is None else [face for face,label in zip(polygons,labels) if label==2]
            ownership=Accessories.resolve(points,candidates,
                [0 if i in skin_creases else part for i,part in enumerate(parts)],plane,eyes)
        parts=list(ownership['parts'])
        for i in skin_creases:parts[i]=2
        manual_units=[e for e in (marked_lashes or []) if e.get('role')==role
                      and e.get('enabled',True) and e.get('manual')]
        manual_ids={i for e in manual_units for i in e['vertices']}
        for i in manual_ids:
            if 0<=i<len(parts):parts[i]=1
        owner_by_vertex={i:row for row in ownership['components'] for i in row['vertices']}
        rings=[('EYE',s,r) for s,r in eyes.items()]
        if mouth:rings.append(('LIP',0,mouth if isinstance(mouth,O.LipRing) else O.LipRing(mouth,surface=(points,polygons,labels) if labels is not None else None)))
        lookup={id(point):i for i,point in enumerate(points)}
        for kind,side,ring in rings:
            for upper in (True,False):
                name=kind+('_UPPER' if upper else '_LOWER')
                entry=dict(key='%s:%s:%d'%(role,name,side),role=role,kind=name,side=side,
                    points=[list(ring.sample(u,upper)) for u in np.linspace(0,1,65)])
                if kind=='LIP':
                    entry.update(vertices=[lookup[id(ring.points[i])] for i in ring.chains[upper]],binding='face_topology_v1')
                entries.append(entry)
        units=L.detect(points,polygons,parts,plane,eyes,ownership=ownership) if detect_lashes else []
        units=[unit for unit in units if not set(unit['vertices'])&manual_ids]
        lash_units[role]=units
        band_units=units+manual_units if detect_lashes else [e for e in (marked_lashes or []) if e['role']==role and e.get('enabled',True)]
        strands={i for unit in band_units for i in unit['vertices'] if i not in unit.get('band_vertices',[])}
        strands-=supported_band_vertices(band_units,ownership)
        for side,eye in eyes.items():
            band=[]
            upper_ids=L.upper_band_vertices(points,polygons,parts,plane,eye,side)
            for face in polygons:
                if all(i in upper_ids for i in face) and not all(i in strands for i in face):band.append(face)
            line=F.strip_centerline(points,band,side=side)
            if len(line)<3 and upper_ids:
                offsets=[np.asarray(points[i])-np.asarray(eye.sample(eye.locate(points[i],True)[0],True)) for i in upper_ids]
                offset=np.median(offsets,axis=0)
                line=[(np.asarray(eye.sample(u,True))+offset).tolist() for u in np.linspace(0,1,65)]
            if len(line)>=3:
                lower_ids={i for i,part in enumerate(parts) if part==1 and (1 if points[i].x>=plane else -1)==side}-upper_ids
                entries.append(dict(key='%s:LASH_LINE:%d'%(role,side),role=role,kind='LASH_LINE',side=side,
                                     points=line,vertices=sorted(upper_ids),lower_vertices=sorted(lower_ids)))
        for number,unit in enumerate(units):
            entries.append(dict(unit,key='%s:LASH:%d:%d'%(role,unit['side'],number),role=role,kind='LASH'))
        # Separate detached crease/brow strips; their editable center curves
        # describe independent surfaces, not a shared lash/brow bounding box.
        faces=[p for p in polygons if all(parts[i]==2 for i in p)]
        from . import region_core as C
        _,components=C.topology(faces)
        for number,component in enumerate(components):
            ids=sorted({i for f in component['faces'] for i in faces[f]});cloud=[points[i] for i in ids]
            side=1 if np.mean([p.x for p in cloud])>=plane else -1
            ring=eyes.get(side)
            if ring is None:continue
            component_faces=[faces[f] for f in component['faces']]
            line=F.strip_centerline(points,component_faces,side=side)
            if len(line)<2:continue
            offsets=[p[2]-ring.sample(ring.locate(Vector(p),True)[0],True).z for p in line]
            # A detached Face strip already identified above the upper lid
            # must not become a brow solely because one end sits higher.
            kind='CREASE' if set(ids)<=skin_creases or np.median(offsets)<ring.frame.height*.2 else 'BROW'
            owners=[owner_by_vertex[i] for i in ids if i in owner_by_vertex]
            if owners and all(row['kind']==owners[0]['kind'] for row in owners) and owners[0]['kind'] in ('BROW','CREASE'):
                kind=owners[0]['kind']
            # Shape-key motion is deliberately excluded from classification.
            # Keep source_motion in the signature for older script callers.
            evidence=None
            if len(line)>1:entries.append(dict(key='%s:%s:%d:%d'%(role,kind,side,number),
                role=role,kind=kind,side=side,points=line,vertices=ids,motion_evidence=evidence,
                binding='accessory_attachment_v1',parent_component=owners[0]['parent'] if owners else None))
    for entry in entries:
        fit=F.fit(entry['points'],entry['kind'])
        if fit:entry['fit']=fit
    return entries,lash_units


def manual_lash(collection,source,target,role,indices):
    ob=source if role=='SOURCE' else target
    if not indices:raise ValueError('请在网格编辑模式选择属于同一根上睫毛的面')
    from .region_transfer import mesh_regions
    labels=mesh_regions(ob)
    if any(labels[i]!=2 for i in indices):raise ValueError('单根睫毛只能选眉睫分区内的面')
    ids=sorted({i for f in indices for i in ob.data.polygons[f].vertices})
    transform=Matrix(json.loads(collection['ek_source_transform'])) if role=='SOURCE' else Matrix.Identity(4)
    data=ob.data.shape_keys.reference_key.data if ob.data.shape_keys else ob.data.vertices
    points=[transform@v.co for v in data];rows=current(collection,target)
    rings={}
    for side in (-1,1):
        upper=next((r for r in rows if r['role']==role and r['kind']=='EYE_UPPER' and r['side']==side),None)
        lower=next((r for r in rows if r['role']==role and r['kind']=='EYE_LOWER' and r['side']==side),None)
        if upper and lower:rings[side]=O.EyeRing([Vector(p) for p in upper['points']]+[Vector(p) for p in lower['points'][-2:0:-1]])
    if not rings:raise ValueError('请先生成该模型的上下眼睑轮廓')
    center=sum((points[i] for i in ids),Vector())/len(ids)
    side=min(rings,key=lambda s:(rings[s].sample(.5,True)-center).length)
    if not rings[side].locate(center)[1]:raise ValueError('所选面靠近下眼睑，请只选择单根上睫毛')
    unit=L.describe(points,ids,rings[side],side)
    shared={i for p in ob.data.polygons if p.index not in indices and labels[p.index]==2 for i in p.vertices}&set(ids)
    unit['connected']=bool(shared)
    unit['band_vertices']=sorted(shared)
    # Manual assignment wins; overlapping automatic units remain visible but disabled.
    for guide in list(collection.all_objects):
        row=json.loads(guide.get('ek_guide_entry','{}'))
        if row.get('role')==role and row.get('kind')=='LASH' and set(row['vertices'])&set(ids):guide['ek_superseded']=True
    number=collection.get('ek_manual_lashes',0)+1;collection['ek_manual_lashes']=number
    entry=dict(unit,key='%s:LASH:manual%d'%(role,number),role=role,kind='LASH',manual=True)
    guide=add_curve(collection,target,entry);bpy.context.view_layer.update()
    guide['ek_guide_base']=dumps(curve_points(guide,target))
    known,deleted=deleted_keys(collection)
    known[entry['key']]={key:entry[key] for key in ('key','role','kind','side')}
    collection['ek_guide_generated_keys']=dumps(known)
    organize_collection(collection,reset_visibility=False)
    show_source_space(collection,target)
    return guide
