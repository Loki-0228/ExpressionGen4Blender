"""Overall facial outlines, independent of tessellation and disconnected pieces."""
from math import atan2, cos, sin, sqrt, isfinite
from collections import defaultdict
from mathutils import Vector

EYE_REGIONS = frozenset((2,3,5,7))
ORAL_REGIONS = frozenset((8,9,12))
OCULAR_REGIONS = frozenset((3,5))


def brow_lash_split(points, eye_points):
    """Separate brow/lash envelopes using eye height, independent of islands."""
    if len(points)<6 or len(eye_points)<3:
        return None
    bottom=min(p.z for p in eye_points);top=max(p.z for p in eye_points)
    height=top-bottom
    if height<=1e-9:
        return None
    rows=sorted(p.z for p in points)
    gaps=[(b-a,(a+b)/2) for i,(a,b) in enumerate(zip(rows,rows[1:]))
          if i>=2 and len(rows)-i-1>=3 and
          top-height*.03 <= (a+b)/2 <= top+height*4]
    if gaps:
        gap,threshold=max(gaps)
        if gap>height*.025:
            return threshold
    threshold=top+height*.08
    if sum(z<threshold for z in rows)>=3 and sum(z>=threshold for z in rows)>=3:
        return threshold
    return None


def hull(points):
    points=sorted(set((float(p[0]),float(p[2])) for p in points))
    def cross(o,a,b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    if len(points)<3:
        return points
    lower,upper=[],[]
    for p in points:
        while len(lower)>=2 and cross(lower[-2],lower[-1],p)<=0:
            lower.pop()
        lower.append(p)
    for p in reversed(points):
        while len(upper)>=2 and cross(upper[-2],upper[-1],p)<=0:
            upper.pop()
        upper.append(p)
    return lower[:-1]+upper[:-1]


class OutlineFrame:
    def __init__(self, points, rotate=False):
        if len(points)<3:
            raise ValueError('外轮廓至少需要三个有效点')
        contour=hull(points)
        if len(contour)<3:
            raise ValueError('外轮廓退化为线段')
        # Compute around a nearby origin: a nearly closed mouth far from the
        # object origin otherwise loses precision in the polygon centroid.
        origin=contour[0]
        local=[(x-origin[0],z-origin[1]) for x,z in contour]
        area=sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(local,local[1:]+local[:1]))
        if abs(area)<1e-12:
            raise ValueError('外轮廓面积为零')
        center=[sum((a[k]+b[k])*(a[0]*b[1]-a[1]*b[0])
            for a,b in zip(local,local[1:]+local[:1]))/(3*area)+origin[k] for k in (0,1)]
        self.center=Vector((center[0],sum(p.y for p in points)/len(points),center[1]))
        xx=sum((x-center[0])**2 for x,z in contour)
        zz=sum((z-center[1])**2 for x,z in contour)
        xz=sum((x-center[0])*(z-center[1]) for x,z in contour)
        self.angle=0.5*atan2(2*xz,xx-zz) if rotate else 0.0
        self.c,self.s=cos(self.angle),sin(self.angle)
        projected=[self.axes(Vector((x,self.center.y,z))) for x,z in contour]
        self.width=max(p[0] for p in projected)-min(p[0] for p in projected)
        self.height=max(p[1] for p in projected)-min(p[1] for p in projected)
        self.depth=max(p.y for p in points)-min(p.y for p in points)
        self.outline=[(x/max(self.width/2,1e-9),z/max(self.height/2,1e-9)) for x,z in projected]

    def axes(self, point):
        d=point-self.center
        return (self.c*d.x+self.s*d.z,-self.s*d.x+self.c*d.z)

    def normalized(self, point):
        x,z=self.axes(point)
        return Vector((x/max(self.width/2,1e-9),z/max(self.height/2,1e-9),
            (point.y-self.center.y)/max(self.depth,self.width*0.1,1e-9)*0.1))

    def radius(self, theta):
        dx,dz=cos(theta),sin(theta)
        hits=[]
        for a,b in zip(self.outline,self.outline[1:]+self.outline[:1]):
            ex,ez=b[0]-a[0],b[1]-a[1]
            denominator=dx*ez-dz*ex
            if abs(denominator)<1e-12:
                continue
            t=(a[0]*ez-a[1]*ex)/denominator
            u=(a[0]*dz-a[1]*dx)/denominator
            if t>=0 and -1e-7<=u<=1+1e-7:
                hits.append(t)
        return min(hits) if hits else 1.0


