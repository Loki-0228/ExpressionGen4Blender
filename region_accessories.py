"""Accessory ownership from physical seams, eyelid support and root attachment.

Only coincident edges join structural components. Nearby fragments compete for
an independently recognized host; they never become hosts through proximity.
All measurements use eye-relative lengths and surface/boundary quadrature.
"""
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree
from . import region_core as C


def quantile(values, weights, fraction):
    values = np.asarray(values)
    order = np.argsort(values, kind='stable')
    weights = np.asarray(weights)[order]
    cumulative = np.cumsum(weights)
    if not len(values):
        return float('inf')
    return float(np.interp(fraction * cumulative[-1], cumulative, values[order]))


def curve_coordinates(points, ring, upper=True):
    """Closest 3D point and local signed height, without an X-only projection."""
    points = np.asarray(points, dtype=float)
    curve = np.array([ring.sample(u, upper) for u in np.linspace(0, 1, 97)])
    edges = np.diff(curve, axis=0)
    length2 = np.maximum(np.sum(edges * edges, axis=1), 1e-30)
    relative = points[:, None] - curve[:-1]
    t = np.clip(np.einsum('nki,ki->nk', relative, edges) / length2, 0, 1)
    offsets = relative - t[:, :, None] * edges
    distances = np.sum(offsets * offsets, axis=2)
    closest = np.argmin(distances, axis=1)
    rows = np.arange(len(points))
    offset = offsets[rows, closest]
    tangent = edges[closest]
    normal = np.column_stack((-tangent[:, 2], np.zeros(len(points)), tangent[:, 0]))
    normal *= np.where(normal[:, 2] < 0, -1., 1.)[:, None]
    normal /= np.maximum(np.linalg.norm(normal, axis=1)[:, None], 1e-30)
    return dict(distance=np.sqrt(distances[rows, closest]),
                u=(closest + t[rows, closest]) / (len(curve) - 1),
                height=np.sum(offset * normal, axis=1), depth=offset[:, 1])


def _surface(points, faces):
    ids = sorted({i for face in faces for i in face})
    index = {i: j for j, i in enumerate(ids)}
    return BVHTree.FromPolygons([Vector(points[i]) for i in ids],
                               [[index[i] for i in face] for face in faces])


def _distances(tree, samples):
    return np.array([tree.find_nearest(Vector(p))[3] for p in samples], dtype=float)


def _geometry(points, faces, spacing):
    triangles = [(face[0], face[j], face[j + 1])
                 for face in faces for j in range(1, len(face) - 1)]
    cloud = points[np.asarray(triangles, dtype=int)]
    areas = np.linalg.norm(np.cross(cloud[:, 1] - cloud[:, 0],
                                   cloud[:, 2] - cloud[:, 0]), axis=1) * .5
    valid = areas > 1e-30
    cloud, areas = cloud[valid], areas[valid]
    if not len(areas):
        return None
    # Three equal-weight samples per triangle; adding tessellation does not
    # give a densely meshed end more votes than the rest of the surface.
    samples = np.concatenate([cloud.mean(axis=1) * .5 + cloud[:, j] * .5
                              for j in range(3)])
    weights = np.tile(areas / 3, 3)
    from collections import Counter
    counts = Counter(tuple(sorted((a, b))) for face in faces
                     for a, b in zip(face, face[1:] + face[:1]))
    boundary = [edge for edge, count in counts.items() if count == 1]
    if not boundary:
        boundary = list(counts)
    edge_points = points[np.asarray(boundary, dtype=int)]
    lengths = np.linalg.norm(edge_points[:, 1] - edge_points[:, 0], axis=1)
    boundary_samples, boundary_weights = [], []
    for edge, length in zip(edge_points, lengths):
        count = max(1, int(np.ceil(length / spacing)))
        parameters = (np.arange(count) + .5) / count
        boundary_samples.extend(edge[0] + parameters[:, None] * (edge[1] - edge[0]))
        boundary_weights.extend([length / count] * count)
    boundary_samples = np.asarray(boundary_samples)
    boundary_weights = np.asarray(boundary_weights)
    return samples, weights, boundary_samples, boundary_weights, float(areas.sum())


def _physical_components(points, faces, tolerance):
    """Virtual seam closure requires a shared edge, never a single touch."""
    ids = sorted({i for face in faces for i in face})
    tree = KDTree(len(ids))
    for i in ids:
        tree.insert(Vector(points[i]), i)
    tree.balance()
    aliases = {}
    for i in ids:
        aliases[i] = min(j for _, j, _ in tree.find_range(Vector(points[i]), tolerance))
    physical = [[aliases[i] for i in face] for face in faces]
    return [[faces[f] for f in component['faces']]
            for component in C.topology(physical)[1]]


