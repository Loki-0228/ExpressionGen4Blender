"""Blender operators - the part that touches ``bpy``.

Everything interesting lives in ``core`` / ``matcher`` / ``generate`` and is
tested outside Blender.  This module is the thin skin that:

* picks the target meshes,
* reads vertex and shape-key data out of them,
* runs one of the two pipelines,
* writes shape keys back,
* records what it created so :class:`EXPRKIT_OT_clear` can undo it.

Two pipelines
-------------
``atoms``
    The model already has morphs.  Match them against ``data/atoms.json``,
    combine the matches with the recipes in ``data/expressions.json``, bake
    the result.  Artist-authored quality.
``procedural``
    The model has no usable morphs.  Find the face from the armature, carve
    the eye/mouth/brow regions out of the mesh, and push those vertices
    around by rule.  Heuristic quality, but it gives a bare model something
    a VMD action can drive.

Space convention: **everything stays in object-local space.**  Shape key data
is local, vertex data is local, so only the handful of landmark points get
converted out of world space.  Mixing the two is the classic way to end up
with morphs that fly off into the distance.
"""

import json
import os
import time

import bpy
from mathutils import Vector

try:
    from . import core, matcher
    from . import landmarks as lmmod
    from . import generate as genmod
except ImportError:                       # pragma: no cover - script mode
    import core
    import matcher
    import landmarks as lmmod
    import generate as genmod

META_KEY = "expression_kit"
META_VERSION = 2
REPORT_PROP = "exprkit_report"


# ------------------------------------------------------------------ helpers

def data_dir():
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_spec(settings=None):
    """Bundled spec, or the user's override directory when one is set."""
    d = data_dir()
    custom = getattr(settings, "spec_dir", "") if settings else ""
    if custom and os.path.isdir(custom):
        if os.path.exists(os.path.join(custom, "expressions.json")):
            d = custom
    return core.load_spec(d)


def target_meshes(context, use_selection):
    if use_selection:
        obs = [o for o in context.selected_objects if o.type == "MESH"]
        if obs:
            return obs
    return [o for o in context.scene.objects if o.type == "MESH"]


def armature_for(ob, context, explicit=None):
    """Find the armature that drives ``ob``.

    Explicit choice wins; then a modifier; then the parent chain; then, if the
    scene holds exactly one armature, that one.
    """
    if explicit is not None and explicit.type == "ARMATURE":
        return explicit
    for m in ob.modifiers:
        if m.type == "ARMATURE" and m.object is not None:
            return m.object
    p = ob.parent
    while p is not None:
        if p.type == "ARMATURE":
            return p
        p = p.parent
    arms = [o for o in context.scene.objects if o.type == "ARMATURE"]
    if len(arms) == 1:
        return arms[0]
    return None


def collect_bones(arm):
    """``{bone_name: (head_world, tail_world)}`` for the whole armature."""
    out = {}
    mw = arm.matrix_world
    for b in arm.data.bones:
        head = mw @ b.head_local
        tail = mw @ b.tail_local
        out[b.name] = ((head.x, head.y, head.z), (tail.x, tail.y, tail.z))
    return out


def read_vertices_flat(ob):
    """Vertex positions in object-local space."""
    n = len(ob.data.vertices)
    buf = [0.0] * (n * 3)
    ob.data.vertices.foreach_get("co", buf)
    return buf


def read_key_flat(kb):
    """Shape key positions in object-local space.

    ``foreach_get`` is two orders of magnitude faster than looping, and on a
    35k-vertex mesh that is the difference between a snappy addon and one that
    appears to hang.
    """
    try:
        buf = [0.0] * (len(kb.data) * 3)
        kb.data.foreach_get("co", buf)
        return buf
    except Exception:                     # pragma: no cover - very old builds
        out = []
        for p in kb.data:
            out.extend((p.co[0], p.co[1], p.co[2]))
        return out


def write_key_flat(kb, flat):
    try:
        kb.data.foreach_set("co", flat)
    except Exception:                     # pragma: no cover - very old builds
        for i, p in enumerate(kb.data):
            p.co = (flat[i * 3], flat[i * 3 + 1], flat[i * 3 + 2])


