"""Face correspondence, independent of bpy and vertex counts.

Evidence comes from several nearest-surface samples per target polygon.
Topology is used to regularize coherent patches, never to require identical meshes.
Labels: >= 0 source material region; -1 outside source support; -2 uncertain.
"""
from collections import Counter, defaultdict, deque
from math import sqrt, log
import re
import unicodedata

# Stable semantic IDs, independent of editable Blender material-slot order.
REGION_NAMES = {-1: '不参与', -2: '不确定', 0: 'Face', 2: 'Eyelashes/Brows',
                3: 'Eyes', 7: 'Blank stare', 8: 'Mouth', 9: 'Teeth', 12: 'Tongue'}
DEFAULT_TRANSFER_REGIONS = frozenset(label for label in REGION_NAMES if label >= 0)


def canonical_region(label):
    """Legacy highlights (5) belong to the iris/highlight assembly (3)."""
    return 3 if label==5 else label


def exact_material_region(name):
    """Recognize current marker names and canonical material names."""
    name = re.sub(r'(\.\d{3})+$', '', name or '').strip()
    if name.startswith(('EK_不参与_','EK_无源对应_')):
        return -1
    if name.startswith('EK_不确定_'):return -2
    while name.startswith('EK_对应_'):
        name=name[len('EK_对应_'):]
    names = {v.casefold(): k for k, v in REGION_NAMES.items()}
    names['mouth/tongue'] = 8
    names['gaze'] = 3
    names.update({'面部':0,'眉睫':2,'眉毛':2,'睫毛':2,'眼睛':3,'左眼':3,'右眼':3,
                  '高光':3,'瞳孔与高光':3,'呆滞眼':7,'口腔':8,'牙齿':9,'舌头':12})
    return names.get(name.casefold())


_ENGLISH_REGION_PATTERNS={
    0:r'face|facial|lips?',
    2:r'eye\s*lash(?:es)?|lash(?:es)?|eye\s*brows?|brows?|eye\s*liners?|eye\s*lines?|double\s*eyelid|eyelid\s*lines?',
    3:r'eyes?|eye\s*balls?|iris(?:es)?|pupils?',
    5:r'gaze|high\s*lights?|catch\s*lights?',
    7:r'blank\s*stare|eye\s*whites?|sclera',
    8:r'mouth|oral',
    9:r'teeth|tooth|dental',
    12:r'tongue',
}
_ENGLISH_REGION_PATTERNS={label:re.compile(r'(?<![a-z])(?:'+pattern+r')(?![a-z])')
                          for label,pattern in _ENGLISH_REGION_PATTERNS.items()}
_CJK_REGION_KEYWORDS={
    0:('面部','脸部','臉部','脸皮','臉皮','顔肌','嘴唇','眼眶'),
    2:('眉睫','眉毛','睫毛','眼线','眼線','双眼皮','雙眼皮','まつげ','まつ毛','アイライン'),
    3:('眼睛','眼球','瞳孔','虹膜','目玉'),
    5:('眼高光','高光','ハイライト'),
    7:('呆滞眼','呆滯眼','眼白','白目'),
    8:('口腔','口内','口內','嘴内','嘴內'),
    9:('牙齿','牙齒','牙龈','牙齦'),
    12:('舌头','舌頭','ベロ','べろ'),
}
_SINGLE_CJK_REGIONS={'脸':0,'臉':0,'顔':0,'眉':2,'目':3,'眼':3,'口':8,'歯':9,'牙':9,'舌':12}


def _material_region(name):
    """Recognize region keywords with prefixes, separators and compound names."""
    name=unicodedata.normalize('NFKC',name or '').strip()
    name=re.sub(r'(\.\d{3,})+$','',name)
    exact=exact_material_region(name)
    if exact is not None:return exact
    # Split authored CamelCase before folding; avoid substring hits in surface,
    # brown, flashlight and eyelet. Numeric Blender suffixes were removed above.
    words=re.sub(r'([A-Z]+)([A-Z][a-z])',r'\1 \2',name)
    words=re.sub(r'([a-z0-9])([A-Z])',r'\1 \2',words).casefold()
    words=re.sub(r'[^\w]+|_', ' ',words)
    if re.search(r'(?<![a-z])face\s*0*2(?!\d)',words):return None
    # A combined mouth/tongue material remains the combined oral partition.
    if re.search(r'(?<![a-z])mouth\s+tongue(?![a-z])',words):return 8
    labels={label for label,pattern in _ENGLISH_REGION_PATTERNS.items() if pattern.search(words)}
    labels.update(label for label,keywords in _CJK_REGION_KEYWORDS.items()
                  if any(keyword in name for keyword in keywords))
    labels.update(label for token,label in _SINGLE_CJK_REGIONS.items()
                  if re.search(r'(?<![^\W_])'+token+r'(?![^\W_])',words))
    # Eye/face/mouth can qualify a more specific feature (Face_EyeLashes,
    # Eye_Highlight, Mouth_Teeth). Equally specific conflicting labels stay unknown.
    specific=labels & {2,5,7,9,12}
    if specific=={9,12} and 8 in labels:return 8
    if len(specific)>1:return None
    if specific:
        label=next(iter(specific))
        if label==5 and 3 not in labels and re.search(r'\b(hair|shirt|skirt|cloth|body)\b',words):return None
        return label
    parts=labels & {3,8}
    if len(parts)>1:return None
    return next(iter(parts)) if parts else (0 if 0 in labels else None)


