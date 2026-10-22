"""Optional native ordered projections, with the original NumPy fallback."""
import ctypes
from pathlib import Path
import sys
import numpy as np

_library=None
_attempted=False


def native():
    global _library,_attempted
    if _attempted:return _library
    _attempted=True
    # The DLL loader checks the actual architecture. platform.machine() can
    # be empty in Blender's restricted background environment.
    if sys.platform!='win32' or ctypes.sizeof(ctypes.c_void_p)!=8:return None
    try:
        library=ctypes.CDLL(str(Path(__file__).parent/'native'/'covering_win64.dll'))
        library.ek_covering_abi.restype=ctypes.c_int
        if library.ek_covering_abi()!=1:return None
        pointer=np.ctypeslib.ndpointer(dtype=np.float64,flags='C_CONTIGUOUS')
        library.ek_covering_project.argtypes=[ctypes.c_int,ctypes.c_int,pointer,pointer,pointer,pointer,
                                            pointer,pointer,ctypes.c_double,ctypes.c_int]
        library.ek_covering_project.restype=ctypes.c_int
        _library=library
    except (OSError,AttributeError,ValueError):pass
    return _library


def project(rows,bounds,directions,norm,tolerance,iterations=16384,pulse=None):
    rows,bounds,directions,norm=[np.ascontiguousarray(a,dtype=np.float64) for a in (rows,bounds,directions,norm)]
    size=rows.shape[1];count=len(rows)
    if (bounds.shape!=(count,) or directions.shape!=rows.shape or norm.shape!=(count,)
            or not all(np.isfinite(a).all() for a in (rows,bounds,directions,norm))):
        raise ValueError('睫毛覆盖约束包含无效数值')
    controls=np.zeros(size);dual=np.zeros(count);library=native()
    if library is not None and count and size<=1024:
        try:
            for start in range(0,iterations,256):
                if pulse:pulse('拟合睫毛覆盖约束',start,iterations)
                result=library.ek_covering_project(count,size,rows,bounds,directions,norm,
                    controls,dual,tolerance,min(256,iterations-start))
                if result<0:raise ValueError('覆盖约束加速计算失败')
                if result:return controls
            return controls
        except (ValueError,ctypes.ArgumentError):
            # Restart from zero; never continue with a partially updated state.
            controls.fill(0.);dual.fill(0.)
    for step in range(iterations):
        if pulse and step%64==0:pulse('拟合睫毛覆盖约束',step,iterations)
        for k,row in enumerate(rows):
            amount=max(dual[k]+float(row@controls-bounds[k])/max(norm[k],1e-20),0.)-dual[k]
            controls-=amount*directions[k];dual[k]+=amount
        if np.max(rows@controls-bounds)<=tolerance:break
    return controls