def resolve(points, polygons, parts, plane, rings, surface_support=True):
    """Return legacy parts plus explicit component ownership and diagnostics.

    parts > 0 identifies candidate accessories, not a trusted brow/lash label.
    Output parts are 1 (eyelid accessory), 2 (brow/crease), or 0 (unresolved).
    """
    coordinates = np.asarray(points, dtype=float)
    result = list(parts)
    records, work, warnings = [], [], []
    for side, ring in rings.items():
        width = max(float(ring.frame.width), 1e-12)
        height = max(float(ring.frame.height), width * .02)
        faces = [list(face) for face in polygons if all(parts[i] > 0 for i in face)
                 and (1 if coordinates[list(face), 0].mean() >= plane else -1) == side]
        for component in _physical_components(coordinates, faces, width * 1e-6):
            geometry = _geometry(coordinates, component, width * .006)
            if geometry is None:
                ids=sorted({i for face in component for i in face})
                for i in ids:result[i]=0
                records.append(dict(id=len(records),side=int(side),vertices=ids,
                    kind='UNRESOLVED',parent=None,confidence=0.,reason='zero_area_surface',
                    is_band=False,span=0.,eye_width=width,root_distance=None))
                continue
            samples, weights, boundary, boundary_weights, area = geometry
            upper = curve_coordinates(samples, ring, True)
            lower = curve_coordinates(samples, ring, False)
            edge_upper = curve_coordinates(boundary, ring, True)
            edge_lower = curve_coordinates(boundary, ring, False)
            ids = sorted({i for face in component for i in face})
            parameter = curve_coordinates(coordinates[ids], ring, True)['u']
            span = float(np.ptp(parameter))
            offset = quantile(upper['height'], weights, .5)
            depth = quantile(abs(upper['depth']), weights, .5)
            rim_distance = np.minimum(edge_upper['distance'], edge_lower['distance'])
            contact = quantile(rim_distance, boundary_weights, .15)
            near = rim_distance <= width * .045
            support = float(boundary_weights[near].sum()) / width
            broad = span >= .24
            kind, reason = 'UNRESOLVED', 'no_supported_host'
            if broad and contact < width * .045 and support >= .10:
                kind, reason = 'LASH', 'eyelid_boundary_support'
            # A brow follows the forehead, whose depth differs from the eye
            # socket. Allow that gradual change with height; eyelid roots
            # still require the strict 3D contact test above/below.
            elif broad and depth < width * .20 + max(offset, 0.) * .25:
                if offset > max(height * .32, width * .085):
                    kind, reason = 'BROW', 'independent_upper_strip'
                elif offset > width * .018 and offset <= max(height * .40, width * .12):
                    kind, reason = 'CREASE', 'parallel_upper_strip'
            record = dict(id=len(records), side=int(side), vertices=ids,
                          kind=kind, parent=None, confidence=.9 if kind != 'UNRESOLVED' else 0.,
                          reason=reason, is_band=kind == 'LASH', span=span,
                          eye_width=width, root_distance=None,
                          upper_offset=offset / width, depth_offset=depth / width,
                          boundary_support=support, boundary_distance=contact / width)
            records.append(record)
            work.append(dict(record=record, faces=component, tree=_surface(coordinates, component),
                             samples=samples, weights=weights, boundary=boundary,
                             boundary_weights=boundary_weights, upper=upper, lower=lower,
                             offset=offset, depth=depth, area=area, ring=ring,
                             lower_host=bool(kind=='LASH' and quantile(edge_lower['distance'],boundary_weights,.15)
                                             <quantile(edge_upper['distance'],boundary_weights,.15))))

    if surface_support:
        for item in work:
            record=item['record']
            if record['kind']!='UNRESOLVED' or record['span']<.24:continue
            width=record['eye_width'];ring=item['ring']
            # A wide card can contain the eyelid contour in its interior.
            # Testing only its boundary rejects the actual covering surface.
            # Require sustained 3D support, using arc length rather than votes
            # from tessellation or proximity to one isolated corner.
            if item['offset']>max(float(ring.frame.height)*.10,width*.018):continue
            support=[]
            for upper in (False,True):
                curve=np.array([ring.sample(t,upper) for t in np.linspace(0,1,97)])
                samples=(curve[:-1]+curve[1:])*.5
                lengths=np.linalg.norm(np.diff(curve,axis=0),axis=1)
                distance=_distances(item['tree'],samples)
                support.append(float(lengths[distance<=width*.045].sum())/width)
            if max(support)>=.24:
                record.update(kind='LASH',reason='eyelid_surface_support',is_band=True,confidence=.9,
                              surface_support=support,surface_upper=bool(support[1]>=support[0]))

    # Hosts are fixed before assigning fragments. A chain of weak neighbors
    # cannot merge a brow and an eyelash band into one semantic component.
    hosts = [item for item in work if item['record']['kind'] != 'UNRESOLVED']
    for item in work:
        record = item['record']
        if record['kind'] != 'UNRESOLVED':
            continue
        width = record['eye_width']
        candidates = []
        for host in hosts:
            parent = host['record']
            if parent['side'] != record['side']:
                continue
            # Root attachment needs a supported interval, not one close tip.
            distances = _distances(host['tree'], item['boundary'])
            close = distances <= width * .018
            contact_length = float(item['boundary_weights'][close].sum())
            if contact_length < width * .0015:
                continue
            root_distance = quantile(distances, item['boundary_weights'], .08)
            if root_distance > width * .025:
                continue
            candidates.append((root_distance / width, host, contact_length))
        candidates.sort(key=lambda row: (row[0], -row[2], row[1]['record']['id']))
        if candidates:
            score, host, contact_length = candidates[0]
            rival = next((r for r in candidates[1:]
                          if r[1]['record']['kind'] != host['record']['kind']), None)
            if rival is None or rival[0] - score > .006:
                parent = host['record']
                record.update(kind=parent['kind'], parent=parent['id'], confidence=.85,
                              reason='root_surface_attachment', root_distance=score * width)
            else:
                record.update(reason='competing_hosts', confidence=.25)
        else:
            if surface_support and record['span']<.24:
                lower_roots=[]
                for host in hosts:
                    if host['record']['side']!=record['side'] or not host['lower_host']:continue
                    distances=_distances(host['tree'],item['boundary'])
                    close=distances<width*.08
                    length=float(item['boundary_weights'][close].sum())
                    distance=quantile(distances,item['boundary_weights'],.08)
                    if length>=width*.0015 and distance<width*.08:
                        lower_roots.append((distance,host))
                if lower_roots:
                    distance,host=min(lower_roots,key=lambda row:row[0])
                    record.update(kind='LASH',parent=host['record']['id'],confidence=.75,
                                  reason='lower_surface_attachment',surface_upper=False,root_distance=distance)
                    continue
            # Some models have individually planted eyelashes with no band.
            # Require a real, localized root interval on the eyelid in 3D.
            edge = curve_coordinates(item['boundary'], item['ring'], True)
            close = edge['distance'] < width * .025
            contact_length = float(item['boundary_weights'][close].sum())
            if (record['span'] < .36 and contact_length >= width * .0015
                    and quantile(edge['distance'], item['boundary_weights'], .08) < width * .025):
                record.update(kind='LASH', confidence=.7, reason='direct_eyelid_root',
                              root_distance=quantile(edge['distance'], item['boundary_weights'], .08))
            elif surface_support and record['span']<.24:
                lower_edge=curve_coordinates(item['boundary'],item['ring'],False)
                upper_edge=curve_coordinates(item['boundary'],item['ring'],True)
                close=lower_edge['distance']<width*.06
                length=float(item['boundary_weights'][close].sum())
                below=quantile(item['lower']['height'],item['weights'],.5)<0
                if (below and length>=width*.0015
                        and quantile(lower_edge['distance'],item['boundary_weights'],.08)<width*.06
                        and quantile(lower_edge['distance'],item['boundary_weights'],.5)
                            <quantile(upper_edge['distance'],item['boundary_weights'],.5)):
                    record.update(kind='LASH',confidence=.7,reason='direct_lower_eyelid_root',
                                  surface_upper=False,root_distance=quantile(lower_edge['distance'],item['boundary_weights'],.08))

    for item in work:
        record = item['record']
        part = 1 if record['kind'] == 'LASH' else 2 if record['kind'] in ('BROW', 'CREASE') else 0
        for i in record['vertices']:
            result[i] = part
    unresolved = [r for r in records if r['kind'] == 'UNRESOLVED']
    if unresolved:
        warnings.append('有 %d 块眉眼附属面片无法确认所属部件，已跳过自动单根睫毛绑定' % len(unresolved))
    return dict(parts=result, components=records, warnings=warnings)


