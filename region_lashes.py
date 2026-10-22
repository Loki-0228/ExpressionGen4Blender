"""Root/tip units from the upper lash silhouette, without cross-model topology matching."""
from collections import Counter, defaultdict
import numpy as np
from mathutils import Vector
from . import region_core as C


def upper_band_vertices(points,polygons,parts,plane,ring,side):
    """Classify whole upper strips from their middle, retaining canthus wings.

    The far tip can be nearer the lower rim. It is not a separate lower lash.
    Full eye loops still keep independent upper/lower branches.
    """
    faces=[f for f in polygons if all(parts[i]==1 for i in f)
           and (1 if np.mean([points[i][0] for i in f])>=plane else -1)==side]
    import heapq
    result=set();left=min(p.x for p in ring.points);right=max(p.x for p in ring.points)
    for island in C.topology(faces)[1]:
        local=[faces[f] for f in island['faces']];ids={i for f in local for i in f}
        seeds={True:set(),False:set()};graph={i:{} for i in ids}
        for face in local:
            for a,b in zip(face,face[1:]+face[:1]):
                length=float(np.linalg.norm(np.asarray(points[a])-points[b]))
                graph[a][b]=length;graph[b][a]=length
        for i in ids:
            point=Vector(points[i]);t=(point.x-left)/max(right-left,1e-12)
            if not .15<t<.85:continue
            distances={upper:(point-ring.sample(ring.locate(point,upper)[0],upper)).length for upper in (True,False)}
            difference=distances[False]-distances[True]
            if abs(difference)>ring.frame.height*.12:seeds[difference>0].add(i)
        if seeds[True] and not seeds[False]:result.update(ids);continue
        if seeds[False] and not seeds[True]:continue
        if not seeds[True]:
            result.update(i for i in ids if ring.locate(Vector(points[i]))[1]);continue
        # A full eye loop can have a very thick upper band and a thin lower
        # band. Area/vertex majority must not absorb the lower outer segment.
        distances={}
        for upper in (True,False):
            distance={i:0. for i in seeds[upper]};queue=[(0.,i) for i in seeds[upper]];heapq.heapify(queue)
            while queue:
                value,i=heapq.heappop(queue)
                if value>distance[i]:continue
                for j,length in graph[i].items():
                    candidate=value+length
                    if candidate<distance.get(j,float('inf')):distance[j]=candidate;heapq.heappush(queue,(candidate,j))
            distances[upper]=distance
        result.update(i for i in ids if distances[True].get(i,float('inf'))<=distances[False].get(i,float('inf')))
    return result


