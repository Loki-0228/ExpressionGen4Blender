"""Shared closure curves and visible accessory layers for different eye shapes."""
import json
from collections import defaultdict
import numpy as np
from .region_lashes import LashMotion
from . import region_guides as G
from mathutils import Vector
from mathutils.bvhtree import BVHTree


class EyeProfile:
    def __init__(self, points, rows, guides=None):
        self.rows=rows;self.guides=guides or {}
        cloud=np.array([points[i] for i,u,upper in rows])
        self.left=float(cloud[:,0].min());self.width=float(np.ptp(cloud[:,0]))
        self.height=float(np.ptp(cloud[:,2]));self.coefficients={}
        for upper in (False,True):
            ids=list(dict.fromkeys(i for i,u,branch in rows if branch==upper or u<1e-7 or u>1-1e-7))
            u=np.array([(points[i][0]-self.left)/self.width for i in ids])
            values=np.array([points[i] for i in ids])
            # Low-order curves remove tessellation notches without using a
            # different horizontal parameter for the two eyelids.
            self.coefficients[upper]=np.polynomial.polynomial.polyfit(u,values,3)
        self.closed_lift=0.0
        required=[points[i][2]-self.closed(points[i][0])[2]+self.height*.005
                  for i,u,upper in rows if not upper and .15<(points[i][0]-self.left)/self.width<.85]
        self.closed_lift=max(max(required,default=0),0)

    def sample(self,x,upper):
        u=np.clip((x-self.left)/self.width,0,1)
        value=np.polynomial.polynomial.polyval(u,self.coefficients[bool(upper)])
        entry=self.guides.get(bool(upper))
        if entry:
            value+=np.array(G.sample(entry['points'],u)-G.sample(entry['base'],u))
        return value

    def closure(self,points,basis):
        posed=EyeProfile(points,self.rows)
        us=np.linspace(.2,.8,13);ratios=[]
        for u in us:
            x=self.left+self.width*u
            gap=self.sample(x,True)[2]-self.sample(x,False)[2]
            if gap>self.height*.2:
                new_gap=posed.sample(x,True)[2]-posed.sample(x,False)[2]
                ratios.append(1-new_gap/gap)
        amount=float(np.clip(np.median(ratios),0,1)) if ratios else 0
        if amount>.85:amount=1.0
        return amount if amount>.04 else 0.0

    def closed(self,x):
        lower=self.sample(x,False);upper=self.sample(x,True)
        result=lower.copy()
        # The lower lid rises only ten percent of the local opening; both lids
        # meet the same smooth line instead of inheriting the source overlap.
        result[2]+=max(upper[2]-lower[2],0)*.10
        result[2]+=self.closed_lift
        result[1]=lower[1]*.9+upper[1]*.1
        result[0]=x
        return result


