"""N-panel UI: settings, buttons, and the scan readout."""

import json

import bpy

try:
    from . import operators as ops
except ImportError:                       # pragma: no cover - script mode
    import operators as ops


CATEGORY = "ExpressionGen"


class EXPRKIT_Settings(bpy.types.PropertyGroup):
    """Everything the panel binds to, stored on the Scene."""

    # ---- pipeline selection
    mode: bpy.props.EnumProperty(
        name="模式",
        description="自动 = 识别到足够原子就走原子组合，否则走程序化生成",
        items=[
            ("AUTO", "自动", "有原子就组合，没有就程序化生成"),
            ("ATOMS", "仅原子组合", "只使用模型已有的表情，质量最高"),
            ("PROCEDURAL", "仅程序化生成", "忽略已有表情，纯几何规则生成"),
        ],
        default="AUTO",
    )
    atom_threshold: bpy.props.IntProperty(
        name="原子数阈值",
        description="识别到多少个原子才认为这个模型「有表情」",
        default=8, min=1, max=64,
    )

    # ---- scope
    # NOTE: an annotated assignment (``x: T = v``) may NOT take a trailing
    # comma - ``x: T = v,`` is a SyntaxError.  Blender reads ``__annotations__``
    # so the annotation form is kept, just without the stray commas.
    use_selection: bpy.props.BoolProperty(
        name="只处理选中物体", default=True,
        description="关闭则处理场景内所有网格")
    armature: bpy.props.PointerProperty(
        name="骨架",
        description="程序化生成用的骨架；留空则自动查找",
        type=bpy.types.Object,
        poll=lambda self, ob: ob.type == "ARMATURE")
    spec_dir: bpy.props.StringProperty(
        name="自定义规范目录",
        description="留空使用内置的 46 条标准表情规范",
        subtype="DIR_PATH",
        default="")

    # ---- expression selection
    panel_eye: bpy.props.BoolProperty(name="眼", default=True)
    panel_mouth: bpy.props.BoolProperty(name="口", default=True)
    panel_eyebrow: bpy.props.BoolProperty(name="眉", default=True)
    panel_other: bpy.props.BoolProperty(name="其他", default=True)

    # ---- options
    naming: bpy.props.EnumProperty(
        name="命名方案",
        description=("按哪种约定给生成的表情命名。下游工具只认名字，"
                     "选错了动作就驱动不了"),
        items=[
            ("MMD", "MMD（日本語）",
             "まばたき / ウィンク / あ —— MMD 与所有 VMD 流程"),
            ("VRM", "VRM（camelCase）",
             "blink / blinkLeft / aa —— UniVRM、VRM4U 的 18 个预设名"),
            ("FBX", "FBX（English）",
             "Blink / Wink / A —— 纯 ASCII，FBX 往返不坏"),
            ("BLENDER", "Blender（id）",
             "blink / wink / a —— 小写下划线，脚本友好"),
        ],
        default="MMD")
    skip_existing: bpy.props.BoolProperty(
        name="跳过同名表情", default=True,
        description="模型已有同名形态键时不覆盖（MMD 原生模型建议开启）")
    include_empty: bpy.props.BoolProperty(
        name="生成素の表情", default=True,
        description="为空配方生成零位移形态键，对应 MMD 的 ニュートラル")
    arkit: bpy.props.BoolProperty(
        name="同时生成 ARKit 命名", default=False,
        description="额外生成 eyeBlinkLeft 等 ARKit 52 命名，供面部捕捉使用")
    swap_wink: bpy.props.BoolProperty(
        name="左右眼对调", default=False,
        description="若 ウィンク 闭的是错误的眼，勾选此项后重新生成")
    rename_atoms: bpy.props.BoolProperty(
        name="原子改名为 atom id", default=False,
        description="把 Eyebrow_Angry 之类的原名改成 brow_angry，可撤销")

    # ---- procedural tuning
    eye_scale: bpy.props.FloatProperty(
        name="眼部范围", default=0.58, min=0.15, max=1.2, precision=2,
        description="眼部区域半径，以双眼间距的一半为单位")
    mouth_scale: bpy.props.FloatProperty(
        name="口部范围", default=0.66, min=0.15, max=1.2, precision=2,
        description="口部区域半径，以双眼间距的一半为单位")
    strength: bpy.props.FloatProperty(
        name="强度", default=1.0, min=0.1, max=3.0, precision=2,
        description="程序化生成的位移倍率")

    # ---- manual landmarks
    use_manual_landmarks: bpy.props.BoolProperty(
        name="手动指定地标", default=False,
        description="骨架识别不到时，手工填写眼睛和嘴巴的坐标")
    lm_eye_L: bpy.props.FloatVectorProperty(name="左眼", default=(0.0, 0.0, 0.0))
    lm_eye_R: bpy.props.FloatVectorProperty(name="右眼", default=(0.0, 0.0, 0.0))
    lm_mouth: bpy.props.FloatVectorProperty(name="口", default=(0.0, 0.0, 0.0))


