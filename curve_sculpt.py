"""Temporary joined ribbons; explicit source bindings survive material changes."""
import colorsys,json,time
import bpy
import numpy as np
from mathutils import Vector
from . import region_guides as G,expression_authoring as Author,region_session as S

TAG='ek_curve_sculpt'


def source(context):
    ob=context.object
    if ob and ob.type=='CURVE' and 'ek_guide_entry' in ob:return ob
    return context.scene.exprkit_regions.guide_selected


def current(context):
    ob=context.object
    return ob if ob and ob.type=='MESH' and ob.get(TAG) else context.scene.exprkit_rules.sculpt_object


def create(context):
    settings=context.scene.exprkit_rules
    if settings.sculpt_object:raise ValueError('已有编辑面片，请先写回或取消编辑')
    selected=source(context);group=Author.owner(selected) if selected else None
    if not group:raise ValueError('请先选择校正曲线或表情曲线副本')
    target=group['ek_guide_target']
    if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    curves=[o for o in group.all_objects if o.type=='CURVE' and 'ek_guide_entry' in o]
    curves=[o for o in curves if (o.select_get() if settings.sculpt_scope=='SELECTED' else o.visible_get())]
    curves.sort(key=lambda o:o.name)
    if not curves:raise ValueError('当前范围中没有可编辑曲线')
    along=settings.sculpt_along;across=settings.sculpt_across
    if len(curves)*(along+1)*(across+1)>2000000:raise ValueError('面片顶点过多，请减少细分或选中较少曲线')
    width=max(np.ptp([v.co.x for v in target.data.vertices]),1e-6)*settings.sculpt_width
    vertices=[];faces=[];face_materials=[];bindings=[];records=[]
    for index,ob in enumerate(curves):
        points=G.curve_points(ob,target)
        centers=np.array([G.sample(points,t) for t in np.linspace(0,1,along+1)])
        tangent=np.gradient(centers,axis=0)
        normals=np.cross(tangent,np.array([0.,-1.,0.]))
        bad=np.linalg.norm(normals,axis=1)<1e-12
        normals[bad]=np.cross(tangent[bad],np.array([0.,0.,1.]))
        if np.any(np.linalg.norm(normals,axis=1)<1e-12):raise ValueError('曲线包含无法展开的重合段：'+ob.name)
        normals/=np.linalg.norm(normals,axis=1)[:,None]
        for row in range(1,len(normals)):
            if normals[row]@normals[row-1]<0:normals[row]*=-1
        start=len(vertices)
        for row,center in enumerate(centers):
            for col,u in enumerate(np.linspace(-.5,.5,across+1)):
                vertices.append(center+normals[row]*width*u);bindings.append((index,row,col))
        for row in range(along):
            for col in range(across):
                a=start+row*(across+1)+col
                faces.append((a,a+1,a+across+2,a+across+1));face_materials.append(index)
        records.append(dict(source=index,entry=ob['ek_guide_entry'],stamp=G.digest(points),hidden=ob.hide_get()))
    mesh=bpy.data.meshes.new('EK曲线雕刻面片');mesh.from_pydata(vertices,[],faces);mesh.update()
    edit=bpy.data.objects.new('EK曲线雕刻面片',mesh);group.objects.link(edit)
    edit.matrix_world=target.matrix_world.copy();edit[TAG]=True;edit[G.A.TAG]=True;edit['ek_sculpt_target']=target
    edit['ek_sculpt_rows']=along+1;edit['ek_sculpt_columns']=across+1
    edit['ek_sculpt_records']=json.dumps(records,ensure_ascii=False)
    edit['ek_sculpt_topology']=G.digest(faces);edit.hide_render=True;edit.show_in_front=True
    for axis,name in enumerate(('ek_sculpt_curve','ek_sculpt_row','ek_sculpt_column')):
        attr=mesh.attributes.new(name,'INT','POINT');attr.data.foreach_set('value',[b[axis] for b in bindings])
    for index,ob in enumerate(curves):
        edit['ek_sculpt_source_'+str(index)]=ob
        material=bpy.data.materials.new('EK面片_'+ob.name);material[TAG]=True
        material.diffuse_color=(*colorsys.hsv_to_rgb((index*.61803398875)%1,.55,.85),1.)
        mesh.materials.append(material)
    for poly,index in zip(mesh.polygons,face_materials):poly.material_index=index;poly.use_smooth=True
    # Face sets let sculpt tools isolate strips, in addition to material slots.
    attr=mesh.attributes.new('.sculpt_face_set','INT','FACE')
    attr.data.foreach_set('value',[index+1 for index in face_materials])
    settings.sculpt_object=edit
    S.focus(context,edit,[target])
    if context.area and context.area.type=='VIEW_3D':context.area.spaces.active.shading.color_type='MATERIAL'
    for ob in curves:ob.hide_set(True)
    bpy.ops.object.mode_set(mode='SCULPT')
    return len(curves)