def unit_attachment(points, unit, ownership, polygons, ring):
    """Validate a detected strand and locate roots on its actual host surface."""
    ids = set(unit['vertices'])
    record = next((r for r in ownership['components']
                   if r['kind'] == 'LASH' and ids <= set(r['vertices'])), None)
    if record is None:
        return None
    if unit.get('connected'):
        return dict(unit, attachment='shared_band', parent_component=record['id'])
    if record['is_band'] and ids == set(record['vertices']):
        return None
    coordinates = np.asarray(points, dtype=float)
    vertices = sorted(ids)
    parent = record.get('parent')
    if parent is not None or record['is_band']:
        host = ownership['components'][parent] if parent is not None else record
        host_ids = set(host['vertices'])
        faces = [list(f) for f in polygons if all(i in host_ids for i in f)
                 and not all(i in ids for i in f)]
        if not faces:
            return None
        distances = _distances(_surface(coordinates, faces), coordinates[vertices])
    else:
        distances = curve_coordinates(coordinates[vertices], ring, True)['distance']
    tolerance = record['eye_width'] * .025
    roots = [i for i, d in zip(vertices, distances) if d <= tolerance]
    if not roots or len(roots) == len(vertices):
        return None
    root = coordinates[roots].mean(axis=0)
    reach = np.linalg.norm(coordinates[vertices] - root, axis=1)
    tips = [i for i, d in zip(vertices, reach) if d >= float(reach.max()) * .85]
    tip = coordinates[tips].mean(axis=0)
    u = curve_coordinates([root], ring, True)['u'][0]
    return dict(unit, roots=roots, tips=tips, points=[root.tolist(), tip.tolist()],
                u=float(u), attachment='shared_band_seam' if record['is_band'] else record['reason'],
                parent_component=record['id'] if record['is_band'] else parent,
                confidence=record['confidence'])