class EyeMotion:
    def __init__(self,fitted,target,points,members,source_points=None):
        from . import region_core as C
        self.points=np.asarray(points);self.members=members
        extent=max(float(np.max(np.ptp(self.points,axis=0))),1e-6)
        self.ray_origin=float(np.min(self.points[:,1]))-extent*2
        self.ray_length=float(np.ptp(self.points[:,1]))+extent*4
        self.source_rows=defaultdict(list);self.target_rows=defaultdict(list)
        for i,side,u,upper in json.loads(fitted.get('ek_eye_rim_controls','[]')):self.source_rows[side].append((i,u,upper))
        for i,side,u,upper in json.loads(fitted.get('ek_target_eye_controls','[]')):self.target_rows[side].append((i,u,upper))
        src=np.array(source_points if source_points is not None else [list(p.co) for p in fitted.data.shape_keys.reference_key.data])
        self.source={s:EyeProfile(src,rows) for s,rows in self.source_rows.items()}
        snapshot=json.loads(fitted.get('ek_guides_snapshot','{}'))
        self.profiles={}
        for side,rows in self.target_rows.items():
            guides={}
            for upper in (True,False):
                entries=G.entries_for(snapshot,'TARGET','EYE_UPPER' if upper else 'EYE_LOWER',side)
                if entries:guides[upper]=entries[0]
            self.profiles[side]=EyeProfile(self.points,rows,guides)
        self.lashes=LashMotion(src,self.points,json.loads(fitted.get('ek_source_lash_units','[]')),
                               json.loads(fitted.get('ek_target_lash_units','[]')))
        self.rim_ids={i for rows in self.target_rows.values() for i,u,upper in rows}
        self.lashes.protected|=self.rim_ids|{i for i,labels in enumerate(members) if 0 in labels}
        self.plane=float(fitted.get('ek_target_eye_plane',0));self.groups=[];self.roles={}
        parts=json.loads(fitted.get('ek_target_eye_parts','[]'))
        polys=[list(p.vertices) for p in target.data.polygons if all(2 in members[i] for i in p.vertices)]
        _,components=C.topology(polys)
        for component in components:
            ids=sorted({i for face in component['faces'] for i in polys[face]})
            side=1 if float(np.mean(self.points[ids,0]))>=self.plane else -1
            profile=self.profiles.get(side)
            if profile is None:continue
            role='lash'
            if parts and sum(parts[i]==2 for i in ids)>len(ids)/2:
                offset=float(np.median([self.points[i,2]-profile.sample(self.points[i,0],True)[2] for i in ids]))
                role='crease' if offset<profile.height*.2 else 'brow'
            self.groups.append((side,role,ids))
            for i in ids:self.roles[i]=(side,role)
        # Exclude detached Face fragments when measuring the front skin layer.
        polys=[list(p.vertices) for p in target.data.polygons if all(0 in members[i] for i in p.vertices)]
        _,components=C.topology(polys)
        self.skin=[polys[f] for c in components if len(c['faces'])>100 for f in c['faces']]
        self.clearances={}
        if self.skin:
            tree=BVHTree.FromPolygons([Vector(p) for p in self.points],self.skin)
            for i in self.roles:
                hit=self.front(tree,self.points[i])
                self.clearances[i]=max(hit-self.points[i,1],.00012) if hit is not None else .00012

    def front(self,tree,p):
        hit,_,_,_=tree.ray_cast(Vector((p[0],self.ray_origin,p[2])),Vector((0,1,0)),self.ray_length)
        return hit.y if hit is not None else None

    def apply(self,raw,source_pose,source_basis):
        result=raw.copy();amounts={s:p.closure(source_pose,source_basis) for s,p in self.source.items()}
        for side,amount in amounts.items():
            if not amount or side not in self.profiles:continue
            profile=self.profiles[side]
            for i,u,upper in self.target_rows[side]:
                point=self.points[i];closed=profile.closed(point[0])
                closed[2]+=(1 if upper else -1)*profile.height*.001
                result[i]=(closed-point)*amount
            for s,role,ids in self.groups:
                if s!=side or role=='brow':continue
                for i in ids:
                    if i in self.rim_ids:continue
                    point=self.points[i]
                    upper=True if role=='crease' else abs(point[2]-profile.sample(point[0],True)[2])<=abs(point[2]-profile.sample(point[0],False)[2])
                    anchor=profile.sample(point[0],upper)
                    result[i]=(profile.closed(point[0])-anchor)*amount
                    result[i,0]=0
        result=self.lashes.apply(result,source_pose)
        return result,amounts

    def keep_visible(self,delta):
        if not self.skin or not np.any(delta):return delta,{}
        points=self.points+delta
        tree=BVHTree.FromPolygons([Vector(p) for p in points],self.skin)
        moved={}
        for side,role,ids in self.groups:
            if any(0 in self.members[i] for i in ids):continue
            shifts=[]
            for i in ids:
                hit=self.front(tree,points[i])
                if hit is not None:shifts.append(hit-points[i,1]-min(self.clearances.get(i,.00012),.003))
            shift=min(min(shifts),0) if shifts else 0
            # One front/back translation per connected strip preserves its
            # thickness and avoids a pointwise shrinkwrap through the skin.
            if shift<0:
                delta[ids,1]+=shift
                moved[role]=max(moved.get(role,0),-float(shift))
        return delta,moved