class OutlineWarp:
    def __init__(self, source, target, rotate=False):
        self.source=OutlineFrame(source,rotate)
        self.target=OutlineFrame(target,rotate)

    def warp(self, point, shape=True):
        uv=self.source.normalized(point)
        ratio=self.target.radius(atan2(uv.y,uv.x))/max(self.source.radius(atan2(uv.y,uv.x)),1e-9) if shape else 1
        x=uv.x*ratio*self.target.width/2
        z=uv.y*ratio*self.target.height/2
        depth_gain=sqrt(self.target.width*self.target.height/max(self.source.width*self.source.height,1e-12))
        depth=self.target.center.y+(point.y-self.source.center.y)*depth_gain
        return Vector((self.target.center.x+self.target.c*x-self.target.s*z,depth,
                       self.target.center.z+self.target.s*x+self.target.c*z))

    def local_face_warp(self, point):
        uv=self.source.normalized(point)
        r=sqrt(uv.x**2+uv.y**2)/max(self.source.radius(atan2(uv.y,uv.x)),1e-9)
        t=min(max(2-r,0),1)
        weight=t*t*(3-2*t)
        return point+(self.warp(point)-point)*weight

    def follow_outline(self,point):
        """Follow a lash contour while preserving an accessory line's offset."""
        uv=self.source.normalized(point)
        radius=sqrt(uv.x*uv.x+uv.y*uv.y)
        if radius<=1e-9:return self.warp(point)
        contour_radius=self.source.radius(atan2(uv.y,uv.x))
        x=uv.x/radius*contour_radius*self.source.width/2
        z=uv.y/radius*contour_radius*self.source.height/2
        anchor=Vector((self.source.center.x+x,self.source.center.y,self.source.center.z+z))
        return self.warp(anchor)+(point-anchor)*(self.target.width/self.source.width)


class MouthFrame:
    """Fit a closed lip ring's major axis, including zero-height projection."""
    def __init__(self, points):
        if len(points)<3 or not all(all(isfinite(v) for v in p) for p in points):
            raise ValueError('口部边界环无效')
        # Exact arc-length moments balance both lip chains despite unequal
        # density, without sampling errors rotating a thin closed mouth.
        segments=[(a,b,sqrt((a.x-b.x)**2+(a.z-b.z)**2))
                  for a,b in zip(points,points[1:]+points[:1])]
        total=sum(length for a,b,length in segments)
        if total<=1e-9:
            raise ValueError('口部边界环没有有效宽度')
        mean=Vector(tuple(sum((a[k]+b[k])*length/2 for a,b,length in segments)/total
                          for k in range(3)))
        xx=zz=xz=0.0
        for a,b,length in segments:
            ax,az=a.x-mean.x,a.z-mean.z
            bx,bz=b.x-mean.x,b.z-mean.z
            xx+=length*(ax*ax+ax*bx+bx*bx)/3
            zz+=length*(az*az+az*bz+bz*bz)/3
            xz+=length*(2*ax*az+ax*bz+bx*az+2*bx*bz)/6
        self.angle=0.5*atan2(2*xz,xx-zz)
        self.c,self.s=cos(self.angle),sin(self.angle)
        self.center=mean
        values=[self.axes(p) for p in points]
        low=[min(v[a] for v in values) for a in (0,1)]
        high=[max(v[a] for v in values) for a in (0,1)]
        x,z=(low[0]+high[0])/2,(low[1]+high[1])/2
        self.center+=Vector((self.c*x-self.s*z,0,self.s*x+self.c*z))
        self.width,self.height=high[0]-low[0],high[1]-low[1]

    def axes(self, point):
        d=point-self.center
        return self.c*d.x+self.s*d.z,-self.s*d.x+self.c*d.z


