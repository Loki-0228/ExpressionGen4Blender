"""Bind mesh contours to edited guides without inheriting raw rim zigzags."""
import numpy as np


class ClosureStyleError(ValueError):
    pass


class DepthCurve:
    """Local monotone cubic interpolation, with no depth overshoot at knots."""
    def __init__(self,x,y):
        self.x=np.asarray(x,dtype=float);self.y=np.asarray(y,dtype=float)
        self.slopes=np.zeros(len(self.x))
        if len(self.x)<2:return
        h=np.maximum(np.diff(self.x),1e-12);d=np.diff(self.y)/h
        self.slopes[0]=d[0];self.slopes[-1]=d[-1]
        for i in range(1,len(self.x)-1):
            if d[i-1]*d[i]<=0:continue
            a=2*h[i]+h[i-1];b=h[i]+2*h[i-1]
            self.slopes[i]=(a+b)/(a/d[i-1]+b/d[i])

    def sample(self,x):
        x=np.asarray(x,dtype=float)
        if len(self.x)==1:return np.full_like(x,self.y[0])
        x=np.clip(x,self.x[0],self.x[-1]);i=np.clip(np.searchsorted(self.x,x,side='right')-1,0,len(self.x)-2)
        h=np.maximum(self.x[i+1]-self.x[i],1e-12);t=(x-self.x[i])/h
        return ((2*t**3-3*t*t+1)*self.y[i]+(t**3-2*t*t+t)*h*self.slopes[i]
                +(-2*t**3+3*t*t)*self.y[i+1]+(t**3-t*t)*h*self.slopes[i+1])


def bezier(controls,t):
    """One cubic segment: two anchors and their two handles."""
    t=np.asarray(t);s=1-t
    weights=np.stack((s*s*s,3*s*s*t,3*s*t*t,t*t*t),axis=-1)
    return weights@np.asarray(controls)


def spline_basis(parameters,count=13):
    """Clamped uniform cubic B-spline weights (C2 at every interior knot)."""
    t=np.clip(np.atleast_1d(parameters).astype(float),0,1)
    knots=np.r_[np.zeros(3),np.linspace(0,1,count-2),np.ones(3)]
    weights=((t[:,None]>=knots[:-1])&(t[:,None]<knots[1:])).astype(float)
    for degree in (1,2,3):
        size=len(knots)-degree-1;next_weights=np.zeros((len(t),size))
        for i in range(size):
            left=knots[i+degree]-knots[i];right=knots[i+degree+1]-knots[i+1]
            if left>0:next_weights[:,i]+=(t-knots[i])/left*weights[:,i]
            if right>0:next_weights[:,i]+=(knots[i+degree+1]-t)/right*weights[:,i+1]
        weights=next_weights
    weights[t==1,-1]=1.
    return weights


def fit_bezier(points,parameters=None):
    """Keep endpoints exact and fit only the two interior handles."""
    points=np.asarray(points,dtype=float)
    t=np.linspace(0,1,len(points)) if parameters is None else np.asarray(parameters)
    s=1-t;matrix=np.column_stack((3*s*s*t,3*s*t*t))
    ends=s[:,None]**3*points[0]+t[:,None]**3*points[-1]
    handles=np.linalg.lstsq(matrix,points-ends,rcond=None)[0]
    controls=np.vstack((points[0],handles,points[-1]))
    # Keep the parameter order even on almost vertical eye corners.
    lo,hi=sorted((points[0,0],points[-1,0]));controls[1:3,0]=np.clip(controls[1:3,0],lo,hi)
    if (controls[2,0]-controls[1,0])*(points[-1,0]-points[0,0])<0:
        controls[1:3,0]=np.mean(controls[1:3,0])
    return controls


