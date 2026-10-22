"""Close the neutral mouth on the target topology."""
from collections import defaultdict
import numpy as np
from mathutils import Vector
from .region_deformation import SkinDisplacementField

def closed_neutral(info,snapshot):
    points=np.array(info['points']);rows=info['rows'].get(('LIP',0),[]);ring=info['mouth']
    if not ring or not rows:return points,dict(changed=False,reason='no_lip_ring')
    width=ring.frame.width
    gap=max(float(np.median([ring.sample(u,True).z-ring.sample(u,False).z for u in np.linspace(.15,.85,15)])),0.)
    if gap<=width*.001:return points,dict(changed=False,reason='already_closed')
    delta=np.zeros_like(points);pins={i for i,u,upper in rows}
    branches=[]
    for upper in (True,False):
        cloud=np.array([ring.sample(u,upper) for u in np.linspace(0,1,65)])
        horizontal=np.array([ring.frame.axes(Vector(p))[0] for p in cloud]);order=np.argsort(horizontal)
        branches.append((horizontal[order],cloud[order]))
    for i,u,upper in rows:
        x=ring.frame.axes(Vector(points[i]))[0]
        paired=[np.array([np.interp(x,h,cloud[:,axis]) for axis in range(3)]) for h,cloud in branches]
        contact=(paired[0]+paired[1])*.5
        # Preserve authored depth and lateral detail at the lip seam.
        delta[i,2]=contact[2]-points[i,2]
    skin={i for i,row in enumerate(info['members']) if 0 in row}
    # Restrict neutral correction to connected skin near the original mouth.
    import heapq
    adjacent=defaultdict(set)
    for face,label in zip(info['faces'],info['labels']):
        if label==0:
            for a,b in zip(face,face[1:]+face[:1]):adjacent[a].add(b);adjacent[b].add(a)
    queue=[(0.,i) for i in pins];heapq.heapify(queue);near=set()
    while queue:
        distance,i=heapq.heappop(queue)
        if i in near or distance>width*.45:continue
        near.add(i)
        for j in adjacent[i]:
            if j not in near:heapq.heappush(queue,(distance+np.linalg.norm(points[i]-points[j]),j))
    field=SkinDisplacementField(points,info['faces'],info['labels'],skin&near,pins);delta=field.solve(delta)
    return points+delta,dict(changed=True,gap_ratio=gap/width,vertices=int(np.sum(np.linalg.norm(delta,axis=1)>1e-10)))