def material_region(name):
    return canonical_region(_material_region(name))

OUTSIDE = -1
UNCERTAIN = -2


def distance(a, b):
    return sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def topology(polygons):
    """Face adjacency through shared edges (touching vertices do not join islands)."""
    edges = defaultdict(list)
    for i, face in enumerate(polygons):
        for a, b in zip(face, face[1:] + face[:1]):
            edges[tuple(sorted((a, b)))].append(i)
    neighbors = [set() for _ in polygons]
    for owners in edges.values():
        for a in owners:
            neighbors[a].update(b for b in owners if b != a)
    todo = set(range(len(polygons)))
    components = []
    while todo:
        root = min(todo)
        todo.remove(root)
        part, queue = [], deque([root])
        while queue:
            a = queue.popleft()
            part.append(a)
            for b in sorted(neighbors[a]):
                if b in todo:
                    todo.remove(b)
                    queue.append(b)
        verts = {v for i in part for v in polygons[i]}
        own_edges = {tuple(sorted((a, b))) for i in part
                     for a, b in zip(polygons[i], polygons[i][1:] + polygons[i][:1])}
        boundary = [e for e in own_edges if len(edges[e]) == 1]
        components.append({'faces': part, 'vertices': len(verts),
                           'edges': len(own_edges), 'boundary_edges': len(boundary),
                           'euler': len(verts) - len(own_edges) + len(part)})
    return neighbors, components


def topology_profiles(polygons):
    """Local connectivity signatures plus boundary distance and island shape.

    Vertex IDs only describe connectivity, never cross-side correspondence.
    Histograms permit different tessellations without requiring equal indices.
    """
    neighbors, components = topology(polygons)
    edges, vertex_edges = defaultdict(list), defaultdict(set)
    for i, face in enumerate(polygons):
        for a, b in zip(face, face[1:] + face[:1]):
            edge = tuple(sorted((a, b)))
            edges[edge].append(i)
            vertex_edges[a].add(edge)
            vertex_edges[b].add(edge)
    boundary = [0] * len(polygons)
    for owners in edges.values():
        if len(owners) == 1:
            boundary[owners[0]] += 1
    depths = [6] * len(polygons)
    queue = deque(i for i, count in enumerate(boundary) if count)
    for i in queue:
        depths[i] = 0
    while queue:
        i = queue.popleft()
        for j in neighbors[i]:
            if depths[j] > depths[i] + 1:
                depths[j] = depths[i] + 1
                queue.append(j)
    islands = {}
    for comp in components:
        signature = (len(comp['faces']), comp['euler'], bool(comp['boundary_edges']))
        islands.update({i: signature for i in comp['faces']})
    profiles = []
    for i, face in enumerate(polygons):
        ring = set(neighbors[i])
        for j in neighbors[i]:
            ring.update(neighbors[j])
        ring.discard(i)
        profiles.append(dict(vertices=len(face), degree=len(neighbors[i]),
            valences=dict(Counter(len(vertex_edges[v]) for v in face)),
            ring=dict(Counter(len(neighbors[j]) for j in ring)),
            boundary=boundary[i] / max(len(face), 1), depth=depths[i],
            island=islands[i]))
    return neighbors, profiles


def topology_cost(a, b, strict=True):
    """Return None for incompatible islands, otherwise normalized difference."""
    na, ea, open_a = a['island']
    nb, eb, open_b = b['island']
    ratio = max(na, nb) / max(min(na, nb), 1)
    if strict and (open_a != open_b or ratio > 8):
        return None
    def delta(x, y):
        return abs(x - y) / max(abs(x), abs(y), 1)
    def histogram(x, y):
        sx, sy = max(sum(x.values()), 1), max(sum(y.values()), 1)
        return sum(abs(x.get(k, 0) / sx - y.get(k, 0) / sy)
                   for k in set(x) | set(y)) / 2
    return (0.10 * delta(a['vertices'], b['vertices']) +
            0.20 * delta(a['degree'], b['degree']) +
            0.20 * histogram(a['valences'], b['valences']) +
            0.20 * histogram(a['ring'], b['ring']) +
            0.10 * abs(a['boundary'] - b['boundary']) +
            0.10 * abs(a['depth'] - b['depth']) / 6 +
            0.05 * delta(ea, eb) + 0.05 * min(log(ratio), 1) +
            (0.10 if open_a != open_b else 0))


