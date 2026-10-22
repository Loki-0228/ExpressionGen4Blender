"""Optional CUDA triangle contacts, using the driver and NVRTC already installed.

No Blender meshes or UI are touched here. Any initialization/launch failure
disables this backend for the current generation and leaves CPU fallback live.
"""
import ctypes as C
import os
from pathlib import Path
import threading
import time
import numpy as np

_backend=None
_disabled=False
_mode='AUTO'
_lock=threading.RLock()
_stats={}


def configure(mode='AUTO'):
    global _mode,_disabled,_stats
    _mode=mode;_disabled=False
    _stats=dict(requested=mode,device='CPU',gpu_calls=0,cpu_calls=0,gpu_seconds=0.,fallback_reason='')


def statistics():return dict(_stats)


def shutdown():
    global _backend
    with _lock:
        if _backend is not None:
            try:_backend.close()
            finally:_backend=None


def _nvrtc_path():
    roots=[Path(value) for key,value in os.environ.items() if key.startswith('CUDA_PATH') and value]
    if os.name=='nt':
        roots+=list((Path(os.environ.get('ProgramFiles','C:/Program Files'))/'NVIDIA GPU Computing Toolkit/CUDA').glob('v*'))
        for root in sorted(set(roots),reverse=True):
            found=sorted((root/'bin').glob('nvrtc64_*.dll'))
            found=[p for p in found if '.alt.' not in p.name]
            if found:return found[-1]
    raise RuntimeError('未找到 CUDA NVRTC 运行库')


def _bind(lib,name,args):
    fn=getattr(lib,name);fn.argtypes=args;fn.restype=C.c_int
    return fn


