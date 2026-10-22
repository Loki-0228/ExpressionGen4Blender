"""Face landmark detection - bone first, manual override always available.

This is the piece that makes the addon work on an *arbitrary* model.  A model
that already ships morphs can be handled by combining them (``matcher`` +
``core``); a model with **no morphs at all** has nothing to combine, so the
only way to invent expressions is to find the eyes, mouth and brows
geometrically and displace those vertices by rule (``generate``).

Faces come in two flavours and both are covered:

* **Bones** - MMD models carry ``左目``/``右目``/``口``/``左眉``/``右眉``;
  VRM models carry humanoid bones.  Names are matched through a big alias
  table after normalisation, so ``LeftEye``, ``eye.L``, ``左目`` and
  ``J_Bip_L_Eye`` all land on the same slot.
* **Manual** - anything else (sculpts, non-human heads, models whose bones
  were stripped on export).  The user types coordinates in the N panel.

Nothing here imports ``bpy``: the caller passes plain ``{name: (head, tail)}``
dicts and ``[(x, y, z), ...]`` vertex arrays, which keeps all of it testable.
"""

from __future__ import annotations

import math
import re
import unicodedata

#: Blender's ``.L`` / ``.R`` suffixes and every other separator we have seen.
_SEP_RE = re.compile(r"[\s_\-\.\|/\\:]+")
_TRAILING_NUM_RE = re.compile(r"\.\d{3}$")