def topology_correspondence(candidates, neighbors, labels, steps=4):
    """Optimize face correspondence with adjacency, not a positional lookup.

    candidates[target] = [(source, geometric_cost, topology_cost, normal_cost)].
    A two-edge allowance accommodates different tessellation. Ambiguous label
    choices and mappings contradicting all mapped neighbors are left unresolved.
    """
    two_ring = {}
    def linked(a, b):
        if a == b or b in neighbors[a]:
            return 0.0
        if a not in two_ring:
            two_ring[a] = set().union(*(neighbors[i] for i in neighbors[a])) if neighbors[a] else set()
        return 0.35 if b in two_ring[a] else 1.0
    def base(row):
        return 0.25 * row[1] + 0.65 * row[2] + 0.10 * row[3]
    mapping = {i: min(rows, key=lambda row: (base(row), row[0]))[0]
               for i, rows in candidates.items() if rows}
    rankings = {}
    for _ in range(steps):
        updated = {}
        for i, rows in candidates.items():
            mapped = [mapping[j] for j in neighbors[i] if j in mapping]
            rankings[i] = sorted((base(row) + (0.55 * sum(linked(row[0], j) for j in mapped)
                                 / len(mapped) if mapped else 0), row[0]) for row in rows)
            if rankings[i]:
                updated[i] = rankings[i][0][1]
        if updated == mapping:
            break
        mapping = updated
    accepted, ambiguous, conflicts = {}, 0, 0
    for i, match in mapping.items():
        ranked = rankings[i]
        if any(score - ranked[0][0] < 0.025 and labels[other] != labels[match]
               for score, other in ranked[1:]):
            ambiguous += 1
            continue
        mapped = [mapping[j] for j in neighbors[i] if j in mapping]
        if mapped and all(linked(match, j) == 1 for j in mapped):
            conflicts += 1
            continue
        accepted[i] = match
    return accepted, dict(ambiguous=ambiguous, adjacency_conflicts=conflicts)


def classify(evidence, neighbors, tolerance, normal_min=0.15,
             seed_score=0.68, accept_score=0.46, smooth_steps=3, manual=None):
    """Combine spatial support, local surface orientation, and face adjacency.

    Each evidence row has samples [{distance, normal_dot, label}], area and normal.
    Unsupported samples are never made into supported regions by graph smoothing.
    Mixed samples near a material boundary remain uncertain unless graph agreement
    is sufficient. Scores are heuristics, not calibrated probabilities.
    """
    if tolerance <= 0:
        raise ValueError('tolerance must be positive')
    if len(evidence) != len(neighbors):
        raise ValueError('evidence and graph size differ')
    manual = dict(manual or {})
    for i, label in manual.items():
        if not 0 <= i < len(evidence) or not isinstance(label, int) or label < UNCERTAIN:
            raise ValueError('invalid manual face label')
    allowed, scores, labels, reasons = [], [], [], []
    for row in evidence:
        samples = row.get('samples', [])
        votes, quality = Counter(), defaultdict(float)
        geometric = 0
        for s in samples:
            d, dot = s['distance'], s['normal_dot']
            if d <= tolerance:
                geometric += 1
            if d > tolerance or dot < normal_min or s['label'] < 0:
                continue
            votes[s['label']] += 1
            quality[s['label']] += (1.0 - 0.6 * d / tolerance) * max(0.0, dot)
        count = max(len(samples), 1)
        support = sum(votes.values()) / count
        strong = support >= 0.6
        allowed.append(strong)
        score = {k: quality[k] / count for k in votes}
        scores.append(score)
        if not strong:
            labels.append(UNCERTAIN if geometric / count >= 0.4 and votes else OUTSIDE)
            reasons.append('mixed_support' if votes else 'distance_or_normal')
        else:
            best = min(score, key=lambda k: (-score[k], k))
            labels.append(best if score[best] >= seed_score else UNCERTAIN)
            reasons.append('surface_seed' if labels[-1] >= 0 else 'low_confidence')
    for i, label in manual.items():
        labels[i], reasons[i] = label, 'manual'

    for _ in range(smooth_steps):
        updated = list(labels)
        for i, adj in enumerate(neighbors):
            if i in manual or not allowed[i] or not scores[i]:
                continue
            votes = Counter(labels[j] for j in adj if labels[j] >= 0)
            total = sum(votes.values())
            candidates = {}
            for label, score in scores[i].items():
                agreement = votes[label] / total if total else 0.0
                candidates[label] = score + 0.2 * agreement
            best = min(candidates, key=lambda k: (-candidates[k], k))
            # Require independent geometric support for the voted label.
            if scores[i][best] >= accept_score and candidates[best] >= seed_score:
                updated[i] = best
                if updated[i] != labels[i]:
                    reasons[i] = 'surface_and_adjacency'
        if updated == labels:
            break
        labels = updated

    return {'labels': labels, 'scores': [max(s.values(), default=0.0) for s in scores],
            'reasons': reasons, 'counts': dict(Counter(labels)),
            'manual_count': len(manual), 'tolerance': tolerance}
