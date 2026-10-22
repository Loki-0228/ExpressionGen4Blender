"""Keep oral parts behind facial skin and one tongue surface above the lining."""
import numpy as np
from . import procedural_surfaces as S,procedural_cavity as C
from . import procedural_lips as Lips
from .region_deformation import SkinDisplacementField
from .generation_progress import notify


def mouth_skin(rig,points):
    if ('LIP',0) not in rig.rows:return []
    # Connected mouth skin includes the slanted/return lip faces. Filtering
    # by current normal sign discarded exactly those collision obstacles.
    return Lips.prepare(rig)['faces']


def oral_face(rig,delta,recipe,shapes,dental_only=False):
    """Repair internal geometry; skin/lip targets and cavity attachments stay fixed."""
    report=dict(oral_face_contacts=0,oral_face_unresolved=0,dental_contact_rigid=0.,dental_contact_flex=0.)
    if not rig.oral_parts or ('LIP',0) not in rig.rows:return shapes,report
    result={kind:np.asarray(value).copy() for kind,value in shapes.items()}
    skin=mouth_skin(rig,rig.points+delta)
    if not skin:return result,report
    skin=np.asarray(skin,dtype=np.int32);width=rig.widths['LIP',0]
    for kind,faces in rig.oral_parts.items():
        if kind.startswith('teeth_')!=dental_only:continue
        face_set=set(faces);triangles=[list(t) for t,f in rig.mesh_triangles if f in face_set]
        if not triangles:continue
        ids,center,rotation,translation=C.part_pose(rig,recipe,kind)
        dental=kind.startswith('teeth_');base=rig.original_points if dental else rig.cavity_points
        shape=result.setdefault(kind,np.zeros_like(delta));freedom=np.zeros(len(delta));freedom[ids]=1.
        if not dental:freedom[list(rig.cavity_links)]=0.
        budget=width*.35;used=np.zeros(len(delta))
        rigid_used=0.
        # A calibrated reference may move the row toward the lips. Contact
        # may cancel that forward travel before spending the small allowance
        # behind its rest depth; otherwise correct Z motion can pierce skin.
        calibrated=dental and recipe.get('dental_reference')
        rigid_budget=width*.025
        if calibrated:
            # Keep a calibrated row rigid. Bound travel by the larger of
            # the dental arch and mouth: a broad row behind a narrow mouth
            # must not be bent or lifted just because the lip width is small.
            span=max(width,float(np.ptp(base[ids,0])))
            rigid_budget=span*.065+max(-float(translation[1]),0.)
            if Lips.closed_reference(recipe):
                rim=sorted({i for i,u,up in rig.rows['LIP',0]})
                narrowing=max(0.,1-float(np.ptp((rig.points+delta)[rim,0]))/width)
                # A closing/narrowing lip wraps around the arch. Permit a
                # little more rigid clearance when the swept skin needs it;
                # a closed recipe alone never causes a dental translation.
                rigid_budget+=span*min(.035,narrowing*.1)
        if dental:
            if not hasattr(rig,'dental_contact_fields'):rig.dental_contact_fields={}
            if kind not in rig.dental_contact_fields:
                polygons=[rig.info['faces'][f] for f in faces]
                rig.dental_contact_fields[kind]=SkinDisplacementField(base,polygons,[0]*len(polygons),ids,(),fidelity=.08)
            field=rig.dental_contact_fields[kind]
        for iteration in range(4):
            correction=np.zeros(len(delta));blocked=0
            for number,t in enumerate(np.linspace(1/16,1,16),1):
                notify(rig,'牙齿与面部接触' if dental else '口腔与面部接触',number,16)
                posed=base+shape*t
                if dental:
                    current_rotation=C.rotation_at(rotation,t)
                    posed=posed.copy();posed[ids]=(posed[ids]-center)@current_rotation.T+center+translation*t
                obstacle=(rig.points+delta*t)[skin]
                change,missed=S.depth_bounds(posed,triangles,obstacle,freedom,front=False,coherent=True,pulse=getattr(rig,'progress',None))
                blocked+=missed
                if dental:
                    direction=np.array((0.,1.,0.))@rotation
                    response=float((direction@current_rotation.T)[1])*t
                    if response>1e-8:correction=np.maximum(correction,change/response)
                    elif np.any(change>width*1e-8):blocked+=1
                else:correction=np.maximum(correction,change/t)
            remaining=int(np.count_nonzero(correction>width*1e-7))
            if not remaining:
                report['oral_face_unresolved']+=blocked;break
            if iteration==3:
                report['oral_face_unresolved']+=blocked+remaining;break
            if dental:
                # Calibrated rows stay rigid; general rows may also use
                # bounded local flex. Store both before the jaw rotation.
                amount=min(float(correction.max()),max(rigid_budget-rigid_used,0.))
                shape[ids]+=direction*amount;rigid_used+=amount
                correction=np.maximum(correction-amount,0.)*freedom
                room=np.maximum(width*.04-used,0.)*freedom
                local=np.zeros_like(correction) if calibrated else C.smooth_depth(field,correction,room)
                # Avoid creating new folded dental triangles while relieving
                # contact. Remaining collisions are rechecked next iteration.
                from .procedural_constraints import minimum_areas
                baseline,_=minimum_areas(base,shape,triangles)
                _,rest_area=minimum_areas(base,np.zeros_like(shape),triangles)
                healthy=(rest_area>1e-14)&(baseline>=rest_area*.005)
                gain=1.
                for _ in range(12):
                    candidate=shape+local[:,None]*direction*gain
                    minimum,_=minimum_areas(base,candidate,triangles)
                    if not np.any(healthy&(minimum<rest_area*.005)):break
                    gain*=.5
                else:gain=0.
                local*=gain
                if amount<=width*1e-9 and np.max(local)<=width*1e-9:
                    report['oral_face_unresolved']+=blocked+remaining;break
                shape+=local[:,None]*direction;used+=local
                report['oral_face_contacts']+=len(ids) if amount>width*1e-9 else int(np.count_nonzero(local>width*1e-9))
                report['dental_contact_rigid']=max(report['dental_contact_rigid'],rigid_used)
                report['dental_contact_flex']=max(report['dental_contact_flex'],float(used.max()))
            else:
                room=np.maximum(budget-used,0.)*freedom
                correction=C.smooth_depth(rig.cavity_field,correction,room)
                correction*=freedom
                if np.max(correction)<=width*1e-9:
                    report['oral_face_unresolved']+=blocked+remaining;break
                shape[:,1]+=correction;used+=correction
                report['oral_face_contacts']+=int(np.count_nonzero(correction>width*1e-8))
    return result,report