def remove(context,edit):
    if not edit or not edit.get(TAG):raise ValueError('此对象不是曲线编辑面片，未删除')
    records=json.loads(edit['ek_sculpt_records']);mesh=edit.data
    for row in records:
        ob=edit.get('ek_sculpt_source_'+str(row['source']))
        if ob:ob.hide_set(row['hidden'])
    materials=list(mesh.materials)
    if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    bpy.data.objects.remove(edit,do_unlink=True)
    if mesh.users==0:bpy.data.meshes.remove(mesh)
    for material in materials:
        if material and material.get(TAG) and material.users==0:bpy.data.materials.remove(material)
    context.scene.exprkit_rules.sculpt_object=None


def write(context):
    edit=current(context)
    if not edit or not edit.get(TAG):raise ValueError('请先创建编辑面片')
    if context.mode!='OBJECT':bpy.ops.object.mode_set(mode='OBJECT')
    target=edit.get('ek_sculpt_target')
    if not target:raise ValueError('原分区模型已删除，编辑面片已保留')
    mesh=edit.data;rows=int(edit['ek_sculpt_rows']);columns=int(edit['ek_sculpt_columns'])
    records=json.loads(edit['ek_sculpt_records']);count=len(records)
    if edit.modifiers:raise ValueError('请先移除或应用修改器；写回需要保留面片拓扑')
    if len(mesh.vertices)!=count*rows*columns or G.digest([list(p.vertices) for p in mesh.polygons])!=edit['ek_sculpt_topology']:
        raise ValueError('面片拓扑已改变；请撤销动态拓扑、重构或细分操作后再写回。编辑面片已保留')
    indices=[]
    for name in ('ek_sculpt_curve','ek_sculpt_row','ek_sculpt_column'):
        attr=mesh.attributes.get(name)
        if attr is None or attr.domain!='POINT' or attr.data_type!='INT':raise ValueError('面片对应信息丢失，无法写回')
        values=np.empty(len(mesh.vertices),dtype=np.int32);attr.data.foreach_get('value',values);indices.append(values)
    bindings=np.column_stack(indices)
    limits=np.array([count,rows,columns])
    if np.any(bindings<0) or np.any(bindings>=limits) or len(np.unique(bindings,axis=0))!=len(bindings):
        raise ValueError('面片对应信息重复或越界，无法写回')
    coordinates=np.array([v.co for v in mesh.vertices]);order=np.lexsort((bindings[:,2],bindings[:,1],bindings[:,0]))
    centers=coordinates[order].reshape(count,rows,columns,3).mean(axis=2)
    if not np.isfinite(centers).all():raise ValueError('面片存在无效坐标，未修改曲线')
    plans=[]
    for index,row in enumerate(records):
        ob=edit.get('ek_sculpt_source_'+str(index))
        if not ob or ob.type!='CURVE' or ob.get('ek_guide_entry')!=row['entry']:raise ValueError('原曲线已删除或重新生成，编辑面片已保留')
        if G.digest(G.curve_points(ob,target))!=row['stamp']:raise ValueError('原曲线在面片编辑期间发生变化，请取消面片后重新创建')
        transform=(G.reference_transform(ob,target)@ob.matrix_world).inverted()@target.matrix_world.inverted()@edit.matrix_world
        points=[list(transform@Vector(p)) for p in centers[index]]
        fit=G.F.fit(points,json.loads(row['entry'])['kind'],context.scene.exprkit_rules.sculpt_fit)
        if not fit:raise ValueError('面片中心线退化为一点：'+ob.name)
        plans.append((ob,fit))
    # Build replacement datablocks first. Original curve identity, rest samples,
    # guide key and region bindings stay unchanged, so edits remain corrections.
    mirror_pairs=[];mirrored=set()
    if context.scene.exprkit_regions.curve_symmetry:
        for ob,fit in sorted(plans,key=lambda row:-json.loads(row[0]['ek_guide_entry'])['side']):
            if ob in mirrored or not json.loads(ob['ek_guide_entry'])['side']:continue
            destination,_=Author.mirror_target(ob)
            mirror_pairs.append((ob,destination));mirrored.update((ob,destination))
    replacements=[];previous=Author._mirroring;Author._mirroring=True
    touched={ob for ob,fit in plans}|{destination for ob,destination in mirror_pairs}
    stamps={ob:{key:ob.get(key) for key in ('ek_curve_edit_time','ek_curve_change_stamp')} for ob in touched}
    try:
        for ob,fit in plans:
            data=ob.data.copy();replacements.append((ob,ob.data,data))
            data.splines.clear();spline=data.splines.new('BEZIER');spline.bezier_points.add(len(fit['points'])-1)
            for point,co,left,right in zip(spline.bezier_points,fit['points'],fit['left'],fit['right']):
                point.co=co;point.handle_left_type='FREE';point.handle_right_type='FREE';point.handle_left=left;point.handle_right=right
            spline.resolution_u=24;data.resolution_u=24
        known={ob for ob,old,data in replacements}
        for destination in touched-known:replacements.append((destination,destination.data,destination.data.copy()))
        for ob,old,data in replacements:ob.data=data
        for ob,destination in mirror_pairs:Author.mirror(context,ob)
        for ob in touched:
            ob['ek_curve_edit_time']=time.time();ob['ek_curve_change_stamp']=G.digest(G.curve_points(ob,target))
    except Exception:
        for ob,old,data in replacements:ob.data=old
        for ob,values in stamps.items():
            for key,value in values.items():
                if value is not None:ob[key]=value
                elif key in ob:del ob[key]
        for ob,old,data in replacements:
            if data.users==0:bpy.data.curves.remove(data)
        raise
    finally:Author._mirroring=previous
    for old in {old for ob,old,data in replacements}:
        if old.users==0:bpy.data.curves.remove(old)
    remove(context,edit)
    S.focus(context,plans[0][0],[target,*[ob for ob,fit in plans]])
    return count


def draw(layout,context):
    s=context.scene.exprkit_rules;box=layout.box()
    row=box.row();row.prop(s,'show_sculpt',text='面片雕刻曲线',icon='TRIA_DOWN' if s.show_sculpt else 'TRIA_RIGHT',emboss=False)
    if not s.show_sculpt:return
    if s.sculpt_object:
        box.label(text=s.sculpt_object.name,icon='MESH_DATA');box.prop(s,'sculpt_fit')
        box.label(text='保留拓扑；材质与面组区分各条曲线')
        if context.scene.exprkit_regions.curve_symmetry:box.label(text='左右均编辑时，以 X 正侧写回对称')
        row=box.row(align=True)
        row.operator('exprkit_rules.edit',text='写回曲线并删除面片').action='SCULPT_WRITE'
        row.operator('exprkit_rules.edit',text='取消').action='SCULPT_CANCEL'
    else:
        box.prop(s,'sculpt_scope');box.prop(s,'sculpt_width')
        row=box.row(align=True);row.prop(s,'sculpt_along');row.prop(s,'sculpt_across')
        box.prop(s,'sculpt_fit')
        box.operator('exprkit_rules.edit',text='合并为面片并雕刻').action='SCULPT'