# ------------------------------------------------------------------- panel

class EXPRKIT_PT_main(bpy.types.Panel):
    bl_idname = "EXPRKIT_PT_main"
    bl_label = "当前模型生成标准表情"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_order = 20
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s = context.scene.exprkit

        self.layout.label(text="组合已有表情，或按地标生成基础表情")
        box = self.layout.box()
        box.label(text="1 · 选择处理范围")
        box.prop(s, "use_selection")
        box.prop(s, "mode")
        if s.mode != "ATOMS":
            box.prop(s, "armature")

        box = self.layout.box()
        box.label(text="2 · 选择表情与命名")
        row = box.row(align=True)
        for attr in ("panel_eye", "panel_mouth", "panel_eyebrow", "panel_other"):
            row.prop(s, attr, toggle=True)

        box.prop(s, "naming")
        box.prop(s, "skip_existing")
        box = self.layout.box()
        box.label(text="3 · 扫描后生成")
        box.operator("exprkit.scan", icon="VIEWZOOM", text="扫描模型与命名预览")
        box.operator("exprkit.build", icon="SHAPEKEY_DATA", text="生成标准表情")
        box.label(text="检查下面的扫描结果与形态键")


class EXPRKIT_PT_procedural(bpy.types.Panel):
    bl_idname = "EXPRKIT_PT_procedural"
    bl_label = "程序化生成参数"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_parent_id = "EXPRKIT_PT_main"
    bl_order = 1
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return context.scene.exprkit.mode != "ATOMS"

    def draw(self, context):
        s, box = context.scene.exprkit, self.layout
        box.label(text="没有可用表情时，按面部地标生成")
        box.prop(s, "eye_scale")
        box.prop(s, "mouth_scale")
        box.prop(s, "strength")
        box.prop(s, "use_manual_landmarks")
        if s.use_manual_landmarks:
            sub = box.column(align=True)
            sub.prop(s, "lm_eye_L")
            sub.prop(s, "lm_eye_R")
            sub.prop(s, "lm_mouth")


class EXPRKIT_PT_advanced(bpy.types.Panel):
    bl_idname = "EXPRKIT_PT_advanced"
    bl_label = "高级选项与清理"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_parent_id = "EXPRKIT_PT_main"
    bl_order = 2
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        s, box = context.scene.exprkit, self.layout
        if s.mode == "AUTO":
            box.prop(s, "atom_threshold")
        box.prop(s, "include_empty")
        box.prop(s, "arkit")
        box.prop(s, "swap_wink")
        box.prop(s, "rename_atoms")
        box.prop(s, "spec_dir")
        box.operator("exprkit.rename_atoms", icon="SORTALPHA")
        box.operator("exprkit.export_report", icon="EXPORT")
        box.separator()
        box.operator("exprkit.clear", icon="TRASH", text="清除插件生成的表情")


class EXPRKIT_PT_report(bpy.types.Panel):
    bl_idname = "EXPRKIT_PT_report"
    bl_label = "扫描结果"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_parent_id = "EXPRKIT_PT_main"
    bl_order = 0
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        _draw_report_body(self.layout, context)