def normalize(name) -> str:
    """``LeftEye`` / ``eye.L`` / ``左目`` -> a comparable key."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name))
    s = _TRAILING_NUM_RE.sub("", s)          # Blender's duplicate suffix
    s = _SEP_RE.sub("", s)
    return s.casefold()


#: slot -> candidate bone names, most specific first.
BONE_ALIASES = {
    "head": (
        "頭", "head", "J_Bip_C_Head", "mixamorigHead", "Head",
        "Bip01_Head", "head1",
    ),
    "neck": (
        "首", "neck", "J_Bip_C_Neck", "mixamorigNeck", "Bip01_Neck",
    ),
    "eye_L": (
        "左目", "eye_l", "eyel", "lefteye", "eyeleft", "lefteyeball",
        "J_Bip_L_Eye", "mixamorigLeftEye", "hitomi_l", "目l", "eye_l_",
        "左眼球", "lefteyejoint",
    ),
    "eye_R": (
        "右目", "eye_r", "eyer", "righteye", "eyeright", "righteyeball",
        "J_Bip_R_Eye", "mixamorigRightEye", "hitomi_r", "目r", "eye_r_",
        "右眼球", "righteye joint",
    ),
    "mouth": (
        "口", "mouth", "jaw", "J_Bip_C_Jaw", "mixamorigJaw",
        "Bip01_Jaw", "口上", "kuchi", "lowerjaw", "chin",
    ),
    "brow_L": (
        "左眉", "brow_l", "browl", "leftbrow", "eyebrow_l", "eyebrowl",
        "lefteyebrow", "mayu_l", "眉l", "J_Bip_L_...",
    ),
    "brow_R": (
        "右眉", "brow_r", "browr", "rightbrow", "eyebrow_r", "eyebrowr",
        "righteyebrow", "mayu_r", "眉r",
    ),
}

#: Slots that must be present before procedural generation can run at all.
REQUIRED_SLOTS = ("eye_L", "eye_R", "mouth")

#: Nice to have - without them the brow expressions are dropped.
OPTIONAL_SLOTS = ("brow_L", "brow_R", "head", "neck")


class Landmarks:
    """World-space anchor points for the face.

    ``confidence`` is ``"bones"`` when every required slot came from an
    armature, ``"partial"`` when some slots were filled in by the user, and
    ``"manual"`` when nothing was auto-detected.
    """

    __slots__ = ("eye_L", "eye_R", "mouth", "brow_L", "brow_R",
                 "head", "neck", "confidence", "sources")

    def __init__(self):
        self.eye_L = None
        self.eye_R = None
        self.mouth = None
        self.brow_L = None
        self.brow_R = None
        self.head = None
        self.neck = None
        self.confidence = "manual"
        #: slot -> bone name it came from, for the report
        self.sources: dict[str, str] = {}

    # -- derived quantities ------------------------------------------------

    @property
    def complete(self) -> bool:
        return all(getattr(self, s) is not None for s in REQUIRED_SLOTS)

    @property
    def has_brows(self) -> bool:
        return self.brow_L is not None and self.brow_R is not None

    def eye_mid(self):
        return _mid(self.eye_L, self.eye_R)

    def eye_span(self) -> float:
        """Distance between the two eye anchors - the natural unit of scale."""
        return _dist(self.eye_L, self.eye_R)

    def half_span(self) -> float:
        return self.eye_span() * 0.5

    def as_dict(self):
        return {s: getattr(self, s) for s in
                ("eye_L", "eye_R", "mouth", "brow_L", "brow_R", "head", "neck",
                 "confidence", "sources")}

    def __repr__(self):
        return "Landmarks(confidence=%s, complete=%s)" % (self.confidence,
                                                          self.complete)


def _mid(a, b):
    if a is None or b is None:
        return None
    return tuple((a[i] + b[i]) * 0.5 for i in range(3))


def _dist(a, b):
    if a is None or b is None:
        return 0.0
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


def resolve_bones(bones):
    """Map an armature's bones onto face slots.

    Parameters
    ----------
    bones : dict
        ``{bone_name: (head_xyz, tail_xyz)}`` in world space.

    Returns
    -------
    (dict, dict)
        ``(slots, sources)`` - ``slots`` maps slot -> world position (bone
        *head*), ``sources`` maps slot -> the bone name that won.
    """
    by_norm = {}
    for name in bones:
        by_norm.setdefault(normalize(name), name)

    slots, sources = {}, {}
    for slot, aliases in BONE_ALIASES.items():
        for alias in aliases:
            key = normalize(alias)
            if key in by_norm:
                real = by_norm[key]
                head = bones[real][0]
                if head is not None:
                    slots[slot] = tuple(head)
                    sources[slot] = real
                    break
    return slots, sources


def landmarks_from_bones(bones, overrides=None):
    """Full detection pipeline with a sanity pass and manual overrides."""
    slots, sources = resolve_bones(bones)

    # A model that names both eye bones the same thing (or has one eye bone
    # aliased twice) resolves eye_L and eye_R onto one position.  Dropping the
    # twin leaves a usable eye_L and lets the user place eye_R by hand, which
    # beats silently generating a blink that shuts both eyes at once.
    eye_l, eye_r = slots.get("eye_L"), slots.get("eye_R")
    if eye_l is not None and eye_r is not None and _dist(eye_l, eye_r) < 1e-6:
        slots.pop("eye_R", None)
        sources.pop("eye_R", None)

    lm = Landmarks()
    for slot in ("eye_L", "eye_R", "mouth", "brow_L", "brow_R", "head", "neck"):
        if slot in slots:
            setattr(lm, slot, slots[slot])
            lm.sources[slot] = sources.get(slot, "?")

    auto = sum(1 for s in REQUIRED_SLOTS if getattr(lm, s) is not None)
    if auto == 0:
        lm.confidence = "manual"
    elif auto == len(REQUIRED_SLOTS):
        lm.confidence = "bones"
    else:
        lm.confidence = "partial"

    if overrides:
        apply_overrides(lm, overrides)

    return lm


def apply_overrides(lm, overrides):
    """Apply ``{slot: (x, y, z)}`` on top of detection.

    The UI exposes every landmark as three float fields.  A field left at
    ``None`` means "keep whatever was detected".
    """
    for slot, value in overrides.items():
        if value is None:
            continue
        if slot not in ("eye_L", "eye_R", "mouth", "brow_L", "brow_R",
                        "head", "neck"):
            continue
        if isinstance(value, (list, tuple)) and len(value) == 3 \
                and all(v is not None for v in value):
            setattr(lm, slot, tuple(float(v) for v in value))
            lm.sources[slot] = "manual"
    if lm.confidence == "bones" and any(
            v == "manual" for v in lm.sources.values()):
        lm.confidence = "partial"
    return lm


def derive_missing(lm):
    """Fill in brows / head when the armature did not provide them.

    Brows and the head centre are not needed for the mouth shapes, but the
    brow expressions and the face frame want them, so we synthesise plausible
    positions from the eyes and mouth rather than silently dropping features.
    """
    span = lm.half_span()
    if span <= 0:
        return lm

    eye_mid = lm.eye_mid()
    if eye_mid is None:
        return lm

    up = (0.0, 0.0, 1.0)
    if lm.head is not None and lm.neck is not None:
        up = _normalize(_sub(lm.head, lm.neck)) or up
    elif lm.mouth is not None:
        up = _normalize(_sub(eye_mid, lm.mouth)) or up

    if lm.brow_L is None and lm.brow_R is None:
        off = _scale(up, span * 0.55)
        lm.brow_L = _add(lm.eye_L, off) if lm.eye_L else None
        lm.brow_R = _add(lm.eye_R, off) if lm.eye_R else None
        if lm.brow_L:
            lm.sources.setdefault("brow_L", "derived")
            lm.sources.setdefault("brow_R", "derived")
    if lm.head is None:
        lm.head = _add(eye_mid, _scale(up, span * 0.9))
        lm.sources.setdefault("head", "derived")
    return lm


# ------------------------------------------------------------------ vectors

def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _add(a, b):
    if a is None or b is None:
        return None
    return tuple(a[i] + b[i] for i in range(3))


def _scale(v, s):
    return tuple(c * s for c in v)


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1],
            a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _length(v):
    return math.sqrt(sum(c * c for c in v))


def _normalize(v):
    n = _length(v)
    if n < 1e-12:
        return None
    return tuple(c / n for c in v)


def _orthogonalize(v, unit):
    """Remove the component of ``v`` along ``unit``."""
    d = _dot(v, unit)
    return tuple(v[i] - unit[i] * d for i in range(3))
