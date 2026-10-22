"""Resolve declarative curves on a new model and feed the existing solver."""
import copy,json
from collections import Counter,defaultdict
import numpy as np
from . import expression_rules as Rules,procedural_binding as B,region_guides as G,region_core as C,region_contours as O


def samples(points,count=65):
    line=B.Line(points)
    return np.array([line.sample(t) for t in np.linspace(0,1,count)])


def vectors(values,count=65):
    # Displacements are indexed by the source curve parameter, not by their
    # own arc length (a constant/zero offset still has two distinct samples).
    values=np.asarray(values,dtype=float)
    return np.array([np.interp(np.linspace(0,1,count),np.linspace(0,1,len(values)),values[:,i]) for i in range(3)]).T


def frame(points):
    p=np.asarray(points);length=max(B.Line(p).length,1e-9)
    direction=p[-1]-p[0]
    if np.linalg.norm(direction)<length*.01:direction=np.array((1.,0.,0.))
    direction/=max(np.linalg.norm(direction),1e-9)
    depth=np.array((0.,1.,0.));depth-=direction*np.dot(direction,depth)
    if np.linalg.norm(depth)<.01:depth=np.array((0.,0.,1.));depth-=direction*np.dot(direction,depth)
    depth/=max(np.linalg.norm(depth),1e-9)
    return np.column_stack((direction,depth,np.cross(direction,depth)))*length


def feature(entry,metric,reference,rig):
    p=np.asarray(entry['points']);ref=np.asarray(reference['points']) if reference else rig.original_points
    lo,hi=ref.min(0),ref.max(0);scale=max(float(np.max(hi-lo)),1e-9)
    if metric.startswith('center_'):return float(((p.min(0)+p.max(0)-lo-hi)/2)[{'x':0,'y':1,'z':2}[metric[-1]]]/scale)
    if metric.startswith('span_'):return float(np.ptp(p,axis=0)[{'x':0,'y':1,'z':2}[metric[-1]]]/scale)
    if metric=='length':return B.Line(p).length/scale
    if metric=='aspect':return float(np.ptp(p[:,0])/max(np.ptp(p[:,2]),scale*.001))
    if metric=='closed':return float(np.linalg.norm(p[0]-p[-1])<scale*.001)
    if metric=='vertices':return len(entry.get('vertices',[]))
    return entry.get(metric,0)


def mesh_entry(rig,region,side=0):
    region=C.canonical_region(region)
    if not hasattr(rig,'_custom_mesh_entries'):rig._custom_mesh_entries={}
    if (region,side) in rig._custom_mesh_entries:return rig._custom_mesh_entries[region,side]
    faces=[p for p,l in zip(rig.info['faces'],rig.info['labels']) if C.canonical_region(l)==region]
    if side:faces=[p for p in faces if (1 if np.mean(rig.original_points[p,0])>=rig.info['plane'] else -1)==side]
    ids=sorted({v for p in faces for v in p})
    if len(ids)<2:raise ValueError('缺少识别所需分区：'+str(region))
    edges=Counter(tuple(sorted((a,b))) for p in faces for a,b in zip(p,p[1:]+p[:1]))
    graph=defaultdict(set)
    for (a,b),n in edges.items():
        if n==1:graph[a].add(b);graph[b].add(a)
    entry=dict(points=rig.original_points[ids],vertices=ids,faces=faces,graph=graph,
               boundary_loops=len(O.boundary_cycles(graph)),components=len(C.topology(faces)[1]))
    rig._custom_mesh_entries[region,side]=entry
    return entry


def section_candidates(rig,region,side,axis,position):
    mesh=mesh_entry(rig,region,side);points=rig.original_points
    cloud=mesh['points'];level=float(cloud[:,axis].min()+np.ptp(cloud[:,axis])*position)
    scale=max(float(np.max(np.ptp(cloud,axis=0))),1e-9);graph=defaultdict(set);coords={};owners=defaultdict(set)
    for poly in mesh['faces']:
        for k in range(1,len(poly)-1):
            triangle=(poly[0],poly[k],poly[k+1]);hits=[]
            for a,b in zip(triangle,triangle[1:]+triangle[:1]):
                da,db=points[a,axis]-level,points[b,axis]-level
                if da*db>0 or abs(da-db)<1e-12:continue
                t=da/(da-db)
                if not 0<=t<=1:continue
                hit=points[a]+t*(points[b]-points[a]);key=tuple(np.round(hit/scale,7))
                coords[key]=hit;owners[key].update((a,b));hits.append(key)
            hits=list(dict.fromkeys(hits))
            if len(hits)==2 and hits[0]!=hits[1]:graph[hits[0]].add(hits[1]);graph[hits[1]].add(hits[0])
    remaining=set(graph);result=[]
    while remaining:
        component=set();queue=[min(remaining)]
        while queue:
            i=queue.pop()
            if i in component:continue
            component.add(i);remaining.discard(i);queue.extend(graph[i]-component)
        if any(len(graph[k])>2 for k in component):continue
        ends=sorted(k for k in component if len(graph[k])==1);root=ends[0] if ends else min(component)
        chain=[root];previous=None;current=root
        while True:
            following=sorted(graph[current]-{previous})
            if not following:break
            following=following[0]
            if following==root:chain.append(root);break
            if following in chain:break
            chain.append(following);previous,current=current,following
        if len(chain)>=2:result.append(dict(points=[coords[k] for k in chain],vertices=sorted({v for k in chain for v in owners[k]}),boundary_loops=mesh['boundary_loops'],components=mesh['components']))
    return result