def describe(points, ids, ring, side, connected=False):
    ids=sorted(set(ids))
    located={i:ring.locate(Vector(points[i]),True)[0] for i in ids}
    distances={i:(Vector(points[i])-ring.sample(located[i],True)).length for i in ids}
    ordered=sorted(ids,key=lambda i:distances[i])
    count=max(1,len(ids)//5)
    tolerance=ring.frame.width*1e-8
    roots=[i for i in ordered if distances[i]<=distances[ordered[count-1]]+tolerance]
    tips=[i for i in ordered if distances[i]>=distances[ordered[-count]]-tolerance]
    root=np.mean([points[i] for i in roots],axis=0)
    tip=np.mean([points[i] for i in tips],axis=0)
    u=ring.locate(Vector(root),True)[0]
    return dict(side=side,u=float(u),vertices=ids,roots=roots,tips=tips,
                points=[root.tolist(),tip.tolist()],connected=connected)


def detect(points, polygons, parts, plane, rings, ownership=None):
    """Separate islands and silhouette lobes on joined strips.

    Connectivity only limits a lobe to its own local surface. Counts/indices
    never need to agree between source and target.
    """
    from . import region_accessories as Accessories
    ownership=ownership or Accessories.resolve(points,polygons,parts,plane,rings)
    parts=ownership['parts']
    points=[Vector(p) for p in points];units=[]
    for side,ring in rings.items():
        faces=[]
        for face in polygons:
            if sum(parts[i]==1 for i in face)<len(face)/2:continue
            center=sum((points[i] for i in face),Vector())/len(face)
            if (1 if center.x>=plane else -1)!=side:continue
            if not ring.locate(center)[1]:continue
            faces.append(face)
        _,components=C.topology(faces)
        for component in components:
            rows=[faces[f] for f in component['faces']]
            ids=sorted({i for face in rows for i in face})
            if len(ids)<3:continue
            # Tips can project onto the adjacent lid segment. Parameterize the
            # joined silhouette at a common horizontal position, so one tall
            # spike cannot create two apparent peaks on either side of itself.
            samples=sorted((ring.sample(u,True).x,float(u)) for u in np.linspace(0,1,129))
            us={i:float(np.interp(points[i].x,[p[0] for p in samples],[p[1] for p in samples])) for i in ids}
            dist={i:(points[i]-ring.sample(us[i],True)).length for i in ids}
            # Use inner->outer order for both eyes. Quantization/peak ties must
            # not select opposite sides just because the mesh is mirrored.
            if side<0:us={i:1-u for i,u in us.items()}
            span=max(us.values())-min(us.values())
            height=max(dist.values())-min(dist.values())
            if height<ring.frame.width*.012:continue
            if span<.36:
                # A short piece of the main band is still a band. A strand
                # must protrude away from the lid more than its along-lid span.
                along=max(points[i].x for i in ids)-min(points[i].x for i in ids)
                if height<max(along*.65,ring.frame.width*.025):continue
                units.append(describe(points,ids,ring,side));continue
            # A long continuous band is not one lash. Detect the protruding
            # lobes of its outside silhouette and keep the root band shared.
            counts=Counter(tuple(sorted((a,b))) for face in rows
                for a,b in zip(face,face[1:]+face[:1]))
            boundary={i for edge,n in counts.items() if n==1 for i in edge}
            if not boundary:continue
            bins=65;envelope=np.zeros(bins);occupancy=np.zeros(bins,dtype=bool)
            for i in boundary:
                k=int(np.clip(np.floor(us[i]*(bins-1)+.5),0,bins-1))
                envelope[k]=max(envelope[k],dist[i]);occupancy[k]=True
            filled=np.flatnonzero(occupancy)
            envelope=np.interp(np.arange(bins),filled,envelope[filled])
            smoothed=np.convolve(np.pad(envelope,1,mode='edge'),[.2,.6,.2],mode='valid')
            prominence=max(ring.frame.width*.012,height*.12)
            peaks=[]
            for k in range(1,bins-1):
                if smoothed[k]>=smoothed[k-1] and smoothed[k]>smoothed[k+1]:
                    low=max(min(smoothed[max(0,k-6):k+1]),min(smoothed[k:min(bins,k+7)]))
                    if smoothed[k]-low>prominence:peaks.append(k)
            accepted=[]
            for k in sorted(peaks,key=lambda k:smoothed[k],reverse=True):
                if all(abs(k-p)>3 for p in accepted):accepted.append(k)
            peaks=sorted(accepted)
            for number,k in enumerate(peaks):
                left=peaks[number-1] if number else 0
                right=peaks[number+1] if number+1<len(peaks) else bins-1
                left+=int(np.argmin(smoothed[left:k+1]))
                right=k+int(np.argmin(smoothed[k:right+1]))
                floor=max(smoothed[left],smoothed[right])
                selected=[i for i in ids if left/(bins-1)<=us[i]<=right/(bins-1)
                          and dist[i]>=floor-prominence*.3]
                if len(selected)>=3:
                    along=max(points[i].x for i in selected)-min(points[i].x for i in selected)
                    reach=max(dist[i] for i in selected)-min(dist[i] for i in selected)
                    # A broad eyelid card or its wing is not a thin strand.
                    # Bending it separately opens holes in the covering band.
                    if reach<max(along*.65,ring.frame.width*.025):continue
                    unit=describe(points,selected,ring,side,connected=True)
                    # Shared root-band vertices supply motion anchors but are
                    # never pulled toward an individual target lash tip.
                    unit['band_vertices']=[i for i in selected if dist[i]<=floor+prominence*.1]
                    units.append(unit)
    units=[attached for unit in units
           if (attached:=Accessories.unit_attachment(points,unit,ownership,polygons,rings[unit['side']])) is not None]
    # Imported double-sided cards may have coincident front/back vertices.
    # They describe one visible lash, not two independent moving units.
    merged=[]
    for unit in units:
        tolerance=rings[unit['side']].frame.width*.005
        same=next((row for row in merged if row['side']==unit['side'] and
            max(np.linalg.norm(np.subtract(a,b)) for a,b in zip(row['points'],unit['points']))<tolerance),None)
        if same:
            for group in ('vertices','roots','tips'):same[group]=sorted(set(same[group])|set(unit[group]))
            same['band_vertices']=sorted(set(same.get('band_vertices',[]))|set(unit.get('band_vertices',[])))
            same['connected']=same['connected'] or unit['connected']
        else:merged.append(unit)
    return sorted(merged,key=lambda row:(row['side'],row['u']))


def rotation_between(a,b):
    a,b=Vector(a),Vector(b)
    if min(a.length,b.length)<1e-10:return np.eye(3)
    return np.array(a.rotation_difference(b).to_matrix())


class LashMotion:
    """Each target lash keeps its own length; source key root/tip motion rotates it."""
    def __init__(self,source_points,target_points,source_units,target_units):
        self.source=np.asarray(source_points);self.target=np.asarray(target_points)
        self.source_units=source_units;self.units=target_units;self.bindings=[]
        self.protected={i for unit in target_units for i in unit.get('band_vertices',[])}
        self.ids={i for unit in target_units for i in unit['vertices']}
        for target in target_units:
            choices=[u for u in source_units if u['side']==target['side']]
            nearest=min(choices,key=lambda u:abs(u['u']-target['u'])) if choices else None
            self.bindings.append((target,nearest))

    def apply(self,delta,source_pose):
        source_pose=np.asarray(source_pose)
        for unit,source in self.bindings:
            ids=[i for i in unit['vertices'] if i not in self.protected];root=np.array(unit['points'][0])
            if not ids:continue
            root_motion=np.mean(delta[unit['roots']],axis=0)
            rotation=np.eye(3)
            if source:
                shift_root=np.mean(source_pose[source['roots']]-self.source[source['roots']],axis=0)
                shift_tip=np.mean(source_pose[source['tips']]-self.source[source['tips']],axis=0)
                direction=np.subtract(source['points'][-1],source['points'][0])
                rotation=rotation_between(direction,direction+shift_tip-shift_root)
            posed=(self.target[ids]-root)@rotation.T+root+root_motion
            correction=posed-self.target[ids]
            if unit.get('connected'):
                length=max(np.linalg.norm(np.subtract(unit['points'][-1],root)),1e-9)
                weights=np.clip(np.linalg.norm(self.target[ids]-root,axis=1)/(length*.3),0,1)
                correction=delta[ids]*(1-weights[:,None])+correction*weights[:,None]
            delta[ids]=correction
        return delta

    def correct_roots(self,delta,correction):
        for unit in self.units:
            ids=[i for i in unit['vertices'] if i not in self.protected]
            if ids:delta[ids]+=np.mean(correction[unit['roots']],axis=0)
        return delta


class CurveSimilarity:
    """One translation, rotation and uniform scale for an entire lash band."""
    def __init__(self,source,target,source_band=(),target_band=(),upper=True,
                 source_edit=None,target_edit=None):
        def anchors(ring,cloud):
            offset=np.median([np.asarray(p)-np.asarray(ring.sample(ring.locate(Vector(p),upper)[0],upper))
                              for p in cloud],axis=0) if len(cloud) else np.zeros(3)
            return np.array([ring.sample(u,upper) for u in np.linspace(0,1,33)])+offset
        a,b=anchors(source,source_band),anchors(target,target_band)
        if source_edit is not None:a+=source_edit
        if target_edit is not None:b+=target_edit
        self.origin=a.mean(axis=0);self.destination=b.mean(axis=0)
        x,y=a-self.origin,b-self.destination
        u,values,v=np.linalg.svd(x.T@y);rotation=v.T@u.T
        if np.linalg.det(rotation)<0:v[-1]*=-1;rotation=v.T@u.T
        self.rotation=rotation
        self.scale=float(np.clip(np.sum((x@rotation.T)*y)/max(np.sum(x*x),1e-15),.1,10))

    def warp(self,point):
        return Vector(self.destination+self.scale*(self.rotation@(np.asarray(point)-self.origin)))

    def delta(self,delta):return Vector(self.scale*(self.rotation@np.asarray(delta)))


class PolylineSimilarity(CurveSimilarity):
    """One transform per accessory strip, inferred from entire guide curves."""
    def __init__(self,source,target):
        def samples(points):
            points=np.array(points);length=np.r_[0,np.cumsum(np.linalg.norm(np.diff(points,axis=0),axis=1))]
            length/=max(length[-1],1e-12)
            return np.column_stack([np.interp(np.linspace(0,1,33),length,points[:,k]) for k in range(3)])
        a,b=samples(source),samples(target)
        if np.linalg.norm(a[0]-b[0])+np.linalg.norm(a[-1]-b[-1])>np.linalg.norm(a[0]-b[-1])+np.linalg.norm(a[-1]-b[0]):b=b[::-1]
        self.origin=a.mean(0);self.destination=b.mean(0);x=a-self.origin;y=b-self.destination
        u,s,v=np.linalg.svd(x.T@y);self.rotation=v.T@u.T
        if np.linalg.det(self.rotation)<0:v[-1]*=-1;self.rotation=v.T@u.T
        self.scale=float(np.clip(np.sum((x@self.rotation.T)*y)/max(np.sum(x*x),1e-15),.25,4))


class MotionEvidence:
    """Use actual source-key motion to distinguish eyelid followers from brows."""
    def __init__(self,points,ids,deltas,names):
        self.points=np.asarray(points)[ids];self.ids={i:n for n,i in enumerate(ids)}
        self.deltas=np.asarray(deltas);self.names=names

    def accessory(self,ids,ring):
        selected=[self.ids[i] for i in ids if i in self.ids]
        if not selected or not len(self.deltas):return None
        def mean_motion(upper):
            anchors=[ring.sample(u,upper) for u in np.linspace(.2,.8,9)]
            indices=[int(np.argmin(np.sum((self.points-np.asarray(p))**2,axis=1))) for p in anchors]
            return self.deltas[:,indices].mean(axis=1)
        upper,lower=mean_motion(True),mean_motion(False)
        closing=(upper[:,2]-lower[:,2]) < -max(ring.frame.height*.05,ring.frame.width*.002)
        if not np.any(closing):return None
        motion=self.deltas[:,selected].mean(axis=1)
        error=np.linalg.norm(motion[closing]-upper[closing],axis=1)
        magnitude=np.maximum(np.linalg.norm(upper[closing],axis=1),ring.frame.width*.002)
        relative=float(np.median(error/magnitude))
        return dict(follows_upper_lid=relative<.35,relative_error=relative,
                    keys=[name for name,used in zip(self.names,closing) if used],method='source_shape_key_motion')