def world_to_local_points(points, matrix_inv):
    out = {}
    for slot, p in points.items():
        if p is None:
            out[slot] = None
            continue
        v = matrix_inv @ Vector(p)
        out[slot] = (v.x, v.y, v.z)
    return out


def key_names(ob):
    if ob.data.shape_keys is None:
        return []
    return [k.name for k in ob.data.shape_keys.key_blocks]


def unique_name(ob, base):
    """Blender silently renames duplicates; do it ourselves so the report is
    accurate and ``clear`` can find the key again."""
    existing = set(key_names(ob))
    if base not in existing:
        return base
    i = 2
    while "%s.%03d" % (base, i) in existing:
        i += 1
    return "%s.%03d" % (base, i)


def ensure_shape_keys(ob):
    if ob.data.shape_keys is None:
        ob.shape_key_add(name="Basis", from_mix=False)
    return ob.data.shape_keys


def add_key(ob, name):
    """Create an empty shape key and return it."""
    ensure_shape_keys(ob)
    try:
        return ob.shape_key_add(name=name, from_mix=False)
    except TypeError:                     # pragma: no cover - signature drift
        return ob.data.shape_keys.key_blocks.new(name=name)


def read_meta(ob):
    raw = ob.get(META_KEY)
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if data.get("version") != META_VERSION:
        return data                        # let the caller decide
    return data


def write_meta(ob, data):
    data["version"] = META_VERSION
    ob[META_KEY] = json.dumps(data, ensure_ascii=False)


def options_from(settings):
    panels = []
    for name in core.PANELS:
        if getattr(settings, "panel_" + name, True):
            panels.append(name)
    return {
        "panels": set(panels) if len(panels) < len(core.PANELS) else None,
        "skip_existing": settings.skip_existing,
        "arkit": settings.arkit,
        "swap_wink": settings.swap_wink,
        "include_empty": settings.include_empty,
        "naming": naming_of(settings),
    }


def naming_of(settings):
    """The naming scheme selected in the panel, always a valid scheme."""
    return core.normalize_scheme(getattr(settings, "naming", "MMD"))


def generate_params(settings):
    return {
        "eye_scale": settings.eye_scale,
        "mouth_scale": settings.mouth_scale,
        "strength": settings.strength,
    }


def manual_overrides(settings):
    """Landmark overrides from the N panel, or ``None`` per unused slot."""
    if not settings.use_manual_landmarks:
        return {}
    return {
        "eye_L": tuple(settings.lm_eye_L),
        "eye_R": tuple(settings.lm_eye_R),
        "mouth": tuple(settings.lm_mouth),
    }


# ------------------------------------------------------------- analysis

def analyse_object(ob, atoms, expressions, settings, context):
    """Work out what we *would* do to this object, without touching it."""
    names = key_names(ob)
    info = {
        "object": ob.name,
        "vertices": len(ob.data.vertices),
        "has_shape_keys": bool(names),
        "shape_key_count": len(names),
        "atoms_matched": 0,
        "atoms_missing": 0,
        "unmatched_keys": [],
        "ambiguous": [],
        "mode": "none",
        "landmarks": None,
        "regions": None,
        "problem": None,
    }

    if not names:
        info["problem"] = "没有形态键"
        if settings.mode in ("AUTO", "PROCEDURAL"):
            info["mode"] = "procedural"
        return info

    match = matcher.match_atoms(names, atoms)
    info["atoms_matched"] = len(match.matched)
    info["atoms_missing"] = len(match.missing_atoms)
    info["unmatched_keys"] = match.unmatched_keys
    info["ambiguous"] = [
        {"key": k, "atom": a, "score": s, "runner_up": r}
        for k, a, s, r in match.ambiguous
    ]

    threshold = settings.atom_threshold
    if settings.mode == "PROCEDURAL":
        info["mode"] = "procedural"
    elif settings.mode == "ATOMS":
        info["mode"] = "atoms"
    else:
        info["mode"] = "atoms" if len(match.matched) >= threshold else "procedural"

    if info["mode"] == "procedural":
        arm = armature_for(ob, context, settings.armature)
        bones = collect_bones(arm) if arm else {}
        lm = lmmod.landmarks_from_bones(bones, manual_overrides(settings))
        lmmod.derive_missing(lm)
        info["landmarks"] = {
            "confidence": lm.confidence,
            "complete": lm.complete,
            "sources": lm.sources,
            "eye_span": lm.eye_span(),
        }
        if lm.complete:
            inv = ob.matrix_world.inverted()
            lm_local = _landmarks_local(lm, inv)
            coords = read_vertices_flat(ob)
            info["regions"] = genmod.region_summary(coords, lm_local,
                                                    generate_params(settings))
        else:
            info["problem"] = "未找到面部地标（需要眼睛/嘴巴骨骼，或手动填写）"

    return info


