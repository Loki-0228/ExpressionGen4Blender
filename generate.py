"""Procedural expression generation for models that have *no* morphs.

When a model ships morphs, ``matcher`` + ``core`` combine them and the result
is artist-authored quality.  When a model has **nothing**, there is no atom to
combine, so expressions have to be invented from geometry.  That is what this
module does, and it is honest to say up front: **the results are heuristic.**
They read correctly on a typical anime/MMD head and give a VMD action something
to drive, but they are not a substitute for a rigger.

How it works
------------
1. Build a **face frame** from the eye and mouth landmarks - an orthonormal
   basis ``(right, up, forward)`` anchored at the eye midpoint.  Every rule is
   written in that frame, so it does not matter whether the model faces +Y,
   -Y or is Z-up vs Y-up.
2. Carve the head vertices into regions: a disc around each eye, a disc around
   the mouth, a band above each eye for the brow.
3. Apply per-expression rules that push those vertices around - "the upper
   lid collapses to the mid line", "the mouth corners rise and spread".

All units are expressed as multiples of ``S``, the half eye-span, which is the
one measurement that scales consistently across head sizes.
"""

from __future__ import annotations

import math

# Installed as a Blender addon these modules live in a package, so the
# relative form is correct; run directly from the tests directory only the
# flat form resolves.  Supporting both keeps the maths testable without bpy.
try:
    from .landmarks import (_add, _cross, _dot, _normalize, _orthogonalize,
                            _scale, _sub)
except ImportError:                       # pragma: no cover - script mode
    from landmarks import (_add, _cross, _dot, _normalize, _orthogonalize,
                           _scale, _sub)

#: Default region sizes, in multiples of the half eye-span ``S``.
#:
#: These are deliberately on the small side.  The eye and mouth discs are
#: clamped against each other at runtime (see :func:`detect_regions`) because
#: a generous eye radius would otherwise reach down over the lips and make the
#: blink drag the mouth along with it.
DEFAULT_PARAMS = {
    "eye_scale": 0.58,       # eye disc radius / S
    "mouth_scale": 0.66,     # mouth disc radius / S
    "brow_scale": 0.80,      # brow half-width / S
    "brow_thickness": 0.32,  # brow band half-height / S
    "brow_gap": 1.02,        # brow band bottom, as a fraction of eye radius
    "region_split": 0.46,    # max share of the eye-mouth gap a disc may take
    "strength": 1.0,         # global multiplier on every displacement
}


def _local_centroid(coords, center, radius):
    """Mean position of the vertices within ``radius`` of ``center``.

    Used to find "inside the head" so the face direction can be derived
    without assuming an axis convention.  Returns ``None`` when nothing is in
    range, which lets the caller fall through to the next heuristic.
    """
    n = len(coords) // 3
    r2 = radius * radius
    cx, cy, cz = center
    sx = sy = sz = 0.0
    count = 0
    for i in range(n):
        x, y, z = coords[i * 3], coords[i * 3 + 1], coords[i * 3 + 2]
        dx, dy, dz = x - cx, y - cy, z - cz
        if dx * dx + dy * dy + dz * dz <= r2:
            sx += x
            sy += y
            sz += z
            count += 1
    if not count:
        return None
    return (sx / count, sy / count, sz / count)