def recognize(rig,spec):
    nodes={}
    ordered=Rules.topological(spec['recognizers'],lambda r:[v for v in [r.get('reference'),*[c.get('reference') for c in r.get('criteria',[])]] if v])
    for r in ordered:
        mode=r['mode'];reference=nodes.get(r.get('reference'))
        if mode=='GUIDE':
            candidates=[copy.deepcopy(e) for e in rig.snapshot['entries'] if e['kind']==r['kind'] and e['side']==r['side'] and e.get('enabled',True)]
            candidates.sort(key=lambda e:e['key'])
            if any(c['metric'] in ('components','boundary_loops') for c in r.get('criteria',[])):
                mesh=mesh_entry(rig,r['region'],r['side'])
                for e in candidates:e.update(components=mesh['components'],boundary_loops=mesh['boundary_loops'])
        elif mode=='DERIVED':
            entry=copy.deepcopy(reference);entry['points']=np.asarray(reference['points'])+frame(reference['points'])@np.array(r.get('offset',[0,0,0]));candidates=[entry]
        elif mode=='BOUNDARY':
            mesh=mesh_entry(rig,r['region'],r['side']);candidates=[dict(points=rig.original_points[ids+[ids[0]]],vertices=ids,boundary_loops=mesh['boundary_loops'],components=mesh['components']) for ids in O.boundary_cycles(mesh['graph']) if len(ids)>=3]
        else:candidates=section_candidates(rig,r['region'],r['side'],r.get('axis',2),r.get('position',.5))
        candidates=[e for e in candidates if all(c['min']<=feature(e,c['metric'],nodes.get(c.get('reference')),rig)<=c['max'] for c in r.get('criteria',[]))]
        candidates.sort(key=lambda e:tuple(np.mean(np.asarray(e['points']),axis=0))) if mode!='GUIDE' else None
        index=int(r.get('index',0))
        if not 0<=index<len(candidates):raise ValueError('无法识别曲线 '+r['id']+'；请检查分区、比例及拓扑条件')
        entry=candidates[index];entry.update(kind=r['kind'],side=r['side'],region=r['region'],id=r['id'])
        # A derived translation keeps its reference's sample correspondence.
        # Resampling its already sampled polyline adds an unintended bend.
        if mode!='DERIVED':entry['points']=samples(entry['points'])
        nodes[r['id']]=entry
    return nodes