def tongue_contact_limit(rig):
    """Small contact travel measured on this tongue, not the whole face."""
    length=float(np.ptp(rig.points[rig.tongue,1])) if rig.tongue else 0.
    return min(length*.12,rig.widths.get(('LIP',0),0.)*.08)


def tongue_side(rig,points,cavity,origin=None,move=True):
    """Keep the upward tongue sheet above the original lower cavity wall.

    A common Z translation retains tongue thickness. The opposite tongue
    sheet is deliberately not constrained against the upper mouth wall.
    """
    report=dict(tongue_cavity_shift=0.,tongue_cavity_unresolved=0)
    if not rig.tongue:return points,report
    tongue=[];floor=[];original=rig.original_points
    ceiling=float(original[rig.tongue,2].max())
    for tri,f in rig.mesh_triangles:
        cloud=points[list(tri)];label=rig.info['labels'][f]
        if label==12:
            normal=np.cross(cloud[1]-cloud[0],cloud[2]-cloud[0])
            if normal[2]>1e-15:tongue.append(list(tri))
        elif label==8 and float(original[list(tri),2].mean())<=ceiling:
            old=original[list(tri)];normal=np.cross(old[1]-old[0],old[2]-old[0])
            if abs(normal[2])>abs(normal[1])*.25:floor.append(list(tri))
    if not tongue or not floor:return points,report
    # Shared lip/lining vertices are anchors, not independent tongue geometry.
    independent=[i for i in rig.tongue if not ({0,8,9}&rig.members[i])]
    freedom=np.zeros(len(points));freedom[independent]=1.
    order=[0,2,1]
    change,blocked=S.depth_bounds(points[:,order],tongue,cavity[np.asarray(floor)][:,:,order],freedom,front=False,coherent=True)
    requested=float(change.max());limit=tongue_contact_limit(rig)
    if origin is not None and independent:
        limit=max(limit-float(np.max(points[independent,2]-origin[independent,2])),0.)
    if not move:limit=0.
    shift=min(requested,limit);result=points.copy();result[independent,2]+=shift
    report.update(tongue_cavity_shift=shift,tongue_cavity_unresolved=blocked+int(requested>limit+1e-9))
    return result,report


