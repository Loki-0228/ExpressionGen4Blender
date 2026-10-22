"""Pure-Python core: recipe blending and bake planning.

Deliberately free of ``bpy`` so the maths can be unit-tested outside Blender.

The one idea worth understanding: **Blender has no group shape key.**  PMX has
morph type 0 (a morph made of other morphs); Blender does not.  So a standard
expression has to be *baked* - evaluated once into a real shape key.

A relative shape key stores **absolute** vertex coordinates, not a delta.  So
for every vertex ``i``::

    delta_atom(i) = atom.co[i] - basis.co[i]
    new.co[i]     = basis.co[i] + sum(delta_atom(i) * weight)

which is exactly what :func:`blend_flat` computes.
"""

from __future__ import annotations

import json
import os

#: Shape keys the addon creates are tagged with this prefix on the object so
#: "clear" can find them again even after a file reload.
META_KEY = "expression_kit"
META_VERSION = 2

PANELS = ("eye", "mouth", "eyebrow", "other")

PANEL_LABELS = {
    "eye": "眼",
    "mouth": "口",
    "eyebrow": "眉",
    "other": "其他",
}


# --------------------------------------------------------------------- spec

def load_spec(data_dir):
    """Read the bundled ``expressions.json`` + ``atoms.json``."""
    with open(os.path.join(data_dir, "expressions.json"), encoding="utf-8") as f:
        spec = json.load(f)
    with open(os.path.join(data_dir, "atoms.json"), encoding="utf-8") as f:
        atoms = json.load(f)
    return spec, atoms


def expressions_of(spec):
    return spec.get("expressions", spec) if isinstance(spec, dict) else spec


def atoms_of(atomspec):
    if isinstance(atomspec, dict):
        return atomspec.get("atoms", [])
    return atomspec


# ------------------------------------------------------------------- naming

#: The naming conventions the addon can produce.  Each one exists because a
#: different downstream tool reads the shape-key name and nothing else:
#:
#: ``MMD``     日本語名 (まばたき / ウィンク / あ).  What MMD itself and every
#:             VMD-driven pipeline expect; PMX morph names must match or the
#:             motion silently does nothing.
#: ``VRM``     camelCase 预设名 (blink / blinkLeft / aa / happy).  UniVRM and
#:             VRM4U match these against the VRM 1.0 preset list; anything not
#:             on that list becomes a custom expression under its own name.
#: ``FBX``     英文首字母大写 (Blink / Wink / A).  ASCII, so it survives an
#:             FBX round-trip and the fbx→engine pipelines that choke on
#:             non-ASCII morph names.
#: ``BLENDER`` 小写下划线 id (blink / wink / a).  Neutral, script-friendly,
#:             no spaces or punctuation - safe in a driver expression or a
#:             ``key_blocks["..."]`` lookup.
NAMING_SCHEMES = ("MMD", "VRM", "FBX", "BLENDER")

NAMING_LABELS = {
    "MMD": "MMD（日本語）",
    "VRM": "VRM（camelCase）",
    "FBX": "FBX（English）",
    "BLENDER": "Blender（id）",
}

#: VRM 1.0's 18 preset expression names.  The spec allows *only* these as
#: presets; everything else is a custom expression keyed by its own name.
VRM_PRESETS = frozenset((
    "happy", "angry", "sad", "relaxed", "surprised", "neutral",
    "aa", "ih", "ou", "ee", "oh",
    "blink", "blinkLeft", "blinkRight",
    "lookUp", "lookDown", "lookLeft", "lookRight",
))


def normalize_scheme(scheme):
    s = str(scheme or "MMD").strip().upper()
    return s if s in NAMING_SCHEMES else "MMD"


def preferred_name(expr, scheme):
    """The name one expression *wants* under ``scheme``, before collisions."""
    scheme = normalize_scheme(scheme)
    eid = expr.get("id") or ""
    if scheme == "MMD":
        return expr.get("mmd") or eid
    if scheme == "FBX":
        return expr.get("mmd_en") or eid
    if scheme == "BLENDER":
        return eid
    # VRM.  The ``custom:`` prefix in the spec is a note *to us* that the name
    # has no VRM 1.0 preset - it is metadata, not part of the name.  Stripping
    # it turns ``custom:halfLid`` into the custom expression ``halfLid``,
    # which is exactly how VRM 1.0 represents an expression with no preset.
    v = expr.get("vrm") or ""
    if v.startswith("custom:"):
        v = v[len("custom:"):]
    return v or expr.get("mmd_en") or eid


