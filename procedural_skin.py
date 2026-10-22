"""Local eye motion with smooth transitions along connected face topology."""
from collections import Counter
import heapq
import numpy as np
from .region_deformation import SkinDisplacementField
from . import procedural_binding as Binding


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
            ids=np.asarray(sorted(set(field.free.tolist())|set(links)),dtype=np.int32);fade=self.falloff[side][ids]
            total[ids]+=solved[ids]*fade[:,None]
            weight[ids]+=fade;moved.update(ids.tolist())
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