def tongue_teeth(rig,points,recipe,origin,move=True):
    """Resolve actual intersecting triangles without copying dental travel.

    Projected overlap alone is insufficient: two surfaces may be far apart
    in depth. Only pairs whose depth difference changes sign need repair.
    A common translation keeps a detached tongue's size and thickness.
    """
    from . import procedural_tongue as Tongue
    report=dict(tongue_teeth_shift=0.,tongue_teeth_unresolved=0)
    if not rig.tongue:return points,report
    ids=[i for i in rig.tongue if not ({0,8,9}&rig.members[i])]
    triangles=np.asarray([tri for tri,f in rig.mesh_triangles if rig.info['labels'][f]==12],dtype=np.int32).reshape((-1,3))
    teeth=C.tooth_triangles(rig,recipe)
    if not ids or not len(triangles) or not len(teeth):return points,report
    freedom=np.zeros(len(points));freedom[ids]=1.
    lo=teeth.min(1);hi=teeth.max(1);plane=teeth[:,:,[0,2]]
    sign=-1. if Tongue.protrusion(recipe)>0 else 1.
    tolerance=max(rig.widths['LIP',0]*1e-7,1e-12)
    def contacts(posed):
        required=0.;crossings=0
        for first in range(0,len(triangles),128):
            notify(rig,'舌头与牙齿实际接触',first,len(triangles))
            local=triangles[first:first+128];cloud=posed[local]
            a,b=np.nonzero(np.all(cloud.min(1)[:,None]<=hi+tolerance,axis=-1)&
                           np.all(cloud.max(1)[:,None]>=lo-tolerance,axis=-1))
            if not len(a):continue
            wa,wb,valid=S.overlap_vertices(cloud[a][:,:,[0,2]],plane[b])
            depth=np.sum(wb*teeth[b,None,:,1],axis=-1)-np.sum(wa*cloud[a,None,:,1],axis=-1)
            crossing=(np.min(np.where(valid,depth,np.inf),axis=1)<-tolerance)&(np.max(np.where(valid,depth,-np.inf),axis=1)>tolerance)
            crossings+=int(np.count_nonzero(crossing))
            selected=valid&crossing[:,None]&(depth*sign>tolerance)
            mobility=np.sum(wa*freedom[local[a]][:,None,:],axis=-1)
            selected&=mobility>1e-8
            if np.any(selected):
                required=max(required,float(np.max(np.where(selected,depth*sign/np.maximum(mobility,1e-12),0.))))
        return required,crossings
    used=max(float(np.max((points[ids,1]-origin[ids,1])*sign)),0.)
    room=max(tongue_contact_limit(rig)-used,0.) if move else 0.
    result=points.copy();total=0.
    if not move:
        _,report['tongue_teeth_unresolved']=contacts(result)
        return result,report
    for _ in range(3):
        required,crossings=contacts(result)
        if not crossings or required<=tolerance:break
        step=min(required+tolerance,max(room-total,0.))
        if step<=tolerance:break
        result[ids,1]+=sign*step;total+=step
    _,remaining=contacts(result)
    report.update(tongue_teeth_shift=sign*total,tongue_teeth_unresolved=remaining)
    return result,report