def _draw_report_body(layout, context):
    raw = context.scene.get(ops.REPORT_PROP)
    if not raw:
        layout.label(text="尚未扫描", icon="INFO")
        return
    try:
        rep = json.loads(raw)
    except ValueError:
        layout.label(text="报告已损坏", icon="ERROR")
        return

    layout.label(text="时间 %s" % rep.get("generated_at", "?"))
    spec = rep.get("spec") or {}
    layout.label(text="规范 %s 条 / %s 原子" %
                 (spec.get("expressions"), spec.get("atoms")))
    if rep.get("naming"):
        layout.label(text="命名方案 %s" % rep["naming"], icon="SORTALPHA")

    for rec in rep.get("objects", []):
        box = layout.box()
        head = box.row()
        head.label(text=rec.get("object", "?"),
                   icon="MESH_DATA" if rec.get("mode") != "none" else "ERROR")
        if rec.get("mode") == "atoms":
            head.label(text="原子", icon="SHAPEKEY_DATA")
        elif rec.get("mode") == "procedural":
            head.label(text="程序化", icon="MOD_MESHDEFORM")

        if rec.get("error"):
            box.label(text=rec["error"], icon="ERROR")
        if rec.get("problem") and not rec.get("error"):
            box.label(text=rec["problem"], icon="INFO")

        if "vertices" in rec:
            box.label(text="顶点 %d ／ 形态键 %d" %
                      (rec["vertices"], rec.get("shape_key_count", 0)))
        if rec.get("atoms_matched") is not None:
            box.label(text="原子 %d ／ 未识别键 %d" %
                      (rec.get("atoms_matched", 0),
                       len(rec.get("unmatched_keys") or [])))
        if rec.get("created"):
            box.label(text="生成 %d 个" % len(rec["created"]))
        if rec.get("skipped_existing"):
            box.label(text="跳过同名 %d 个" % len(rec["skipped_existing"]))
        if rec.get("partial"):
            box.label(text="配方不全 %d 个" % len(rec["partial"]), icon="INFO")
        # VRM 只有 18 个预设名，几条表情会撞在一起；被降级成自定义名的
        # 那些必须报出来，否则用户会以为表情丢了。
        for fb in (rec.get("name_fallbacks") or [])[:6]:
            box.label(text="%s：%s → %s" %
                      (fb["id"], fb["wanted"], fb["given"]), icon="INFO")
        if rec.get("landmarks"):
            lm = rec["landmarks"]
            box.label(text="地标 %s（%s）" %
                      ("完整" if lm.get("complete") else "不完整",
                       lm.get("confidence")))
        if rec.get("regions"):
            box.label(text="区域 " + " ".join(
                "%s:%d" % (k, v) for k, v in rec["regions"].items()))

        prev = rec.get("name_preview")
        if prev:
            box.label(text="将生成 %d 个（%s 命名）" %
                      (prev.get("count", 0), prev.get("naming", "?")),
                      icon="SORTALPHA")
            for fb in (prev.get("fallbacks") or [])[:4]:
                box.label(text="%s：%s → %s" %
                          (fb["id"], fb["wanted"], fb["given"]), icon="INFO")
            shown = prev.get("names") or []
            for n in shown[:8]:
                box.label(text="· %s" % n["name"])
            if len(shown) > 8:
                box.label(text="… 另有 %d 个" % (len(shown) - 8))


class EXPRKIT_PT_help(bpy.types.Panel):
    bl_idname = "EXPRKIT_PT_help"
    bl_label = "帮助"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = CATEGORY
    bl_parent_id = "EXPRKIT_PT_main"
    bl_order = 3
    bl_options = {"DEFAULT_CLOSED"}

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text="模型已有表情 → 自动组合")
        col.label(text="完全没有表情 → 按骨骼地标几何生成")
        col.separator()
        col.label(text="命名方案：下游工具只认名字")
        col.label(text="MMD    まばたき / あ")
        col.label(text="VRM    blink / blinkLeft / aa")
        col.label(text="FBX    Blink / A")
        col.label(text="Blender  blink / a")
        col.separator()
        col.label(text="想同时要四套名字：换命名方案")
        col.label(text="再点一次生成（同名会自动跳过）")
        col.separator()
        col.label(text="程序化生成需要眼睛/嘴巴骨骼：")
        col.label(text="MMD: 左目 右目 口 頭 首")
        col.label(text="VRM: LeftEye RightEye Jaw")
        col.separator()
        col.label(text="生成是启发式的，不替代绑定师")
        col.label(text="改名前请先备份 .blend")


CLASSES = (EXPRKIT_Settings, EXPRKIT_PT_main, EXPRKIT_PT_report,
           EXPRKIT_PT_procedural, EXPRKIT_PT_advanced, EXPRKIT_PT_help)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    bpy.types.Scene.exprkit = bpy.props.PointerProperty(type=EXPRKIT_Settings)


def unregister():
    try:
        del bpy.types.Scene.exprkit
    except AttributeError:
        pass
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