class FaceFrame:
    """Orthonormal basis for the face: ``(right, up, forward)``.

    ``right`` runs from the model's left eye to its right eye.  ``forward``
    points out of the face - its sign is settled by checking that the mouth
    sits in front of the eye midpoint, which works for every axis convention.
    """

    __slots__ = ("origin", "right", "up", "forward")

    def __init__(self, origin, right, up, forward):
        self.origin = origin
        self.right = right
        self.up = up
        self.forward = forward

    @classmethod
    def from_landmarks(cls, lm, coords=None):
        """Build the basis, settling ``forward`` as robustly as possible.

        The mouth-alone sign test (``is the mouth in front of the eyes?``)
        collapses when the mouth happens to sit at the same depth as the eyes,
        which is common on flat-ish anime faces.  So we prefer the **mesh
        centroid**: the face features sit on the *outside* of the head while
        their neighbourhood centroid sits *inside* it, so ``eye_mid -
        centroid`` points out of the face for any axis convention.
        """
        if not (lm.eye_L and lm.eye_R and lm.mouth):
            return None
        origin = lm.eye_mid()
        r = _normalize(_sub(lm.eye_R, lm.eye_L))
        if r is None:
            return None

        # "up" - prefer neck->head, then head->eyes, then mouth->eyes.
        u0 = None
        if lm.head and lm.neck:
            u0 = _sub(lm.head, lm.neck)
        elif lm.head:
            u0 = _sub(lm.head, origin)
        if u0 is None:
            u0 = _sub(origin, lm.mouth)
        u = _normalize(_orthogonalize(u0, r))
        if u is None:
            return None

        f = None
        if coords:
            c = _local_centroid(coords, origin, max(lm.half_span(), 1e-9) * 3.0)
            if c is not None:
                f = _normalize(_orthogonalize(_orthogonalize(_sub(origin, c), u), r))
        if f is None and lm.head is not None:
            f = _normalize(_orthogonalize(_orthogonalize(_sub(origin, lm.head), u), r))
        if f is None:
            f = _normalize(_cross(u, r))
            if f is None:
                return None
            if _dot(f, _sub(lm.mouth, origin)) < 0:
                f = _scale(f, -1.0)
        return cls(origin, r, u, f)

    def to_local(self, p):
        d = _sub(p, self.origin)
        return (_dot(d, self.right), _dot(d, self.up), _dot(d, self.forward))

    def delta_to_world(self, d):
        out = [0.0, 0.0, 0.0]
        for i in range(3):
            out[i] = (self.right[i] * d[0] + self.up[i] * d[1]
                      + self.forward[i] * d[2])
        return tuple(out)


# ---------------------------------------------------------------- regions

def _disc(indices, locals_, anchor_local, radius, z_slack=3.0):
    """Vertices whose (x, y) distance from ``anchor_local`` is under radius.

    The eye and mouth are surfaces wrapped around a head, so membership is
    judged in the ``right``/``up`` plane only.  ``z_slack`` is a safety net
    that drops vertices sitting far behind the face plane, which keeps hair
    cards and the back of the skull out of the region.
    """
    ax, ay, az = anchor_local
    out = []
    for vi in indices:
        lx, ly, lz = locals_[vi]
        if abs(lz - az) > radius * z_slack:
            continue
        if (lx - ax) ** 2 + (ly - ay) ** 2 <= radius * radius:
            out.append(vi)
    return out


def detect_regions(coords, frame, lm, params=None):
    """Return ``(regions, locals_, params)``.

    ``regions`` maps a region name to a list of vertex indices; ``locals_``
    holds each vertex's ``(right, up, forward)`` coordinates.  ``coords`` is a
    flat ``[x, y, z, ...]`` array in the same space as the landmarks (world
    space, after applying the object matrix).

    The eye and mouth radii are clamped against each other: each may claim at
    most ``region_split`` of the eye-to-mouth distance, so the discs can never
    meet however the user tunes the scales.  Without this a generous eye
    radius reaches down over the lips and the blink drags the mouth along.
    """
    p = dict(DEFAULT_PARAMS)
    p.update(params or {})
    S = lm.half_span()

    n = len(coords) // 3
    locals_ = [None] * n
    for i in range(n):
        locals_[i] = frame.to_local((coords[i * 3], coords[i * 3 + 1],
                                     coords[i * 3 + 2]))

    all_idx = range(n)
    eye_anchor_L = frame.to_local(lm.eye_L)
    eye_anchor_R = frame.to_local(lm.eye_R)
    mouth_anchor = frame.to_local(lm.mouth)
    eye_mid_local = tuple((eye_anchor_L[i] + eye_anchor_R[i]) * 0.5
                          for i in range(3))

    gap = math.dist(eye_mid_local, mouth_anchor)
    cap = gap * p["region_split"] if gap > 1e-9 else S
    eye_r = min(S * p["eye_scale"], cap)
    mouth_r = min(S * p["mouth_scale"], cap)
    p["eye_radius_used"] = eye_r
    p["mouth_radius_used"] = mouth_r
    p["eye_mouth_gap"] = gap

    regions = {
        "eye_L": _disc(all_idx, locals_, eye_anchor_L, eye_r),
        "eye_R": _disc(all_idx, locals_, eye_anchor_R, eye_r),
        "mouth": _disc(all_idx, locals_, mouth_anchor, mouth_r),
    }

    # Brows live in a band that starts above the eye disc, so a brow move and a
    # blink can never touch the same vertex.
    brow_half_w = S * p["brow_scale"]
    band_lo = eye_anchor_L[1] + eye_r * p["brow_gap"]
    band_hi = band_lo + S * p["brow_thickness"] * 2.0
    for side, anchor in (("L", eye_anchor_L), ("R", eye_anchor_R)):
        band = []
        for vi in all_idx:
            lx, ly, lz = locals_[vi]
            if abs(lx - anchor[0]) > brow_half_w:
                continue
            if ly < band_lo or ly > band_hi:
                continue
            band.append(vi)
        regions["brow_" + side] = band

    return regions, locals_, p