def finish(rig,delta,recipe,shapes):
    report=dict(oral_face_contacts=0,oral_face_unresolved=0,tongue_cavity_shift=0.,tongue_cavity_unresolved=0,
                tongue_teeth_shift=0.,tongue_teeth_unresolved=0)
    if not Lips.active(rig,recipe) and not recipe.get('oral'):return delta,shapes,report
    shapes,dental_report=oral_face(rig,delta,recipe,shapes,dental_only=True)
    report.update({k:dental_report[k] for k in ('dental_contact_rigid','dental_contact_flex')})
    rig.last_teeth_deformation={key:value for key,value in shapes.items() if key.startswith('teeth_')}
    if dental_report['oral_face_contacts']:
        cavity,quality=C.deform(rig,delta,recipe);shapes.update(cavity)
        report['oral_face_unresolved']+=quality.get('cavity_unresolved_overlaps',0)+quality.get('cavity_depth_limited_vertices',0)
    shapes,skin_report=oral_face(rig,delta,recipe,shapes)
    for key in ('oral_face_contacts','oral_face_unresolved'):report[key]+=dental_report[key]+skin_report[key]
    cavity=rig.cavity_points.copy()
    for kind,faces in rig.oral_parts.items():
        if kind.startswith('mouth_') and kind in shapes:
            ids=sorted({i for f in faces for i in rig.info['faces'][f]});cavity[ids]+=shapes[kind][ids]
    from . import procedural_tongue as Tongue
    delta,size_report=Tongue.limit_size(rig,delta,recipe);report.update(size_report)
    if not rig.tongue:return delta,shapes,report
    # Repeated repairs share one travel allowance; a recheck cannot reset it.
    origin=rig.points+delta;exterior_conflicts=0
    for _ in range(2):
        before=delta[rig.tongue].copy()
        posed,contact=tongue_side(rig,rig.points+delta,cavity,origin,move=Tongue.protrusion(recipe)<=0)
        report['tongue_cavity_shift']+=contact['tongue_cavity_shift']
        posed,teeth=tongue_teeth(rig,posed,recipe,origin)
        report['tongue_teeth_shift']+=teeth['tongue_teeth_shift']
        delta[rig.tongue]=posed[rig.tongue]-rig.points[rig.tongue]
        delta,exterior=Tongue.keep_exterior(rig,delta,recipe)
        exterior_conflicts=exterior['tongue_exterior_conflicts']
        delta,bounded=Tongue.limit_size(rig,delta,recipe)
        report['tongue_size_limited']|=bounded['tongue_size_limited']
        report['tongue_size_gain']=min(report['tongue_size_gain'],bounded['tongue_size_gain'])
        if np.max(abs(delta[rig.tongue]-before))<1e-12:break
    # Validate after alternating repairs without spending another allowance.
    delta=Tongue.support_lower(rig,delta,recipe)
    _,contact=tongue_side(rig,rig.points+delta,cavity,origin,move=False)
    _,teeth=tongue_teeth(rig,rig.points+delta,recipe,origin,move=False)
    report['tongue_cavity_unresolved']=contact['tongue_cavity_unresolved']+exterior_conflicts
    report['tongue_teeth_unresolved']=teeth['tongue_teeth_unresolved']
    if 'tongue_final_span' in report:report['tongue_final_span']=np.ptp((rig.points+delta)[rig.tongue],axis=0).tolist()
    return delta,shapes,report