def _landmarks_local(lm, matrix_inv):
    """Copy a Landmarks into object-local space."""
    out = lmmod.Landmarks()
    for slot in ("eye_L", "eye_R", "mouth", "brow_L", "brow_R", "head", "neck"):
        p = getattr(lm, slot)
        if p is None:
            continue
        v = matrix_inv @ Vector(p)
        setattr(out, slot, (v.x, v.y, v.z))
    out.confidence = lm.confidence
    out.sources = dict(lm.sources)
    return out


# ------------------------------------------------------------- pipelines

def bake_atoms(ob, match, spec, settings, report):
    """Pipeline A - combine the model's own morphs."""
    opts = options_from(settings)
    plan = core.plan_object(ob.name, key_names(ob), match, spec, opts)

    kb = ob.data.shape_keys.key_blocks
    by_name = {k.name: k for k in kb}
    basis_flat = read_key_flat(kb[0])

    # Deltas are computed once per *shape key* and shared by every recipe that
    # uses that atom, which matters: the 46 recipes draw on 64 atoms but make
    # ~110 uses.  The map is keyed by shape-key name because that is what
    # ``core.build_key_delta_map`` looks up - keying it by atom id here was a
    # silent mismatch that left every recipe with no data.
    key_deltas = {}
    for atom_id, key_name in match.matched.items():
        src = by_name.get(key_name)
        if src is None or key_name in key_deltas:
            continue
        key_deltas[key_name] = core.sparse_deltas(basis_flat, read_key_flat(src))
    atom_deltas = core.build_key_delta_map(match, key_deltas)

    created = []
    for item in plan.items:
        parts = core.parts_to_deltas(item, atom_deltas)
        if not parts:
            # An empty recipe is 素の表情 / neutral, and it is meant to be
            # baked: a zero-displacement key is exactly the morph MMD calls
            # ニュートラル.  Skipping it here (as an earlier version did) loses
            # the one expression that lets a VMD action reset the face.
            if not item.get("empty"):
                continue
            result = list(basis_flat)
        else:
            result = core.blend_sparse(basis_flat, parts)
        name = unique_name(ob, item["name"])
        key = add_key(ob, name)
        write_key_flat(key, result)
        key.value = 0.0
        try:
            key.slider_min, key.slider_max = 0.0, 1.0
        except AttributeError:            # pragma: no cover
            pass
        created.append(name)
        by_name[name] = key

        for aname in item["arkit"]:
            if aname in by_name:
                continue
            akey = add_key(ob, aname)
            write_key_flat(akey, result)
            akey.value = 0.0
            created.append(aname)
            by_name[aname] = akey

    report.update({
        "mode": "atoms",
        "naming": plan.namer.scheme,
        "created": created,
        "skipped_existing": plan.skipped_existing,
        "skipped_no_atoms": plan.skipped_no_atoms,
        "name_fallbacks": plan.name_fallbacks,
        "partial": [
            {"id": it["id"], "name": it["name"], "missing": it["missing"]}
            for it in plan.partial
        ],
        "unsupported": plan.skipped_unsupported,
        "arkit_dupes": sorted(set(plan.arkit_dupes)),
    })
    return len(created)