def evaluate(rig,recipe):
    if hasattr(rig,'_custom_original_entries'):
        for e in rig.snapshot['entries']:e['points']=copy.deepcopy(rig._custom_original_entries[e['key']])
    offsets={};custom=[];diagnostics=[];rule_targets={};controlled=set()
    for spec in recipe.get('custom_rules',[]):
        nodes=recognize(rig,spec);outputs={};params={p['id']:p['default'] for p in spec['parameters']}
        params.update(spec.get('values',{}));weight=float(spec.get('weight',1))
        for r in Rules.topological(spec['rules'],lambda r:[r['target_rule']] if r.get('target_rule') else []):
            source=nodes[r['source']];base=samples(source['points'])
            if source.get('key'):controlled.add((source['kind'],source['side'],source['key']))
            if r.get('target_rule'):target=outputs[r['target_rule']].copy()
            elif r.get('target_curve'):target=samples(nodes[r['target_curve']]['points'])
            else:target=base+vectors(r['target_points'])@frame(base).T
            rule_targets[spec['name'],r['id']]=target.copy()
            amount=r.get('amount',1)*params.get(r.get('parameter'),1)
            for f in r.get('influences',[]):
                entry=nodes[f['curve']] if f.get('curve') else mesh_entry(rig,f['region'])
                v=feature(entry,f['metric'],source,rig)
                t=float(np.clip((v-f['input_min'])/(f['input_max']-f['input_min']),0,1))
                amount*=f['output_min']+(f['output_max']-f['output_min'])*t
            amount=float(np.clip(amount,0,1))*weight;movement=(target-base)*amount;outputs[r['id']]=base+movement
            if not np.any(abs(movement)>1e-12):
                diagnostics.append(dict(rule=r['id'],amount=amount));continue
            if source['kind']=='CUSTOM':
                if source['region']!=0:raise ValueError('自定义面部控制曲线必须绑定 Face；其他分区曲线可作为识别和计算参照')
                custom.append((source,movement))
            else:
                if not source.get('key') or not any(e['key']==source['key'] and e['kind']==source['kind'] for e in rig.snapshot['entries']):
                    bindings=sorted((e for e in rig.snapshot['entries'] if e['kind']==source['kind'] and e['side']==source['side'] and e.get('enabled',True)),
                                    key=lambda e:(-len(set(e.get('vertices',[]))&set(source.get('vertices',[]))),e['key']))
                    if not bindings:raise ValueError('新增曲线缺少对应的 '+G.KINDS[source['kind']]+' 校正曲线；可用 Face 自定义控制或补齐该部位')
                    binding=bindings[0];line=B.Line(base)
                    us=[line.project(p)[0] for p in samples(binding['points'])]
                    movement=np.array([np.interp(us,np.linspace(0,1,len(movement)),movement[:,axis]) for axis in range(3)]).T
                    source=dict(source,key=binding['key'])
                key=(source['kind'],source['side'],source.get('key',''))
                offsets[key]=offsets.get(key,np.zeros_like(movement))+movement
            diagnostics.append(dict(rule=r['id'],amount=amount))
    # One physical eyebrow may use several overlapping material cards. A
    # portable edit authored on a single-card model must move those cards
    # together. Explicit edits to another card still take precedence.
    explicit=dict(offsets)
    for entry in rig.snapshot['entries']:
        key=(entry['kind'],entry['side'],entry['key'])
        if entry['kind']!='BROW' or not entry.get('enabled',True) or key in controlled:continue
        cloud=samples(entry['points']);matches=[]
        for source in rig.snapshot['entries']:
            source_key=(source['kind'],source['side'],source['key'])
            if source['kind']!='BROW' or source['side']!=entry['side'] or source_key not in explicit:continue
            base=samples(source['points']);span=max(float(np.ptp(base[:,0])),1e-9)
            overlap=min(cloud[:,0].max(),base[:,0].max())-max(cloud[:,0].min(),base[:,0].min())
            if overlap<.7*max(span,float(np.ptp(cloud[:,0]))):continue
            line=B.Line(base);projections=[line.project(p) for p in cloud]
            us=np.array([p[0] for p in projections]);distance=np.linalg.norm(cloud-np.array([line.sample(u) for u in us]),axis=1)
            if np.quantile(distance,.9)>span*.08:continue
            matches.append((float(np.mean(distance)),source_key,us))
        if matches:
            _,source_key,us=min(matches,key=lambda row:row[0]);movement=explicit[source_key]
            offsets[key]=np.array([np.interp(us,np.linspace(0,1,len(movement)),movement[:,axis]) for axis in range(3)]).T
    rig.custom_offsets=offsets;rig.custom_controls=custom;rig.custom_rule_report=diagnostics;rig.custom_rule_targets=rule_targets
    # Restore per-expression accessory inputs, so a custom recipe cannot leak
    # changes into the next expression in the same generation batch.
    if not hasattr(rig,'_custom_original_entries'):
        rig._custom_original_entries={e['key']:copy.deepcopy(e['points']) for e in rig.snapshot['entries']}
        rig._custom_lash_lines=dict(rig.lash_lines);rig._custom_field=rig.field
    rig.lash_lines=dict(rig._custom_lash_lines);rig.field=rig._custom_field
    for e in rig.snapshot['entries']:
        e['points']=copy.deepcopy(rig._custom_original_entries[e['key']])
        key=(e['kind'],e['side'],e['key'])
        if key not in offsets or e['kind'].startswith(('EYE','LIP')):continue
        e['points']=(samples(e['points'])+offsets[key]).tolist()
        if e['kind']=='LASH_LINE' and e['side'] in rig.lash_lines:
            rig.lash_lines[e['side']]=(rig.lash_lines[e['side']][0],B.Line(e['points']))
    rig.lashes=G.units(rig.snapshot,'TARGET',[],rig.info['points'],rig.rings) if rig.snapshot.get('process_lashes',True) else []
    rig.lashes=[unit for unit in rig.lashes if unit['side'] in rig.rings]
    # Per-expression curve edits rebuild units, but must not discard the
    # physical band/seam ownership resolved when the rig was constructed.
    for unit in rig.lashes:
        unit['band_vertices']=sorted(set(unit.get('band_vertices',[]))|(set(unit['vertices'])-rig.strands))
    if custom:
        from .region_deformation import SkinDisplacementField
        pins={i for rows in rig.rows.values() for i,u,upper in rows}|rig.inactive_pins|rig.creases
        pins.update(i for entry,movement in custom for i in entry['vertices'])
        skin={i for i,labels in enumerate(rig.members) if 0 in labels}
        rig.field=SkinDisplacementField(rig.points,rig.info['faces'],rig.info['labels'],skin,pins)
        rig.field.set_triangles([tri for tri,f in rig.mesh_triangles if rig.info['labels'][f]==0])
    for kind,side,key in offsets:
        if (kind.startswith('EYE') or kind in ('CREASE','LASH_LINE','LASH')) and str(side) not in recipe['eyes']:
            recipe['eyes'][str(side)]=dict(upper=np.zeros((17,3)),lower=np.zeros((17,3)),closure=0.,blink=0.,lower_share=.1,smile=0.,flat=0.)
        if kind.startswith('LIP') and not recipe['mouth']:recipe['mouth']={branch:np.zeros((17,3)) for branch in ('upper','lower')}
        if kind=='BROW' and str(side) not in recipe['brows']:recipe['brows'][str(side)]=np.zeros((3,3))
        if kind=='TONGUE' and not recipe.get('tongue'):recipe['tongue']=dict(centerline=np.zeros((3,3)),width_gain=1.,protrusion=0.)
        if kind=='TONGUE':
            extension=max(float(np.max(-offsets[kind,side,key][:,1])),0.)/max(rig.widths.get(('LIP',0),1),1e-9)
            recipe['tongue']['protrusion']=max(recipe['tongue'].get('protrusion',0),min(extension,1.))


