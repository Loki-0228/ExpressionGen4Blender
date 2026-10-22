"""ExpressionGen: target-only procedural expressions and editable contours."""

bl_info = {
    "name": "ExpressionGen",
    "author": "ExpressionGen",
    "version": (2, 0, 0),
    # Current node interfaces, GPU shader names and UILayout.progress use
    # Blender 4.0 APIs; expression generation does not require Blender 4.5.
    "blender": (4, 0, 0),
    "location": "View3D > Sidebar (N) > ExpressionGen",
    "description": ("根据目标形状分区与可编辑轮廓，程序化生成 Vodyanitsa 派生表情；"
                    "支持分区修正、曲线编辑和同网格口腔随唇运动"),
    "warning": "已用模型副本验证生成流程；复杂眼角及中间权重的接触仍需检查",
    "doc_url": "https://github.com/Loki-0228/ExpressionGen4Blender",
    "category": "Object",
}

# Blender reloads the package initializer after an on-disk addon update.
# Reload dependencies as well, so an enabled older install cannot keep serving
# stale fitting code while the panel already comes from the new package.
if 'bpy' in locals():
    import importlib
    import sys
    _gpu=sys.modules.get(__name__+'.procedural_gpu')
    if _gpu is not None:_gpu.shutdown()
    _job=sys.modules.get(__name__+'.generation_job')
    if _job is not None:_job.shutdown()
    for _name in ('procedural_gpu','procedural_projection','generation_progress','generation_job','core','matcher','landmarks','generate','operators','ui',
                  'region_core','region_preset','region_blender','region_contours','region_detection','region_accessories','region_lashes','region_curve_fit','region_guides',
                  'region_deformation','region_eye_motion','region_rigid_parts','region_transfer','procedural_neutral','region_session','region_commit','region_ui',
                  'procedural_anatomy','procedural_surfaces','procedural_binding','procedural_tongue','procedural_lips','procedural_constraints','procedural_commit','procedural_oral','procedural_skin','procedural_rig','procedural_cavity','procedural_contacts','procedural_lashes','expression_rules','expression_runtime','procedural_atoms','procedural_generate','procedural_ui','expression_authoring','procedural_symmetry','expression_relations','curve_sculpt','expression_ui','guide_overlay','lifecycle'):
        _module=sys.modules.get(__name__+'.'+_name)
        if _module is not None:importlib.reload(_module)

import bpy

try:
    from . import core, matcher, landmarks, generate, operators, ui
    from . import region_core, region_blender, region_contours, region_detection, region_accessories, region_lashes, region_curve_fit, region_guides, region_deformation, region_eye_motion, region_rigid_parts, region_transfer, procedural_neutral, region_session, region_commit, region_ui
    from . import procedural_anatomy,procedural_surfaces,procedural_binding,procedural_tongue,procedural_lips,procedural_constraints,procedural_oral,procedural_skin,procedural_rig,procedural_cavity,procedural_lashes,procedural_atoms,procedural_generate,procedural_ui,guide_overlay
    from . import expression_rules,expression_runtime,expression_authoring,procedural_contacts,procedural_symmetry,expression_relations,curve_sculpt,expression_ui
    from . import lifecycle
except ImportError as exc:                # pragma: no cover
    raise ImportError(
        "ExpressionGen: 模块导入失败（%s）。请确认整个文件夹一起安装，"
        "而不是只拷贝 __init__.py。" % exc)

_MODULES = (region_ui,procedural_ui,expression_ui)

#: order matters - operators first, then the panel that references them
_RELOAD = (core, matcher, landmarks, generate, operators, ui,
           region_core, region_blender, region_contours, region_detection, region_accessories, region_lashes, region_curve_fit, region_guides, region_deformation, region_eye_motion, region_rigid_parts, region_transfer, procedural_neutral, region_session, region_commit, region_ui,
           procedural_anatomy,procedural_surfaces,procedural_binding,procedural_lips,procedural_constraints,procedural_oral,procedural_skin,procedural_rig,procedural_cavity,procedural_lashes,expression_rules,expression_runtime,procedural_atoms,procedural_generate,procedural_ui,expression_authoring,procedural_contacts,procedural_symmetry,expression_relations,curve_sculpt,expression_ui,guide_overlay,lifecycle)


def register():
    lifecycle.register(_MODULES)


def unregister():
    from . import generation_job
    generation_job.shutdown()
    lifecycle.unregister(_MODULES)
    from . import procedural_gpu
    procedural_gpu.shutdown()


if __name__ == "__main__":
    register()
