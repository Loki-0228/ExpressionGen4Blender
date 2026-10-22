"""Preset correspondence by part structure and ratios, without spatial queries."""
from collections import Counter,defaultdict
import numpy as np
from .region_core import canonical_region


def parts(points,polygons,groups):
    points=np.asarray(points,dtype=float)
    edge_faces=defaultdict(list)
    for f,poly in enumerate(polygons):
        for a,b in zip(poly,poly[1:]+poly[:1]):edge_faces[tuple(sorted((a,b)))].append(f)
    graph=[set() for _ in polygons]
    for owners in edge_faces.values():
        for f in owners:graph[f].update(j for j in owners if j!=f and groups[j]==groups[f])
    owner=np.full(len(polygons),-1,dtype=int);rows=[]
    for root in range(len(polygons)):
        if owner[root]>=0:continue
        number=len(rows);owner[root]=number;stack=[root];faces=[]
        while stack:
            f=stack.pop();faces.append(f)
            for j in graph[f]:
                if owner[j]<0:owner[j]=number;stack.append(j)
        ids=sorted({v for f in faces for v in polygons[f]})
        cloud=points[ids];low=cloud.min(0);high=cloud.max(0)
        edges=Counter(tuple(sorted((a,b))) for f in faces
                      for a,b in zip(polygons[f],polygons[f][1:]+polygons[f][:1]))
        boundary=defaultdict(set)
        for (a,b),count in edges.items():
            if count==1:boundary[a].add(b);boundary[b].add(a)
        todo=set(boundary);loops=0
        while todo:
            loops+=1;queue=[todo.pop()]
            while queue:
                for v in boundary[queue.pop()]:
                    if v in todo:todo.remove(v);queue.append(v)
        triangles=[(poly[0],poly[j],poly[j+1]) for f in faces
                   for poly in [polygons[f]] for j in range(1,len(poly)-1)]
        tri=points[np.asarray(triangles,dtype=int)]
        weights=np.linalg.norm(np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0]),axis=1)*.5
        area=float(weights.sum())
        if area<=1e-20:
            center=cloud.mean(0);eigen=np.zeros(3)
        else:
            total=tri.sum(1);center=np.sum(total*weights[:,None],axis=0)/(3*area)
            moment=(np.einsum('tvi,tvj->tij',tri,tri)+np.einsum('ti,tj->tij',total,total))/12
            covariance=np.sum(moment*weights[:,None,None],axis=0)/area-np.outer(center,center)
            eigen=np.maximum(np.linalg.eigvalsh(covariance),0)
            eigen/=max(float(eigen.sum()),1e-20)
        rows.append(dict(faces=faces,area=area,size=high-low,low=low,high=high,center=center,
            eigen=eigen,loops=loops,euler=len(ids)-len(edges)+len(faces),
            branched=any(len(v)!=2 for v in boundary.values()),
            nonmanifold=any(n>2 for n in edges.values()),neighbors=set(),label=groups[root]))
    for owners in edge_faces.values():
        nodes={int(owner[f]) for f in owners}
        for i in nodes:rows[i]['neighbors'].update(nodes-{i})
    if not rows:raise ValueError('预设或需添加表情的模型没有可匹配的面')
    main=max(rows,key=lambda r:r['area']);scale=max(float(np.max(main['size'])),1e-12)
    for row in rows:
        # Dimensionless proportions; coordinates are used only to establish
        # ordering/containment inside each model, never source-target distance.
        row['ratio']=np.r_[row['size']/scale,row['area']/max(main['area'],1e-20)]
        row['side']=0 if row['low'][0]<=main['center'][0]<=row['high'][0] else int(np.sign(row['center'][0]-main['center'][0]))
    return rows,owner


def ratio_cost(a,b):
    return float(np.mean(np.minimum(abs(np.log((np.asarray(a)+1e-6)/(np.asarray(b)+1e-6)))/np.log(4),1)))


def structure_cost(a,b):
    topology=(min(abs(a['loops']-b['loops']),3)/3+min(abs(a['euler']-b['euler']),3)/3
              +float(a['branched']!=b['branched'])+float(a['nonmanifold']!=b['nonmanifold'])
              +min(abs(len(a['neighbors'])-len(b['neighbors'])),4)/4)/5
    proportions=ratio_cost(a['ratio'],b['ratio'])
    shape=float(np.mean(abs(a['eigen']-b['eigen'])))*1.5
    side=float(a['side']!=b['side'])
    return .42*topology+.36*proportions+.16*shape+.06*side


