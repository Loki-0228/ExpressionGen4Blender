"""Versioned, declarative expression recipes; no Blender dependency or eval."""
import copy,json,math,re
from functools import lru_cache
from pathlib import Path
import numpy as np

FORMAT='ExpressionGen.expression_rules'
LEGACY_FORMAT='ExpressionKit.expression_rules'
SCHEMA_VERSION=1
FAMILIES=('eye','brow','mouth','tongue','jaw','custom')
KINDS=('EYE_UPPER','EYE_LOWER','LIP_UPPER','LIP_LOWER','BROW','CREASE','LASH_LINE','LASH','TONGUE','CUSTOM')
REGIONS=(-1,0,2,3,5,7,8,9,12)
METRICS=('center_x','center_y','center_z','span_x','span_y','span_z','length','aspect','boundary_loops','components','closed','vertices')
CONSTRAINTS=('face_fold','eye_depth','eyelid_direction','lash_attachment','closed_seam','lip_order','cavity_attachment','teeth_follow','tongue_exit')


def has_channels(recipe,*keys):
    """Channel presence works for both JSON lists and runtime NumPy arrays."""
    for key in keys:
        value=recipe.get(key)
        if isinstance(value,np.ndarray):
            if value.size:return True
        elif value is not None and bool(value):return True
    return False


def smirk_outline(reference,neutral,closed=False):
    """Reduce the whole vertical action, then shear both lips together."""
    curves={up:np.asarray(reference[up],dtype=float).copy() for up in ('upper','lower')}
    rest={up:np.asarray(neutral[up],dtype=float) for up in curves}
    if closed:
        middle=(curves['upper']+curves['lower'])*.5
        basis=(rest['upper']+rest['lower'])*.5
        curves={up:middle.copy() for up in curves};rest={up:basis for up in rest}
    for up,points in curves.items():
        points[:,2]=rest[up][:,2]+.70*(points[:,2]-rest[up][:,2])
    ends=(curves['upper'][[0,-1]]+curves['lower'][[0,-1]])*.5
    span=max(float(ends[1,0]-ends[0,0]),1e-12);center=float(ends[:,0].mean())
    slope=(.15-float(ends[1,2]-ends[0,2]))/span
    # One affine shear across the complete mouth. Both lips at a given X
    # receive the same shift, preserving the reduced opening and smoothness.
    for points in curves.values():points[:,2]+=slope*(points[:,0]-center)
    return {up:points.tolist() for up,points in curves.items()}