class MouthOpeningTransform:
    """One similarity transform for all oral parts, including tongue keys.

    A closed mouth's height is not a scale reference. Width determines scale;
    rotation and translation follow the lip opening, preserving internal shape.
    """
    def __init__(self, source, target, source_face_width, target_face_width):
        self.source=MouthFrame(source)
        self.target=MouthFrame(target)
        for frame,face_width in ((self.source,source_face_width),
                                 (self.target,target_face_width)):
            if not isfinite(face_width) or face_width<=1e-9:
                raise ValueError('口腔贴合失败：面部范围无效')
            if not all(isfinite(v) for v in frame.center) or not (
                face_width*0.015 <= frame.width <= face_width*0.6):
                raise ValueError('口腔贴合失败：口洞宽度不可靠，请检查 Face 的口部边界')
            if frame.height>frame.width*0.85:
                raise ValueError('口腔贴合失败：所识别的边界不像口洞')
        self.scale=self.target.width/self.source.width
        if not isfinite(self.scale) or not 0.25<=self.scale<=4.0:
            raise ValueError('口腔贴合失败：口洞缩放超过安全范围，请先对齐模型')
        angle=self.target.angle-self.source.angle
        self.c,self.s=cos(angle),sin(angle)

    def warp(self, point, shape=False):
        d=point-self.source.center
        return self.target.center+Vector((self.c*d.x-self.s*d.z,d.y,
                                         self.s*d.x+self.c*d.z))*self.scale

    def local_face_warp(self, point):
        # Width-based influence is stable even when the opening is almost flat.
        x,z=self.source.axes(point)
        radius=sqrt(x*x+z*z)/max(self.source.width/2,1e-9)
        t=min(max(2-radius,0),1)
        return point+(self.warp(point)-point)*(t*t*(3-2*t))


