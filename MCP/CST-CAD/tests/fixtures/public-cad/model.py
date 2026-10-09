"""Synthetic CAD regression fixture; no paper or solver-performance claim."""
from cst_cad.dsl import ModelBuilder


def build(overrides=None):
    m = ModelBuilder('public-cad-fixture', title='Synthetic CAD regression fixture',
                     source={'kind': 'internal', 'reference': 'Public CAD test specification'},
                     overrides=overrides)
    m.units(length='mm', frequency='GHz')
    evidence = 'Synthetic test specification; not measured or paper-derived'
    h = m.param('sub_h', 1.0, provenance='assumption', source=evidence)
    t = m.param('cu_t', .035, provenance='assumption', source=evidence)
    width = m.param('trace_w', 1.0, provenance='synthesized', source=evidence)
    xmax = m.param('board_xmax', 30.0, provenance='synthesized', source=evidence)
    gap = m.param('coupling_gap', .5, provenance='synthesized', source=evidence,
                  tunable=True, minimum=.25, maximum=1.0)
    top = m.param('top_z', h + t, provenance='synthesized', source=evidence)
    m.material('TestDielectric', epsilon=3.2, mu=1.0, tan_delta=.002)
    m.material('PEC', kind='pec')
    m.layer('ground_plane', -t, 0, 'PEC', role='ground')
    m.layer('substrate', 0, h, 'TestDielectric', role='substrate')
    m.layer('signal', h, top, 'PEC', role='signal')
    m.net('BOARD', 'substrate', net_class='reference').box(0, -8, xmax, 8)
    m.net('GROUND', 'ground_plane', net_class='reference').box(0, -8, xmax, 8)
    m.net('SOURCE_FEED', 'signal').rect(0, -width / 2, 6, width)
    m.net('LOAD_FEED', 'signal').rect(24, -width / 2, 6, width)
    resonator = m.net('RESONATOR_1', 'signal')
    resonator.rect(8, 1, width, 4, solid_id='leg')
    resonator.rect(8, 4, 8, width, solid_id='arm')
    second = m.net('RESONATOR_2', 'signal')
    second.rect(20 + gap, -5, width, 4, solid_id='leg')
    second.rect(14 + gap, -5, 7, width, solid_id='arm')
    m.port('P1', 1, 'SOURCE_FEED', 'xmin', 0, -2, -t, 0, 2, 3*h,
           reference_net='GROUND')
    m.port('P2', 2, 'LOAD_FEED', 'xmax', xmax, -2, -t, xmax, 2, 3*h,
           reference_net='GROUND')
    m.boundaries(zmin='electric', zmax='expanded open')
    m.mesh(kind='tetrahedral', steps_per_wavelength_near=10)
    m.rule('width', 'min_width', 'layer:signal', min_width=.25)
    m.rule('spacing', 'min_spacing', 'layer:signal', min_spacing=.2)
    m.rule('shorts', 'no_cross_net_short', 'layer:signal')
    m.rule('contained', 'board_containment', 'layer:signal', reference_net='BOARD')
    m.rule('ports', 'port_attachment', 'port:*', tolerance=1e-6)
    for name in ['SOURCE_FEED', 'LOAD_FEED', 'RESONATOR_1', 'RESONATOR_2']:
        m.rule('connected_' + name.lower(), 'net_connectivity', 'net:' + name, max_components=1)
    m.simulation(solver='frequency_domain', frequency_min=1, frequency_max=5, frequency_center=3,
                 convergence={'adaptive_mesh': True, 'max_passes': 4})
    return m.build()
