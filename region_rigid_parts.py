"""Whole-part oral transforms driven continuously by expression values."""
import json
import bpy
import numpy as np
from mathutils import Matrix,Vector


def drive_channel(ob,path,axis,rows,keys,base=0.,minimum=None):
    """Split sums before Blender's 255-character driver expression limit."""
    inputs=[(keys,keys.key_blocks[name].path_from_id('value'),value) for name,value in rows]
    generation=0
    def configure(curve,items,constant=0.,floor=None):
        driver=curve.driver;driver.type='SCRIPTED';terms=[repr(float(constant))]
        for index,(owner,data_path,value) in enumerate(items):
            variable=driver.variables.new();variable.name='v'+str(index);variable.type='SINGLE_PROP'
            variable.targets[0].id_type='KEY' if isinstance(owner,bpy.types.Key) else 'OBJECT'
            variable.targets[0].id=owner;variable.targets[0].data_path=data_path
            terms.append('%.9g*%s'%(value,variable.name))
        expression='+'.join(terms)
        driver.expression=('max(%s,%s)'%(floor,expression)) if floor is not None else expression
        if len(expression)>230:raise ValueError('口腔驱动表达式过长')
    while len(inputs)>8:
        outputs=[]
        for index in range(0,len(inputs),8):
            prop='ek_oral_%s_%d_%d_%d'%(path,axis,generation,index//8)
            ob[prop]=0.;data_path='['+json.dumps(prop)+']'
            configure(ob.driver_add(data_path),inputs[index:index+8])
            outputs.append((ob,data_path,1.))
        inputs=outputs;generation+=1
    configure(ob.driver_add(path,axis),inputs,base,minimum)


class RigidTeeth:
    region=9
    kind='teeth'
    allow_scale=False
    def __init__(self,fitted,target,groups):
        from .region_transfer import mesh_regions
        labels=json.loads(fitted['ek_vertex_regions'])
        self.source_ids=[i for i,label in enumerate(labels) if label==self.region]
        self.target_ids=[i for i,row in enumerate(groups) if self.region in row]
        self.faces=[i for i,label in enumerate(mesh_regions(target)) if label==self.region]
        # Solve in world space. A nonuniform parent scale followed by a local
        # rotation would otherwise stretch teeth even with no shape keys.
        self.transform=fitted.matrix_world.copy()
        self.basis=np.array([list(self.transform @ fitted.data.shape_keys.reference_key.data[i].co) for i in self.source_ids])
        target_basis=target.data.shape_keys.reference_key.data if target.data.shape_keys else target.data.vertices
        self.center=np.mean([target.matrix_world @ target_basis[i].co for i in self.target_ids],axis=0) if self.target_ids else np.zeros(3)
        self.poses={}

    def add_pose(self,key):
        if len(self.source_ids)<3 or not self.target_ids:return
        pose=np.array([list(self.transform @ key.data[i].co) for i in self.source_ids])
        a,b=self.basis.mean(axis=0),pose.mean(axis=0)
        u,s,v=np.linalg.svd((self.basis-a).T @ (pose-b))
        rotation=v.T @ u.T
        if np.linalg.det(rotation)<0:v[-1]*=-1;rotation=v.T @ u.T
        scale=float(np.clip(np.sum(((self.basis-a)@rotation.T)*(pose-b))/
                    max(np.sum((self.basis-a)**2),1e-15),.25,4)) if self.allow_scale else 1.
        translation=scale*(rotation @ (self.center-a))+b-self.center
        euler=np.array(Matrix(rotation.tolist()).to_euler('XYZ'))
        self.poses[key.name]=(translation,euler,np.full(3,scale))

    def create(self,output,basis_points=None):
        if not self.poses:return None
        from . import region_blender as A
        faces=[output.data.polygons[i] for i in self.faces]
        if not faces:return None
        ordered=sorted({i for p in faces for i in p.vertices});lookup={v:i for i,v in enumerate(ordered)}
        mesh=bpy.data.meshes.new(output.name+'_rigid_'+self.kind+'_mesh')
        mesh.from_pydata([output.matrix_world @ (Vector(basis_points[i]) if basis_points is not None else output.data.vertices[i].co)-Vector(self.center) for i in ordered],[],
                         [[lookup[i] for i in p.vertices] for p in faces])
        for slot in output.material_slots:mesh.materials.append(slot.material)
        for a,b in zip(mesh.polygons,faces):a.material_index=b.material_index;a.use_smooth=b.use_smooth
        for layer in output.data.uv_layers:
            destination=mesh.uv_layers.new(name=layer.name)
            for a,b in zip(mesh.polygons,faces):
                for x,y in zip(a.loop_indices,b.loop_indices):destination.data[x].uv=layer.data[y].uv
        teeth=bpy.data.objects.new(output.name+'_Rigid'+self.kind.title(),mesh)
        output.users_collection[0].objects.link(teeth)
        teeth.parent=output;teeth.matrix_parent_inverse=output.matrix_world.inverted()
        teeth.location=Vector(self.center);teeth.rotation_mode='XYZ'
        teeth[A.TAG]=True;teeth['ek_rigid_owner']=output.name;teeth['ek_rigid_region']=self.region
        teeth['ek_rigid_faces']=json.dumps([p.index for p in faces])
        teeth['ek_rigid_vertices']=json.dumps(ordered)
        keys=output.data.shape_keys
        for channel,path in enumerate(('location','rotation_euler')+(('scale',) if self.allow_scale else ())):
            for axis in range(3):
                rows=[]
                for name,values in self.poses.items():
                    if name not in keys.key_blocks:continue
                    parent=self.poses.get(keys.key_blocks[name].relative_key.name)
                    value=float(values[channel][axis]-(parent[channel][axis] if parent else (1 if path=='scale' else 0)))
                    if abs(value)>1e-9:rows.append((name,value))
                if not rows:continue
                drive_channel(teeth,path,axis,rows,keys,
                              float(self.center[axis]) if path=='location' else 1. if path=='scale' else 0.,
                              .05 if path=='scale' else None)
        mask_part(output,[p.index for p in faces],ordered,self.kind)
        output['ek_rigid_'+self.kind]=teeth.name
        parts=json.loads(output.get('ek_rigid_parts','{}'));parts[self.kind]=teeth.name
        output['ek_rigid_parts']=json.dumps(parts)
        return teeth


class RigidMouth(RigidTeeth):
    region=8
    kind='mouth'
    allow_scale=True


def mask_part(output,faces,vertices,kind):
    """Hide only mouth faces, including when their rim shares skin vertices."""
    if kind=='teeth':
        group=output.vertex_groups.new(name='EK_RigidTeeth_HiddenInSkin');group.add(vertices,1.0,'REPLACE')
        mask=output.modifiers.new('牙齿由独立刚体副本显示','MASK')
        mask.vertex_group=group.name;mask.invert_vertex_group=True
        return mask,group,None
    attribute=output.data.attributes.new('EK_RigidMouth_Faces','BOOLEAN','FACE')
    for index in faces:attribute.data[index].value=True
    nodes=bpy.data.node_groups.new('EK_口腔面隐藏','GeometryNodeTree')
    nodes.interface.new_socket(name='Geometry',in_out='INPUT',socket_type='NodeSocketGeometry')
    nodes.interface.new_socket(name='Geometry',in_out='OUTPUT',socket_type='NodeSocketGeometry')
    entry=nodes.nodes.new('NodeGroupInput');exit=nodes.nodes.new('NodeGroupOutput')
    selection=nodes.nodes.new('GeometryNodeInputNamedAttribute');selection.data_type='BOOLEAN'
    selection.inputs['Name'].default_value=attribute.name
    remove=nodes.nodes.new('GeometryNodeDeleteGeometry');remove.domain='FACE';remove.mode='ONLY_FACE'
    nodes.links.new(entry.outputs['Geometry'],remove.inputs['Geometry'])
    nodes.links.new(selection.outputs['Attribute'],remove.inputs['Selection'])
    nodes.links.new(remove.outputs['Geometry'],exit.inputs['Geometry'])
    mask=output.modifiers.new('口腔由整体变换副本显示','NODES');mask.node_group=nodes
    return mask,None,attribute