class LipRing:
    """Continuous upper/lower envelopes of a topology-ordered mouth ring."""
    def __init__(self, points, horizontal=False, surface=None, branches=None):
        self.points=points
        self.frame=MouthFrame(points)
        if horizontal:
            # Eyes can be taller than wide. PCA would turn the upper/lower
            # eyelid axis through 90 degrees; use the aligned face's X axis.
            self.frame.angle=0;self.frame.c=1;self.frame.s=0
            self.frame.center=Vector(((min(p.x for p in points)+max(p.x for p in points))/2,
                sum(p.y for p in points)/len(points),(min(p.z for p in points)+max(p.z for p in points))/2))
            self.frame.width=max(p.x for p in points)-min(p.x for p in points)
            self.frame.height=max(p.z for p in points)-min(p.z for p in points)
        self.coordinates=[self.frame.axes(p) for p in points]
        self.left=min(x for x,z in self.coordinates)
        self.right=max(x for x,z in self.coordinates)
        if self.right-self.left<=1e-9:
            raise ValueError('嘴唇环宽度无效')
        left=min(range(len(points)),key=lambda i:self.coordinates[i][0])
        right=max(range(len(points)),key=lambda i:self.coordinates[i][0])
        def chain(step):
            indices=[left];i=left
            while i!=right:
                i=(i+step)%len(points);indices.append(i)
            return indices
        a,b=chain(1),chain(-1)
        def mean_height(indices):
            rows=[(self.coordinates[i],self.coordinates[j]) for i,j in zip(indices,indices[1:])]
            weights=[abs(q[0]-p[0]) for p,q in rows]
            return sum((p[1]+q[1])*.5*w for (p,q),w in zip(rows,weights))/max(sum(weights),1e-12)
        # Vertex counts can differ between two coincident, curved lip paths.
        # Integrating along their horizontal span avoids density-dependent swaps.
        difference=mean_height(a)-mean_height(b)
        self.branch_method='horizontal_span_height'
        if not horizontal and surface is not None:
            scores=self.surface_sides((a,b),surface)
            if scores is not None and min(scores)<-.15 and max(scores)>.15:
                difference=scores[0]-scores[1];self.branch_method='adjacent_face_topology'
        if difference<0:
            a,b=b,a
        if branches is not None:
            a,b=branches;self.branch_method='guide_vertex_binding'
        self.upper=set(a)
        self.chains={True:a,False:b}
        self.arcs={};self.arc_parameters={}
        for upper,indices in self.chains.items():
            lengths=[0.0]
            for i,j in zip(indices,indices[1:]):
                x,z=self.coordinates[i];xx,zz=self.coordinates[j]
                lengths.append(lengths[-1]+sqrt((xx-x)**2+(zz-z)**2))
            total=max(lengths[-1],1e-9)
            self.arcs[upper]=[(length/total,points[i]) for i,length in zip(indices,lengths)]
            for i,length in zip(indices,lengths):self.arc_parameters[i,upper]=length/total

    def surface_sides(self,chains,surface):
        """Classify touching lips by which side their connected facial skin lies.

        Use vertex identity, not coordinate matching: closed upper/lower rim
        vertices may coincide while belonging to different sides of the face.
        """
        points,polygons,labels=surface
        lookup={id(point):i for i,point in enumerate(points)}
        ids=[lookup.get(id(point)) for point in self.points]
        if any(i is None for i in ids):return None
        rim=set(ids);edges={tuple(sorted((ids[i],ids[j]))) for chain in chains for i,j in zip(chain,chain[1:])}
        owners=defaultdict(list);adjacent=defaultdict(set)
        for polygon,label in zip(polygons,labels):
            if label!=0:continue
            for i,j in zip(polygon,polygon[1:]+polygon[:1]):
                if i not in rim and j not in rim:adjacent[i].add(j);adjacent[j].add(i)
            outside=[i for i in polygon if i not in rim]
            if not outside:continue
            center=sum((points[i] for i in outside),Vector())/len(outside)
            for i,j in zip(polygon,polygon[1:]+polygon[:1]):
                edge=tuple(sorted((i,j)))
                if edge in edges:owners[edge].append((center,outside))
        scores=[]
        for chain in chains:
            score=total=0.;seeds=[]
            for i,j in zip(chain,chain[1:]):
                candidates=owners.get(tuple(sorted((ids[i],ids[j]))),[])
                if not candidates:continue
                # At an unsplit projection fold, prefer the outer facial side
                # over the rear lining. The aligned face looks towards -Y.
                center,outside=min(candidates,key=lambda row:row[0].y)
                midpoint=(self.points[i]+self.points[j])*.5
                direction=center-midpoint
                dz=-self.frame.s*direction.x+self.frame.c*direction.z
                distance=sqrt(direction.x**2+direction.z**2)
                x,z=self.frame.axes(midpoint)
                u=min(max((x-self.left)/(self.right-self.left),0.),1.)
                if .15<=u<=.85:
                    seeds.extend(((points[v]-midpoint).length,v,tuple(midpoint)) for v in outside)
                weight=abs(self.coordinates[j][0]-self.coordinates[i][0])*4*u*(1-u)
                if distance<=self.frame.width*1e-8:continue
                score+=weight*dz/distance;total+=weight
            local_score=score/total if total>self.frame.width*1e-6 else None
            # Closed/interpenetrating lips can turn inward in their first row
            # of faces. Walk farther onto each side's skin, never crossing the
            # rim or going around a corner to reach the opposite lip.
            if seeds:
                import heapq
                radius=min(max(self.frame.width*.18,min(row[0] for row in seeds)*1.5),self.frame.width*.4)
                queue=list(seeds);heapq.heapify(queue);visited=set();score=total=0.
                while queue:
                    distance,i,origin=heapq.heappop(queue)
                    if i in visited or distance>radius:continue
                    visited.add(i);point=points[i];x,z=self.frame.axes(point)
                    u=(x-self.left)/(self.right-self.left)
                    if not .10<u<.90:continue
                    direction=point-Vector(origin)
                    planar=sqrt(direction.x**2+direction.z**2)
                    if planar>self.frame.width*1e-8:
                        weight=(distance/radius)**2*4*u*(1-u)
                        score+=weight*(-self.frame.s*direction.x+self.frame.c*direction.z)/planar;total+=weight
                    for j in sorted(adjacent[i]-visited):
                        heapq.heappush(queue,(distance+(points[j]-point).length,j,origin))
                if total>1e-8:local_score=score/total
            if local_score is None:return None
            scores.append(local_score)
        return scores

    def parameter(self, index):
        upper=index in self.upper
        return self.arc_parameters[index,upper],upper

    def locate(self, point, upper=None):
        candidates=[]
        for branch in ((True,False) if upper is None else (bool(upper),)):
            for (a,p),(b,q) in zip(self.arcs[branch],self.arcs[branch][1:]):
                dx,dz=q.x-p.x,q.z-p.z
                t=min(max(((point.x-p.x)*dx+(point.z-p.z)*dz)/max(dx*dx+dz*dz,1e-20),0),1)
                error=(point.x-p.x-t*dx)**2+(point.z-p.z-t*dz)**2
                candidates.append((error,a+(b-a)*t,branch))
        error,u,branch=min(candidates,key=lambda row:row[0])
        return u,branch

    def sample(self, u, upper=True):
        rows=self.arcs[bool(upper)];u=min(max(u,0),1)
        for (a,p),(b,q) in zip(rows,rows[1:]):
            if a<=u<=b and b-a>1e-12:return p+(q-p)*((u-a)/(b-a))
        return rows[0 if u<=0 else -1][1].copy()


