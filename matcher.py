"""Atom-name matching.

The reference model's native shape keys are called ``Eyebrow_Angry``,
``Mouth_A01``, ``Eye_Wink01_L`` ... but the *next* model you feed this addon
will almost certainly use different names.  So we never assume an exact match:
every shape key on the object is scored against every known atom, and the best
**unambiguous** assignment wins.

Scoring (higher wins):

======  ============================================================
score   rule
======  ============================================================
100     ``key == atom["ref"]``            exact, the reference model
 98     ``key == atom["id"]``             exact, already normalised
 90     normalised key == normalised ref
 88     normalised key == normalised id
 85     alias-table hit
 80     key equals the atom's Japanese note
 72     *loose* match - digits stripped (``Eye_Wink_L`` vs ``Eye_Wink01_L``)
60-65   fuzzy ratio (difflib), only when >= 0.82
======  ============================================================

Anything below :data:`MIN_SCORE` is "no match".

Why the ambiguity guard matters: the reference model ships paired atoms that
differ by a single digit - ``Eye_Wink01_L`` / ``Eye_Wink02_L``,
``Eyebrow_Shy`` / ``Eyebrow_Shy02``.  A naive fuzzy matcher will happily map
``Eye_Wink02_L`` onto ``eye_wink01_L``.  Every match below score 80 must
therefore beat the runner-up by :data:`AMBIGUITY_MARGIN`.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

MIN_SCORE = 60
AMBIGUITY_MARGIN = 6
FUZZY_MIN_RATIO = 0.82

_SPLIT_RE = re.compile(r"[\s_\-\.\|/\\:]+")
_DIGITS_RE = re.compile(r"\d+")

#: Names seen in the wild for the same atom, keyed by atom id.
#: Values are compared *normalised*, so write them however you like.
BUILTIN_ALIASES: dict[str, tuple[str, ...]] = {
    "eye_wink01_L": ("eye_wink_l", "wink_l", "eye_close_l", "eyelid_close_l",
                     "eye_blink_l", "blink_l", "eye_shut_l"),
    "eye_wink01_R": ("eye_wink_r", "wink_r", "eye_close_r", "eyelid_close_r",
                     "eye_blink_r", "blink_r", "eye_shut_r"),
    "eye_wink02_L": ("eye_wink2_l", "wink2_l", "eye_close2_l", "eye_smile_l"),
    "eye_wink02_R": ("eye_wink2_r", "wink2_r", "eye_close2_r", "eye_smile_r"),
    "eye_half": ("eye_half", "eye_half1", "half_eye", "jitome", "eye_narrow"),
    "eye_contempt": ("eye_contempt", "jitome", "eye_scorn", "eye_jeer"),
    "brow_up": ("brow_up", "eyebrow_up", "brow_raise"),
    "brow_down": ("brow_down", "eyebrow_down", "brow_lower", "brow_furrow"),
    "mouth_a": ("mouth_a", "a", "mouth_ah", "lip_a"),
    "mouth_i": ("mouth_i", "i", "mouth_ih", "lip_i"),
    "mouth_u": ("mouth_u", "u", "mouth_uh", "lip_u"),
    "mouth_e": ("mouth_e", "e", "mouth_eh", "lip_e"),
    "mouth_o": ("mouth_o", "o", "mouth_oh", "lip_o"),
    "mouth_n": ("mouth_n", "n", "mouth_nn"),
    "mouth_smile": ("mouth_smile", "smile_mouth", "mouth_joy", "mouth_happy"),
    "mouth_angry": ("mouth_angry", "angry_mouth", "mouth_anger"),
    "eye_highlight_off": ("eye_highlight_off", "highlight_missing",
                          "eye_highlight_missing", "highlight_off"),
    "eye_highlight_down": ("eye_highlight_down", "highlight_down",
                           "eye_highlight_weak", "highlight_weak"),
    "eye_look_up": ("eye_look_up", "eye_lookat_top", "eye_up", "look_up"),
    "eye_look_down": ("eye_look_down", "eye_lookat_bottom", "eye_down", "look_down"),
    "eye_look_left": ("eye_look_left", "eye_lookat_left", "eye_left", "look_left"),
    "eye_look_right": ("eye_look_right", "eye_lookat_right", "eye_right", "look_right"),
    "tongue_up": ("tongue_up", "tongue_out", "tongue"),
    "tongue_down": ("tongue_down", "tongue_in", "tongue_pull"),
}


def normalize(name) -> str:
    """Casefold, NFKC, and strip every separator. ``Eye_Wink01_L`` -> ``eyewink01l``."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", str(name))
    s = _SPLIT_RE.sub("", s)
    return s.casefold()


def loose(name) -> str:
    """Like :func:`normalize` but also drops digit runs.

    ``Eye_Wink01_L`` and ``Eye_Wink_L`` both collapse to ``eyewinkl``.  Used
    only as a fallback because it deliberately loses the ``01``/``02``
    distinction.
    """
    return _DIGITS_RE.sub("", normalize(name))


def _alias_sets(aliases):
    """Normalise the alias table once so lookups are cheap."""
    out = {}
    for atom_id, names in (aliases or {}).items():
        out[atom_id] = {normalize(n) for n in names}
    return out