def relation(a,b,linked):
    span=np.maximum(a['size']+b['size'],1e-12)
    order=np.sign(a['center']-b['center'])
    order[abs(a['center']-b['center'])<span*.03]=0
    contains=(a['low'][[0,2]]<=b['low'][[0,2]]) & (a['high'][[0,2]]>=b['high'][[0,2]])
    inside=(b['low'][[0,2]]<=a['low'][[0,2]]) & (b['high'][[0,2]]>=a['high'][[0,2]])
    return order,contains,inside,linked


def relation_cost(a,anchor_a,b,anchor_b,linked_a,linked_b):
    ar=relation(a,anchor_a,linked_a);br=relation(b,anchor_b,linked_b)
    topology=float(ar[3]!=br[3])
    sizes=ratio_cost(a['ratio']/np.maximum(anchor_a['ratio'],1e-6),
                     b['ratio']/np.maximum(anchor_b['ratio'],1e-6))
    arrangement=(float(np.mean(ar[0]!=br[0]))+float(np.mean(ar[1]!=br[1]))+float(np.mean(ar[2]!=br[2])))/3
    return .4*topology+.4*sizes+.2*arrangement


def match(source_points,source_polygons,source_labels,target_points,target_polygons,target_groups,manual=None):
    source,_=parts(source_points,source_polygons,source_labels)
    target,owner=parts(target_points,target_polygons,target_groups)
    base=np.array([[structure_cost(a,b) for b in source] for a in target])
    candidates=[np.argsort(row,kind='stable')[:min(24,len(source))].tolist() for row in base]
    scores=base.copy()

    def classify(row,indices):
        by_label={}
        for j in indices:
            label=source[j]['label']
            if label not in by_label or row[j]<by_label[label][0]:by_label[label]=(float(row[j]),j)
        ranked=sorted((cost,label,j) for label,(cost,j) in by_label.items())
        cost,label,j=ranked[0]
        margin=ranked[1][0]-cost if len(ranked)>1 else 1.
        return label,j,cost,margin

    # Only confident structural matches become relational anchors. Ambiguous
    # islands cannot propagate a guessed region through neighboring parts.
    for _ in range(3):
        seeds=[]
        for i,row in enumerate(scores):
            label,j,cost,margin=classify(row,candidates[i])
            if cost<.30 and margin>.055:seeds.append((i,j))
        seeds=sorted(seeds,key=lambda pair:-target[pair[0]]['area'])[:12]
        if not seeds:break
        updated=base.copy()
        for i,choices in enumerate(candidates):
            for j in choices:
                costs=[relation_cost(target[i],target[a],source[j],source[b],
                                     a in target[i]['neighbors'],b in source[j]['neighbors'])
                       for a,b in seeds if a!=i and b!=j]
                if costs:updated[i,j]=.65*base[i,j]+.35*float(np.mean(costs))
        scores=updated
    labels=[-2]*len(target_polygons);confidence=[0.]*len(labels);reasons=['structure_ambiguous']*len(labels)
    matched=0
    for i,row in enumerate(target):
        label,j,cost,margin=classify(scores[i],candidates[i])
        reliable=cost<.36 and margin>.045 and row['area']>1e-20
        if reliable:matched+=1
        for f in row['faces']:
            labels[f]=label if reliable else -2;confidence[f]=max(0.,1-cost)
            if reliable:reasons[f]='part_topology_proportions_relations'
    for f,label in (manual or {}).items():
        if not 0<=f<len(labels):raise ValueError('手动面编号已失效，请采用当前修正分区重建标准')
        labels[f]=canonical_region(label);reasons[f]='manual';confidence[f]=1.
    return dict(labels=labels,counts=dict(Counter(labels)),scores=confidence,reasons=reasons,
        method='part_topology_proportions_relations',manual_count=len(manual or {}),depth_guard=True,
        topology=dict(source_parts=len(source),target_parts=len(target),matched_parts=matched,
                      uncertain_parts=len(target)-matched),spatial_proximity=False,exact_matches=0,tolerance=0.)