# ------------------------------------------------------------------ rules
#
# Each rule receives (verts, R, S) where ``verts`` is a list of
# ``(vi, lx, ly, lz)`` local to the region anchor, and returns
# ``{vi: (dx, dy, dz)}`` in the same local frame.  The caller converts to
# world space.

def _falloff_x(lx, R):
    """1 at the centre, 0 at the corners - keeps corners from over-collapsing."""
    t = min(1.0, abs(lx) / (R * 1.25))
    return max(0.0, 1.0 - t * t)


def _rule_eye_close(verts, R, S, k=0.92, only_upper=True):
    """Upper lid collapses onto the mid line - the blink."""
    out = {}
    for vi, lx, ly, lz in verts:
        if only_upper and ly <= 0:
            continue
        f = _falloff_x(lx, R)
        if f <= 0:
            continue
        out[vi] = (0.0, -ly * k * f, 0.0)
    return out


def _rule_mouth_open(verts, R, S, amount=0.42, upper_ratio=0.28):
    """Lower lip drops, upper lip lifts a little - あ / お / びっくり."""
    out = {}
    for vi, lx, ly, lz in verts:
        f = _falloff_x(lx, R)
        if f <= 0:
            continue
        if ly < 0:
            out[vi] = (0.0, -S * amount * f, 0.0)
        else:
            out[vi] = (0.0, S * amount * upper_ratio * f, 0.0)
    return out


def _rule_mouth_wide(verts, R, S, amount=0.30):
    """Corners pull outward - い / え."""
    out = {}
    for vi, lx, ly, lz in verts:
        t = min(1.0, abs(lx) / R)
        if t <= 0.05:
            continue
        sign = 1.0 if lx >= 0 else -1.0
        out[vi] = (sign * S * amount * t * t, 0.0, 0.0)
    return out


def _rule_mouth_round(verts, R, S, push=0.22, narrow=0.34, drop=0.10):
    """Lips purse forward and pinch inward - う / お."""
    out = {}
    for vi, lx, ly, lz in verts:
        f = _falloff_x(lx, R)
        dz = S * push * f
        dx = -lx * narrow
        dy = -S * drop * f if ly < 0 else 0.0
        out[vi] = (dx, dy, dz)
    return out


def _rule_mouth_corners(verts, R, S, up=0.34, out_amt=0.20, inner=0.55):
    """Corner weighting - rise for a smile, drop for a scowl."""
    out = {}
    for vi, lx, ly, lz in verts:
        t = min(1.0, abs(lx) / R)
        if t < inner:
            continue
        w = (t - inner) / max(1e-6, 1.0 - inner)
        sign = 1.0 if lx >= 0 else -1.0
        out[vi] = (sign * S * out_amt * w, S * up * w, 0.0)
    return out