def offset(rig,kind,side,u):
    result=np.zeros(3)
    for (k,s,key),points in rig.custom_offsets.items():
        if k==kind and s==side:
            result+=np.array([np.interp(u,np.linspace(0,1,len(points)),points[:,axis]) for axis in range(3)])
    return result


def apply_controls(rig,delta):
    protected={i for rows in rig.rows.values() for i,u,upper in rows}
    for entry,movement in rig.custom_controls:
        line=B.Line(entry['points'])
        for i in entry['vertices']:
            if i in protected:continue
            u=line.project(rig.original_points[i])[0]
            delta[i]+=np.array([np.interp(u,np.linspace(0,1,len(movement)),movement[:,axis]) for axis in range(3)])
    return delta


def capture_curves(rig,delta):
    result=[];posed=rig.points+delta
    if not hasattr(rig,'_expression_curve_bindings'):rig._expression_curve_bindings={}
    for entry in rig.snapshot['entries']:
        if not entry.get('enabled',True):continue
        ids=[i for i in entry.get('vertices',[]) if 0<=i<len(posed)]
        kind=entry['kind'];side=entry['side']
        if kind.startswith(('EYE','LIP')):
            part='EYE' if kind.startswith('EYE') else 'LIP';upper=kind.endswith('UPPER')
            ids=[i for i,u,up in rig.rows.get((part,side),[]) if bool(up)==upper]
        if not ids:continue
        if entry['key'] not in rig._expression_curve_bindings:
            base=np.asarray(entry['base']);line=B.Line(base)
            parameters=np.array([line.project(rig.original_points[i])[0] for i in ids])
            unique,inverse=np.unique(parameters,return_inverse=True)
            rig._expression_curve_bindings[entry['key']]=(unique,inverse,np.bincount(inverse),samples(base))
        unique,inverse,counts,neutral=rig._expression_curve_bindings[entry['key']]
        movement=posed[ids]-rig.original_points[ids]
        average=np.array([np.bincount(inverse,weights=movement[:,axis])/counts for axis in range(3)]).T
        ts=np.linspace(0,1,65)
        target=neutral+np.array([np.interp(ts,unique,average[:,axis]) for axis in range(3)]).T
        original=copy.deepcopy(entry)
        original['points']=copy.deepcopy(rig._custom_original_entries[entry['key']])
        result.append(dict(entry=Rules.plain(original),points=target.tolist(),neutral=neutral.tolist()))
    return result