def score(key_name, atom, alias_sets) -> int:
    """How well does ``key_name`` describe ``atom``?  0 = not at all."""
    if not key_name:
        return 0
    ref = atom.get("ref") or ""
    aid = atom.get("id") or ""

    if key_name == ref:
        return 100
    if key_name == aid:
        return 98

    k = normalize(key_name)
    if not k:
        return 0
    nref, nid = normalize(ref), normalize(aid)
    if nref and k == nref:
        return 90
    if nid and k == nid:
        return 88

    if k in alias_sets.get(aid, ()):
        return 85

    note = normalize(atom.get("note"))
    if note and k == note:
        return 80

    lk = loose(key_name)
    if lk and (lk == loose(ref) or lk == loose(aid)):
        return 72

    candidates = [c for c in (nref, nid) if c]
    if not candidates:
        return 0
    ratio = max(difflib.SequenceMatcher(None, k, c).ratio() for c in candidates)
    if ratio >= FUZZY_MIN_RATIO:
        return int(40 + ratio * 25)
    return 0


class MatchResult:
    """Outcome of matching one object's shape keys against the atom table."""

    __slots__ = ("matched", "unmatched_keys", "missing_atoms", "scores", "ambiguous")

    def __init__(self):
        #: ``{atom_id: shape_key_name}`` - the assignment we will bake with.
        self.matched: dict[str, str] = {}
        #: Shape keys that no atom claimed (Basis, existing standard keys, junk).
        self.unmatched_keys: list[str] = []
        #: Atom ids with no shape key on this object.
        self.missing_atoms: list[str] = []
        #: ``{(key, atom_id): score}`` for every assignment we made.
        self.scores: dict[tuple[str, str], int] = {}
        #: ``[(key, best_atom_id, best_score, runner_up_score)]`` for rejected
        #: fuzzy candidates - surfaced in the UI so the user can map by hand.
        self.ambiguous: list[tuple[str, str, int, int]] = []

    def __repr__(self):
        return "MatchResult(matched=%d, unmatched=%d, missing=%d)" % (
            len(self.matched), len(self.unmatched_keys), len(self.missing_atoms))


def match_atoms(key_names, atoms, aliases=None, manual=None):
    """Assign every atom at most one shape key, greedily by score.

    Parameters
    ----------
    key_names : iterable of str
        Shape key names on one object.  ``Basis`` is ignored.
    atoms : list of dict
        Entries from ``data/atoms.json``.
    aliases : dict, optional
        Extra alias table, merged over :data:`BUILTIN_ALIASES`.
    manual : dict, optional
        ``{shape_key_name: atom_id}`` - user overrides.  These win outright and
        are applied before automatic matching.

    Returns
    -------
    MatchResult
    """
    merged = dict(BUILTIN_ALIASES)
    for k, v in (aliases or {}).items():
        merged[k] = tuple(merged.get(k, ())) + tuple(v)
    alias_sets = _alias_sets(merged)

    keys = [k for k in key_names if k and k != "Basis"]
    result = MatchResult()

    by_id = {a["id"]: a for a in atoms}
    taken_keys: set[str] = set()
    taken_atoms: set[str] = set()

    # 1) manual overrides - the user knows better than the scorer.
    for key, atom_id in (manual or {}).items():
        if atom_id in by_id and key in keys and key not in taken_keys:
            result.matched[atom_id] = key
            result.scores[(key, atom_id)] = 1000
            taken_keys.add(key)
            taken_atoms.add(atom_id)

    # 2) score every remaining (key, atom) pair.
    triples = []
    for key in keys:
        if key in taken_keys:
            continue
        for atom in atoms:
            if atom["id"] in taken_atoms:
                continue
            s = score(key, atom, alias_sets)
            if s >= MIN_SCORE:
                triples.append((s, key, atom["id"]))

    # 3) per-key ranking, so we can apply the ambiguity guard.
    by_key: dict[str, list[tuple[int, str]]] = {}
    for s, key, aid in triples:
        by_key.setdefault(key, []).append((s, aid))
    for key, cands in by_key.items():
        cands.sort(key=lambda t: (-t[0], t[1]))

    ranked = []
    for key, cands in by_key.items():
        best_s, best_a = cands[0]
        runner_s = cands[1][0] if len(cands) > 1 else 0
        if best_s < 80 and (best_s - runner_s) < AMBIGUITY_MARGIN:
            result.ambiguous.append((key, best_a, best_s, runner_s))
            continue
        ranked.append((best_s, key, best_a))

    # 4) greedy global assignment, highest score first.
    ranked.sort(key=lambda t: (-t[0], t[1], t[2]))
    for s, key, aid in ranked:
        if key in taken_keys or aid in taken_atoms:
            continue
        result.matched[aid] = key
        result.scores[(key, aid)] = s
        taken_keys.add(key)
        taken_atoms.add(aid)

    result.unmatched_keys = [k for k in keys if k not in taken_keys]
    result.missing_atoms = [a["id"] for a in atoms if a["id"] not in taken_atoms]
    return result


def is_standard_name(name, expressions):
    """True when ``name`` is already one of our standard expression names.

    Used to detect models that already ship MMD-style expressions so we can
    leave them alone instead of baking a duplicate.
    """
    n = normalize(name)
    if not n:
        return False
    for e in expressions:
        for field in ("mmd", "mmd_en", "id", "zh"):
            if normalize(e.get(field)) == n:
                return True
    return False