def lip_weights(rows,u,upper):
    """Piecewise linear displacement weights, never mixing upper/lower lips."""
    selected=sorted({(parameter,index) for index,parameter,branch in rows
        if bool(branch)==bool(upper) or parameter<1e-7 or parameter>1-1e-7})
    if not selected:
        return []
    if u<=selected[0][0]:return [(selected[0][1],1.0)]
    if u>=selected[-1][0]:return [(selected[-1][1],1.0)]
    for a,b in zip(selected,selected[1:]):
        if a[0]<=u<=b[0] and b[0]-a[0]>1e-9:
            t=(u-a[0])/(b[0]-a[0])
            return [(a[1],1-t),(b[1],t)]
    return []


def contour_weights(rows,u,upper,bandwidth=.075):
    """A smooth silhouette field for lashes with unrelated tessellations."""
    from math import exp
    selected=[(index,parameter) for index,parameter,branch in rows if bool(branch)==bool(upper)]
    if not selected:return []
    nearest=min(abs(parameter-u) for index,parameter in selected)
    width=max(bandwidth,nearest+bandwidth)
    weighted=[(index,exp(-((parameter-u)/width)**2)) for index,parameter in selected
              if abs(parameter-u)<=width*3]
    total=sum(w for index,w in weighted)
    return [(index,w/total) for index,w in weighted]


class EyeRing(LipRing):
    """Arc length along each eye contour, independent of vertex density.

    X alone collapses a tall inner canthus to almost one parameter, producing
    a sudden jump even on a correctly classified upper/lower eyelid.
    """
    def __init__(self,points):
        super().__init__(points,horizontal=True)
        self.arcs={};self.arc_parameters={}
        for upper,chain in self.chains.items():
            lengths=[0.0]
            for a,b in zip(chain,chain[1:]):
                d=points[b]-points[a];lengths.append(lengths[-1]+sqrt(d.x*d.x+d.z*d.z))
            total=max(lengths[-1],1e-9)
            self.arcs[upper]=[(length/total,points[i]) for i,length in zip(chain,lengths)]
            for i,length in zip(chain,lengths):self.arc_parameters[i,upper]=length/total

    def parameter(self,index):
        upper=index in self.upper
        return self.arc_parameters[index,upper],upper

    def sample(self,u,upper=True):
        rows=self.arcs[bool(upper)];u=min(max(u,0),1)
        for (a,p),(b,q) in zip(rows,rows[1:]):
            if a<=u<=b and b-a>1e-12:return p+(q-p)*((u-a)/(b-a))
        return rows[0 if u<=0 else -1][1].copy()

    def locate(self,point,upper=None):
        candidates=[]
        for branch in ((True,False) if upper is None else (bool(upper),)):
            rows=self.arcs[branch]
            for (a,p),(b,q) in zip(rows,rows[1:]):
                dx,dz=q.x-p.x,q.z-p.z
                t=min(max(((point.x-p.x)*dx+(point.z-p.z)*dz)/max(dx*dx+dz*dz,1e-20),0),1)
                error=(point.x-p.x-t*dx)**2+(point.z-p.z-t*dz)**2
                candidates.append((error,a+(b-a)*t,branch))
        error,u,branch=min(candidates,key=lambda row:row[0])
        return u,branch


