"""Pure native readback verification shared by execution and durable evidence."""
import math


def leaves(value, prefix=''):
    if isinstance(value, dict) and value:
        for key, item in sorted(value.items()):
            yield from leaves(item, f'{prefix}.{key}' if prefix else key)
    else:
        yield prefix, value


def port_requirements(ports):
    """Checks supported by port getters, additional to full port coverage.

    A center does not prove aperture size, orientation or attachment. The
    original ports coverage gate remains required until those are verified.
    """
    yield 'ports.count', len(ports)
    if not ports:
        return
    numbers = sorted(p['number'] for p in ports)
    yield 'ports.consecutive', numbers == list(range(1, len(ports)+1))
    for port in sorted(ports, key=lambda p: p['number']):
        prefix = f'ports.{port["number"]}.'
        yield prefix+'kind', port['kind']
        yield prefix+'label', port.get('label') or port['name']
        yield prefix+'modes', port.get('modes', 1)
        axis, side = port['orientation'][0], port['orientation'][1:]
        for coordinate in 'xyz':
            box = port['extent']
            center = (box[coordinate+'0'] + box[coordinate+'1']) / 2
            if coordinate == axis:
                center = box[coordinate+('0' if side == 'min' else '1')]
            yield prefix+'center.'+coordinate, center


def verify_readback(document, observation, setup, actual, *, scope='core'):
    """Verify the declared readback scope without hiding unsupported fields.

    Bboxes verify the planar primitive envelope, not general B-rep equivalence.
    Metadata and inactive adaptation limits are recorded as such, never getters.
    Core execution requires native model/parameter identity, solver/frequency,
    units, boundaries, mesh density, monitor absence and port inventory/centers.
    Unavailable detailed settings remain deferred; ANY observed mismatch blocks.
    The full scope is retained for later exhaustive setting-readback acceptance.
    """
    if scope not in ('core', 'full'):
        raise ValueError('unknown native readback scope')
    from cst_cad.verify import compare, normalize_observation
    entities = observation.get('entities', [])
    names = [(e.get('component', ''), e.get('name', '')) for e in entities]
    if len(set(names)) != len(names):
        raise ValueError('duplicate observed entity names')
    for entity in entities:
        box = entity.get('bounding_box', {})
        if set(box) != {'x0', 'x1', 'y0', 'y1', 'z0', 'z1'} or any(
            type(v) not in (int, float) or not math.isfinite(v) for v in box.values()
        ):
            raise ValueError('complete finite native bounding boxes are required')
    parameters = observation.get('parameters', {})
    if set(parameters) != {p['name'] for p in document['parameters']} or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in parameters.values()
    ):
        raise ValueError('native parameter inventory is incomplete or nonfinite')
    geometry = compare(document, normalize_observation(observation), tolerance=1e-7)
    if geometry['status'] != 'match' or any(e['status'] != 'match' for e in geometry['entities']):
        raise ValueError('native geometry/parameter readback differs from prepared IR')
    rows = []
    for name, expected in [*leaves(setup), *port_requirements(setup['ports'])]:
        if name in ('schema_version', 'version', 'fidelity'):
            rows.append(dict(field=name, status='metadata', expected=expected))
            continue
        if name.startswith('convergence.') and name != 'convergence.adaptive_mesh' and not setup['convergence']['adaptive_mesh']:
            rows.append(dict(field=name, status='inactive', expected=expected))
            continue
        # TD does not use the adaptation-frequency center.
        if name == 'frequency.center' and setup['solver'] == 'time_domain':
            rows.append(dict(field=name, status='inactive', expected=expected))
            continue
        observed = actual.get(name, {})
        found = observed.get('value')
        equal = found == expected and type(found) is type(expected)
        if type(expected) in (int, float) and type(found) in (int, float):
            equal = math.isfinite(found) and math.isclose(found, expected, rel_tol=1e-9, abs_tol=1e-10)
        rows.append(dict(field=name, expected=expected, observed=observed,
                         status='match' if observed.get('method') and equal else
                         'mismatch' if 'value' in observed else 'unavailable'))
    core_fields = {'solver', 'frequency.min', 'frequency.max', 'monitors',
                   'mesh.steps_per_wavelength_near', 'mesh.cells_per_max_cell_near'}
    core_fields.update(name for name, _ in port_requirements(setup['ports']))
    core_fields.update(name for name, _ in leaves(setup) if name.startswith('units.') or
                       name in {f'boundaries.{face}' for face in ('xmin','xmax','ymin','ymax','zmin','zmax')} or
                       name.startswith('boundaries.symmetry.'))
    missing, deferred = [], []
    for row in rows:
        row['required'] = scope == 'full' or row['field'] in core_fields
        if row['status'] == 'mismatch' or row['status'] == 'unavailable' and row['required']:
            missing.append(row['field'])
        elif row['status'] == 'unavailable':
            deferred.append(row['field'])
    return dict(schema_version=2, scope=scope, geometry=geometry, settings=rows,
                status='verified' if not missing else 'incomplete', unresolved=missing,
                full_settings_status='incomplete' if missing or deferred else 'verified',
                deferred=deferred)