def _rule_brow(verts, R, S, amount=0.34, inner_bias=0.0, side="L"):
    """Whole brow up/down; ``inner_bias`` tilts it toward the nose.

    ``verts`` is rebased on the brow band's centroid, so ``lx`` measures
    distance from the *middle* of the brow and only its **sign** says which
    end is the inner one.  On the model's left brow (``side="L"``, the -X
    side) the inner end is the one with the larger ``lx``; on the right brow
    it is the smaller.  Getting this wrong makes ``怒り`` push the outer brow
    down and the inner brow up - i.e. exactly the wrong expression.

    ``R`` is unused but kept so every rule shares one signature.
    """
    if not verts:
        return {}
    half_w = max((abs(v[1]) for v in verts), default=0.0) or 1.0
    out = {}
    for vi, lx, ly, lz in verts:
        u = lx / half_w                       # -1 .. +1 across the brow
        inner_t = (u + 1.0) * 0.5 if side == "L" else (1.0 - u) * 0.5
        w = 1.0 - 0.45 * abs(u)
        out[vi] = (0.0, S * amount * w + S * inner_bias * inner_t, 0.0)
    return out


# ------------------------------------------------------------- expressions

def _combine(*dicts):
    """Merge rule outputs; later rules add to earlier ones."""
    out = {}
    for d in dicts:
        for vi, v in d.items():
            if vi in out:
                a = out[vi]
                out[vi] = (a[0] + v[0], a[1] + v[1], a[2] + v[2])
            else:
                out[vi] = v
    return out


def _combine_builders(*builders):
    """Compose builders, not their results.

    ``_expr_defs`` has to combine expressions that are still builders at the
    time the table is built - ``_combine`` would be applied to functions and
    blow up.  This wraps the composition so the inner ``_combine`` runs later,
    against real vertex data.
    """
    def build(regions, locals_, S):
        out = {}
        for b in builders:
            out = _combine(out, b(regions, locals_, S))
        return out
    return build


def _region_radius(verts):
    if not verts:
        return 1.0
    return max(math.hypot(v[1], v[2]) for v in verts) or 1.0


def _region_local_anchor(verts):
    """Centroid of a region in local space, used as the rule origin."""
    if not verts:
        return (0.0, 0.0, 0.0)
    n = float(len(verts))
    return (sum(v[1] for v in verts) / n,
            sum(v[2] for v in verts) / n,
            sum(v[3] for v in verts) / n)


def _rebase(verts, anchor):
    ax, ay, az = anchor
    return [(vi, lx - ax, ly - ay, lz - az) for vi, lx, ly, lz in verts]


def _rebased(regions, locals_, name):
    """Region vertices, re-centred on their own centroid.

    Rules like "the lid collapses to the mid line" assume the origin sits at
    the middle of the feature, so each rule gets its own centred copy.
    """
    verts = [(vi, *locals_[vi]) for vi in regions[name]]
    centred = _rebase(verts, _region_local_anchor(verts))
    return centred, _region_radius(centred)


