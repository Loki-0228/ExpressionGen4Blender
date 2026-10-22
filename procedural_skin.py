"""Connected facial skin and synchronized disconnected Face layers."""
from collections import Counter
import heapq
import numpy as np
from .region_deformation import SkinDisplacementField
from . import procedural_binding as Binding


class FaceFollowers:
    """Bind disconnected Face layers to the skin carrying facial controls.

    Transfer final displacement, retaining each layer's original offset and
    tessellation. All explicitly marked Face islands participate, including
    full-size face overlays; other partitions never become followers.
    """
    def __init__(self,points,triangles,controls):
        from mathutils import Vector
        from mathutils.bvhtree import BVHTree
        self.vertices=np.empty(0,dtype=np.int32)
        self.triangles=np.empty((0,3),dtype=np.int32)
        self.weights=np.empty((0,3),dtype=float)
        points=np.asarray(points,dtype=float)
        triangles=np.asarray(triangles,dtype=np.int32).reshape((-1,3))
        if not len(triangles):return
        parent={int(i):int(i) for i in triangles.ravel()}
        def root(i):
            while parent[i]!=i:
                parent[i]=parent[parent[i]];i=parent[i]
            return i
        for a,b,c in triangles:
            a=root(int(a));parent[root(int(b))]=a;parent[root(int(c))]=a
        groups={}
        for i in parent:groups.setdefault(root(i),set()).add(i)
        controls=set(controls)
        controlled=[ids for ids in groups.values() if ids&controls]
        if len(controlled)>1:
            # Controls can be split between overlapping Face layers. Select
            # the local driver by its contour, never by material name or by
            # declaring every controlled layer an independent whole face.
            from mathutils.kdtree import KDTree
            contour=sorted(controls&set(parent));tree=KDTree(len(contour))
            # Use facial coordinates: a layer's depth offset must not change
            # which contour owns the same point on the visible face.
            for i in contour:tree.insert(Vector((points[i,0],0.,points[i,2])),i)
            tree.balance()
            owner={i:root(tree.find(Vector((points[i,0],0.,points[i,2])))[1]) for i in parent}
            bindings=[]
            for ids in controlled:
                binding=FaceFollowers(points,triangles,controls&ids)
                source=root(next(iter(ids)))
                keep=np.array([owner[int(i)]==source for i in binding.vertices],dtype=bool)
                bindings.append((binding,keep))
            self.vertices=np.concatenate([b.vertices[k] for b,k in bindings])
            self.triangles=np.concatenate([b.triangles[k] for b,k in bindings])
            self.weights=np.concatenate([b.weights[k] for b,k in bindings])
            return
        hosts=set().union(*(ids for ids in groups.values() if ids&controls))
        if not hosts:
            # Custom-only rigs can have no eye or lip contour. Use geometric
            # area, rather than vertex count, to identify their main skin.
            areas={key:0. for key in groups}
            for tri in triangles:
                p=points[tri];areas[root(int(tri[0]))]+=float(np.linalg.norm(np.cross(p[1]-p[0],p[2]-p[0])))
            hosts=groups[max(areas,key=areas.get)]
        followers=sorted(set(parent)-hosts)
        if not followers:return
        source=[tri.tolist() for tri in triangles if int(tri[0]) in hosts
                and np.linalg.norm(np.cross(points[tri[1]]-points[tri[0]],points[tri[2]]-points[tri[0]]))>0]
        if not source:return
        tree=BVHTree.FromPolygons([Vector(p) for p in points],source,all_triangles=True)
        vertices=[];bound=[];weights=[]
        for i in followers:
            hit,normal,index,distance=tree.find_nearest(Vector(points[i]))
            if index is None:continue
            tri=source[index];a,b,c=points[tri];u=b-a;v=c-a;q=np.asarray(hit)-a
            uu=float(u@u);uv=float(u@v);vv=float(v@v)
            denominator=uu*vv-uv*uv
            if denominator<=0:continue
            s=(float(q@u)*vv-float(q@v)*uv)/denominator
            t=(float(q@v)*uu-float(q@u)*uv)/denominator
            weight=np.clip((1-s-t,s,t),0,1);weight/=weight.sum()
            vertices.append(i);bound.append(tri);weights.append(weight)
        self.vertices=np.asarray(vertices,dtype=np.int32)
        self.triangles=np.asarray(bound,dtype=np.int32).reshape((-1,3))
        self.weights=np.asarray(weights,dtype=float).reshape((-1,3))

    def apply(self,delta):
        result=delta.copy()
        if len(self.vertices):
            result[self.vertices]=np.einsum('ij,ijk->ik',self.weights,delta[self.triangles])
        return result