class Namer:
    """Assigns shape-key names for one mesh under one naming scheme.

    Why this is a stateful object and not a one-line ``expr["mmd"]`` lookup:
    VRM 1.0 defines only 18 preset names and several of the 46 standard
    expressions want the same one - three recipes map to ``happy`` and four to
    ``relaxed``.  A mesh cannot hold two keys with one name, so the assignment
    has to be order-dependent: the first recipe to ask for a preset keeps it,
    the rest fall back to their own id, which is the "custom expression"
    escape hatch VRM 1.0 provides.  The fallbacks are recorded so the report
    can say exactly which names were demoted instead of quietly renaming
    things.
    """

    def __init__(self, scheme="MMD", existing=()):
        self.scheme = normalize_scheme(scheme)
        #: Names already on the mesh that we must not step on.
        self.mesh_names = set(existing)
        self.assigned_names = set()
        #: ``{expression id: (wanted, given)}`` for every demoted name.
        self.fell_back = {}
        self.assigned = {}

    def take(self, expr):
        """Return the final name for ``expr``, or ``None`` if it must be skipped.

        ``None`` means the preferred name is already on the mesh (and the user
        asked not to overwrite); the caller records it under
        ``skipped_existing``.
        """
        eid = expr.get("id") or ""
        want = preferred_name(expr, self.scheme)

        if want in self.mesh_names:
            return None

        if want in self.assigned_names:
            # Only reachable for VRM with the bundled spec (shared presets),
            # or for a hand-edited spec that repeats a name.  Degrade to the
            # expression id rather than dropping the expression - losing a
            # morph the user asked for is worse than an unexpected name.
            alt = eid or (want + "_2")
            while alt in self.mesh_names or alt in self.assigned_names:
                alt = "_" + alt
            self.fell_back[eid] = (want, alt)
            want = alt

        self.assigned_names.add(want)
        self.assigned[eid] = want
        return want


# ------------------------------------------------------------------- maths

def deltas_flat(basis_flat, coords_flat):
    """``coords - basis`` element-wise.  Both are flat ``[x,y,z,x,y,z,...]``."""
    return [c - b for c, b in zip(coords_flat, basis_flat)]


def blend_flat(basis_flat, parts):
    """Evaluate a recipe over flat vertex arrays.

    Parameters
    ----------
    basis_flat : sequence of float
        The Basis shape key, flat ``[x,y,z, x,y,z, ...]``.
    parts : sequence of (deltas_flat, weight)
        Each atom's precomputed delta array plus its weight in the recipe.

    Returns
    -------
    list of float
        Flat absolute coordinates for the new shape key.
    """
    n = len(basis_flat)
    out = [0.0] * n
    for i in range(0, n, 3):
        bx, by, bz = basis_flat[i], basis_flat[i + 1], basis_flat[i + 2]
        dx = dy = dz = 0.0
        for deltas, w in parts:
            dx += deltas[i] * w
            dy += deltas[i + 1] * w
            dz += deltas[i + 2] * w
        out[i] = bx + dx
        out[i + 1] = by + dy
        out[i + 2] = bz + dz
    return out


def max_delta(basis_flat, result_flat):
    """Largest absolute displacement, for sanity-reporting in the UI."""
    if not basis_flat:
        return 0.0
    return max(abs(c - b) for c, b in zip(result_flat, basis_flat))


