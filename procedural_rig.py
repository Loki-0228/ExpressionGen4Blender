"""Target-only partitions, editable curves and geometry bindings."""
import json
import numpy as np
import bpy
from mathutils import Vector,Matrix
from . import region_blender as A,region_core as C,region_contours as O,region_guides as G
from .region_transfer import mesh_regions,memberships
from .region_deformation import SkinDisplacementField
from . import procedural_binding as B,region_detection as D
from . import procedural_tongue as Tongue
from . import procedural_anatomy as Anatomy
from . import region_accessories as Accessories


def analyze(ob, transform=None, surface_support=False):
    A.check_mesh(ob)
    points=[v.co.copy() for v in (ob.data.shape_keys.reference_key.data if ob.data.shape_keys else ob.data.vertices)]
    if transform is not None:points=[transform@point for point in points]
    faces=[list(p.vertices) for p in ob.data.polygons];labels=mesh_regions(ob);members=memberships(ob,labels)
    skin=[i for i,row in enumerate(members) if 0 in row]
    if not skin:raise ValueError('目标缺少 Face 分区，请先标记面部')
    plane=(min(points[i].x for i in skin)+max(points[i].x for i in skin))/2
    width=max(points[i].x for i in skin)-min(points[i].x for i in skin)
    holes=O.face_openings(faces,labels,points);eyes={};mouth=None;warnings=[];methods={}
    boundary_eyes,boundary_mouth=D.boundary_features(holes,[points[i] for i in skin])
    anatomy=Anatomy.detect(points,faces,labels,plane)
    for side in (-1,1):
        cloud=[]
        for label in (3,7,5):
            cloud=[p for i,p in enumerate(points) if label in members[i] and (1 if p.x>=plane else -1)==side]
            if len(cloud)>=3:break
        if len(cloud)<3:
            strips=[face for face,label in zip(faces,labels) if label==2
                    and (1 if np.mean([points[i].x for i in face])>=plane else -1)==side]
            islands=D.components(points,strips) if strips else []
            if islands:cloud=[points[i] for i in max(islands,key=lambda r:len(r['faces']))['ids']]
        opening,method=D.opening_for_region(holes,points,faces,labels,cloud,width)
        if side in anatomy:
            globe_opening=Anatomy.opening(holes,anatomy[side],width)
            if globe_opening is not None:opening,method=globe_opening,'convex_globe_aperture'
        if not opening and not cloud and side in boundary_eyes:
            opening=boundary_eyes[side];method='paired_face_boundaries'
        if opening:eyes[side]=O.EyeRing(opening);methods['eye_'+str(side)]=method
        elif cloud:warnings.append(('X 正侧' if side>0 else 'X 负侧')+'未找到可靠眼缘；已检查 Face 边界和内凹表面')
    oral=[p for i,p in enumerate(points) if set(members[i])&{8,9,12}]
    mouth_details={}
    opening,method=D.opening_for_region(holes,points,faces,labels,oral,width,mouth=True,details=mouth_details)
    if not opening and not oral and boundary_mouth:
        opening,method=D.opening_for_region(holes,points,faces,labels,boundary_mouth,width,mouth=True,details=mouth_details)
    if opening:
        support=mouth_details.get('surface_faces')
        surface_labels=labels if support is None else [label if i in support else -1 for i,label in enumerate(labels)]
        mouth=O.LipRing(opening,surface=(points,faces,surface_labels));methods['mouth']=method
        methods['lip_branches']=mouth.branch_method
    elif method=='unreliable_open_mouth':
        warnings.append('口洞边界位于内侧或前方脸皮连接不可靠，未用深处边界生成嘴唇；请检查 Face 的唇缘分区与法线')
    elif oral:warnings.append('未找到可靠嘴唇轮廓；已检查 Face 边界和内凹表面，不要求单独 Mouth 分区')
    parts=[0]*len(points);lash_faces=[face for face,label in zip(faces,labels) if label==2]
    for side,ring in eyes.items():
        cloud=[p for i,p in enumerate(points) if 2 in members[i] and (1 if p.x>=plane else -1)==side]
        split=O.brow_lash_split(cloud,ring.points)
        split=split if split is not None else max(p.z for p in ring.points)+ring.frame.height*.15
        for i,part in O.brow_lash_parts(points,lash_faces,split,plane,side).items():parts[i]=part
    ownership=Accessories.resolve(points,lash_faces,parts,plane,eyes,surface_support=surface_support)
    parts=ownership['parts'];warnings.extend(ownership['warnings'])
    # Detached skin strips above an eye are also editable crease candidates.
    skin_faces=[face for face,label in zip(faces,labels) if label==0]
    _,components=C.topology(skin_faces)
    biggest=max((len(c['faces']) for c in components),default=0)
    for component in components:
        if len(component['faces'])>=max(biggest*.2,20):continue
        ids=sorted({i for f in component['faces'] for i in skin_faces[f]});cloud=np.array([points[i] for i in ids])
        center=cloud.mean(0);side=1 if center[0]>=plane else -1;ring=eyes.get(side)
        if ring and np.ptp(cloud[:,0])<ring.frame.width*1.4 and np.ptp(cloud[:,2])<ring.frame.height*.5:
            offset=center[2]-ring.sample(ring.locate(Vector(center),True)[0],True).z
            if 0<offset<ring.frame.height*.6:
                for i in ids:parts[i]=2
    lookup={id(p):i for i,p in enumerate(points)}
    rows={('EYE',side):[(lookup[id(p)],*ring.parameter(k)) for k,p in enumerate(ring.points)] for side,ring in eyes.items()}
    if mouth:rows['LIP',0]=[(lookup[id(p)],*mouth.parameter(k)) for k,p in enumerate(mouth.points)]
    return dict(points=points,faces=faces,labels=labels,members=members,plane=plane,width=width,
                eyes=eyes,mouth=mouth,parts=parts,rows=rows,warnings=warnings,
                detection_methods=methods,eye_anatomy=anatomy,present_regions=sorted(set(labels)-{-1,-2}),
                accessory_ownership=ownership)