def _procedural_names(spec, settings, ob):
    """Map the generator's MMD-keyed output onto the chosen naming scheme.

    ``generate.generate`` returns its deltas keyed by the MMD name (that is
    what the geometry rules were written against).  The spec is the single
    source of truth for the other three conventions, so each generated name is
    routed through its expression record - that way a procedural build and an
    atom build of the same model produce identically named keys.

    Order matters and must be the **spec** order, not ``EXPRESSION_NAMES``
    order.  VRM has one preset per concept and several recipes want the same
    one (にっこり and 笑い both want ``happy``); whoever asks first keeps it.
    Iterating the generator's own list handed ``happy`` to にっこり, while
    pipeline A - which walks the spec - handed it to 笑い, so the *same*
    expression came out with a different name depending on which pipeline ran.
    Walking the spec fixes the order in both places.
    """
    wanted = set(genmod.EXPRESSION_NAMES)
    namer = core.Namer(
        naming_of(settings),
        set(key_names(ob)) if settings.skip_existing else set())

    out = []
    seen = set()
    for e in core.expressions_of(spec):
        mmd = e.get("mmd")
        if mmd not in wanted or mmd in seen:
            continue
        seen.add(mmd)
        out.append((mmd, namer.take(e)))

    # A generator name with no spec entry - keep it verbatim rather than
    # dropping a shape key the user asked for.
    for mmd in genmod.EXPRESSION_NAMES:
        if mmd not in seen:
            out.append((mmd, mmd))

    return out, namer


def bake_procedural(ob, spec, settings, context, report):
    """Pipeline B - invent expressions from geometry."""
    arm = armature_for(ob, context, settings.armature)
    bones = collect_bones(arm) if arm else {}
    lm = lmmod.landmarks_from_bones(bones, manual_overrides(settings))
    lmmod.derive_missing(lm)

    if not lm.complete:
        report["error"] = ("找不到眼睛/嘴巴地标。请指定骨架，"
                           "或在面板里手动填写地标坐标。")
        return 0

    inv = ob.matrix_world.inverted()
    lm_local = _landmarks_local(lm, inv)
    coords = read_vertices_flat(ob)

    deltas, info = genmod.generate(coords, lm_local, generate_params(settings))
    if not deltas:
        report["error"] = info.get("error", "生成失败")
        return 0

    basis = None
    if ob.data.shape_keys is not None:
        basis = ob.data.shape_keys.key_blocks[0]
    basis_flat = read_key_flat(basis) if basis else list(coords)

    named, namer = _procedural_names(spec, settings, ob)

    created = []
    for src_name, target in named:
        moves = deltas.get(src_name)
        if moves is None:
            continue
        if target is None:
            report.setdefault("skipped_existing", []).append(src_name)
            continue
        result = core.blend_sparse(basis_flat, [(moves, 1.0)])
        final = unique_name(ob, target)
        key = add_key(ob, final)
        write_key_flat(key, result)
        key.value = 0.0
        try:
            key.slider_min, key.slider_max = 0.0, 1.0
        except AttributeError:            # pragma: no cover
            pass
        created.append(final)

    report.update({
        "mode": "procedural",
        "naming": namer.scheme,
        "created": created,
        "name_fallbacks": [{"id": k, "wanted": w, "given": g}
                           for k, (w, g) in sorted(namer.fell_back.items())],
        "landmarks": {
            "confidence": lm.confidence,
            "sources": lm.sources,
            "eye_span": lm.eye_span(),
        },
        "regions": info.get("regions"),
        "params": info.get("params"),
        "armature": arm.name if arm else None,
    })
    return len(created)


# -------------------------------------------------------------- operators

class _Base:
    bl_options = {"REGISTER", "UNDO"}

    @classmethod
    def poll(cls, context):
        return any(o.type == "MESH" for o in context.scene.objects)


class EXPRKIT_OT_scan(_Base, bpy.types.Operator):
    bl_idname = "exprkit.scan"
    bl_label = "扫描模型"
    bl_description = "只分析不修改：看看每个网格能识别出多少原子、走哪条流水线"

    def execute(self, context):
        s = context.scene.exprkit
        try:
            spec, atomspec = load_spec(s)
        except Exception as exc:
            self.report({"ERROR"}, "读取规范失败: %s" % exc)
            return {"CANCELLED"}

        atoms = core.atoms_of(atomspec)
        exprs = core.expressions_of(spec)
        obs = target_meshes(context, s.use_selection)

        results = [analyse_object(o, atoms, exprs, s, context) for o in obs]
        for ob, rec in zip(obs, results):
            rec["name_preview"] = _name_preview(ob, exprs, s)
        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": "scan",
            "spec": core.spec_fingerprint(spec, atomspec),
            "naming": naming_of(s),
            "objects": results,
        }
        context.scene[REPORT_PROP] = json.dumps(report, ensure_ascii=False)

        total_atoms = sum(r["atoms_matched"] for r in results)
        self.report({"INFO"}, "扫描 %d 个网格，共识别 %d 个原子" %
                    (len(results), total_atoms))
        return {"FINISHED"}