class Backend:
    def __init__(self):
        path=_nvrtc_path()
        self.dll_directory=os.add_dll_directory(str(path.parent))
        self.driver=C.WinDLL('nvcuda.dll');self.nvrtc=C.CDLL(str(path))
        p=C.c_void_p;u=C.c_uint;ull=C.c_uint64;i=C.c_int;size=C.c_size_t
        signatures={
            'cuInit':[u],'cuDeviceGet':[C.POINTER(i),i],
            'cuDeviceGetName':[p,i,i],'cuDeviceGetAttribute':[C.POINTER(i),i,i],
            'cuDevicePrimaryCtxRetain':[C.POINTER(p),i],
            'cuDevicePrimaryCtxRelease_v2':[i],
            'cuCtxPushCurrent_v2':[p],'cuCtxPopCurrent_v2':[C.POINTER(p)],
            'cuModuleLoadData':[C.POINTER(p),p],'cuModuleUnload':[p],
            'cuModuleGetFunction':[C.POINTER(p),p,C.c_char_p],
            'cuMemAlloc_v2':[C.POINTER(ull),size],'cuMemFree_v2':[ull],
            'cuMemcpyHtoD_v2':[ull,p,size],'cuMemcpyDtoH_v2':[p,ull,size],
            'cuLaunchKernel':[p,u,u,u,u,u,u,u,p,C.POINTER(p),C.POINTER(p)],
            'cuCtxSynchronize':[]}
        self.api={name:_bind(self.driver,name,args) for name,args in signatures.items()}
        self.context=p();self.module=p();self.device=i();self.buffers={};self.function=p()
        self.call('cuInit',0);self.call('cuDeviceGet',C.byref(self.device),0)
        name=C.create_string_buffer(256);self.call('cuDeviceGetName',name,256,self.device)
        self.name=name.value.decode('utf8','replace')
        major=i();minor=i()
        self.call('cuDeviceGetAttribute',C.byref(major),75,self.device)
        self.call('cuDeviceGetAttribute',C.byref(minor),76,self.device)
        self.call('cuDevicePrimaryCtxRetain',C.byref(self.context),self.device)
        try:
            self.push()
            try:
                ptx=self.compile(major.value*10+minor.value)
                self.call('cuModuleLoadData',C.byref(self.module),ptx)
                self.call('cuModuleGetFunction',C.byref(self.function),self.module,b'depth_contacts')
            finally:self.pop()
        except Exception:
            self.close();raise

    def call(self,name,*args):
        code=self.api[name](*args)
        if code:raise RuntimeError('%s 返回 CUDA 错误 %d'%(name,code))

    def push(self):self.call('cuCtxPushCurrent_v2',self.context)

    def pop(self):
        previous=C.c_void_p();self.call('cuCtxPopCurrent_v2',C.byref(previous))

    def compile(self,architecture):
        p=C.c_void_p;program=p();size=C.c_size_t()
        create=_bind(self.nvrtc,'nvrtcCreateProgram',[C.POINTER(p),C.c_char_p,C.c_char_p,C.c_int,p,p])
        compile_program=_bind(self.nvrtc,'nvrtcCompileProgram',[p,C.c_int,C.POINTER(C.c_char_p)])
        destroy=_bind(self.nvrtc,'nvrtcDestroyProgram',[C.POINTER(p)])
        get_size=_bind(self.nvrtc,'nvrtcGetPTXSize',[p,C.POINTER(C.c_size_t)])
        get_ptx=_bind(self.nvrtc,'nvrtcGetPTX',[p,p])
        code=create(C.byref(program),KERNEL.encode(),b'expressiongen_contacts.cu',0,None,None)
        if code:raise RuntimeError('NVRTC 创建程序失败：%d'%code)
        try:
            opts=(C.c_char_p*3)(('--gpu-architecture=compute_%d'%architecture).encode(),b'--fmad=false',b'--std=c++11')
            code=compile_program(program,3,opts)
            if code:
                _bind(self.nvrtc,'nvrtcGetProgramLogSize',[p,C.POINTER(C.c_size_t)])(program,C.byref(size))
                log=C.create_string_buffer(size.value or 1)
                _bind(self.nvrtc,'nvrtcGetProgramLog',[p,p])(program,log)
                raise RuntimeError('NVRTC 编译失败：'+log.value.decode('utf8','replace')[:1400])
            code=get_size(program,C.byref(size))
            if code:raise RuntimeError('NVRTC PTX 大小读取失败：%d'%code)
            ptx=C.create_string_buffer(size.value)
            if get_ptx(program,ptx):raise RuntimeError('NVRTC PTX 读取失败')
            return ptx
        finally:destroy(C.byref(program))

    def upload(self,key,array):
        array=np.ascontiguousarray(array);entry=self.buffers.get(key)
        if entry is None or entry[1]<array.nbytes:
            if entry is not None:self.call('cuMemFree_v2',entry[0])
            self.buffers.pop(key,None);address=C.c_uint64()
            self.call('cuMemAlloc_v2',C.byref(address),max(array.nbytes,8))
            entry=(address,max(array.nbytes,8));self.buffers[key]=entry
        self.call('cuMemcpyHtoD_v2',entry[0],array.ctypes.data,array.nbytes)
        return entry[0]

    def depth(self,points,ids,obstacles,movable,front,coherent,tolerance,pulse,rest=None,obstacle_rest=None):
        self.push()
        try:
            out=np.zeros(len(points),dtype=np.float64);counts=np.zeros(2,dtype=np.uint64)
            arrays=(np.asarray(points,dtype=np.float64),np.asarray(ids,dtype=np.int32),
                    np.asarray(obstacles,dtype=np.float64),np.asarray(movable,dtype=np.float64),out,counts)
            addresses=[self.upload(str(k),a) for k,a in enumerate(arrays)]
            reference=[addresses[0],addresses[2]] if rest is None else [self.upload('rest',np.asarray(rest,dtype=np.float64)),self.upload('obstacle_rest',np.asarray(obstacle_rest,dtype=np.float64))]
            args=addresses+reference+[C.c_int(len(ids)),C.c_int(len(obstacles)),C.c_double(-1. if front else 1.),
                            C.c_int(bool(coherent)),C.c_int(rest is not None),C.c_double(tolerance),C.c_uint64(0),C.c_uint64(0)]
            params=(C.c_void_p*len(args))(*[C.cast(C.byref(a),C.c_void_p) for a in args])
            pairs=len(ids)*len(obstacles)
            # Bound a single launch so background progress/cancellation remains
            # responsive on large meshes and display-driver watchdogs stay safe.
            batch=4*1024*1024
            for start in range(0,pairs,batch):
                if pulse:pulse()
                size=min(batch,pairs-start);args[-2].value=start;args[-1].value=size
                self.call('cuLaunchKernel',self.function,(size+127)//128,1,1,128,1,1,0,None,params,None)
                self.call('cuCtxSynchronize')
            self.call('cuMemcpyDtoH_v2',out.ctypes.data,addresses[4],out.nbytes)
            self.call('cuMemcpyDtoH_v2',counts.ctypes.data,addresses[5],counts.nbytes)
            recorder=getattr(pulse,'count',None)
            if recorder:recorder(depth_bbox_pairs=pairs,depth_overlap_pairs=int(counts[1]))
            return out*(-1. if front else 1.),int(counts[0])
        finally:self.pop()

    def close(self):
        if not self.context.value:return
        try:
            self.push()
            try:
                for address,_ in self.buffers.values():self.api['cuMemFree_v2'](address)
                self.buffers.clear()
                if self.module.value:self.api['cuModuleUnload'](self.module)
            finally:self.pop()
        finally:
            self.api['cuDevicePrimaryCtxRelease_v2'](self.device);self.context=C.c_void_p()


def try_depth(points,ids,obstacles,movable,front,coherent,tolerance,pulse=None,rest=None,obstacle_rest=None):
    global _backend,_disabled
    if not _stats:configure()
    if _mode=='CPU' or _disabled or len(ids)*len(obstacles)<8192:
        _stats['cpu_calls']+=1;return None
    with _lock:
        started=time.perf_counter()
        try:
            if _backend is None:_backend=Backend()
            result=_backend.depth(points,ids,obstacles,movable,front,coherent,tolerance,pulse,rest,obstacle_rest)
            _stats['device']=_backend.name;_stats['gpu_calls']+=1
            _stats['gpu_seconds']+=time.perf_counter()-started
            return result
        except Exception as exc:
            # Cancellation belongs to the caller, not to backend fallback.
            if pulse and type(exc).__module__.endswith('generation_progress'):raise
            _disabled=True;_stats['fallback_reason']=str(exc);_stats['cpu_calls']+=1
            if _backend is not None:
                try:_backend.close()
                except Exception:pass
                _backend=None
            return None


KERNEL=r'''
__device__ double cross(double ax,double az,double bx,double bz){return ax*bz-az*bx;}
__device__ bool bary(const double *t,double x,double z,double *w){
    double ax=t[3]-t[0],az=t[5]-t[2],bx=t[6]-t[0],bz=t[8]-t[2];
    double det=cross(ax,az,bx,bz),scale=fmax(ax*ax+az*az+bx*bx+bz*bz,1e-30);
    if(fabs(det)<=scale*1e-12)return false;
    double qx=x-t[0],qz=z-t[2];w[1]=cross(qx,qz,bx,bz)/det;w[2]=cross(ax,az,qx,qz)/det;w[0]=1-w[1]-w[2];
    return w[0]>=-1e-9 && w[1]>=-1e-9 && w[2]>=-1e-9 && w[0]<=1+1e-9 && w[1]<=1+1e-9 && w[2]<=1+1e-9;
}
__device__ bool area(const double *t){
    double ax=t[3]-t[0],az=t[5]-t[2],bx=t[6]-t[0],bz=t[8]-t[2];
    return fabs(cross(ax,az,bx,bz))>fmax(ax*ax+az*az+bx*bx+bz*bz,1e-30)*1e-12;
}
__device__ void maximum(double *p,double value){
    unsigned long long *address=(unsigned long long*)p,old=*address,assumed;
    while(__longlong_as_double(old)<value){assumed=old;old=atomicCAS(address,assumed,__double_as_longlong(value));if(old==assumed)break;}
}
__device__ void contact(const double *a,const double *b,const int *ids,const double *mob,
                       double *out,unsigned long long *counts,double *wa,double *wb,double sign,int coherent,double tol,
                       const double *rest,const double *obrest,int allowance){
    double sa=0,sb=0;for(int j=0;j<3;++j){wa[j]=fmax(wa[j],0.);wb[j]=fmax(wb[j],0.);sa+=wa[j];sb+=wb[j];}
    double ay=0,by=0,den=0;
    for(int j=0;j<3;++j){wa[j]/=fmax(sa,1e-30);wb[j]/=fmax(sb,1e-30);ay+=wa[j]*a[3*j+1];by+=wb[j]*b[3*j+1];den+=(coherent?wa[j]:wa[j]*wa[j])*mob[ids[j]];}
    double need=sign*(by-ay);
    if(allowance){double ay0=0,by0=0;for(int j=0;j<3;++j){ay0+=wa[j]*rest[ids[j]*3+1];by0+=wb[j]*obrest[j*3+1];}need+=fmin(sign*(ay0-by0),0.);}
    if(need<=tol)return;
    if(den<=1e-12){atomicAdd(counts,1ULL);return;}
    for(int j=0;j<3;++j)maximum(out+ids[j],need*(coherent?1.:wa[j])*mob[ids[j]]/den);
}
extern "C" __global__ void depth_contacts(const double *points,const int *tri,const double *obstacles,
    const double *movable,double *out,unsigned long long *counts,const double *rest,const double *obstacle_rest,
    int n,int m,double sign,int coherent,int allowance,double tol,
    unsigned long long start,unsigned long long size){
    unsigned long long local=(unsigned long long)blockIdx.x*blockDim.x+threadIdx.x;if(local>=size)return;
    unsigned long long pair=start+local;int ia=pair/m,ib=pair%m;if(ia>=n)return;
    int ids[3]={tri[ia*3],tri[ia*3+1],tri[ia*3+2]};double a[9];const double *b=obstacles+ib*9;
    for(int j=0;j<3;++j)for(int k=0;k<3;++k)a[j*3+k]=points[ids[j]*3+k];
    for(int k=0;k<3;k+=2){
        double al=fmin(a[k],fmin(a[k+3],a[k+6])),ah=fmax(a[k],fmax(a[k+3],a[k+6]));
        double bl=fmin(b[k],fmin(b[k+3],b[k+6])),bh=fmax(b[k],fmax(b[k+3],b[k+6]));
        if(al>bh || ah<bl)return;
    }
    atomicAdd(counts+1,1ULL);if(!area(a)||!area(b))return;
    for(int i=0;i<3;++i){
        double wa[3]={0,0,0},wb[3]={0,0,0};wa[i]=1;
        if(bary(b,a[i*3],a[i*3+2],wb))contact(a,b,ids,movable,out,counts,wa,wb,sign,coherent,tol,rest,obstacle_rest+ib*9,allowance);
        wa[0]=wa[1]=wa[2]=0;wb[0]=wb[1]=wb[2]=0;wb[i]=1;
        if(bary(a,b[i*3],b[i*3+2],wa))contact(a,b,ids,movable,out,counts,wa,wb,sign,coherent,tol,rest,obstacle_rest+ib*9,allowance);
    }
    for(int i=0;i<3;++i)for(int k=0;k<3;++k){
        int j=(i+1)%3,l=(k+1)%3;
        double rx=a[j*3]-a[i*3],rz=a[j*3+2]-a[i*3+2],sx=b[l*3]-b[k*3],sz=b[l*3+2]-b[k*3+2];
        double denominator=cross(rx,rz,sx,sz),scale=fmax(sqrt(rx*rx+rz*rz)*sqrt(sx*sx+sz*sz),1e-30);
        if(fabs(denominator)<=scale*1e-12)continue;
        double qx=b[k*3]-a[i*3],qz=b[k*3+2]-a[i*3+2],u=cross(qx,qz,sx,sz)/denominator,v=cross(qx,qz,rx,rz)/denominator;
        if(u<-1e-9 || u>1+1e-9 || v<-1e-9 || v>1+1e-9)continue;
        double wa[3]={0,0,0},wb[3]={0,0,0};wa[i]=1-u;wa[j]=u;wb[k]=1-v;wb[l]=v;
        contact(a,b,ids,movable,out,counts,wa,wb,sign,coherent,tol,rest,obstacle_rest+ib*9,allowance);
    }
}
'''