def _expr_defs():
    """``{name: builder}`` - the procedural expression set.

    Each builder takes ``(regions, locals_, S)`` and returns local-space
    displacements keyed by vertex index.
    """
    def blink_one(side):
        def build(regions, locals_, S):
            verts, R = _rebased(regions, locals_, "eye_" + side)
            return _rule_eye_close(verts, R, S)
        return build

    def blink_both(regions, locals_, S):
        out = {}
        for side in ("L", "R"):
            verts, R = _rebased(regions, locals_, "eye_" + side)
            out = _combine(out, _rule_eye_close(verts, R, S))
        return out

    def brows(amount, inner_bias=0.0):
        def build(regions, locals_, S):
            out = {}
            for side in ("L", "R"):
                verts, R = _rebased(regions, locals_, "brow_" + side)
                out = _combine(out, _rule_brow(verts, R, S, amount=amount,
                                               inner_bias=inner_bias, side=side))
            return out
        return build

    def mouth_rule(fn):
        def build(regions, locals_, S):
            verts, R = _rebased(regions, locals_, "mouth")
            return fn(verts, R, S)
        return build

    return {
        "まばたき": blink_both,
        "ウィンク": blink_one("R"),          # MMD: ウィンク = model's right eye
        "ウィンク２": blink_one("L"),
        "あ": _combine_builders(mouth_rule(_rule_mouth_open),
                                mouth_rule(_rule_mouth_wide)),
        "い": mouth_rule(lambda v, R, S: _combine(
            _rule_mouth_wide(v, R, S, amount=0.34),
            _rule_mouth_open(v, R, S, amount=0.10, upper_ratio=0.4))),
        "う": mouth_rule(_rule_mouth_round),
        "え": mouth_rule(lambda v, R, S: _combine(
            _rule_mouth_wide(v, R, S, amount=0.26),
            _rule_mouth_round(v, R, S, push=0.10, narrow=0.18, drop=0.16))),
        "お": mouth_rule(lambda v, R, S: _combine(
            _rule_mouth_round(v, R, S, push=0.26, narrow=0.38, drop=0.18),
            _rule_mouth_open(v, R, S, amount=0.16))),
        "にっこり": mouth_rule(lambda v, R, S: _rule_mouth_corners(
            v, R, S, up=0.34, out_amt=0.22)),
        "笑い": _combine_builders(
            mouth_rule(lambda v, R, S: _rule_mouth_corners(
                v, R, S, up=0.46, out_amt=0.30)),
            mouth_rule(lambda v, R, S: _rule_mouth_open(
                v, R, S, amount=0.18))),
        "怒り": _combine_builders(
            brows(0.10, inner_bias=-0.34),
            mouth_rule(lambda v, R, S: _rule_mouth_corners(
                v, R, S, up=-0.30, out_amt=0.06))),
        "困る": brows(0.06, inner_bias=0.30),
        "びっくり": _combine_builders(
            brows(0.40),
            mouth_rule(lambda v, R, S: _rule_mouth_open(
                v, R, S, amount=0.46, upper_ratio=0.20))),
        "眉上げ": brows(0.34),
        "眉下げ": brows(-0.34),
        "素の表情": lambda regions, locals_, S: {},
    }


EXPRESSION_NAMES = (
    "まばたき", "ウィンク", "ウィンク２",
    "あ", "い", "う", "え", "お",
    "にっこり", "笑い", "怒り", "困る", "びっくり",
    "眉上げ", "眉下げ", "素の表情",
)


def generate(coords, lm, params=None, frame=None):
    """Procedurally build expressions for a head with no morphs.

    Parameters
    ----------
    coords : sequence of float
        Flat ``[x, y, z, ...]`` vertex positions in world space.
    lm : landmarks.Landmarks
        Detected or user-supplied face anchors.
    params : dict, optional
        Overrides for :data:`DEFAULT_PARAMS`.

    Returns
    -------
    (dict, dict)
        ``({name: [(vi, dx, dy, dz), ...]}, info)``.  The displacement lists
        are in **world space** and use the same sparse format as
        ``core.sparse_deltas``, so they drop straight into ``core.blend_sparse``.
        ``info`` carries the face frame and region sizes for the report.
    """
    if frame is None:
        frame = FaceFrame.from_landmarks(lm, coords)
    if frame is None or not lm.complete:
        return {}, {"error": "landmarks incomplete"}

    regions, locals_, p = detect_regions(coords, frame, lm, params)
    S = lm.half_span()
    strength = p["strength"]

    result = {}
    for name, builder in _expr_defs().items():
        local_deltas = builder(regions, locals_, S)
        if not local_deltas:
            result[name] = []
            continue
        world = []
        for vi, d in local_deltas.items():
            wd = frame.delta_to_world(d)
            wd = (wd[0] * strength, wd[1] * strength, wd[2] * strength)
            if abs(wd[0]) > 1e-9 or abs(wd[1]) > 1e-9 or abs(wd[2]) > 1e-9:
                world.append((vi, wd[0], wd[1], wd[2]))
        result[name] = world

    info = {
        "frame": {
            "origin": frame.origin,
            "right": frame.right,
            "up": frame.up,
            "forward": frame.forward,
        },
        "regions": {k: len(v) for k, v in regions.items()},
        "params": p,
        "half_span": S,
    }
    return result, info


def region_summary(coords, lm, params=None):
    """Region sizes only - used by the UI to warn about bad detection."""
    frame = FaceFrame.from_landmarks(lm, coords)
    if frame is None or not lm.complete:
        return None
    regions, _, _ = detect_regions(coords, frame, lm, params)
    return {k: len(v) for k, v in regions.items()}