class EyeApertureWarp:
    """Attach each lid to its own aperture curve; preserve lash/crease offset."""
    def __init__(self,source,target):
        self.source=EyeRing(source)
        self.target=EyeRing(target)
        self.scale=self.target.frame.width/self.source.frame.width
        self.height_scale=self.target.frame.height/max(self.source.frame.height,1e-9)
        self._gains={}

    def warp(self,point,u=None,upper=None):
        if u is None:u,upper=self.source.locate(point)
        a,b=self.source.sample(u,upper),self.target.sample(u,upper)
        return b+(point-a)*self.scale

    def delta(self,delta,u):
        # Work in the REST branch. A closing upper eyelid must never switch
        # to the lower branch half way through evaluating its shape key.
        gain=self._gains.get(u)
        if gain is None:
            source_gap=self.source.sample(u,True).z-self.source.sample(u,False).z
            target_gap=self.target.sample(u,True).z-self.target.sample(u,False).z
            gain=target_gap/source_gap if source_gap>self.source.frame.height*.1 else self.height_scale
            gain=min(max(gain,.2),5.0)
            self._gains[u]=gain
        return Vector((delta.x*self.scale,delta.y*self.scale,delta.z*gain))


class EyeFrameTransform:
    """The iris and highlight share the aperture's size and relative center."""
    def __init__(self,aperture):
        self.source=aperture.source.frame
        self.target=aperture.target.frame
        x=self.target.width/max(self.source.width,1e-9)
        z=self.target.height/max(self.source.height,1e-9)
        self.gains=Vector((x,sqrt(x*z),z))

    def delta(self,delta):
        return Vector(tuple(delta[a]*self.gains[a] for a in range(3)))

    def warp(self,point):
        return self.target.center+self.delta(point-self.source.center)