class EXPRKIT_OT_build(_Base, bpy.types.Operator):
    bl_idname = "exprkit.build"
    bl_label = "一键生成表情"
    bl_description = "为选中的（或全部）网格生成标准表情形态键"

    def execute(self, context):
        s = context.scene.exprkit
        try:
            spec, atomspec = load_spec(s)
        except Exception as exc:
            self.report({"ERROR"}, "读取规范失败: %s" % exc)
            return {"CANCELLED"}

        atoms = core.atoms_of(atomspec)
        exprs = core.expressions_of(spec)
        obs = target_meshes(context, s.use_selection)
        if not obs:
            self.report({"WARNING"}, "没有可处理的网格")
            return {"CANCELLED"}

        if s.rename_atoms:
            _rename_atoms(obs, atoms)

        out = []
        total = 0
        for ob in obs:
            info = analyse_object(ob, atoms, exprs, s, context)
            rec = {
                "object": ob.name,
                "mode": info["mode"],
                "atoms_matched": info["atoms_matched"],
                "created": [],
                "skipped_existing": [],
                "error": None,
            }

            if info["mode"] == "atoms":
                match = matcher.match_atoms(key_names(ob), atoms)
                n = bake_atoms(ob, match, spec, s, rec)
            elif info["mode"] == "procedural":
                n = bake_procedural(ob, spec, s, context, rec)
            else:
                rec["error"] = info.get("problem") or "无可用的表情来源"
                n = 0

            total += n
            rec["created_count"] = n

            meta = read_meta(ob) or {"created": [], "renamed": {}}
            meta["created"] = sorted(set(meta.get("created", [])) |
                                     set(rec.get("created", [])))
            meta["mode"] = info["mode"]
            write_meta(ob, meta)
            out.append(rec)

        report = {
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": "build",
            "spec": core.spec_fingerprint(spec, atomspec),
            "naming": naming_of(s),
            "objects": out,
        }
        context.scene[REPORT_PROP] = json.dumps(report, ensure_ascii=False)
        _select_created(context, obs, out)

        self.report({"INFO"}, "生成了 %d 个形态键" % total)
        return {"FINISHED"}


def _name_preview(ob, exprs, settings):
    """What the 46 expressions would be called on this mesh, before baking.

    Cheap (no vertex data touched) and worth it: a user who picks the wrong
    naming scheme otherwise finds out only after a slow bake, and a user who
    is not sure what ``VRM`` means can just look.
    """
    namer = core.Namer(naming_of(settings),
                       set(key_names(ob)) if settings.skip_existing else set())
    names = []
    for e in exprs:
        if e.get("unsupported"):
            continue
        got = namer.take(e)
        if got is None:
            continue
        names.append({"id": e.get("id"), "name": got})
    return {
        "naming": namer.scheme,
        "count": len(names),
        "names": names,
        "fallbacks": [{"id": k, "wanted": w, "given": g}
                      for k, (w, g) in sorted(namer.fell_back.items())],
    }


def _select_created(context, obs, results):
    """Leave the first created key active so the user sees it immediately.

    The writable attribute is ``Object.active_shape_key_index``.  Two traps
    live here, both verified against Blender 3.6.23:

    * ``ob.data.shape_keys`` is a ``bpy.types.Key``, and ``Key`` has **no**
      ``active_key`` attribute at all (only ``key_blocks`` and
      ``reference_key``).
    * ``Object.active_shape_key`` exists but is **read-only** - assigning to
      it raises ``AttributeError: bpy_struct: attribute "active_shape_key"
      from "Object" is read-only``.

    So the index is the only way in.  Setting the wrong one aborts the whole
    operator *after* the shape keys were created, which is the worst possible
    moment: the work is done but the user sees an error.
    """
    for ob, rec in zip(obs, results):
        if not rec.get("created"):
            continue
        keys = getattr(ob.data, "shape_keys", None)
        if keys is None:
            continue
        idx = keys.key_blocks.find(rec["created"][0])
        if idx >= 0:
            try:
                ob.active_shape_key_index = idx
            except (AttributeError, TypeError):   # pragma: no cover
                pass
        break