def sparse_deltas(basis_flat, coords_flat, eps=1e-9):
    """Only the vertices an atom actually moves, as ``(vert_index, dx, dy, dz)``.

    A face morph typically touches a few hundred vertices out of tens of
    thousands, so keeping the sparse form turns the per-expression cost from
    O(all_vertices) into O(moved_vertices).  The reference model's largest atom
    moves ~2000 vertices on a 35k-vertex mesh; the speed-up is roughly 20x.
    """
    out = []
    for i in range(0, len(basis_flat), 3):
        dx = coords_flat[i] - basis_flat[i]
        dy = coords_flat[i + 1] - basis_flat[i + 1]
        dz = coords_flat[i + 2] - basis_flat[i + 2]
        if dx > eps or dx < -eps or dy > eps or dy < -eps or dz > eps or dz < -eps:
            out.append((i // 3, dx, dy, dz))
    return out


def blend_sparse(basis_flat, parts):
    """Same result as :func:`blend_flat`, but takes sparse deltas.

    ``parts`` is ``[(sparse_deltas, weight), ...]``.  Verified equivalent to
    the dense path in ``tests/test_core.py``.
    """
    out = list(basis_flat)
    for moves, w in parts:
        if w == 0.0:
            continue
        for vi, dx, dy, dz in moves:
            i = vi * 3
            out[i] += dx * w
            out[i + 1] += dy * w
            out[i + 2] += dz * w
    return out


# ---------------------------------------------------------------- planning

class BakePlan:
    """What to create on one object."""

    __slots__ = ("object_name", "items", "skipped_existing", "skipped_unsupported",
                 "skipped_empty", "skipped_no_atoms", "arkit_dupes", "note",
                 "namer")

    def __init__(self, object_name):
        self.object_name = object_name
        #: list of dicts: id / name / panel / parts / missing / arkit / empty
        self.items: list[dict] = []
        self.skipped_existing: list[str] = []
        self.skipped_unsupported: list[str] = []
        #: Empty *recipes* (neutral) that were dropped by ``include_empty=False``.
        self.skipped_empty: list[str] = []
        #: Expressions with a real recipe but no matching atom on this mesh.
        self.skipped_no_atoms: list[str] = []
        self.arkit_dupes: list[str] = []
        self.note = None
        #: Set by :func:`plan_object`; the Namer that produced the names.
        self.namer = None

    @property
    def name_fallbacks(self):
        """``[{id, wanted, given}]`` - names demoted to avoid a collision."""
        if self.namer is None:
            return []
        return [{"id": k, "wanted": w, "given": g}
                for k, (w, g) in sorted(self.namer.fell_back.items())]

    @property
    def partial(self):
        return [it for it in self.items if it["missing"]]

    def __repr__(self):
        return "BakePlan(%s, items=%d, partial=%d)" % (
            self.object_name, len(self.items), len(self.partial))


def _swap_wink(parts):
    """Swap the L/R atom of the wink recipes.

    MMD convention is ``ウィンク`` = the model's *right* eye.  Whether a given
    model's ``_L``/``_R`` suffixes mean model-side or viewer-side cannot be
    determined from the file, so the user gets a toggle.
    """
    swapped = []
    for atom_id, w in parts:
        if atom_id.endswith("_L"):
            atom_id = atom_id[:-2] + "_R"
        elif atom_id.endswith("_R"):
            atom_id = atom_id[:-2] + "_L"
        swapped.append((atom_id, w))
    return swapped


def plan_object(object_name, key_names, match, spec, opts):
    """Decide which standard expressions to bake onto one object.

    Parameters
    ----------
    key_names : iterable of str
        Existing shape key names on the object.
    match : matcher.MatchResult
        Output of :func:`matcher.match_atoms` for this object.
    spec : dict
        Parsed ``expressions.json``.
    opts : dict
        ``panels``  - iterable of panel names to include, or None for all
        ``skip_existing`` - do not touch a name that already exists
        ``arkit``   - also bake ARKit-named keys
        ``swap_wink`` - flip L/R in wink and wink2
        ``include_empty`` - bake a zero-displacement key for recipes with no
            parts (``素の表情`` / neutral).  MMD models conventionally ship
            ``ニュートラル`` as an empty morph so VMD actions can reset, and
            :func:`blend_flat` with no parts returns the Basis verbatim - which
            is exactly that morph.  Default True.
        ``naming``  - one of :data:`NAMING_SCHEMES`.  Picks which of the
            spec's four name fields becomes the shape-key name.  Default MMD.
    """
    plan = BakePlan(object_name)
    existing = set(key_names)
    panels = opts.get("panels")
    skip_existing = opts.get("skip_existing", True)
    want_arkit = opts.get("arkit", False)
    swap_wink = opts.get("swap_wink", False)
    include_empty = opts.get("include_empty", True)
    namer = opts.get("namer")
    if namer is None:
        namer = Namer(opts.get("naming", "MMD"),
                      existing if skip_existing else ())
    plan.namer = namer

    arkit_used: set[str] = set(existing) if skip_existing else set()

    for e in expressions_of(spec):
        eid = e.get("id")
        if e.get("unsupported"):
            plan.skipped_unsupported.append(eid)
            continue
        if panels and e.get("panel") not in panels:
            continue

        parts = []
        missing = []
        for p in e.get("parts", []):
            atom_id = p["atom"]
            key = match.matched.get(atom_id)
            if key is None:
                missing.append(atom_id)
            else:
                parts.append((atom_id, float(p.get("w", 1.0))))

        # Two different kinds of "nothing to bake", and they must not be
        # confused:
        #   * the recipe itself is empty (素の表情 / neutral) -> bake a
        #     zero-displacement key, that IS the morph MMD calls ニュートラル.
        #   * the recipe has parts but none of them live on *this* mesh
        #     (怒り spans the brow and mouth meshes; the eyeball mesh has
        #     neither) -> skip entirely, otherwise every mesh in the scene
        #     collects a useless zero key for every expression it can't do.
        spec_parts = e.get("parts") or []
        if not parts and spec_parts:
            plan.skipped_no_atoms.append(eid)
            continue
        if not parts and not include_empty:
            plan.skipped_empty.append(eid)
            continue

        if swap_wink and eid in ("wink", "wink2"):
            parts = _swap_wink(parts)

        name = namer.take(e)
        if name is None:
            # The mesh already owns this name and skip_existing is on.
            plan.skipped_existing.append(preferred_name(e, namer.scheme))
            continue

        arkit_names = []
        if want_arkit:
            for an in e.get("arkit", []):
                if an in arkit_used:
                    plan.arkit_dupes.append(an)
                else:
                    arkit_used.add(an)
                    arkit_names.append(an)

        plan.items.append({
            "id": eid,
            "name": name,
            "name_en": e.get("mmd_en") or eid,
            "name_mmd": e.get("mmd") or eid,
            "panel": e.get("panel"),
            "vrm": e.get("vrm"),
            "parts": parts,
            "missing": missing,
            "arkit": arkit_names,
            "empty": not parts,
        })

    return plan


def build_key_delta_map(match, key_deltas):
    """``{atom_id: deltas_flat}`` from a match result and per-key deltas.

    ``key_deltas`` maps a *shape key name* to its delta array.  Doing the
    lookup once per object means a recipe that uses the same atom twice, and
    every recipe that reuses a popular atom, all share one array.
    """
    out = {}
    for atom_id, key_name in match.matched.items():
        d = key_deltas.get(key_name)
        if d is not None:
            out[atom_id] = d
    return out


def parts_to_deltas(plan_item, atom_deltas):
    """``[(deltas_flat, weight), ...]`` ready for :func:`blend_flat`.

    Atom ids with no delta array are dropped - :func:`plan_object` already
    recorded them under ``missing`` so the UI can report the shortfall.
    """
    out = []
    for atom_id, w in plan_item["parts"]:
        d = atom_deltas.get(atom_id)
        if d is not None:
            out.append((d, w))
    return out


# ------------------------------------------------------------------ report

def summarize(plans, match_results=None):
    """Aggregate per-object plans into a printable summary."""
    total_items = sum(len(p.items) for p in plans)
    total_partial = sum(len(p.partial) for p in plans)
    total_empty = sum(1 for p in plans for it in p.items if it.get("empty"))
    return {
        "objects": len(plans),
        "shape_keys_to_create": total_items,
        "partial": total_partial,
        "neutral_keys": total_empty,
        "skipped_existing": sum(len(p.skipped_existing) for p in plans),
        "skipped_unsupported": sorted({i for p in plans for i in p.skipped_unsupported}),
        "skipped_empty": sorted({i for p in plans for i in p.skipped_empty}),
        "skipped_no_atoms": sum(len(p.skipped_no_atoms) for p in plans),
    }


def spec_fingerprint(spec, atomspec):
    """Short stable id of the spec, stored on objects for provenance."""
    names = [e.get("id") for e in expressions_of(spec)]
    aids = [a.get("id") for a in atoms_of(atomspec)]
    return {
        "spec_name": spec.get("name") if isinstance(spec, dict) else None,
        "spec_version": spec.get("version") if isinstance(spec, dict) else None,
        "expressions": len(names),
        "atoms": len(aids),
    }