@lru_cache(maxsize=1)
def _builtin_profile():
    data=json.loads((Path(__file__).parent/'data/procedural_vody.json').read_text(encoding='utf8'))
    dental=json.loads((Path(__file__).parent/'data/dental_vody.json').read_text(encoding='utf8'))
    # Tooth islands can straddle the lip height. Their coherent Original
    # opening action identifies the row; centroid height alone mixed rows.
    for recipe in data['recipes']:
        if recipe['family'] not in ('mouth','tongue'):continue
        oral=recipe.setdefault('oral',{})
        for kind in ('teeth_upper','teeth_lower'):oral.pop(kind,None)
        oral.update(copy.deepcopy(dental['recipes'][recipe['name']]))
        recipe['dental_reference']=True
    # Explicit semantic corrections learned from user review. Keep the audited
    # reference samples unchanged on disk so their provenance remains clear.
    t=np.linspace(0,1,17)
    smile=next(r for r in data['recipes'] if r['name']=='にやり')
    smile_line=(np.asarray(smile['mouth_reference']['upper'])+np.asarray(smile['mouth_reference']['lower']))*.5
    middle=float(smile_line[len(smile_line)//2,2])
    smile_line[:,2]=middle+1.40*(smile_line[:,2]-middle)
    smile['mouth_reference']={branch:smile_line.tolist() for branch in ('upper','lower')}
    for recipe in data['recipes']:
        name=recipe['name']
        parent={'ウィンク':('笑い',1),'ウィンク右':('笑い',-1),
                'ウィンク２':('まばたき',1),'ウィンク２右':('まばたき',-1),
                'なごみ左':('なごみ',1),'なごみ右':('なごみ',-1)}.get(name)
        if recipe['family']=='brow' and name.endswith(('左','右')):parent=(name[:-1],1 if name.endswith('左') else -1)
        recipe['special']=name in ('てへぺろ','ぺろっ','にやり２','にやり３')
        recipe['can_symmetrize']=not parent and not recipe['special']
        if name in ('ん','ω','口角上げ','口角下げ','口横広げ','口横狭め','てへぺろ','ぺろっ'):
            # The reference's inner return strip has finite thickness. Its
            # extracted gap is not a request to expose teeth on a closed lip.
            ref=recipe['mouth_reference']
            seam=(np.asarray(ref['upper'])+np.asarray(ref['lower']))*.5
            recipe['mouth_reference']={branch:seam.tolist() for branch in ('upper','lower')}
        if parent:recipe['relation']=dict(mode='SIDE',source=parent[0],side=parent[1])
        if recipe.get('tongue'):
            # A depth adjustment to an internal tongue is not automatically
            # a protrusion. These two reference actions explicitly expose it.
            recipe['tongue']['protrusion']=1. if name in ('てへぺろ','ぺろっ') else 0.
            if name=='ぺろっ':recipe['tongue']['support_lip']='lower'
        for eye in recipe.get('eyes',{}).values():
            eye['smile']=1. if name in ('笑い','ウィンク','ウィンク右') else 0.
            eye['lash_shape_preserve']=.85 if eye['smile'] else 0.
            eye['flat']=1. if name in ('なごみ','なごみ左','なごみ右') else 0.
            if name in ('眼角上','眼角下','下眼上','睫下'):
                # These reference actions are independent controls, not blinks.
                eye['closure']=0.;eye['smile']=0.
            motions={
                'じと目':dict(upper_drop=.30,upper_bias=0.,upper_flatten=1.,lower_lift=0.,lower_flatten=0.,lower_fixed=1.),
                'ジト目':dict(upper_drop=.50,upper_bias=0.,upper_flatten=1.,lower_lift=0.,lower_flatten=0.,lower_fixed=1.),
                '悲しむ':dict(upper_drop=.28,upper_bias=.32,upper_flatten=0.,upper_peak=.30,upper_motion_scale=.75,lower_lift=.14,lower_flatten=0.,lower_fixed=0.),
                '怒り目':dict(upper_drop=.30,upper_bias=-.34,upper_flatten=0.,lower_lift=.10,lower_flatten=.65,lower_fixed=0.)}
            if name in motions:
                eye['open_motion']=motions[name];eye['closure']=0.;eye['blink']=0.
                eye['upper']=np.zeros((17,3)).tolist();eye['lower']=np.zeros((17,3)).tolist()
            if name=='びっくり':eye['sclera_aperture_follow']=1.
        if name in ('下眼上','睫下'):
            for side,eye in recipe['eyes'].items():
                ratio=data['neutral_eyes'][side]['width_height_ratio']
                movement=np.zeros((17,3))
                movement[:,2]=(.30 if name=='下眼上' else -.12)*ratio*4*t*(1-t)
                eye['lower' if name=='下眼上' else 'upper']=movement.tolist()
                eye['upper' if name=='下眼上' else 'lower']=np.zeros((17,3)).tolist()
        if name in ('にやり','にやり２','にやり３'):
            # The second smile is the first smile's closed shape with a tilt,
            # not the wider outline from the old second reference.
            source=smile if name=='にやり２' else recipe
            neutral=data['mouth_reference_basis']
            if name!='にやり':recipe['mouth_reference']=smirk_outline(source['mouth_reference'],neutral,closed=name=='にやり２')
            if name=='にやり２':recipe['oral']=copy.deepcopy(smile['oral'])
            if name=='にやり３' and recipe.get('tongue',{}).get('rigid_reference'):
                rigid=recipe['tongue']['rigid_reference']
                rigid['translation']=(np.asarray(rigid['translation'])*.70).tolist()
            # Keep the fallback displacement samples consistent with the
            # reference outline used by the normal generation path.
            recipe['mouth']={}
            for branch,values in recipe['mouth_reference'].items():
                motion=np.asarray(values)-np.asarray(neutral[branch]);u=np.linspace(0,1,len(motion))
                recipe['mouth'][branch]=np.column_stack([np.interp(t,u,motion[:,axis]) for axis in range(3)]).tolist()
    # Tone down the complete action, including dental travel, so the lining
    # and teeth remain compatible with the smaller lip aperture.
    for recipe in data['recipes']:
        gain={'あ２':.70,'い１':.85,'い２':.85}.get(recipe['name'])
        if gain is None:continue
        for branch,values in recipe.get('mouth_reference',{}).items():
            rest=np.asarray(data['mouth_reference_basis'][branch])
            recipe['mouth_reference'][branch]=(rest+gain*(np.asarray(values)-rest)).tolist()
        for branch,values in recipe.get('mouth',{}).items():
            recipe['mouth'][branch]=(np.asarray(values)*gain).tolist()
        for pose in recipe.get('oral',{}).values():
            if 'translation' in pose:pose['translation']=(np.asarray(pose['translation'])*gain).tolist()
            if 'rotation' in pose:
                u,_,vh=np.linalg.svd(np.eye(3)+gain*(np.asarray(pose['rotation'])-np.eye(3)))
                pose['rotation']=(u@vh).tolist()
    data['feedback_revision']=45
    return data


def builtin_profile():return copy.deepcopy(_builtin_profile())


def plain(value):
    if isinstance(value,np.ndarray):return value.tolist()
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,dict):return {str(k):plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    return value


def topological(rows,dependencies):
    lookup={r['id']:r for r in rows}
    if len(lookup)!=len(rows):raise ValueError('规则或识别曲线 ID 重复')
    ordered=[];visiting=set();done=set()
    def visit(key):
        if key in done:return
        if key not in lookup:raise ValueError('引用不存在：'+str(key))
        if key in visiting:raise ValueError('不允许循环引用：'+str(key))
        visiting.add(key)
        for reference in dependencies(lookup[key]):visit(reference)
        visiting.remove(key);done.add(key);ordered.append(lookup[key])
    for key in lookup:visit(key)
    return ordered


def number(value,label,low=None,high=None):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):raise ValueError(label+'必须是有限数字')
    if low is not None and value<low or high is not None and value>high:raise ValueError(label+'超出允许范围')
    return value


def points(value):
    if not isinstance(value,list) or not 2<=len(value)<=257:raise ValueError('曲线需要 2～257 个三维采样点')
    for row in value:
        if not isinstance(row,list) or len(row)!=3:raise ValueError('曲线采样点必须包含 XYZ 三个值')
        for v in row:number(v,'归一化曲线坐标',-10,10)


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',value):raise ValueError('ID 必须由字母开头，仅含字母、数字和下划线，最多 64 字符')


def array(value,shape,label):
    try:a=np.asarray(value,dtype=float)
    except (TypeError,ValueError):raise ValueError(label+' 数值无效')
    if a.shape!=shape or not np.isfinite(a).all():raise ValueError(label+' 维度错误或包含无效数字')


def validate_base(recipe,depth):
    if not isinstance(recipe,dict):raise ValueError('基础配方必须是对象')
    if depth>8:raise ValueError('基础配方嵌套超过 8 层')
    if recipe.get('relation'):
        validate_relation(recipe['relation']);number(recipe.get('relation_weight',1),'依赖幅度',0,128)
        embedded=recipe.get('relation_recipes',{})
        if not isinstance(embedded,dict) or len(embedded)>32:raise ValueError('内嵌来源配方无效')
        for parent in embedded.values():validate_base(parent,depth+1)
    for key in ('eyes','mouth','brows','oral'):
        if not isinstance(recipe.get(key,{}),dict):raise ValueError('基础配方 '+key+' 必须是对象')
    if 'dental_reference' in recipe and not isinstance(recipe['dental_reference'],bool):
        raise ValueError('牙齿原始动作标记必须为布尔值')
    for side,eye in recipe.get('eyes',{}).items():
        if side not in ('-1','1'):raise ValueError('基础配方眼部侧别无效')
        for branch in ('upper','lower'):array(eye.get(branch),(17,3),'眼睑采样')
        for key in ('closure','lower_share','smile','flat','blink','lash_shape_preserve','sclera_aperture_follow'):number(eye.get(key,0),key,0,1)
        if 'open_motion' in eye:
            motion=eye['open_motion']
            if not isinstance(motion,dict):raise ValueError('睁眼动作参数必须是对象')
            for key in ('upper_drop','upper_flatten','lower_lift','lower_flatten','lower_fixed'):number(motion.get(key,0),key,0,1)
            number(motion.get('upper_bias',0),'上眼睑内外侧偏重',-1,1)
            if 'upper_peak' in motion:number(motion['upper_peak'],'上眼睑最高点',.2,.8)
            if 'upper_motion_scale' in motion:number(motion['upper_motion_scale'],'上眼睑动作幅度',0,1)
        number(eye.get('lash_pitch',0),'睫毛角度')
    for branch,value in recipe.get('mouth',{}).items():
        if branch not in ('upper','lower'):raise ValueError('基础配方嘴唇分支无效')
        array(value,(17,3),'嘴唇采样')
    for side,value in recipe.get('brows',{}).items():
        if side not in ('-1','1'):raise ValueError('基础配方眉毛侧别无效')
        if not isinstance(value,list) or not 1<=len(value)<=17:raise ValueError('眉毛系数数量无效')
        array(value,(len(value),3),'眉毛系数')
    for pose in recipe.get('oral',{}).values():
        array(pose.get('rotation'),(3,3),'口内旋转');array(pose.get('translation'),(3,),'口内位移')
    if not isinstance(recipe.get('baked_oral_source',{}),dict):raise ValueError('烘焙前口内配方必须是对象')
    for pose in recipe.get('baked_oral_source',{}).values():
        array(pose.get('rotation'),(3,3),'烘焙前口内旋转');array(pose.get('translation'),(3,),'烘焙前口内位移')
    if recipe.get('tongue'):
        t=recipe['tongue'];array(t.get('centerline'),(3,3),'舌头系数');number(t.get('width_gain'),'舌宽',0,10)
        if t.get('shape_reference'):
            ref=t['shape_reference'];points(ref.get('curve'))
            array(ref.get('basis_span_per_mouth'),(3,),'参考舌头尺寸')
            if min(ref['basis_span_per_mouth'])<=0:raise ValueError('参考舌头尺寸必须大于零')
            number(ref.get('width_gain'),'参考舌宽',.01,10)
            for key in ('tip_x','tip_depth','tip_height'):number(ref.get(key),'参考舌尖位置')
        if t.get('rigid_reference'):
            ref=t['rigid_reference'];array(ref.get('translation'),(3,),'舌头位移');array(ref.get('rotation'),(3,3),'舌头旋转')
        if 'protrusion' in t:number(t['protrusion'],'吐舌程度',0,1)
        if 'support_lip' in t and t['support_lip']!='lower':raise ValueError('舌头支撑嘴唇必须为 lower')
    if 'jaw' in recipe:array(recipe['jaw'],(3,),'下颌位移')
    refs=[r['reference'] for r in recipe.get('mouth_targets',[])]
    if recipe.get('mouth_reference'):refs.append(recipe['mouth_reference'])
    for ref in refs:
        for branch in ('upper','lower'):points(ref.get(branch))
    for item in recipe.get('mouth_targets',[]):number(item.get('weight'),'口型参考幅度',0,128)
    if len(recipe.get('custom_rules',[]))>128:raise ValueError('累计规则过多，请拆分表情')
    for spec in recipe.get('custom_rules',[]):validate(spec,depth+1)


def validate(spec,depth=0):
    if depth>8:raise ValueError('基础配方嵌套超过 8 层，请简化规则')
    if not isinstance(spec,dict) or spec.get('solver')!='curve_rules_v1':raise ValueError('不支持的自定义求解格式')
    if not isinstance(spec.get('name'),str) or not spec['name'].strip() or len(spec['name'].encode('utf-8'))>63 or spec['name']=='Basis':raise ValueError('表情名不能为空或 Basis，且 UTF-8 长度不能超过 63 字节')
    if spec.get('family') not in FAMILIES:raise ValueError('表情类别无效')
    if set(spec.get('constraints',[]))!=set(CONSTRAINTS):raise ValueError('自定义表情必须保留全部内置约束')
    for key in ('can_symmetrize','special'):
        if key in spec and not isinstance(spec[key],bool):raise ValueError(key+' 必须为布尔值')
    if spec.get('relation'):
        validate_relation(spec['relation'])
        for key in ('recognizers','rules','parameters'):
            if not isinstance(spec.get(key),list):raise ValueError('表情关系的 '+key+' 需保留为空列表')
        if spec.get('recognizers') or spec.get('rules') or spec.get('parameters'):
            raise ValueError('子表情和组合使用引用来源的规则；额外曲线修正请通过表情曲线副本保存')
        return spec
    builtin={r['name'] for r in _builtin_profile()['recipes']}
    if spec.get('base') and spec['base'] not in builtin:raise ValueError('基础表情必须是内置表情，不能循环继承自定义表情')
    for key in ('recognizers','rules','parameters'):
        if not isinstance(spec.get(key),list) or len(spec[key])>128:raise ValueError(key+' 必须是最多 128 项的列表')
        for row in spec[key]:
            if not isinstance(row,dict):raise ValueError(key+' 每项必须是对象')
            identifier(row.get('id'))
    if not spec['recognizers'] or not spec['rules']:raise ValueError('至少需要一条识别曲线和一条计算规则')
    parameters={p['id']:p for p in spec['parameters']}
    if len(parameters)!=len(spec['parameters']):raise ValueError('参数 ID 重复')
    for p in spec['parameters']:
        lo=number(p['min'],'参数下限',0,1);hi=number(p['max'],'参数上限',lo,1)
        number(p['default'],'参数默认值',lo,hi)
        if not isinstance(p.get('exposed'),bool):raise ValueError('参数 exposed 必须为布尔值')
    if not isinstance(spec.get('values',{}),dict):raise ValueError('参数值必须是对象')
    for key,value in spec.get('values',{}).items():
        if key not in parameters:raise ValueError('参数值引用不存在：'+key)
        number(value,'参数值',parameters[key]['min'],parameters[key]['max'])
    number(spec.get('weight',1),'规则幅度',0,128)
    if spec.get('base_recipe'):validate_base(spec['base_recipe'],depth)
    ids={r['id'] for r in spec['recognizers']}
    for r in spec['recognizers']:
        if r.get('mode') not in ('GUIDE','BOUNDARY','SECTION','DERIVED'):raise ValueError('不支持的识别方式')
        if r.get('kind') not in KINDS or r.get('region') not in REGIONS or r.get('side') not in (-1,0,1):raise ValueError('曲线部位、分区或左右侧无效')
        if r.get('mode')=='DERIVED' and not r.get('reference'):raise ValueError('派生曲线需要引用原始曲线')
        if r.get('mode')=='SECTION':
            if r.get('axis') not in (0,1,2):raise ValueError('截面轴无效')
            number(r.get('position'),'截面位置比例',0,1)
        if not isinstance(r.get('index',0),int) or r.get('index',0)<0:raise ValueError('候选序号必须为非负整数')
        array(r.get('offset',[0,0,0]),(3,),'派生曲线偏移')
        for v in r.get('offset',[0,0,0]):number(v,'派生曲线偏移',-2,2)
        if not isinstance(r.get('criteria',[]),list) or len(r.get('criteria',[]))>128:raise ValueError('识别条件最多 128 项')
        for c in r.get('criteria',[]):
            if c.get('metric') not in METRICS:raise ValueError('不支持的识别特点')
            if c.get('reference') and c['reference'] not in ids:raise ValueError('识别条件引用不存在')
            number(c['min'],'识别特点下限');number(c['max'],'识别特点上限',c['min'])
    topological(spec['recognizers'],lambda r:[v for v in [r.get('reference'),*[c.get('reference') for c in r.get('criteria',[])]] if v])
    rules={r['id']:r for r in spec['rules']}
    for r in spec['rules']:
        if r.get('source') not in ids:raise ValueError('计算规则的原始曲线不存在')
        if r.get('target_curve') and r.get('target_rule'):raise ValueError('目标曲线与目标规则只能指定一种')
        if r.get('target_curve') and r['target_curve'] not in ids:raise ValueError('目标曲线引用不存在')
        if not r.get('target_rule') and not r.get('target_curve'):points(r.get('target_points'))
        number(r.get('amount',1),'接近目标程度',0,1)
        if r.get('parameter') and r['parameter'] not in parameters:raise ValueError('规则参数引用不存在')
        if not isinstance(r.get('influences',[]),list) or len(r.get('influences',[]))>128:raise ValueError('影响项最多 128 项')
        for f in r.get('influences',[]):
            if f.get('metric') not in METRICS:raise ValueError('不支持的影响特点')
            if f.get('curve') and f['curve'] not in ids:raise ValueError('影响曲线引用不存在')
            if not f.get('curve') and f.get('region') not in REGIONS:raise ValueError('影响分区不存在')
            for field in ('input_min','input_max'):number(f[field],field)
            if f['input_max']<=f['input_min']:raise ValueError('影响输入上限必须大于下限')
            for field in ('output_min','output_max'):number(f[field],field,0,1)
    topological(spec['rules'],lambda r:[r['target_rule']] if r.get('target_rule') else [])
    return spec


def runtime_recipe(spec,recipes):
    validate(spec)
    if spec.get('relation'):
        return dict(name=spec['name'],family=spec['family'],eyes={},mouth={},brows={},oral={},
                    relation=copy.deepcopy(spec['relation']),can_symmetrize=False,special=spec.get('special',False))
    base=next((r for r in recipes if r['name']==spec.get('base')),None)
    result=copy.deepcopy(spec.get('base_recipe') or base) if (spec.get('base_recipe') or base) else dict(eyes={},mouth={},brows={},oral={})
    result.update(name=spec['name'],family=spec['family'],can_symmetrize=spec.get('can_symmetrize',False),special=spec.get('special',False))
    own=copy.deepcopy(spec);own.pop('base_recipe',None)
    result.setdefault('custom_rules',[]).append(own)
    return result


def validate_relation(relation):
    if not isinstance(relation,dict) or relation.get('mode') not in ('SIDE','FILTER','COMBINATION'):raise ValueError('表情关系类型无效')
    if relation['mode']=='COMBINATION':
        terms=relation.get('terms')
        if not isinstance(terms,list) or not 1<=len(terms)<=32:raise ValueError('组合需包含 1～32 个表情')
        for term in terms:
            if not isinstance(term,dict) or not isinstance(term.get('source'),str) or not term['source']:raise ValueError('组合来源不能为空')
            number(term.get('weight',1),'组合权重',0,1)
        if not any(t.get('weight',1)>0 for t in terms):raise ValueError('组合至少有一项权重大于零')
    else:
        if not isinstance(relation.get('source'),str) or not relation['source']:raise ValueError('子表情来源不能为空')
        if relation['mode']=='SIDE' and relation.get('side') not in (-1,1):raise ValueError('请选择子表情左右侧')
        if relation['mode']=='FILTER':
            conditions=relation.get('conditions')
            if not isinstance(conditions,list) or not 1<=len(conditions)<=32:raise ValueError('网格子表情需要 1～32 条筛选条件')
            for row in conditions:
                if row.get('region',-2) not in (*REGIONS,-2):raise ValueError('筛选分区无效')
                if row.get('axis') not in (0,1,2):raise ValueError('筛选坐标轴无效')
                lo=number(row.get('min'),'位置比例下限',0,1);number(row.get('max'),'位置比例上限',lo,1)


def dependencies(recipe):
    relation=recipe.get('relation',{})
    if not relation:return []
    return ([t['source'] for t in relation['terms']] if relation['mode']=='COMBINATION' else [relation['source']])


def validate_library(custom):
    names=[s['name'] for s in custom]
    if len(set(names))!=len(names):raise ValueError('自定义表情名称重复')
    for spec in custom:validate(spec)
    lookup={r['name']:r for r in _builtin_profile()['recipes']};lookup.update({s['name']:s for s in custom})
    topological([dict(id=name,recipe=recipe) for name,recipe in lookup.items()],lambda row:dependencies(row['recipe']))
    return custom


CRITERIA=[
 ('输入','当前可见分区与校正曲线','按当前标记读取；已删除必要曲线所依赖的表情跳过','procedural_rig.checkpoint'),
 ('眼部目标','眼睑动作与角色曲率','按眼宽和眼高归一化；普通闭眼反射当前上眼缘曲率，笑闭眼保留上拱','procedural_atoms.character_arc'),
 ('眼缘拟合','有界曲线拟合','上下缘共用闭眼接缝；上缘向下、水平下缘不下降且上移上限 30%，笑眼弧顶额外 10%。闭眼内眼角允许下降，但不低于原始下眼睑横向主体，并略微上提。笑眼保持上拱，なごみ保持直线；边界冲突则跳过并说明原因','procedural_atoms.solve'),
 ('嘴型目标','嘴唇及口型参考','按口宽适配目标轮廓，保留上下唇拓扑归属','procedural_atoms.mouth_outline'),
 ('眉毛目标','多项式动作','以同侧眉毛共同中心和眼宽计算位置，并叠加当前校正','procedural_atoms.solve'),
 ('舌头目标','原始参考、截面与出口','普通口型保留 Original 舌头的整体位移和旋转。てへぺろ按原曲线侧伸，ぺろっ居中下卷；截面沿等弧长曲线弯曲，过厚或过宽的目标舌头在吐舌形态中按原参考与嘴宽的比例等比缩小，不修改生成的 Basis。尺寸检查保留旋转和平移，限制额外边长 ≤ Basis 的 1.04 倍；沿去除整体旋转后的方向检查 X/Y 跨度 ≤ 1.08/1.04 倍，Z 跨度 ≤ 原厚度 + 舌长的 28%。出口局部最多变薄 15%','procedural_tongue.reference_pose / deform / limit_size'),
 ('人中与唇周','表面轮廓与唇缘斜面','开口沿当前 Face 的局部轮廓采样有限深度变化，不沿初始切线无限外推；唇缘邻近面片共同平移，保留原斜面与厚度，再向周围脸皮平滑过渡','procedural_lips.surface_motion / deform'),
 ('下颌目标','下颌位移','以口宽归一化并按距口部的范围连续衰减','procedural_atoms.solve'),
 ('皮肤求解','拓扑连续位移场','固定眼口控制点，沿 Face 邻接平滑传播','procedural_skin.EyelidSkin.deform'),
 ('防破面','局部翻折修复','保持轮廓约束，限制局部修正，残余冲突写入报告','procedural_constraints.finalize_skin'),
 ('眼部接触','眼球、脸皮、睫毛','沿用原始预设的眼层依次避让。高光、瞳孔、眼白依次执行整体深度位移，保留原始间距和形状；检查 Basis 到终点的 16 个权重。位移上限保留闭眼眼宽 24%、睁眼 35%，Basis 不变。整片睫毛向内贴合、向外避让，保留原始嵌入。未消除的接触与覆盖问题写入报告','procedural_constraints.closed_eye_stack / procedural_lashes.lower_owned_upper_sections'),
 ('睫毛','整带与单根附着','拟合原始截面中心，沿最终 XYZ 闭眼曲线统一平移和旋转截面，保留厚度；眼尾连续延伸，不截断修正斜率。单根睫毛、双眼皮等共用最终截面变换，眉毛独立。竖向眼角平滑进入弯折区，之后执行贴脸与避让，并复查最终闭合线覆盖。まばたき下凹、笑い上拱且弧度延续到眼尾、なごみ优先水平平直；闭眼接合和下眼睑限幅更强。单根只读取已有标记','procedural_lashes.style_band / fold_vertical_sections / finish_upper_sweep / deform / audit_closed_band'),
 ('风格设置','下眼参与、笑眼弧度与形态保持','下眼睑参与量在可行闭合范围中选择接合位置，不改变下眼睑 30% 上移及笑眼弧顶额外 10% 的硬上限。笑眼弧度与形态保持调整曲线偏好，闭合、接触和厚度优先。组合、曲线写回沿用生成时保存的风格设置','procedural_ui.generation_options / procedural_binding.styled_closure'),
 ('闭眼层次','下眼睫毛遮盖','下睫毛随实际下眼眶的连续位移和旋转运动。闭眼时将整条下睫毛的上下缘收在上睫毛投影内，再求解前后层次。Face 接触后复查并修正遮盖，最终悬空和覆盖不足单独报告','procedural_lashes.follow_lower_rim / cover_lower_band / finish_closed_order'),
 ('眼角弯折','连续斜率权重','跟随下眼眶的强度随切线倾角连续增加，垂直达到 1，继续内斜仍保持 1。按原曲线弧长定位截面，避免竖向长度展开成内眼角横向拉长。普通闭眼保留内眼角跨度约束，なごみ和笑闭眼保持整条中心线的横向长度；单眼表情继承对应约束','procedural_lashes.slope_follow_weight / finish_upper_sweep'),
 ('计算设备','自动 GPU 与 CPU 回退','Windows NVIDIA CUDA 可用时，以双精度 GPU 内核求解三角面投影接触。小任务、缺少运行库、显存或调用失败时使用 CPU。两种设备共用几何规则、容差和可移动条件，报告设备、调用数与回退原因','procedural_gpu.try_depth'),
 ('口腔','固定唇缘连接','口内边界固定到实际唇缘，内部连续变形；强制镜像后重新贴合 Face 与 Mouth，避免两次表面插值产生小接缝','procedural_cavity.deform'),
 ('牙齿','参考上下牙动作、咬合与 Face 避让','内置口型按 Original 张口时牙片的一致运动校准上下排，再按嘴宽适配各自位移与旋转，不重复叠加竖向随唇浮动。原参考静止的牙齿保持原位；目标有小间隙时，下牙整组上移至首次接触，最多嘴宽的 30%，缺少独立上下牙则跳过。未校准的自定义或下颌动作保留有界随唇处理。接触可先收回校准动作中的前移，再按牙弓与嘴宽的较大值取 6.5% 额度整排后移，保留牙弓及上下行程；未校准动作仍采用 2.5% 共同后移及 4% 局部后移。检查局部修正是否引入新的三角面翻折；额度不足记录穿插，不向外推 Face，不缩放牙弓，不改变 Basis','procedural_constraints.close_dental_contact / procedural_contacts.oral_face'),
 ('吐舌接触','出口与外露面','检查外露下表面和外侧面；独立舌头整体平移避开 Face，避免把外露截面拉离舌根；焊接舌头保留局部处理及最终尺寸限制，冲突写入报告','procedural_tongue.keep_exterior'),
 ('口内接触','牙齿、口腔与 Face','按唇缘相连拓扑选择 Face 接触面，包含斜面及内翻唇面；牙齿及口腔退回面部内侧，口腔唇缘固定。取消舌头随整排牙齿最前点后退；牙齿与舌头的接触只由实际三角面交叉触发。舌头上表面避开下口腔，Basis 同样检查；接触位移上限取舌长 12% 和口宽 8% 的较小值，同次修正反复检查共用额度；超出额度报告冲突','procedural_contacts.finish / tongue_teeth / tongue_side'),
 ('写入','同一网格与可追溯曲线','表情形态键、口腔联动和最终变形曲线一起保存','procedural_generate.generate')]


def criteria(recipe):
    channels=set()
    numeric=recipe.get('base_recipe') or recipe
    if recipe.get('base'):numeric=next(r for r in _builtin_profile()['recipes'] if r['name']==recipe['base'])
    for key in ('eyes','mouth','mouth_reference','mouth_targets','brows','tongue','jaw'):
        if has_channels(numeric,key):channels.add(key)
    for node in recipe.get('recognizers',[]):
        if node['kind'].startswith('EYE') or node['kind'] in ('LASH','LASH_LINE','CREASE'):channels.add('eyes')
        elif node['kind'].startswith('LIP'):channels.add('mouth')
        elif node['kind']=='BROW':channels.add('brows')
        elif node['kind']=='TONGUE':channels.add('tongue')
    specific={'眼部目标':{'eyes'},'眼缘拟合':{'eyes'},'眼部接触':{'eyes'},'睫毛':{'eyes'},'眼角弯折':{'eyes'},
              '嘴型目标':{'mouth','mouth_reference','mouth_targets'},'人中与唇周':{'mouth','mouth_reference','mouth_targets'},'眉毛目标':{'brows'},'舌头目标':{'tongue'},'下颌目标':{'jaw'},'吐舌接触':{'tongue'}}
    rows=[]
    rows.append(dict(id='symmetry_policy',stage='对称策略',title='独立表情资格',formula=(
        '允许强制左右对称；正侧完成约束后直接镜像最终坐标到负侧，不再两侧平均。独立眼眉在相关顶点可配对时只计算正侧，不要求三角面划分相同。跨中线口型保留整体求解；活动顶点无法配对则跳过。镜像后的翻折数量写入报告' if recipe.get('can_symmetrize') and not recipe.get('special') and not recipe.get('relation')
        else '不对该表情强制镜像；保留子表情、组合或特殊动作的定义'),parameters_path='can_symmetrize / special / relation',
        condition='生成时开启强制对称',implementation='procedural_symmetry'))
    if recipe.get('relation'):
        rows.append(dict(id='expression_relation',stage='表情依赖',title='子表情或组合',
            formula='引用来源='+', '.join(dependencies(recipe))+'；条件在模型归一化坐标及当前分区中计算，边界连续衰减；不参与强制对称',
            parameters_path='relation',condition='来源可生成且依赖无循环',implementation='expression_relations.Solver'))
    for index,(stage,title,formula,implementation) in enumerate(CRITERIA):
        if stage in specific and not specific[stage]&channels:continue
        rows.append(dict(id='solver_%02d'%index,stage=stage,title=title,formula=formula,implementation=implementation,
                         condition='存在对应分区时执行',parameters_path='recipe'))
    def add(key,stage,title,formula,path,condition='按当前曲线与分区计算',implementation='expression_runtime.evaluate'):
        rows.append(dict(id=key,stage=stage,title=title,formula=formula,parameters_path=path,condition=condition,implementation=implementation))
    for side,eye in numeric.get('eyes',{}).items():
        if eye.get('open_motion'):
            meanings={'じと目':'下眼睑固定；上眼睑小幅下移，趋于平直。',
                      'ジト目':'下眼睑固定；上眼睑比じと目下移更多，趋于平直。',
                      '悲しむ':'上眼睑向下、外侧更多；最高点靠内眼角，向外侧平滑下斜。下眼睑上移、中部更多。',
                      '怒り目':'上眼睑向下、内侧更多；下眼睑上移，曲率减小并趋于平直。'}
            add('eye_'+side+'_open_motion','睁眼动作',numeric.get('name',''),meanings.get(numeric.get('name'),'按显式睁眼参数求解。'),
                'recipe.eyes.'+side+'.open_motion',implementation='procedural_atoms.open_lid_rule')
        for branch in ('upper','lower'):
            add('eye_'+side+'_'+branch,'眼部数值',side+' '+branch,
                '位移采样 × 当前眼宽；Z 再乘当前眼高与参考高宽比修正；17 个 XYZ 采样保存在 JSON',
                'recipe.eyes.'+side+'.'+branch,implementation='procedural_atoms.sampled')
        add('eye_'+side+'_style','闭合规则',side,
            '闭合=%g；下眼参与=%g；笑眼=%g；平直=%g。上缘不升、水平下缘不降且限幅；竖向眼角以转折为下降边界。笑眼上拱、なごみ平直，冲突不回退为相反曲率。'%tuple(eye.get(k,0) for k in ('closure','lower_share','smile','flat')),
            'recipe.eyes.'+side,implementation='procedural_atoms.solve')
    for key in ('mouth','mouth_reference','mouth_targets','brows','tongue','jaw','oral'):
        if has_channels(numeric,key):
            add('numeric_'+key,'数值配方',key,'使用 JSON 中该字段的完整数值；随表情整体幅度一同缩放，不单独解除约束','recipe.'+key,implementation='procedural_atoms.merge')
    for node in recipe.get('recognizers',[]):
        add('recognize_'+node['id'],'识别曲线',node['id'],
            '方式=%s；分区=%s；侧别=%s；候选=%s；参照=%s'%(node['mode'],node['region'],node['side'],node.get('index',0),node.get('reference') or '模型'),
            'recognizers.'+node['id'],implementation='expression_runtime.recognize')
        for i,c in enumerate(node.get('criteria',[])):
            add('recognize_'+node['id']+'_'+str(i),'识别条件',c['metric'],
                '%s ≤ %s ≤ %s；参照 %s'%(c['min'],c['metric'],c['max'],c.get('reference') or '模型'),
                'recognizers.'+node['id']+'.criteria.'+str(i),implementation='expression_runtime.feature')
    for r in recipe.get('rules',[]):
        target=r.get('target_rule') or r.get('target_curve') or '归一化目标偏移'
        add(r['id'],'自定义曲线',r['source'],'原始曲线 + %g × 参数 %s × 各影响项乘积 ×（%s - 原始曲线）'%(r.get('amount',1),r.get('parameter') or '1',target),'rules.'+r['id'])
        for i,f in enumerate(r.get('influences',[])):
            add(r['id']+'_influence_'+str(i),'接近程度影响',f['metric'],
                '%s 的 %s：输入 [%g, %g] 线性映射至 [%g, %g]，超范围取端值'%(f.get('curve') or ('分区 '+str(f['region'])),f['metric'],f['input_min'],f['input_max'],f['output_min'],f['output_max']),
                'rules.'+r['id']+'.influences.'+str(i))
    return rows


def document(custom=()):
    validate_library(custom)
    data=builtin_profile()
    names={r['name'] for r in custom}
    expressions=[dict(name=r['name'],family=r['family'],solver='builtin_v1',recipe=r,criteria=criteria(r),constraints=list(CONSTRAINTS)) for r in data['recipes'] if r['name'] not in names]
    for spec in custom:validate(spec);expressions.append(dict(spec,criteria=criteria(spec)))
    return dict(format=FORMAT,schema_version=SCHEMA_VERSION,engine='curve_rules_v1',neutral_eyes=data['neutral_eyes'],
        constraints=list(CONSTRAINTS),expressions=expressions)


def read_document(value):
    if not isinstance(value,dict) or value.get('format') not in (FORMAT,LEGACY_FORMAT) or value.get('schema_version')!=SCHEMA_VERSION:raise ValueError('不支持的表情规则文件版本')
    if not isinstance(value.get('expressions'),list) or len(value['expressions'])>512:raise ValueError('表情列表无效或超过 512 项')
    builtin={r['name']:r for r in builtin_profile()['recipes']};custom=[];names=set()
    for row in value['expressions']:
        if row['name'] in names:raise ValueError('表情名重复：'+row['name'])
        names.add(row['name'])
        if row.get('solver')=='builtin_v1':
            if row.get('recipe')!=builtin.get(row['name']):raise ValueError('内置配方已改变；请另存为自定义曲线规则')
        else:custom.append(validate(copy.deepcopy(row)))
    return validate_library(custom)


def write_document(path,custom=()):
    path=Path(path).with_suffix('.json');value=document(custom)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(plain(value),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    lines=['# 表情计算规则','', 'JSON 与本表同名；JSON 保留完整数值、曲线、依赖和参数，可在插件中重新导入。内置公式由指定求解器执行，不执行文件中的脚本。','']
    def cell(v):return str(v).replace('|','\\|').replace('\n',' ')
    for row in value['expressions']:
        lines+=['## '+row['name'],'','| 顺序 | 阶段 | 计算准则 | 条件 | 数值路径 | 实现 |','| --- | --- | --- | --- | --- | --- |']
        for i,r in enumerate(row['criteria'],1):lines.append('| '+' | '.join(map(cell,[i,r['stage'],r['formula'],r.get('condition','按规则引用'),r.get('parameters_path',''),r['implementation']]))+' |')
        lines+=['','数值定义：JSON 中 `expressions` 的同名项。','']
        if row.get('parameters'):
            lines+=['| 参数 | 默认值 | 范围 | 界面显示 |','| --- | --- | --- | --- |']
            for p in row['parameters']:lines.append('| '+' | '.join(map(cell,[p.get('label',p['id']),p['default'],str(p['min'])+'～'+str(p['max']),'是' if p['exposed'] else '否']))+' |')
            lines+=['']
    path.with_suffix('.md').write_text('\n'.join(lines),encoding='utf-8')
    return path,path.with_suffix('.md')