def brow_lash_parts(points,polygons,threshold,plane,side):
    """Classify a strip as a whole, without matching source/target islands.

    A horizontal threshold through a sloping upper lash otherwise assigns its
    tip to the brow while its root closes with the eye, producing long spikes.
    Connectivity is only used for coherence within this one annotated mesh.
    """
    graph=defaultdict(set)
    for poly in polygons:
        ids=[i for i in poly if (1 if points[i].x>=plane else -1)==side]
        for i in ids:graph[i].update(ids)
    remaining=set(graph);parts={}
    while remaining:
        seed=remaining.pop();component={seed};queue=[seed]
        while queue:
            for i in graph[queue.pop()]:
                if i in remaining:
                    remaining.remove(i);component.add(i);queue.append(i)
        heights=sorted(points[i].z for i in component)
        middle=len(heights)//2
        median=(heights[middle]+heights[(len(heights)-1)//2])/2
        part=2 if median>=threshold else 1
        for i in component:parts[i]=part
    return parts


def boundary_cycles(graph):
    """Trace real edge cycles even when a material boundary has side branches."""
    visited=set();loops=[]
    for root in sorted(graph):
        if root in visited:continue
        path=[root];active={root:0};visited.add(root)
        stack=[(root,None,iter(sorted(graph[root])))]
        while stack:
            vertex,parent,adjacent=stack[-1];other=next(adjacent,None)
            if other is None:
                stack.pop();active.pop(vertex);path.pop();continue
            if other==parent:continue
            if other in active:
                cycle=path[active[other]:]
                if len(cycle)>=3:loops.append(cycle.copy())
            elif other not in visited:
                visited.add(other);active[other]=len(path);path.append(other)
                stack.append((other,vertex,iter(sorted(graph[other]))))
    return loops


def face_openings(polygons, labels, points):
    """Find Face boundary loops; connectivity only identifies the openings.

    Correspondence is made by opening location and silhouette, not loop IDs,
    valences, or equal vertex counts. Closed lips can touch at vertices, joining
    the upper/lower chains into an even-degree closed boundary graph.
    """
    edges=defaultdict(int)
    oral_edges=set()
    for poly,label in zip(polygons,labels):
        if label in ORAL_REGIONS:
            oral_edges.update(tuple(sorted((a,b))) for a,b in zip(poly,poly[1:]+poly[:1]))
        if label!=0:
            continue
        for a,b in zip(poly,poly[1:]+poly[:1]):
            edges[tuple(sorted((a,b)))]+=1
    graph=defaultdict(set)
    for (a,b),count in edges.items():
        if count==1:
            graph[a].add(b); graph[b].add(a)
    # A tiny outside-material loop can touch the true mouth at a corner.
    # An Euler walk through both loops assigns the side loop to opposite lips.
    # Prefer the closed Face/cavity interface when material evidence exists;
    # keep the full graph as fallback for separate or closed cavity meshes.
    oral_graph=defaultdict(set)
    for a,b in oral_edges:
        if edges.get((a,b))==1:
            oral_graph[a].add(b);oral_graph[b].add(a)
    def components(boundary, oral_boundary=False):
        remaining=set(boundary)
        found=[]
        while remaining:
            root=next(iter(remaining));part={root};queue=[root];remaining.remove(root)
            while queue:
                for j in boundary[queue.pop()]:
                    if j in remaining:
                        remaining.remove(j);part.add(j);queue.append(j)
            if len(part)<3 or not all(len(boundary[i]) in (2,4) for i in part):continue
            unused={i:set(boundary[i]) for i in part};stack=[min(part)];order=[]
            while stack:
                current=stack[-1]
                if unused[current]:
                    following=min(unused[current]);unused[current].remove(following)
                    unused[following].remove(current);stack.append(following)
                else:order.append(stack.pop())
            vertices=order[::-1][:-1];cloud=[points[i] for i in vertices]
            try:
                frame=MouthFrame(cloud)
                found.append(dict(points=cloud,vertices=vertices,center=frame.center,width=frame.width,height=frame.height,
                    contact_vertices=sum(len(boundary[i])==4 for i in part),oral_boundary=oral_boundary))
            except ValueError:pass
        return found
    found=components(graph)+components(oral_graph,True)
    seen={(frozenset(row['vertices']),row['oral_boundary']) for row in found}
    for boundary,oral_boundary in ((graph,False),(oral_graph,True)):
        for ring in boundary_cycles(boundary):
            if (frozenset(ring),oral_boundary) in seen:continue
            cloud=[points[i] for i in ring]
            try:frame=MouthFrame(cloud)
            except ValueError:continue
            found.append(dict(points=cloud,vertices=ring,center=frame.center,width=frame.width,height=frame.height,
                              contact_vertices=0,oral_boundary=oral_boundary))
            seen.add((frozenset(ring),oral_boundary))
    return found


def opening_candidates(openings, region_points, face_width, mouth=False):
    """Location/size candidates only; a material seam is not proof of a lip."""
    if len(region_points)<3:
        return []
    try:
        anchor=OutlineFrame(region_points)
    except ValueError:
        anchor=MouthFrame(region_points)
    choices=[]
    for row in openings:
        if row['width']>face_width*0.65:
            continue  # Outer head/neck boundary is not a mouth or eye hole.
        dx=row['center'].x-anchor.center.x
        dz=row['center'].z-anchor.center.z
        distance=sqrt(dx*dx+dz*dz)
        if distance>face_width*0.3:
            continue
        if mouth:
            # The cavity localizes the ring. Check bilateral overlap so a
            # nearby eye/ear boundary cannot replace a missing lip boundary.
            half=max(anchor.width/2,face_width*.025)
            if not row['center'].x-row['width']/2 < anchor.center.x < row['center'].x+row['width']/2:
                continue
            if abs(dx)>half or abs(dz)>max(anchor.height,face_width*.12):
                continue
            if row['height']>row['width']*.85:
                continue
        else:
            # A crease above the eye is a narrow strip, not the aperture.
            if row['height']<anchor.height*.3 or abs(dx)>anchor.width*.75:
                continue
        size=abs(row['width']-anchor.width)/max(row['width'],anchor.width,1e-9)
        choices.append((distance/max(face_width,1e-9)+0.08*size,row))
    return choices


def pick_opening(openings, region_points, face_width, mouth=False):
    choices=opening_candidates(openings,region_points,face_width,mouth=mouth)
    if mouth and any(row.get('oral_boundary') for score,row in choices):
        choices=[(score,row) for score,row in choices if row.get('oral_boundary')]
    return min(choices,key=lambda item:item[0])[1]['points'] if choices else None
