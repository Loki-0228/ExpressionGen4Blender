"""Regularize expression displacement on connected skin, never the rest mesh."""
import numpy as np


class SkinDisplacementField:
    """Positive graph energy with aperture and unmapped constraints.

    The same linear solve is used for every relative key. Edges come only from
    Face polygons, so an open mouth/eye cannot be crossed by proximity and oral
    pieces retain their own transform. A short edge penalizes displacement
    disagreement more strongly than a long edge.
    """
    def __init__(self, points, polygons, labels, mapped, pins, fidelity=.06):
        skin=set();edges=set()
        for poly,label in zip(polygons,labels):
            if label!=0:continue
            skin.update(poly)
            edges.update(tuple(sorted((a,b))) for a,b in zip(poly,poly[1:]+poly[:1]))
        self.n=len(points)
        self.free=np.array(sorted(skin & set(mapped)-set(pins)),dtype=np.int32)
        self.count=len(self.free)
        self.a=np.array([a for a,b in sorted(edges)],dtype=np.int32)
        self.b=np.array([b for a,b in sorted(edges)],dtype=np.int32)
        coords=np.asarray(points,dtype=np.float64)
        lengths=np.linalg.norm(coords[self.a]-coords[self.b],axis=1)
        typical=np.median(lengths[lengths>1e-10]) if np.any(lengths>1e-10) else 1.0
        self.w=np.minimum(typical/np.maximum(lengths,typical*.1),10.0)
        edge_count=np.bincount(self.a,minlength=self.n)+np.bincount(self.b,minlength=self.n)
        self.edge_length=(np.bincount(self.a,lengths,minlength=self.n)+np.bincount(self.b,lengths,minlength=self.n))/np.maximum(edge_count,1)
        degree=np.bincount(self.a,self.w,minlength=self.n)+np.bincount(self.b,self.w,minlength=self.n)
        self.mass=np.maximum(degree*fidelity,1e-8)
        self.diagonal=(degree+self.mass)[self.free]
        self.points=coords
        self.degree=degree

    def set_triangles(self, triangles, corner_controls=()):
        self.triangles=np.asarray(triangles,dtype=np.int32).reshape((-1,3))
        p=self.points[self.triangles]
        normal=np.cross(p[:,1]-p[:,0],p[:,2]-p[:,0])
        self.areas=np.linalg.norm(normal,axis=1)
        self.normals=normal/np.maximum(self.areas[:,None],1e-20)
        movable=np.zeros(self.n,dtype=float);movable[self.free]=1
        # Endpoints of a very different opening may be incompatible with the
        # target's corner triangles. Permit a small corner correction while
        # keeping central lips/lids exact and outside vertices fixed.
        movable[list(corner_controls)]=.05
        self.movable=movable[self.triangles]

    def constrain_triangles(self, delta, mobility=None, iterations=100, reference=None, pulse=None,budget_scale=.35):
        """Keep skin triangles from turning through the rest surface.

        Optional per-axis mobility keeps contours and final depth exact.
        The signed projected area is quadratic in key strength; check its
        minimum over the whole 0..1 interval, not only sampled strengths.
        """
        original=delta.copy();delta=delta.copy();ids=self.triangles
        recorder=getattr(pulse,'count',None)
        if not len(ids):return delta,dict(corrected=0,unresolved=0,max_correction=0.0)
        freedom=np.broadcast_to(self.movable[:,:,None],(*self.movable.shape,3)) if mobility is None else np.asarray(mobility)[ids]
        active=self.areas>1e-14
        corrected=set()
        rest=self.points[ids]
        first=rest[:,1]-rest[:,0];second=rest[:,2]-rest[:,0]
        scale=np.maximum(self.areas,1e-20)
        # Cap each update by local edge length, with a finite total correction
        # budget. A locked or near-degenerate triangle must not launch a point.
        step_limit=self.edge_length*.08
        reference=original if reference is None else np.asarray(reference)
        budget=self.edge_length*budget_scale
        movable=np.zeros_like(delta)
        if mobility is None:movable[self.free]=1.
        else:movable=(np.asarray(mobility)>0).astype(float)
        def minimum_state(values):
            if recorder:recorder(fold_triangle_evaluations=len(ids))
            movement=values[ids]
            da=movement[:,1]-movement[:,0];db=movement[:,2]-movement[:,0]
            a=np.sum(np.cross(da,db)*self.normals,axis=1)
            b=np.sum((np.cross(da,second)+np.cross(first,db))*self.normals,axis=1)
            strength=np.ones(len(ids));convex=a>1e-20
            strength[convex]=np.clip(-b[convex]/(2*a[convex]),0,1)
            p=rest+movement*strength[:,None,None]
            area=self.areas+b*strength+a*strength*strength
            return p,area,strength
        def error(area):
            return float(np.sum(np.maximum(.025-area[active]/scale[active],0.)**2))
        _,initial_area,_=minimum_state(original)
        healthy=active & (initial_area>=self.areas*.005)
        for iteration in range(iterations):
            if pulse and iteration%10==0:pulse('脸皮局部防翻折',iteration,iterations)
            if recorder:recorder(fold_iterations=1)
            total=np.zeros_like(delta);diagonal=np.zeros_like(delta)
            p,area,strength=minimum_state(delta)
            which=np.flatnonzero(active & (area<self.areas*.025))
            corrected.update(which.tolist())
            if not len(which):break
            q=p[which];normal=self.normals[which]
            gradients=np.stack([np.cross(q[:,1]-q[:,2],normal),
                np.cross(q[:,2]-q[:,0],normal),np.cross(q[:,0]-q[:,1],normal)],axis=1)
            gradients*=strength[which,None,None]/scale[which,None,None]
            violation=.025-area[which]/scale[which]
            values=gradients*violation[:,None,None]*freedom[which]
            weights=gradients*gradients*(freedom[which]>0)
            vertices=ids[which].reshape(-1)
            for axis in range(3):
                total[:,axis]=np.bincount(vertices,values[:,:,axis].ravel(),minlength=self.n)
                diagonal[:,axis]=np.bincount(vertices,weights[:,:,axis].ravel(),minlength=self.n)
            step=total/np.maximum(diagonal,1e-20)
            # Independent triangle gradients produce alternating spikes.
            # Share their correction along Face edges before line search,
            # keeping contour controls and every locked axis fixed.
            for _ in range(3):
                step=(step-.45*self.laplace(step)/np.maximum(self.degree[:,None],1e-12))*movable
            step*=np.minimum(1.,step_limit/np.maximum(np.linalg.norm(step,axis=1),1e-20))[:,None]
            if np.max(np.abs(step))<1e-12:break
            score=error(area);accepted=False
            for factor in (.8,.4,.2,.1,.05,.025):
                candidate=delta+step*factor
                correction=candidate-reference
                correction*=np.minimum(1.,budget/np.maximum(np.linalg.norm(correction,axis=1),1e-20))[:,None]
                candidate=reference+correction
                _,next_area,_=minimum_state(candidate)
                if np.any(healthy & (next_area<self.areas*.005)):continue
                if error(next_area)<score-1e-18:
                    delta=candidate;accepted=True;break
            if not accepted:break
        p,area,strength=minimum_state(delta)
        unresolved=int(np.sum(active & (area<self.areas*.005)))
        return delta,dict(corrected=len(corrected),unresolved=unresolved,
            max_correction=float(np.max(np.linalg.norm(delta-original,axis=1))))

    def laplace(self,values):
        diff=(values[self.a]-values[self.b])*self.w[:,None]
        return np.stack([np.bincount(self.a,diff[:,axis],minlength=self.n)-
                         np.bincount(self.b,diff[:,axis],minlength=self.n) for axis in range(3)],axis=1)

    def solve(self, raw):
        raw=np.asarray(raw,dtype=np.float64)
        if not self.count:return raw.copy()
        # Solve the correction with zero boundary values; pins remain bitwise
        # unchanged, including vertices deliberately excluded from transfer.
        rhs=-self.laplace(raw)[self.free]
        def matrix(values):
            full=np.zeros_like(raw);full[self.free]=values
            return (self.laplace(full)+self.mass[:,None]*full)[self.free]
        correction=np.zeros_like(rhs);residual=rhs.copy()
        z=residual/self.diagonal[:,None];direction=z.copy()
        dot=float(np.sum(residual*z));initial=max(float(np.sum(rhs*rhs)),1e-30)
        for _ in range(160):
            if float(np.sum(residual*residual))<initial*1e-14:break
            ad=matrix(direction);denom=float(np.sum(direction*ad))
            if denom<=1e-30:break
            step=dot/denom;correction+=step*direction;residual-=step*ad
            z=residual/self.diagonal[:,None];updated=float(np.sum(residual*z))
            direction=z+(updated/max(dot,1e-30))*direction;dot=updated
        result=raw.copy();result[self.free]+=correction
        return result

    def smooth_displacement(self,raw,bending=2.):
        """Regularize motion slopes, preserving the rest mesh and exact pins."""
        raw=np.asarray(raw,dtype=np.float64)
        if not self.count or not np.any(raw):return raw.copy()
        inverse=1/np.maximum(self.degree,1e-8)
        neighbor=np.bincount(self.a,self.w**2*inverse[self.b],minlength=self.n)
        neighbor+=np.bincount(self.b,self.w**2*inverse[self.a],minlength=self.n)
        diagonal=(self.degree+bending*(self.degree**2*inverse+neighbor)+self.mass)[self.free]
        # Symmetric bending energy L D^-1 L penalizes sharp changes of motion
        # across adjacent triangles, rather than rotating each vertex freely.
        def energy(values):
            first=self.laplace(values)
            return first+bending*self.laplace(first*inverse[:,None])
        rhs=-energy(raw)[self.free]
        def matrix(values):
            full=np.zeros_like(raw);full[self.free]=values
            return (energy(full)+self.mass[:,None]*full)[self.free]
        change=np.zeros_like(rhs);residual=rhs.copy()
        z=residual/diagonal[:,None];direction=z.copy()
        dot=float(np.sum(residual*z));initial=max(float(np.sum(rhs*rhs)),1e-30)
        for _ in range(240):
            if float(np.sum(residual*residual))<initial*1e-12:break
            ad=matrix(direction);denom=float(np.sum(direction*ad))
            if denom<=1e-30:break
            step=dot/denom;change+=step*direction;residual-=step*ad
            z=residual/diagonal[:,None];updated=float(np.sum(residual*z))
            direction=z+updated/max(dot,1e-30)*direction;dot=updated
        result=raw.copy();result[self.free]+=change
        return result

    def deform(self,raw,iterations=10):
        """Rotate local skin neighborhoods while keeping every contour exact.

        A large eyelid/lip displacement needs a change of local frame. Merely
        smoothing translations or scaling the entire expression prevents an
        aperture from closing. This local/global solve changes free skin only.
        """
        raw=np.asarray(raw,dtype=np.float64)
        if not self.count or not np.any(raw):return raw.copy()
        target=self.points+raw;posed=self.points+self.solve(raw)
        rest=self.points[self.a]-self.points[self.b]
        mass=self.mass*.1;diagonal=self.diagonal-self.mass[self.free]+mass[self.free]
        def matrix(values):
            full=np.zeros_like(raw);full[self.free]=values
            return (self.laplace(full)+mass[:,None]*full)[self.free]
        for _ in range(iterations):
            edge=posed[self.a]-posed[self.b]
            covariance=np.zeros((self.n,3,3))
            outer=np.einsum('ei,ej->eij',rest,edge)*self.w[:,None,None]
            np.add.at(covariance,self.a,outer);np.add.at(covariance,self.b,outer)
            u,_,vt=np.linalg.svd(covariance)
            rotation=vt.transpose(0,2,1)@u.transpose(0,2,1)
            reflected=np.linalg.det(rotation)<0
            vt[reflected,-1]*=-1;rotation=vt.transpose(0,2,1)@u.transpose(0,2,1)
            desired=np.einsum('eij,ej->ei',(rotation[self.a]+rotation[self.b])*.5,rest)*self.w[:,None]
            divergence=np.zeros_like(raw)
            np.add.at(divergence,self.a,desired);np.add.at(divergence,self.b,-desired)
            rhs=(divergence-self.laplace(target))[self.free]
            change=np.zeros_like(rhs);residual=rhs.copy();z=residual/diagonal[:,None];direction=z.copy()
            dot=float(np.sum(residual*z));initial=max(float(np.sum(rhs*rhs)),1e-30)
            for _ in range(140):
                if float(np.sum(residual*residual))<initial*1e-13:break
                ad=matrix(direction);denom=float(np.sum(direction*ad))
                if denom<=1e-30:break
                step=dot/denom;change+=step*direction;residual-=step*ad
                z=residual/diagonal[:,None];updated=float(np.sum(residual*z))
                direction=z+updated/max(dot,1e-30)*direction;dot=updated
            posed=target.copy();posed[self.free]+=change
        result=raw.copy();result[self.free]=posed[self.free]-self.points[self.free]
        return result