class EyelidSkin:
    def __init__(self,rig):
        self.rig=rig;self.regions={};self.fields={};self.falloff={};self.controls={};self.collars={};self.collar_fields={}
        self.skin={i for i,labels in enumerate(rig.members) if 0 in labels}
        self.pins={i for rows in rig.rows.values() for i,u,upper in rows}|rig.creases|rig.inactive_pins
        faces=[face for face,label in zip(rig.info['faces'],rig.info['labels']) if label==0]
        edges=Counter(tuple(sorted((a,b))) for f in faces for a,b in zip(f,f[1:]+f[:1]))
        # Keep the mask perimeter attached to the surrounding head. Apertures
        # are intentional moving boundaries, so exclude their controls here.
        border={i for edge,count in edges.items() if count==1 for i in edge}-self.pins
        self.border=border
        graph={i:[] for i in self.skin}
        for a,b in edges:
            length=float(np.linalg.norm(rig.points[a]-rig.points[b]))
            graph[a].append((b,length));graph[b].append((a,length))
        for side in rig.rings:
            controls={i for i,u,upper in rig.rows['EYE',side]}
            controls.update(i for s,kind,ids,entry in rig.accessories if s==side and kind=='CREASE' for i in ids)
            controls&=self.skin
            radius=max(rig.widths['EYE',side]*.95,rig.heights['EYE',side],1e-9)
            globe=getattr(rig,'eye_anatomy',{}).get(side)
            if globe:radius=max(radius,globe['radius']*2.2)
            blocked=(self.pins-controls)|border
            distance=np.full(len(rig.points),np.inf);queue=[]
            for i in controls:distance[i]=0.;heapq.heappush(queue,(0.,i))
            while queue:
                value,i=heapq.heappop(queue)
                if value>distance[i] or value>=radius or i in blocked:continue
                for j,length in graph[i]:
                    # Follow connected skin through the nose bridge. A hard
                    # X=0 cut tears the transition next to a moving canthus;
                    # the other eye's contour stays pinned independently.
                    candidate=value+length
                    if candidate<distance[j] and candidate<radius:
                        distance[j]=candidate;heapq.heappush(queue,(candidate,j))
            region={i for i in self.skin if distance[i]<radius}-blocked
            t=np.clip(distance/radius,0,1)
            fade=1-t**3*(10-15*t+6*t*t)
            fade[list(blocked)]=0.;fade[list(controls)]=1.
            self.regions[side]=region;self.falloff[side]=fade;self.controls[side]=controls
            self.fields[side]=SkinDisplacementField(rig.points,rig.info['faces'],rig.info['labels'],region,self.pins|border,fidelity=.002)
            rim={i for i,u,up in rig.rows['EYE',side]}
            collar={j for i in rim for j,length in graph[i] if length<rig.widths['EYE',side]*.18}-self.pins-border
            collar|={j for i in list(collar) for j,length in graph[i]
                     if length<rig.widths['EYE',side]*.10}-self.pins-border
            branches={up:[i for u,i in sorted({(u,i) for i,u,upper in rig.rows['EYE',side]
                        if upper==up or u<1e-7 or u>1-1e-7})] for up in (False,True)}
            lines={up:Binding.Line(rig.points[ids]) for up,ids in branches.items()}
            links={}
            for i in collar:
                up,u,_=min([(up,*line.project(rig.points[i])) for up,line in lines.items()],key=lambda row:row[2])
                links[i]=(up,u)
            self.collars[side]=(branches,lines,links)
            self.collar_fields[side]=SkinDisplacementField(rig.points,rig.info['faces'],rig.info['labels'],region,self.pins|border|collar,fidelity=.002)

    def deform(self,raw,sides):
        result=raw.copy();total=np.zeros_like(raw);weight=np.zeros(len(raw));moved=set()
        for side in sides:
            use_collar=bool(getattr(sides[side],'open_motion',{}))
            field=self.collar_fields[side] if use_collar else self.fields[side]
            controls=self.controls[side];seed=np.zeros_like(raw)
            indices=sorted(controls);seed[indices]=raw[indices]
            branches,lines,links=self.collars[side]
            if not use_collar:links={}
            posed=self.rig.points+raw
            def curve(up):
                points=posed[branches[up]];params=lines[up].parameters
                return lambda t:np.array([np.interp(t,params,points[:,axis]) for axis in range(3)])
            curves={up:curve(up) for up in (False,True)}
            if use_collar:
                from .procedural_lashes import orbital_section_transport
                rim_transport=orbital_section_transport(self.rig,raw,side)
            for i,(up,u) in links.items():
                # The return strip and the lash card must rotate around the
                # same continuous rim, especially where branches meet.
                target=rim_transport(self.rig.points[i])[0]
                seed[i]=target-self.rig.points[i]
            if use_collar:
                solved=field.deform(seed)
                solved=field.smooth_displacement(solved,bending=.5)
            else:solved=field.smooth_displacement(seed)
            followers=getattr(self.rig,'eye_followers',{}).get(side)
            ids=np.asarray(sorted(set(field.free.tolist())|set(links)),dtype=np.int32)
            if followers is not None and len(followers.vertices):
                ids=np.union1d(ids,sorted(controls))
            fade=self.falloff[side][ids]
            contribution=np.zeros_like(raw);coverage=np.zeros((len(raw),1))
            contribution[ids]=solved[ids]*fade[:,None];coverage[ids,0]=fade
            if followers is not None:
                contribution=followers.apply(contribution);coverage=followers.apply(coverage)
            total+=contribution;weight+=coverage[:,0]
            moved.update(np.flatnonzero(coverage[:,0]>0).tolist())
        if moved:
            ids=sorted(moved)
            # Overlap is a partition of influence, never a double eyelid pull.
            # The field already has a fixed outer boundary and penalizes
            # motion slopes. Do not apply a second amplitude fade to it.
            result[ids]=total[ids]/np.maximum(weight[ids,None],1e-12)
        return result

    def depth_correction(self,raw,contacts,sides,front=True):
        sides=list(sides);region=set().union(*(self.regions[side] for side in sides))
        pins=self.pins|self.border|set(contacts)
        field=SkinDisplacementField(self.rig.points,self.rig.info['faces'],self.rig.info['labels'],region,pins,fidelity=.002)
        result=field.smooth_displacement(raw)
        # Preserve the requested sign. Eye coverage goes forward; the final
        # lash contact pass can move protruding skin back inside its corridor.
        result[:,1]=np.minimum(result[:,1],0.) if front else np.maximum(result[:,1],0.)
        return result
