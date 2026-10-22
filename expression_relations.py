"""Dependency-aware expression solving, partial meshes, and bilateral reuse."""
import copy
import numpy as np
from . import expression_rules as Rules,procedural_atoms as E,procedural_symmetry as Sym
from . import expression_runtime as Custom,procedural_constraints as Q,procedural_lashes as Lashes
from . import procedural_contacts as Contacts,procedural_cavity as C,region_guides as G


def smooth(value):
    t=np.clip(value,0,1);return t*t*t*(10-15*t+6*t*t)


def mask(rig,relation):
    points=rig.points;result=np.ones(len(points));width=max(rig.info['width'],1e-9)
    if relation['mode']=='SIDE':
        return smooth((points[:,0]-rig.info['plane'])*relation['side']/(width*.04))
    lo=rig.original_points.min(0);span=np.maximum(np.ptp(rig.original_points,axis=0),1e-12)
    normalized=(rig.original_points-lo)/span
    for row in relation['conditions']:
        value=normalized[:,row['axis']];a,b=row['min'],row['max'];fade=max(min((b-a)*.2,.02),1e-9)
        part=np.ones(len(points))
        if a>0:part*=smooth((value-a)/fade)
        if b<1:part*=smooth((b-value)/fade)
        region=row.get('region',-2)
        if region!=-2:
            selected=np.array([region in memberships for memberships in rig.members]);part*=selected
            # Fade inside region seams; never split a shared mesh vertex.
            boundary=set()
            for f in rig.info['faces']:
                if any(not selected[i] for i in f):boundary.update(i for i in f if selected[i])
            part[list(boundary)]=0.
            for _ in range(3):
                next_part=part.copy()
                for f in rig.info['faces']:
                    floor=min(part[f]);next_part[f]=np.minimum(next_part[f],floor+.25)
                part=next_part*selected
        result*=part
    return result


def baked_oral(rig,recipe,shapes):
    result={kind:value.copy() for kind,value in shapes.items()}
    for kind in rig.oral_parts:
        if not kind.startswith('teeth_'):continue
        ids,center,rotation,translation=C.part_pose(rig,recipe,kind)
        shape=result.setdefault(kind,np.zeros_like(rig.points));points=rig.original_points[ids]+shape[ids]
        shape[ids]=(points-center)@rotation.T+center+translation-rig.original_points[ids]
    return result


def available(rig,recipe):
    family=recipe.get('family')
    if (family in ('mouth','tongue','jaw') or Rules.has_channels(recipe,'mouth','mouth_reference','mouth_targets','tongue','jaw')) and not rig.info['mouth']:
        raise ValueError(rig.incomplete.get(('LIP',0),'缺少可靠的嘴唇边界'))
    if any(int(s) not in rig.rings for s in recipe.get('eyes',{})):raise ValueError('该表情所需的眼部校正曲线不完整')
    if recipe.get('brows') and (not rig.brows or any(e['kind']=='BROW' and str(e['side']) in recipe['brows'] for e in rig.snapshot.get('suppressed',[]))):raise ValueError('该表情所需的眉毛校正曲线不完整')
    if (family=='tongue' or recipe.get('tongue')) and not rig.tongue:raise ValueError('缺少舌头分区或校正曲线')


def repair(rig,delta,recipe,shapes):
    """Recheck blended geometry using the same face and internal contacts."""
    delta,lip=Q.lower_lip_depth(rig,delta,recipe)
    delta,profiles,quality=Q.finalize_skin(rig,delta,recipe);quality.update(lip)
    eye_shape,eye_quality=Q.closed_eye_stack(rig,delta,recipe);quality.update(eye_quality)
    shapes['_eyes']=eye_shape
    delta,attachment=Lashes.conform_band(rig,delta,recipe);quality.update(attachment)
    delta,contact=Lashes.skin_behind_band(rig,delta,recipe);quality.update(contact)
    delta,shapes,oral=Contacts.finish(rig,delta,recipe,shapes);quality.update(oral)
    minimum,rest=Q.minimum_areas(rig.points,delta,rig.triangles)
    quality['unresolved']=int(np.count_nonzero((rest>1e-14)&(minimum<rest*.005)))
    quality['unresolved']+=sum(quality.get(key,0) for key in ('eye_depth_limited_vertices','eye_immovable_overlaps','lash_skin_depth_conflicts','oral_face_unresolved','tongue_cavity_unresolved','tongue_teeth_unresolved'))
    quality['unresolved']+=quality.get('lash_attachment_conflicts',0)+quality.get('lash_path_contact_conflicts',0)
    return delta,shapes,quality