class EXPRKIT_OT_rename_atoms(_Base, bpy.types.Operator):
    bl_idname = "exprkit.rename_atoms"
    bl_label = "原子改名为 atom id"
    bl_description = ("把模型原有的形态键改成本套件的 atom id "
                      "（例如 Eyebrow_Angry -> brow_angry），便于跨模型统一")

    def execute(self, context):
        s = context.scene.exprkit
        spec, atomspec = load_spec(s)
        atoms = core.atoms_of(atomspec)
        obs = target_meshes(context, s.use_selection)
        total = _rename_atoms(obs, atoms)
        self.report({"INFO"}, "改名 %d 个形态键" % total)
        return {"FINISHED"}


def _rename_atoms(obs, atoms):
    """Rename native shape keys to their atom id, recording the old name.

    The old name is kept in the object's metadata so :class:`EXPRKIT_OT_clear`
    can put it back - renaming is destructive otherwise, and a user who tries
    the addon and changes their mind should not be left with a broken model.
    """
    total = 0
    for ob in obs:
        names = key_names(ob)
        if not names:
            continue
        match = matcher.match_atoms(names, atoms)
        kb = ob.data.shape_keys.key_blocks
        by_name = {k.name: k for k in kb}
        meta = read_meta(ob) or {"created": [], "renamed": {}}
        renamed = dict(meta.get("renamed", {}))

        for atom_id, key_name in match.matched.items():
            if key_name == atom_id:
                continue
            if atom_id in by_name and by_name[atom_id] is not by_name.get(key_name):
                continue                    # never clobber a different key
            by_name[key_name].name = atom_id
            renamed[key_name] = atom_id
            by_name[atom_id] = by_name.pop(key_name)
            total += 1

        meta["renamed"] = renamed
        write_meta(ob, meta)
    return total


class EXPRKIT_OT_clear(_Base, bpy.types.Operator):
    bl_idname = "exprkit.clear"
    bl_label = "清除本插件生成的表情"
    bl_description = "删除由本插件创建的全部形态键，并还原被改名的原子"

    def execute(self, context):
        obs = target_meshes(context, context.scene.exprkit.use_selection)
        removed = 0
        restored = 0
        for ob in obs:
            meta = read_meta(ob)
            if not meta or ob.data.shape_keys is None:
                continue
            kb = ob.data.shape_keys.key_blocks

            for name in meta.get("created", []):
                k = kb.get(name)
                if k is not None and k != kb[0]:
                    ob.shape_key_remove(k)
                    removed += 1

            # put renamed atoms back
            for old, new in (meta.get("renamed") or {}).items():
                k = kb.get(new)
                if k is not None and old not in kb:
                    k.name = old
                    restored += 1

            try:
                del ob[META_KEY]
            except (KeyError, TypeError):
                pass

        self.report({"INFO"}, "删除 %d 个，还原 %d 个" % (removed, restored))
        return {"FINISHED"}


class EXPRKIT_OT_export_report(_Base, bpy.types.Operator):
    bl_idname = "exprkit.export_report"
    bl_label = "导出报告"
    bl_description = "把上次扫描/生成的报告写成 JSON"

    filepath: bpy.props.StringProperty(subtype="FILE_PATH")
    filter_glob: bpy.props.StringProperty(default="*.json", options={"HIDDEN"})

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = os.path.join(
                os.path.expanduser("~"), "expressiongen_report.json")
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        raw = context.scene.get(REPORT_PROP)
        if not raw:
            self.report({"WARNING"}, "还没有报告，先扫描或生成一次")
            return {"CANCELLED"}
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(raw)
        self.report({"INFO"}, "报告已写入 %s" % self.filepath)
        return {"FINISHED"}


CLASSES = (
    EXPRKIT_OT_scan,
    EXPRKIT_OT_build,
    EXPRKIT_OT_rename_atoms,
    EXPRKIT_OT_clear,
    EXPRKIT_OT_export_report,
)


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)


def unregister():
    for c in reversed(CLASSES):
        bpy.utils.unregister_class(c)