def detect(ob,process_lashes=None,*,fill_lashes=True,recover_lashes=False):
    A.merge_eye_regions(ob)
    G.apply_working_transforms(ob,ob)
    previous=G.find(ob,ob)
    if process_lashes is None:process_lashes=bool(previous.get('ek_process_individual_lashes',True)) if previous else True
    info=analyze(ob,surface_support=fill_lashes or recover_lashes)
    marked=[]
    repair_lines={}
    if previous and previous.get('ek_guide_geometry')==G.fingerprint(ob,ob,None,include_regions=False):
        for guide in previous.all_objects:
            entry=json.loads(guide.get('ek_guide_entry','{}'))
            if entry.get('kind')=='LASH' and G.is_active(guide):
                entry['_edited']=G.edited(guide,ob);marked.append(entry)
            if recover_lashes and entry.get('kind')=='LASH_LINE' and G.is_active(guide) and not G.edited(guide,ob):
                supported={i for row in info['accessory_ownership']['components']
                           if row['side']==entry['side'] and row.get('reason')=='eyelid_surface_support'
                           for i in row['vertices']}
                if supported-set(entry.get('vertices',[])):repair_lines[entry['key']]=guide
    entries,_=G.detection_entries(info['points'],info['points'],info['faces'],info['faces'],info['parts'],info['parts'],
        info['plane'],info['plane'],info['eyes'],info['eyes'],info['mouth'],info['mouth'],
        source_labels=info['labels'],target_labels=info['labels'],detect_lashes=bool(process_lashes and fill_lashes),marked_lashes=marked,
        source_ownership=info['accessory_ownership'],target_ownership=info['accessory_ownership'])
    entries=[entry for entry in entries if entry['role']=='TARGET']
    tongue=[i for i,labels in enumerate(info['members']) if 12 in labels]
    if len(tongue)>=3:
        cloud=np.array([info['points'][i] for i in tongue]);lo,hi=np.min(cloud[:,1]),np.max(cloud[:,1]);line=[]
        for y in np.linspace(hi,lo,7):
            ids=np.argsort(abs(cloud[:,1]-y))[:max(3,len(cloud)//7)]
            center=cloud[ids].mean(0);center[1]=y;line.append(center.tolist())
        entry=dict(key='TARGET:TONGUE:0',role='TARGET',kind='TONGUE',side=0,points=line,vertices=tongue)
        entry['fit']=G.F.fit(line,'CREASE');entries.append(entry)
    if not entries:raise ValueError('未找到可生成的检查曲线：'+'；'.join(info['warnings'] or ['请检查 Face 的表面结构和现有分区']))
    collection,report=G.capture(ob,ob,None,entries,Matrix.Identity(4),
        retire_lashes=bool(process_lashes and fill_lashes),preserve_shapes=not fill_lashes)
    for entry in entries:
        if entry['key'] in repair_lines:G.set_curve_shape(repair_lines[entry['key']],ob,entry)
    collection['ek_procedural_guides']=True
    collection['ek_process_individual_lashes']=process_lashes
    collection['ek_accessory_ownership']=json.dumps(info['accessory_ownership']['components'],ensure_ascii=False)
    # Explicit detection may adopt the new ownership policy. Merely generating
    # from an older saved collection must not discard its existing lash faces.
    if (fill_lashes or previous is None or 'ek_accessory_policy' in collection) and not (
            recover_lashes and previous is not None and 'ek_accessory_policy' in collection):
        collection['ek_accessory_policy']=json.dumps(dict(
            version=1,unresolved_vertices=sorted({
                i for row in info['accessory_ownership']['components']
                if row['kind']=='UNRESOLVED' for i in row['vertices']})))
    return collection,dict(report,warnings=info['warnings'],methods=info['detection_methods'],
                           eye_anatomy=Anatomy.summary(info['eye_anatomy']),present_regions=info['present_regions'])


def checkpoint(ob,collection,process_lashes=None,*,recover_lashes=False):
    # Reconcile every generation: curves never created are filled, known
    # deleted keys remain suppressed, and edited existing curves are retained.
    # Individual lashes are optional marks, never a required missing curve.
    # Generation does not discover fresh strands after the artist edited them.
    collection,_=detect(ob,process_lashes,fill_lashes=False,recover_lashes=recover_lashes)
    return collection,G.checkpoint(collection,ob,ob,None)


class Rig:
    def __init__(self,ob,snapshot,close_mouth=True):
        import copy
        snapshot=copy.deepcopy(snapshot)
        self.ob=ob;self.info=analyze(ob, surface_support=True);self.points=np.array(self.info['points']);self.snapshot=snapshot
        # An unresolved accessory must not silently re-enter the lash solver.
        # Explicit artist-authored guides still take precedence over detection.
        explicit={i for e in snapshot['entries'] if e.get('enabled',True)
                  and e.get('role')=='TARGET' and e.get('kind') in ('LASH','BROW','CREASE','LASH_LINE')
                  for field in ('vertices','lower_vertices','band_vertices')
                  for i in e.get(field,[])}
        policy=snapshot.get('accessory_policy',{})
        uncertain=(set(policy.get('unresolved_vertices',[]))-explicit
                   if policy.get('version')==1 else set())
        self.recovered_lash_groups=[r for r in self.info['accessory_ownership']['components'] if r['kind'] == 'LASH' and set(r['vertices']) & set(policy.get('unresolved_vertices', []))]
        self.recovered_lash_vertices={i for r in self.recovered_lash_groups for i in r['vertices'] if i in uncertain}
        uncertain-=self.recovered_lash_vertices
        if uncertain:
            self.info['labels']=[-2 if label==2 and all(i in uncertain for i in face) else label
                                 for face,label in zip(self.info['faces'],self.info['labels'])]
            self.info['members']=[labels-{2} if i in uncertain else labels
                                  for i,labels in enumerate(self.info['members'])]
        self.inactive_pins=set();self.incomplete={}
        suppressed={(e['kind'],int(e['side'])) for e in snapshot.get('suppressed',[]) if e['role']=='TARGET'}
        for (kind,side),rows in list(self.info['rows'].items()):
            missing=[kind+suffix for suffix in ('_UPPER','_LOWER')
                     if not G.entries_for(snapshot,'TARGET',kind+suffix,side)]
            if kind=='EYE' and ('LASH_LINE',side) in suppressed:missing.append('LASH_LINE')
            if missing:
                self.inactive_pins.update(i for i,u,upper in rows)
                self.incomplete[kind,side]='缺少或已删除必要曲线：'+', '.join(missing)
                del self.info['rows'][kind,side]
                if kind=='EYE':self.info['eyes'].pop(side,None)
                else:self.info['mouth']=None
        if self.info['mouth']:
            self.info['mouth'],self.info['rows']['LIP',0]=B.guide_lips(self.info,snapshot)
        from .procedural_neutral import closed_neutral
        self.original_points=self.points.copy()
        self.points,self.neutral_report=closed_neutral(self.info,snapshot) if close_mouth else (self.points,{'changed':False,'reason':'disabled'})
        self.members=self.info['members'];self.rows=dict(self.info['rows']);self.rings=dict(self.info['eyes'])
        self.eye_anatomy=self.info['eye_anatomy']
        self.guides={};self.guide_lines={};self.bind_lines={};self.widths={};self.heights={};self.accessories=[];self.warnings=list(self.info['warnings'])
        for (kind,side),rows in self.rows.items():
            ring=self.info['mouth'] if kind=='LIP' else self.rings[side]
            self.widths[kind,side]=ring.frame.width
            branches={}
            for upper in (True,False):
                entries=G.entries_for(snapshot,'TARGET',kind+('_UPPER' if upper else '_LOWER'),side)
                if not entries:raise ValueError('缺少有效的目标检查曲线：'+kind)
                branches[upper]=entries[0]
            self.guides[kind,side]=branches
            lines={upper:B.Line(entry['points']) for upper,entry in branches.items()}
            self.guide_lines[kind,side]=lines
            # Keep each mesh vertex at its original position along the rule.
            # Reprojecting onto an edited curve cancels part of the edit and
            # makes vertices slide between sections when a handle is moved.
            self.bind_lines[kind,side]={upper:B.Line(entry['base']) for upper,entry in branches.items()}
            self.rows[kind,side]=B.bind_rows(self.original_points,rows,self.bind_lines[kind,side])
            cloud=np.concatenate([line.points for line in lines.values()])
            self.widths[kind,side]=max(float(np.ptp(cloud[:,0])),1e-9)
            self.heights[kind,side]=max(float(np.ptp(cloud[:,2])),1e-9)
        self.lash_lines={};self.lash_sections={}
        for side in self.rings:
            entries=G.entries_for(snapshot,'TARGET','LASH_LINE',side)
            if entries:
                raw_base=B.Line(entries[0]['base'])
                # Mesh samples can alternate between opposite edges of a
                # thick strip. Subtracting that zigzag from every section
                # imprints its inverse on an otherwise smooth expression.
                controls=B.fit_bezier(raw_base.points,raw_base.parameters)
                base=B.Line(B.bezier(controls,np.linspace(0,1,129)))
                raw_current=B.Line(entries[0]['points'])
                edited_controls=B.fit_bezier(raw_current.points,raw_current.parameters)
                current=B.Line(B.bezier(edited_controls,np.linspace(0,1,129)))
                self.lash_lines[side]=(base,current)
                x,inverse=np.unique(base.points[:,0],return_inverse=True)
                parameters=np.bincount(inverse,base.parameters)/np.bincount(inverse)
                self.lash_sections[side]=(x,parameters)
        self.lashes=G.units(snapshot,'TARGET',[],self.info['points'],self.rings) if snapshot.get('process_lashes',True) else []
        self.lashes=[unit for unit in self.lashes if unit['side'] in self.rings]
        band={i for unit in self.lashes for i in unit.get('band_vertices',[])}
        band.update(G.supported_band_vertices(snapshot['entries'],self.info['accessory_ownership']))
        self.strands={i for unit in self.lashes for i in unit['vertices']}-band
        self.brows=set();self.creases=set()
        manual_lash_ids={i for e in snapshot['entries'] if e.get('role')=='TARGET'
                        and e.get('kind')=='LASH' and e.get('enabled',True) and e.get('manual')
                        for i in e.get('vertices',[])}
        for entry in snapshot['entries']:
            if entry['role']!='TARGET' or not entry.get('enabled',True):continue
            if entry['kind'] in ('BROW','CREASE'):
                ids=[i for i in entry.get('vertices',[]) if i<len(self.points) and i not in manual_lash_ids]
                if not ids:continue
                self.accessories.append((entry['side'],entry['kind'],ids,entry))
                (self.brows if entry['kind']=='BROW' else self.creases).update(ids)
        # UV seams and double-sided cards may duplicate the same material
        # point. Shared band roots must remain band roots on every copy.
        from mathutils.kdtree import KDTree
        lash_ids=[i for i,labels in enumerate(self.members) if 2 in labels and i not in self.brows|self.creases] if self.rings else []
        tree=KDTree(len(lash_ids))
        for i in lash_ids:tree.insert(Vector(self.points[i]),i)
        tree.balance();visited=set();self.lash_stitches=[]
        tolerance=max((self.widths.get(('EYE',side),0.) for side in self.rings),default=1e-6)*1e-6
        for i in lash_ids:
            if i in visited:continue
            group=sorted(j for co,j,d in tree.find_range(Vector(self.points[i]),tolerance))
            visited.update(group)
            if len(group)<2:continue
            self.lash_stitches.append(group)
            if set(group)-self.strands:
                band.update(group);self.strands.difference_update(group)
        for unit in self.lashes:
            unit['band_vertices']=sorted(set(unit.get('band_vertices',[]))|(set(unit['vertices'])&band))
        self.lash_upper={}
        lash_faces=[face for face,label in zip(self.info['faces'],self.info['labels']) if label==2]
        for island in C.topology(lash_faces)[1]:
            ids=sorted({i for f in island['faces'] for i in lash_faces[f]}-self.brows-self.creases)
            if not ids:continue
            side=1 if self.points[ids,0].mean()>=self.info['plane'] else -1
            if side not in self.rings:continue
            branches=[bool(self.rings[side].locate(Vector(self.points[i]))[1]) for i in ids]
            share=float(np.mean(branches))
            # A thick upper strip's lower edge/tips can fall nearer the lower
            # rim at a canthus. Move that strip coherently, not two directions
            # within one cross-section. A full eye loop keeps both branches.
            if share>=.7 or share<=.3:
                self.lash_upper.update((i,share>=.7) for i in ids)
        for side in self.rings:
            for entry in G.entries_for(snapshot,'TARGET','LASH_LINE',side):
                self.lash_upper.update((i,True) for i in entry.get('vertices',[]) if 0<=i<len(self.points) and i not in self.brows|self.creases)
                self.lash_upper.update((i,False) for i in entry.get('lower_vertices',[]) if 0<=i<len(self.points) and i not in self.brows|self.creases)
        for unit in self.lashes:self.lash_upper.update((i,True) for i in unit['vertices'])
        supported_hosts={r['id'] for r in self.info['accessory_ownership']['components']
                         if r.get('reason')=='eyelid_surface_support'}
        corner_groups=[r for r in self.info['accessory_ownership']['components'] if r.get('parent') in supported_hosts]
        self.lash_return_groups=[]
        for group in {r['id']:r for r in self.recovered_lash_groups+corner_groups}.values():
            side=group['side'];ids=group['vertices']
            # A returned corner is a whole card, even when a few vertices
            # cross the upper locator. Do not split its two edges between
            # opposite eyelid transports after rebuilding the locator.
            lower_return=(not group.get('is_band') and group.get('parent') is not None
                and np.mean([self.rings[side].locate(Vector(self.points[i]))[1] for i in ids])<=.3)
            if group.get('surface_upper') is False or lower_return:
                self.lash_upper.update((i,False) for i in group['vertices'] if i not in manual_lash_ids)
            extent=np.ptp(self.points[ids],axis=0)
            hanging=extent[2]>extent[0]*1.2 and extent[2]>self.widths['EYE',side]*.06
            if lower_return and hanging and group in corner_groups and not set(ids)&manual_lash_ids:
                self.lash_return_groups.append(group)
        self.lash_return_vertices={i for group in self.lash_return_groups for i in group['vertices']}
        for group in self.lash_stitches:
            side=1 if self.points[group[0],0]>=self.info['plane'] else -1
            if side not in self.rings:continue
            upper=self.rings[side].locate(Vector(self.points[group[0]]))[1]
            # Preserve authored main-band ownership if any alias has it.
            upper=any(self.lash_upper.get(i,upper) for i in group)
            self.lash_upper.update((i,upper) for i in group)
        pins={i for rows in self.rows.values() for i,u,upper in rows}|self.inactive_pins
        skin={i for i,labels in enumerate(self.members) if 0 in labels}
        self.field=SkinDisplacementField(self.points,self.info['faces'],self.info['labels'],skin,pins|self.creases)
        ob.data.calc_loop_triangles()
        self.mesh_triangles=[(tuple(t.vertices),t.polygon_index) for t in ob.data.loop_triangles]
        # A separate double-lid strip may share the lash partition without a
        # dedicated CREASE guide. It follows the main strip, never contributes
        # a second centreline to its thickness/style/fold fit.
        self.upper_followers=set();self.upper_follower_groups=[]
        for side in self.rings:
            # A skin crease guide does not cover a second detached eyeliner
            # crease. Weld seam topology first, then classify whole islands.
            # Find physical islands before removing strand triangles. Cutting
            # out joined tips first fragments one ribbon into false creases.
            faces=[list(t) for t,f in self.mesh_triangles if self.info['labels'][f]==2
                   and not set(t)&(self.brows|self.creases)
                   and (1 if self.points[list(t),0].mean()>=self.info['plane'] else -1)==side
                   ]
            representative={i:min(group) for group in self.lash_stitches for i in group}
            _,islands=C.topology([[representative.get(i,i) for i in face] for face in faces])
            groups=[]
            for island in islands:
                triangles=np.asarray([faces[f] for f in island['faces']]);cloud=self.points[triangles]
                ids=sorted(set(triangles.ravel()))
                if np.mean([self.lash_upper.get(i,self.rings[side].locate(Vector(self.points[i]))[1]) for i in ids])<.5:continue
                if len(set(ids)-self.strands)<3:continue
                area=float(np.linalg.norm(np.cross(cloud[:,1]-cloud[:,0],cloud[:,2]-cloud[:,0]),axis=1).sum())
                groups.append((area,ids,triangles))
            if len(groups)>1:
                primary=max(groups,key=lambda row:row[0])
                from mathutils.bvhtree import BVHTree
                primary_surface=BVHTree.FromPolygons([Vector(p) for p in self.points],primary[2].tolist())
                for group in groups:
                    if group is primary:continue
                    # Front/back copies of a two-sided ribbon are one band.
                    distances=[primary_surface.find_nearest(Vector(self.points[i]))[3] for i in group[1]]
                    if np.quantile(distances,.8)<self.widths['EYE',side]*.02:continue
                    ids=sorted(set(group[1])-self.strands)
                    if len(ids)<3:continue
                    self.upper_followers.update(ids);self.upper_follower_groups.append((side,ids))
        self.field.set_triangles([tuple(t.vertices) for t in ob.data.loop_triangles if self.info['labels'][t.polygon_index]==0])
        from .procedural_skin import EyelidSkin
        self.eye_skin=EyelidSkin(self)
        self.oral_parts={}
        mouth=self.info['mouth'];height=mouth.frame.center.z if mouth else float(np.median(self.points[:,2]))
        for label,kind in ((8,'mouth'),(9,'teeth')):
            faces=[i for i,l in enumerate(self.info['labels']) if l==label]
            selected=[self.info['faces'][i] for i in faces];_,components=C.topology(selected)
            groups={'upper':[],'lower':[]}
            for component in components:
                indices=[faces[f] for f in component['faces']]
                ids={i for f in indices for i in self.info['faces'][f]}
                branch='upper' if np.mean(self.points[list(ids),2])>=height else 'lower'
                attribute=ob.data.attributes.get('ek_procedural_oral_group')
                for f in indices:
                    override=attribute.data[f].value if attribute else 0
                    groups['upper' if override>0 else 'lower' if override<0 else branch].append(f)
            # A single connected cavity remains one part; do not cut its mesh.
            for branch,indices in groups.items():
                if indices:self.oral_parts[kind+'_'+branch]=indices
        self.tongue=[i for i,labels in enumerate(self.members) if 12 in labels and 0 not in labels] if G.entries_for(snapshot,'TARGET','TONGUE',0) and self.info['mouth'] else []
        self.points,self.tongue_report=Tongue.neutral(self)
        if self.tongue_report['reason']=='ambiguous_tongue_plane':
            self.warnings.append('舌头的主体平面不明确，Basis 保留原姿态，请检查 Tongue 分区')
        self.triangles=[tuple(t.vertices) for t in ob.data.loop_triangles if self.info['labels'][t.polygon_index] in (0,2)]
        from . import procedural_cavity as Cavity
        Cavity.prepare(self)
        from . import procedural_contacts as Contacts
        self.points,contact=Contacts.tongue_side(self,self.points,self.cavity_points)
        self.tongue_report.update(contact)
        self.tongue_report['changed']|=contact['tongue_cavity_shift']>1e-10
        # Eyes/teeth retain their rest spacing. Only the lining fits the lip
        # seam; a detached tongue levels by one rigid transform, never a scale.

    def parameter(self,kind,side,upper,point):
        return self.bind_lines[kind,side][bool(upper)].project(point)[0]

    def lash_transport(self,side,point,lid,closure=0.,shape_preserve=0.,flat=0.):
        """Sweep the original cross-section along the posed upper-lid curve."""
        pair=self.lash_lines.get(side)
        if pair is None:return None
        base,current=pair
        # A near-vertical canthus is longitudinal curve geometry, not one
        # tall X section. Project along its rest arc so it can turn with the
        # closed lid without collapsing or hanging below that lid.
        u=base.project(point)[0]
        preserve=float(np.clip(shape_preserve,0,1))
        open_motion=getattr(lid,'open_motion',{})
        if open_motion:flat=max(flat,float(open_motion.get('upper_flatten',0.)))
        flat=float(np.clip(flat,0,1));preserve*=1-flat
        key=(side,lid,float(closure),preserve,flat)
        if key not in self.lash_pose_curves:
            from .procedural_lashes import slope_follow_weight
            neutral_eye=B.Line(self.guides['EYE',side][True]['base'])
            neutral_lower=B.Line(self.guides['EYE',side][False]['base'])
            parameters=np.linspace(0,1,65);samples=[];offsets=[];anchors=[];lid_points=[]
            apex=float(base.parameters[np.argmax(base.points[:,2])])
            for t in parameters:
                anchor=current.sample(t)
                eye_u=neutral_eye.project(base.sample(t))[0]
                # Relative to the generated rest eye, not the edited eye.
                # Subtracting the edited curve cancels the artist's correction.
                offset=anchor-neutral_eye.sample(eye_u)
                # Preserve horizontal extension and depth, but close onto
                # the actual facial seam. The old vertical tail offset cannot
                # override the closed lid, even at full shape preservation.
                offset[2]*=1-float(np.clip(closure,0,1))
                offsets.append((t,offset[1],0.))
                lid_point=lid(eye_u,True)
                target=lid_point+offset
                # A wing becomes progressively owned by the lower orbital
                # curve as it turns vertical. Past vertical it must not lose
                # that ownership merely because the X tangent changes sign.
                direction=-1. if t<apex else 1.
                tangent=(base.sample(min(t+.02,1))-base.sample(max(t-.02,0)))*direction
                outward=np.sign(base.sample(0. if t<apex else 1.)[0]-base.sample(apex)[0]) or 1.
                follow=slope_follow_weight(tangent,outward)
                lower_u=neutral_lower.project(base.sample(t))[0]
                old=neutral_lower.sample(lower_u)
                def lower_curve(v):return lid(v,False)
                before=B.spatial_frame(neutral_lower.sample,lower_u);after=B.spatial_frame(lower_curve,lower_u)
                rotated=lower_curve(lower_u)+(after@before.T)@(anchor-old)
                translated=anchor+lower_curve(lower_u)-old
                # An open-eye lower-curve tangent can turn sharply while its
                # canthus stays fixed. Rotating the entire upper attachment
                # about it drove the inner Face rim through the nose. Opening
                # follows its displacement; closing progressively folds it.
                folding=float(np.clip(closure,0,1))
                folding=folding*folding*(3-2*folding)
                lower_target=translated*(1-folding)+rotated*folding
                # Keep authored transverse depth and let the final contact
                # solve fit it; orientation controls the in-plane wing here.
                target=(1-follow)*target+follow*lower_target
                samples.append(target);anchors.append(anchor);lid_points.append(lid_point)
            samples=np.asarray(samples);anchors=np.asarray(anchors);lid_points=np.asarray(lid_points)
            # During partial closure preserve the character's outline;
            # complete closure has the stronger facial-curve target.
            movement=samples-anchors;translation=np.mean(movement[8:-8],axis=0)
            keep=preserve*float(np.clip(closure,0,1))*(1-float(np.clip(closure,0,1)))
            samples[:,[0,2]]=anchors[:,[0,2]]+(1-keep)*movement[:,[0,2]]+keep*translation[[0,2]]
            if flat:
                gap=float(np.median(samples[8:-8,2]-lid_points[8:-8,2]))
                samples[:,2]=(1-flat)*samples[:,2]+flat*(lid_points[:,2]+gap)
            if open_motion:
                count=13 if open_motion.get('upper_flatten',0.)>.5 else 7
                matrix=B.spline_basis(parameters,count)
                bending=np.diff(np.eye(count),n=2,axis=0)
                posed=np.linalg.solve(matrix.T@matrix+.06*bending.T@bending+np.eye(count)*1e-12,matrix.T@samples)
            else:posed=B.fit_bezier(samples,parameters)
            self.lash_pose_curves[key]=(posed,B.fit_bezier(offsets,parameters)[:,1])
        posed,offsets=self.lash_pose_curves[key]
        def center(t):
            # One analytic XYZ curve, including the canthus extension.
            # Replacing Y with a clamped eyelid profile creates a derivative
            # jump where the wing extends past the facial aperture.
            return B.bezier(posed,t) if len(posed)==4 else (B.spline_basis([t],len(posed))@posed)[0]
        # Section folding uses the FINAL lower rim in procedural_lashes.
        # Shape preservation controls the planar arc, never the inward fold.
        before=base.sample(min(u+.02,1))-base.sample(max(u-.02,0))
        after=center(min(u+.02,1))-center(max(u-.02,0))
        angle=np.arctan2(before[2],before[0])-np.arctan2(after[2],after[0]);c,s=np.cos(angle),np.sin(angle)
        transform=np.array(((c,0.,s),(0.,1.,0.),(-s,0.,c)))
        return center(u)+transform@(np.asarray(point)-base.sample(u)),transform,np.array((1.,0.,0.))

    def lash_position(self,side,point,lid,closure=0.,shape_preserve=0.,flat=0.):
        transport=self.lash_transport(side,point,lid,closure,shape_preserve,flat)
        return transport[0] if transport is not None else None

    def curve(self,kind,side,upper,u):
        entry=self.guides[kind,side][bool(upper)]
        point=np.array(G.sample(entry['points'],u))
        if kind=='LIP' and self.neutral_report['changed']:
            rows=self.rows[kind,side]
            for i,w in O.lip_weights(rows,u,upper):point+=(self.points[i]-self.original_points[i])*w
        return point

    def neutral(self,kind,side,upper,u):
        entry=self.guides[kind,side][bool(upper)]
        return np.array(G.sample(entry['base'],u))

    def tongue_entry(self):
        return next((e for e in self.snapshot['entries'] if e['kind']=='TONGUE' and e.get('enabled',True)),None)