class Solver:
    def __init__(self,rig,profile,lower_lid_scale=1.,force_symmetry=False):
        self.rig=rig;self.profile=profile;self.scale=lower_lid_scale;self.force=force_symmetry
        self.recipes={r['name']:r for r in profile['recipes']};self.cache={};self.stack=set()

    def solve(self,recipe,weight=1.,allow_symmetry=True):
        key=G.digest((Rules.plain(recipe),weight,allow_symmetry))
        if key in self.cache:
            delta,effective,shapes,quality,curves=self.cache[key]
            self.rig.last_oral_deformation=shapes;self.rig.last_expression_curves=curves
            return delta,copy.deepcopy(effective),shapes,dict(quality,dependency_cache_reused=True),curves
        if key in self.stack:raise ValueError('表情存在循环引用：'+recipe['name'])
        if len(self.stack)>=16:raise ValueError('表情依赖超过 16 层')
        self.stack.add(key)
        try:
            result=self.derived(recipe,weight) if recipe.get('relation') else self.independent(recipe,weight,allow_symmetry)
            followers=getattr(self.rig,'face_followers',None)
            if followers is not None and len(followers.vertices):
                delta,effective,shapes,quality,curves=result
                # Mirroring and filtered combinations may alter the finished
                # host after its solve. Keep every Face layer in that pose.
                delta=followers.apply(delta)
                quality=dict(quality,face_follower_vertices=len(followers.vertices))
                result=delta,effective,shapes,quality,Custom.capture_curves(self.rig,delta)
            delta,effective,shapes,quality,curves=result
            delta,contact=Lashes.fit_rigid_contact(self.rig,delta,effective)
            quality=dict(quality,**contact)
            quality.update(Lashes.audit_attachment(self.rig,delta,effective))
            quality.update(Lashes.audit_connections(self.rig,delta))
            quality.update(Lashes.audit_closed_band(self.rig,delta,effective))
            result=delta,effective,shapes,quality,Custom.capture_curves(self.rig,delta)
            self.cache[key]=result
            self.rig.last_oral_deformation=result[2];self.rig.last_expression_curves=result[4]
            return result
        finally:self.stack.remove(key)

    def independent(self,recipe,weight,allow_symmetry):
        rig=self.rig;available(rig,recipe)
        effective=E.merge([recipe],[weight]);effective['name']=recipe['name']
        for eye in effective.get('eyes',{}).values():
            if eye.get('smile',0.)>.5:
                eye['lash_shape_preserve']=float(getattr(rig,'style_options',{}).get('smile_preserve',eye.get('lash_shape_preserve',.85)))
        force=self.force and allow_symmetry and Sym.eligible(recipe)
        half=Sym.half_recipe(rig,effective) if force else None
        solved=half if half is not None else effective
        delta,quality=E.solve(rig,solved,self.profile,self.scale);shapes=rig.last_oral_deformation
        effective['oral']=copy.deepcopy(rig.last_oral_poses)
        quality.update(symmetry_applied=False,symmetry_half_reused=False)
        if force:
            # Bake bone travel before mirroring, so teeth also reflect their
            # final position instead of applying an asymmetric bone afterward.
            source_shapes=baked_oral(rig,effective,shapes)
            mirrored,mirrored_shapes,applied,reason=Sym.mirror(rig,delta,source_shapes)
            if applied:
                delta=mirrored;shapes=mirrored_shapes
                effective['baked_oral_source']=copy.deepcopy(effective.get('oral',{}));effective['oral']={}
                # The positive side has already completed contacts and style
                # constraints. Copy that result exactly; do not average it
                # with a second solve or run an asymmetric repair afterward.
                minimum,rest=Q.minimum_areas(rig.points,delta,rig.triangles)
                conflicts=int(np.count_nonzero((rest>1e-14)&(minimum<rest*.005)))
                quality['symmetry_constraint_conflicts']=conflicts
                quality['unresolved']=max(quality.get('unresolved',0),conflicts)
                if reason:quality['symmetry_note']=reason
                if conflicts:quality['symmetry_note']='已镜像正侧最终坐标；原网格差异导致局部翻折，需检查'
                quality.update(symmetry_applied=applied,symmetry_half_reused=half is not None)
                quality['symmetry_surface_vertices']=getattr(rig,'last_symmetry_surface_vertices',0)
                rig.last_expression_curves=Custom.capture_curves(rig,delta)
            else:quality['symmetry_note']=reason+'，已逐侧计算'
        effective['can_symmetrize']=recipe.get('can_symmetrize',False);effective['special']=recipe.get('special',False)
        return delta,effective,shapes,quality,copy.deepcopy(rig.last_expression_curves)

    def derived(self,recipe,weight):
        weight*=recipe.get('relation_weight',1.)
        relation=recipe['relation'];rig=self.rig;embedded=recipe.get('relation_recipes',{})
        def source(name):
            value=embedded.get(name) or self.recipes.get(name)
            if value is None:raise ValueError('来源表情不存在：'+name)
            return value
        terms=relation['terms'] if relation['mode']=='COMBINATION' else [dict(source=relation['source'],weight=1.)]
        sources=[source(t['source']) for t in terms if t.get('weight',1)>0]
        weights=[float(t.get('weight',1))*weight for t in terms if t.get('weight',1)>0]
        # Compose unmasked actions in rule space so blink closure stays bounded.
        if relation['mode']=='COMBINATION' and all(not r.get('relation') for r in sources) and not recipe.get('custom_rules'):
            for original in sources:available(rig,original)
            effective=E.merge(sources,weights);effective.update(name=recipe['name'],can_symmetrize=False)
            delta,quality=E.solve(rig,effective,self.profile,self.scale)
            effective['oral']=copy.deepcopy(rig.last_oral_poses)
            # Sources carry their own controls. Do not replay those inherited
            # controls a second time as edits on the combination itself.
            effective['custom_rules']=[]
            effective['relation']=copy.deepcopy(relation);effective['relation_recipes']={r['name']:Rules.plain(r) for r in sources}
            effective['relation_weight']=weight
            return delta,effective,rig.last_oral_deformation,quality,copy.deepcopy(rig.last_expression_curves)
        # A one-sided eye/brow action is selected before solving. This also
        # avoids computing its other eye when the parent is not selected.
        if relation['mode']=='SIDE' and len(sources)==1 and not sources[0].get('relation') and not recipe.get('custom_rules'):
            parent=sources[0]
            if not Rules.has_channels(parent,'mouth','mouth_reference','mouth_targets','tongue','jaw','oral','custom_rules'):
                subset=copy.deepcopy(parent);side=str(relation['side']);subset['name']=recipe['name']
                for key in ('eyes','brows'):subset[key]={s:v for s,v in subset.get(key,{}).items() if s==side}
                subset['can_symmetrize']=False
                delta,effective,shapes,quality,curves=self.independent(subset,weight,False)
                effective['relation']=copy.deepcopy(relation);effective['relation_recipes']={parent['name']:Rules.plain(parent)};effective['relation_weight']=weight
                return delta,effective,shapes,quality,curves
        results=[self.solve(r,w,False) for r,w in zip(sources,weights)]
        selection=mask(rig,relation) if relation['mode']!='COMBINATION' else np.ones(len(rig.points))
        divisor=max(sum(weights),1.) if relation['mode']=='COMBINATION' else 1.
        delta=sum((r[0] for r in results),np.zeros_like(rig.points))*selection[:,None]/divisor
        shapes={}
        for values in results:
            for kind,shape in baked_oral(rig,values[1],values[2]).items():
                shapes[kind]=shapes.get(kind,np.zeros_like(delta))+shape*selection[:,None]/divisor
        effective=E.merge([r[1] for r in results],[1/divisor]*len(results));effective.update(name=recipe['name'],oral={})
        if relation['mode']=='SIDE':
            for channel in ('eyes','brows'):effective[channel]={s:v for s,v in effective[channel].items() if s==str(relation['side'])}
        effective['custom_rules']=copy.deepcopy(recipe.get('custom_rules',[]))
        Custom.evaluate(rig,effective)
        if effective['custom_rules']:
            extra=np.zeros_like(delta)
            for entry in rig.snapshot['entries']:
                line=E.B.Line(entry['base'])
                for i in entry.get('vertices',[]):
                    u=line.project(rig.original_points[i])[0]
                    extra[i]+=Custom.offset(rig,entry['kind'],entry['side'],u)
            delta+=rig.field.deform(Custom.apply_controls(rig,extra))
        # Shared lip attachment uses the selected facial rim, including filter
        # boundaries. Recompute lining after composing dental travel.
        rig.last_teeth_deformation={k:v for k,v in shapes.items() if k.startswith('teeth_')}
        cavity,cavity_quality=C.deform(rig,delta,effective);shapes.update(cavity)
        delta,shapes,quality=repair(rig,delta,effective,shapes)
        quality['unresolved']+=cavity_quality.get('cavity_unresolved_overlaps',0)+cavity_quality.get('cavity_depth_limited_vertices',0)
        quality['source_unresolved']=sum(r[3].get('unresolved',0) for r in results)
        quality['unresolved']+=quality['source_unresolved']
        quality['relation_mode']=relation['mode'];quality['relation_blend_divisor']=divisor
        effective.update(relation=copy.deepcopy(relation),relation_recipes={r['name']:Rules.plain(r) for r in sources},relation_weight=weight,can_symmetrize=False)
        return delta,effective,shapes,quality,Custom.capture_curves(rig,delta)