def lower_body_height(points,plane):
    """Height of the first horizontal lower-lid section from the inner end."""
    points=np.asarray(points);points=points[np.argsort(abs(points[:,0]-plane))]
    if len(points)<2:return float(points[0,2])
    edges=np.diff(points,axis=0);span=max(float(np.ptp(points[:,0])),1e-12)
    horizontal=(abs(edges[:,2])<=abs(edges[:,0])*1.05)&(abs(edges[:,0])>span*1e-6)
    inner=abs(points[:-1,0]-points[0,0])<=span*.6
    candidates=np.flatnonzero(horizontal&inner)
    if len(candidates):
        first=int(candidates[0]);return float(max(points[first,2],points[first+1,2]))
    return float(np.median(points[max(1,len(points)//4):max(2,3*len(points)//4),2]))


def bounded_height(controls,parameters,lower,upper):
    """Closest cubic height subject to directional eyelid bounds.

    Curvature is an objective, never permission to leave the aperture.
    Dykstra projections retain the original off-centre shape where feasible;
    callers retain a final envelope clamp for incompatible edited contours.
    """
    t=np.asarray(parameters);s=1-t
    basis=np.column_stack((s**3,3*s*s*t,3*s*t*t,t**3))
    lower=np.asarray(lower);upper=np.maximum(np.asarray(upper),lower)
    rows=np.vstack((basis,-basis));limits=np.r_[upper,-lower]
    result=np.asarray(controls).copy();height=result[:,2].copy()
    memory=np.zeros_like(rows);norms=np.einsum('ij,ij->i',rows,rows)
    tolerance=max(float(np.ptp(np.r_[lower,upper]))*1e-7,1e-10)
    for _ in range(96):
        previous=height.copy()
        for i,(row,bound) in enumerate(zip(rows,limits)):
            trial=height+memory[i];excess=max(float(row@trial-bound),0.)
            height=trial-row*(excess/max(norms[i],1e-12));memory[i]=trial-height
        if np.max(abs(height-previous))<tolerance and np.max(rows@height-limits)<tolerance:break
    result[:,2]=height
    return result,int(np.count_nonzero(rows@height-limits>tolerance))


def upward_closure(controls,parameters,lower,upper):
    """Keep the smile bow's sign and apex when it fits the eyelid bounds.

    Scale the two positive handles together instead of projecting each one
    independently into a bowl. Meeting and limited lower-lid travel remain
    stronger constraints; incompatible apertures use the bounded solve and
    report the style conflict, never raising the lower-lid allowance.
    """
    result=np.asarray(controls).copy();t=np.asarray(parameters);s=1-t
    lower=np.asarray(lower);upper=np.maximum(np.asarray(upper),lower)
    result[[0,3],2]=np.clip(result[[0,3],2],lower[[0,-1]],upper[[0,-1]])
    chord=np.linspace(result[0,2],result[3,2],4)
    handles=result[1:3,2]-chord[1:3]
    basis=np.column_stack((3*s*s*t,3*s*t*t))
    desired=basis@handles;candidates=[np.zeros(2)]
    if min(handles)>=0 and handles[0]<=2*handles[1] and handles[1]<=2*handles[0]:candidates.append(handles)
    for ray in (np.array((1.,2.)),np.array((2.,1.))):
        curve=basis@ray;candidates.append(ray*max(float(curve@desired/max(curve@curve,1e-20)),0.))
    handles=min(candidates,key=lambda h:float(np.sum((basis@h-desired)**2)))
    bow=basis@handles;baseline=(1-t)*chord[0]+t*chord[-1]
    tolerance=max(float(np.ptp(np.r_[lower,upper]))*1e-7,1e-10)
    moving=bow>tolerance;fixed=~moving
    minimum=max(0.,float(np.max((lower[moving]-baseline[moving])/bow[moving]))) if np.any(moving) else 0.
    maximum=min(1.,float(np.min((upper[moving]-baseline[moving])/bow[moving]))) if np.any(moving) else 1.
    feasible=minimum<=maximum and np.all(baseline[fixed]>=lower[fixed]-tolerance) and np.all(baseline[fixed]<=upper[fixed]+tolerance)
    if feasible:
        result[:,2]=chord;result[1:3,2]+=handles*maximum
        return result,0,dict(upward_arc_scale=float(maximum),upward_arc_conflicts=int(np.any(moving) and maximum<=1e-7))
    result,conflicts=bounded_height(controls,t,lower,upper)
    return result,conflicts,dict(upward_arc_scale=None,upward_arc_conflicts=1)


def upward_handles(handles):
    """Retain measured arch magnitude, with nonpositive second derivatives."""
    values=np.abs(np.asarray(handles,dtype=float))
    candidates=[np.zeros(2)]
    if values[0]<=2*values[1] and values[1]<=2*values[0]:candidates.append(values)
    for ray in (np.array((1.,2.)),np.array((2.,1.))):
        candidates.append(ray*max(float(ray@values/(ray@ray)),0.))
    return min(candidates,key=lambda h:float(np.sum((h-values)**2)))


def _closure_tilt_feasible(parameters,bow,low,high,candidate,minimum_gain):
    """Resolve the normalized tilt/gain polygon after eliminating translation.

    Every lower sample must be below every upper sample after the common
    translation is removed. These pairwise inequalities are half-planes in
    tilt/gain. The extreme parameters provide finite tilt limits for the
    existing gain interval; no arbitrary search radius or lid margin is used.
    """
    t=np.asarray(parameters,dtype=float);bow=np.asarray(bow,dtype=float)
    low=np.asarray(low,dtype=float);high=np.asarray(high,dtype=float)
    gain_low,gain_high=float(minimum_gain),1. if minimum_gain else 0.
    first,last=int(np.argmin(t)),int(np.argmax(t));span=float(t[last]-t[first])
    if span<=np.finfo(float).eps:return None
    end_bow=float(bow[last]-bow[first])
    tilt_low=min((low[last]-high[first]-gain*end_bow)/span for gain in (gain_low,gain_high))
    tilt_high=max((high[last]-low[first]-gain*end_bow)/span for gain in (gain_low,gain_high))
    epsilon=np.finfo(float).eps*128*max(1.,float(np.max(np.abs(np.r_[low,high]))))
    if tilt_low>tilt_high+epsilon:return None
    polygon=np.array(((tilt_low,gain_low),(tilt_high,gain_low),
                      (tilt_high,gain_high),(tilt_low,gain_high)),dtype=float)
    normals=np.stack((t[:,None]-t[None,:],bow[:,None]-bow[None,:]),axis=-1).reshape((-1,2))
    bounds=(low[:,None]-high[None,:]).ravel()
    for normal,bound in zip(normals,bounds):
        length=float(np.linalg.norm(normal))
        if length<=np.finfo(float).eps:
            if bound>epsilon:return None
            continue
        normal=normal/length;bound=float(bound/length)
        distances=polygon@normal-bound
        if float(distances.min())>=-epsilon:continue
        if float(distances.max())<-epsilon:return None
        clipped=[]
        for index,a in enumerate(polygon):
            following=(index+1)%len(polygon);b=polygon[following]
            da,db=float(distances[index]),float(distances[following])
            inside_a,inside_b=da>=-epsilon,db>=-epsilon
            if inside_a:clipped.append(a)
            if inside_a!=inside_b:
                clipped.append(a+(b-a)*float(np.clip(da/(da-db),0.,1.)))
        if not clipped:return None
        polygon=np.asarray(clipped)
    # Retain the approximate projection's tilt/curvature when feasible. If it
    # lies outside, project it onto the polygon using the same relative metric.
    target=np.asarray(candidate[1:],dtype=float);metric=np.array((4.,1.))
    shifted_low=low-target[0]*(t-.5)-target[1]*bow
    shifted_high=high-target[0]*(t-.5)-target[1]*bow
    if not (gain_low<=target[1]<=gain_high and shifted_low.max()<=shifted_high.min()):
        choices=[]
        for a,b in zip(polygon,np.roll(polygon,-1,axis=0)):
            edge=b-a;norm=float((edge*metric)@edge)
            weight=float(np.clip(((target-a)*metric)@edge/norm,0.,1.)) if norm>0 else 0.
            choices.append(a+edge*weight)
        target=min(choices,key=lambda point:float(((point-target)*metric)@(point-target)))
    tilt,gain=target
    bottom=float(np.max(low-tilt*(t-.5)-gain*bow))
    top=float(np.min(high-tilt*(t-.5)-gain*bow))
    if bottom>top+epsilon*8:return None
    shift=float(np.clip(candidate[0],bottom,top))
    return np.array((shift,tilt,gain))


def styled_closure(controls,parameters,lower,upper,flat=False,preference=1.):
    """Translate a whole bow/line and reduce its bow without reversing it.

    First solve common Z shift and curvature gain with the original chord.
    If necessary, adapt chord tilt within the same bounds. A finite projection
    budget is not an infeasibility proof; exact half-plane clipping provides
    a fallback without changing the aperture or reversing the bow.
    """
    result=np.asarray(controls).copy();t=np.asarray(parameters)
    lower=np.asarray(lower);upper=np.maximum(upper,lower)
    chord=np.linspace(result[0,2],result[3,2],4)
    if flat:chord[:]=float(np.mean(chord))
    handles=np.zeros(2) if flat else result[1:3,2]-chord[1:3]
    scale=max(float(np.ptp(np.r_[lower,upper])),1e-9);tolerance=scale*1e-7
    if not flat:
        # Custom offsets also pass through the upward-curvature constraint.
        candidates=[np.zeros(2)]
        if min(handles)>=0 and handles[0]<=2*handles[1] and handles[1]<=2*handles[0]:candidates.append(handles)
        for ray in (np.array((1.,2.)),np.array((2.,1.))):
            candidates.append(ray*max(float(ray@handles/(ray@ray)),0.))
        handles=min(candidates,key=lambda h:float(np.sum((h-handles)**2)))
    if not flat and np.max(handles)<=tolerance:handles[:]=scale*.02
    bow=np.column_stack((3*(1-t)**2*t,3*(1-t)*t*t))@handles
    baseline=(1-t)*chord[0]+t*chord[-1]
    low=lower-baseline;high=upper-baseline
    difference=bow[:,None]-bow[None,:];need=low[:,None]-high[None,:]
    positive=difference>tolerance;negative=difference<-tolerance
    minimum=max(.02 if not flat else 0.,float(np.max(need[positive]/difference[positive])) if np.any(positive) else 0.)
    maximum=min(1.,float(np.min(need[negative]/difference[negative])) if np.any(negative) else 1.)
    feasible=minimum<=maximum+1e-9 and not np.any(need[~(positive|negative)]>tolerance)
    gain=float(np.clip(maximum,minimum,1.)) if feasible else (0. if flat else 1.)
    hi=float(np.min(high-gain*bow));tilt=0.
    # Choose the preferred position inside the feasible interval. Style
    # cannot relax either lid's movement boundary.
    lo=float(np.max(low-gain*bow))
    shift=lo+(hi-lo)*float(np.clip(preference,0,1))
    solver='interval';solve_failed=False
    if not feasible:
        # A slanted original canthus chord may prevent a pure translation.
        # Allow its tilt to adapt while preserving the bow sign and ALL
        # horizontal-lid bounds, rather than clipping it into a bowl.
        design=np.column_stack((np.ones(len(t)),t-.5,bow/scale))
        rows=np.vstack((design,-design,(0.,0.,1.),(0.,0.,-1.)))
        limits=np.r_[high,-low,scale if not flat else 0.,-scale*.02 if not flat else 0.]
        values=np.array((shift,0.,gain*scale));memory=np.zeros_like(rows)
        metric=np.diag((1.,.25,1.));directions=rows@metric;norm=np.sum(rows*directions,axis=1)
        solver='projection'
        for _ in range(192):
            previous=values.copy()
            for k,row in enumerate(rows):
                candidate=values+memory[k]
                values=candidate-directions[k]*max(float(row@candidate-limits[k]),0.)/max(norm[k],1e-20)
                memory[k]=candidate-values
            if np.max(abs(values-previous))<tolerance and np.max(rows@values-limits)<tolerance:break
        if np.max(rows@values-limits)>tolerance:
            fallback=_closure_tilt_feasible(t,bow/scale,low/scale,high/scale,
                                            values/scale,0. if flat else .02)
            solver='feasible_polygon'
            if fallback is None:solve_failed=True
            else:values=np.array((fallback[0]*scale,fallback[1]*scale,fallback[2]*scale))
        shift,tilt,amount=values;gain=float(amount/scale)
    result[:,2]=chord+shift+tilt*(np.linspace(0,1,4)-.5);result[1:3,2]+=gain*handles
    height=bezier(result,t)[:,2]
    conflicts=int(np.count_nonzero((height<lower-tolerance)|(height>upper+tolerance)))
    if conflicts or solve_failed:
        raise ClosureStyleError(('平直闭眼' if flat else '笑闭眼')+'曲率与当前眼睑移动边界冲突，请检查眼角转折及校正曲线；未输出变形错误的表情')
    return result,conflicts,dict(style='flat' if flat else 'upward',style_gain=gain,
        style_translation=float(shift),style_tilt=float(tilt),style_bound_conflicts=conflicts,style_feasible=True,
        style_feasibility_solver=solver)


def planar_frame(controls,u):
    tangent=bezier(controls,min(u+.005,1))-bezier(controls,max(u-.005,0))
    tangent[1]=0.;tangent/=max(np.linalg.norm(tangent),1e-12)
    depth=np.array((0.,1.,0.))
    return np.column_stack((tangent,depth,np.cross(tangent,depth)))


def spatial_frame(sample,u):
    tangent=sample(min(u+.005,1))-sample(max(u-.005,0))
    tangent/=max(np.linalg.norm(tangent),1e-12)
    depth=np.array((0.,1.,0.));depth-=tangent*np.dot(depth,tangent)
    if np.linalg.norm(depth)<1e-8:
        depth=np.array((0.,0.,1.));depth-=tangent*np.dot(depth,tangent)
    depth/=max(np.linalg.norm(depth),1e-12)
    return np.column_stack((tangent,depth,np.cross(tangent,depth)))


def depth_envelope(parameters,values):
    """Fit one smooth cubic no farther back than the required contacts.

    Bounds constrain the curve, not its handles. A curved minimum may need a
    handle farther forward than the minimum itself; clamping handles would
    flatten the entire eyelid. No per-sample clipping follows the fit.
    """
    t=np.clip(np.asarray(parameters),0,1);y=np.asarray(values)
    s=1-t;matrix=np.column_stack((s**3,3*s*s*t,3*s*t*t,t**3))
    bending=np.array(((1.,-2.,1.,0.),(0.,1.,-2.,1.)))
    h=matrix.T@matrix+max(len(t),1)*.02*bending.T@bending+np.eye(4)*1e-10
    grid=np.unique(np.r_[t,np.linspace(0,1,65)]);s=1-grid
    samples=np.column_stack((s**3,3*s*s*grid,3*s*grid*grid,grid**3))
    front=float(y.min());back=float(y.max())
    bounds=np.r_[y,np.full(len(grid),-front),np.full(len(grid),back)]
    constraints=np.vstack((matrix,-samples,samples))
    rhs=matrix.T@y;controls=np.full(4,front);active=[]
    tolerance=max((back-front)*1e-8,1e-12)
    # Primal active-set QP in four coefficients. Start from a feasible constant
    # and retain feasibility at every step, including at iteration limits.
    for _ in range(160):
        gradient=h@controls-rhs
        if active:
            rows=constraints[active];count=len(active)
            system=np.block([[h,rows.T],[rows,np.zeros((count,count))]])
            solution=np.linalg.lstsq(system,np.r_[-gradient,np.zeros(count)],rcond=None)[0]
            step=solution[:4];multipliers=solution[4:]
        else:step=np.linalg.solve(h,-gradient);multipliers=np.empty(0)
        if np.max(abs(step))<=tolerance:
            if len(multipliers) and multipliers.min()<-tolerance:
                active.pop(int(np.argmin(multipliers)));continue
            break
        slopes=constraints@step;eligible=np.flatnonzero(slopes>tolerance)
        amount=1.;blocker=None
        if len(eligible):
            ratios=np.maximum(bounds[eligible]-constraints[eligible]@controls,0.)/slopes[eligible]
            index=int(np.argmin(ratios))
            if ratios[index]<amount:amount=float(ratios[index]);blocker=int(eligible[index])
        controls+=amount*step
        if blocker is not None and blocker not in active:
            if np.linalg.matrix_rank(constraints[active+[blocker]],tol=1e-9)>len(active):active.append(blocker)
            elif amount<=tolerance:break
    return controls


class Line:
    def __init__(self,points):
        self.points=np.asarray(points,dtype=float)
        self.lengths=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(self.points,axis=0),axis=1))]
        self.length=max(float(self.lengths[-1]),1e-12)
        self.parameters=self.lengths/self.length

    def sample(self,u):
        return np.array([np.interp(float(np.clip(u,0,1)),self.parameters,self.points[:,k]) for k in range(3)])

    def project(self,point):
        # Depth does not decide which side of a thick eyelid strip owns a point.
        a=self.points[:-1];edges=np.diff(self.points,axis=0)
        e=edges[:,[0,2]];v=(np.asarray(point)-a)[:,[0,2]]
        t=np.clip(np.sum(e*v,axis=1)/np.maximum(np.sum(e*e,axis=1),1e-24),0,1)
        dist=np.sum((v-e*t[:,None])**2,axis=1);i=int(np.argmin(dist))
        u=self.parameters[i]+t[i]*(self.parameters[i+1]-self.parameters[i])
        return float(u),float(dist[i]**.5)

    def frame(self,u):
        tangent=self.sample(min(u+.025,1))-self.sample(max(u-.025,0))
        tangent/=max(np.linalg.norm(tangent),1e-12)
        depth=np.array((0.,1.,0.));depth-=tangent*np.dot(depth,tangent)
        depth/=max(np.linalg.norm(depth),1e-12)
        return np.column_stack((tangent,depth,np.cross(tangent,depth)))


def ordered_parameters(points,line):
    """Nearest planar binding with topology order and positive segment spacing."""
    points=np.asarray(points);n=len(points)
    if n<2:return [0.]*n
    desired=np.array([line.project(p)[0] for p in points]);desired[0]=0.;desired[-1]=1.
    lengths=np.linalg.norm(np.diff(points[:,[0,2]],axis=0),axis=1)
    spacing=np.maximum(lengths/max(float(lengths.sum()),1e-12)*.02,1e-7)
    floors=np.r_[0.,np.cumsum(spacing)];values=np.clip(desired-floors,0,1-floors[-1])
    weights=np.ones(n);weights[[0,-1]]=1e12;blocks=[]
    for i,(value,weight) in enumerate(zip(values,weights)):
        blocks.append([i,i,float(weight),float(value*weight)])
        while len(blocks)>1 and blocks[-2][3]/blocks[-2][2]>blocks[-1][3]/blocks[-1][2]:
            b=blocks.pop();a=blocks[-1];a[1]=b[1];a[2]+=b[2];a[3]+=b[3]
    result=np.zeros(n)
    for block_first,block_last,weight,total in blocks:result[block_first:block_last+1]=total/weight
    result+=floors;result[0]=0.;result[-1]=1.
    if not np.isfinite(result).all() or np.any(result<0) or np.any(result>1) or np.any(np.diff(result)<0):
        raise ValueError('眼口曲线对应参数无效，请重新生成；现有曲线无需删除')
    return result.tolist()


def bind_rows(points,rows,branches):
    assignments={}
    for upper in (True,False):
        chain=sorted({(u,i) for i,u,up in rows if up==upper or u<1e-7 or u>1-1e-7})
        params=ordered_parameters([points[i] for u,i in chain],branches[upper])
        for (old,i),u in zip(chain,params):assignments[i,upper]=u
    return [(i,assignments[i,bool(upper)],upper) for i,old,upper in rows]


def closed_rim(rows,targets,side):
    """Both skin rims trace one polygon, even with different vertex counts.

    Sampling the same cubic at unrelated parameters leaves slivers between
    the two linear mesh edges. Match a monotone subset of the denser chain to
    every knot of the shorter chain; its extra vertices lie on those edges.
    Matching runs inner->outer on both eyes, never by vertex index or global X.
    """
    chains={upper:sorted({(u,i) for i,u,up in rows if bool(up)==upper or u<1e-7 or u>1-1e-7},
                         reverse=side<0) for upper in (False,True)}
    template=min((False,True),key=lambda upper:len(chains[upper]))
    short=chains[template];long=chains[not template];m,n=len(short),len(long)
    if m<2:return {}
    # Upper/lower rest arc lengths differ at a steep lower canthus. Match
    # their posed horizontal locations rather than unrelated rest parameters.
    span=max(float(np.ptp(targets[[i for u,i in short],0])),1e-12)
    origin=float(targets[short[0][1],0])
    a=np.array([(targets[i,0]-origin)*side/span for u,i in short])
    b=np.array([(targets[i,0]-origin)*side/span for u,i in long])
    a=np.maximum.accumulate(a);b=np.maximum.accumulate(b)
    cost=np.full((m,n),np.inf);parents=np.full((m,n),-1,dtype=np.int32);cost[0,0]=0.
    for k in range(1,m):
        best=np.inf;previous=-1
        for j in range(1,n):
            if cost[k-1,j-1]<best:best=cost[k-1,j-1];previous=j-1
            if k<=j<=n-m+k and (k<m-1 or j==n-1):
                cost[k,j]=best+(a[k]-b[j])**2;parents[k,j]=previous
    knots=[n-1]
    for k in range(m-1,0,-1):knots.append(int(parents[k,knots[-1]]))
    knots.reverse()
    if any(index<0 for index in knots):raise ValueError('闭眼轮廓顶点无法按拓扑顺序接合，请检查眼角连接')
    line=np.array([targets[i] for u,i in short]);result={i:point.copy() for (u,i),point in zip(short,line)}
    for k,(first,last) in enumerate(zip(knots,knots[1:])):
        for j in range(first,last+1):
            t=(b[j]-b[first])/max(b[last]-b[first],1e-12)
            result[long[j][1]]=line[k]*(1-t)+line[k+1]*t
    return result


def guide_lips(info,snapshot):
    """Keep the checked guide's upper/lower vertex ownership through generation."""
    from . import region_contours as O
    paths=[];points=info['points']
    face_edges={tuple(sorted((a,b))) for face,label in zip(info['faces'],info['labels']) if label==0
                for a,b in zip(face,face[1:]+face[:1])}
    for kind in ('LIP_UPPER','LIP_LOWER'):
        entries=[e for e in snapshot['entries'] if e['role']=='TARGET' and e['kind']==kind and e.get('enabled',True)]
        if len(entries)!=1 or entries[0].get('binding')!='face_topology_v1':
            raise ValueError('嘴唇曲线缺少当前顶点对应，请先重新生成 / 更新目标检查曲线')
        ids=entries[0]['vertices']
        if (len(ids)<2 or len(set(ids))!=len(ids) or any(i<0 or i>=len(points) for i in ids)
                or any(tuple(sorted((a,b))) not in face_edges for a,b in zip(ids,ids[1:]))):
            raise ValueError('嘴唇曲线的顶点链已失效，请重新生成 / 更新目标检查曲线')
        paths.append(ids)
    upper,lower=paths
    if upper[0]!=lower[0] or upper[-1]!=lower[-1] or set(upper[1:-1])&set(lower[1:-1]):
        raise ValueError('上下唇必须只在两侧嘴角相接，请检查唇缘拓扑后更新曲线')
    ids=upper+list(reversed(lower[1:-1]));a=list(range(len(upper)))
    b=[0]+list(range(len(ids)-1,len(upper)-1,-1))+[len(upper)-1]
    ring=O.LipRing([points[i] for i in ids],branches=(a,b))
    return ring,[(i,*ring.parameter(k)) for k,i in enumerate(ids)]


def edit_offset(entry,point):
    base=Line(entry['base']);current=Line(entry['points']);u,_=base.project(point)
    return current.sample(u)-base.sample(u)
