"""Neutral, internally specified two-port fixture; no paper interpretation.

Dimensions follow the archived 2026-09-10 stepped-impedance smoke case.
This is a stability test, not a high-fidelity filter design acceptance.
"""
from cst_cad.dsl import ModelBuilder


def build(overrides=None):
    m = ModelBuilder(model_id="guardian-lowpass", title="Guardian low-pass verification",
        source={"kind": "internal", "reference": "20260914-step1-step2-verification"},
        overrides=overrides)
    m.units(length="mm", frequency="GHz")
    values = {"sub_h": .813, "cu_t": .035, "sub_w": 15., "lfeed": 5.,
              "w50": 1.8332, "wh": .3543, "wl": 5.1049,
              "l1": 6.8538, "l2": 8.2153, "l3": 13.9312, "l4": 8.2153, "l5": 6.8538}
    p = {k: m.param(k, v, provenance="synthesized", unit="mm", tunable=(k == "l3"),
                   source="Archived internal stepped-impedance smoke synthesis") for k, v in values.items()}
    h, t, w = p['sub_h'], p['cu_t'], p['sub_w']
    length = 2*p['lfeed'] + sum(p[f'l{i}'] for i in range(1, 6))
    m.material("RO4003C", epsilon=3.55, mu=1., tan_delta=.0027)
    m.material("TraceCopper", kind="lossy_metal", conductivity=5.8e7)
    m.layer("substrate", -h, 0., "RO4003C", role="substrate")
    m.layer("bottom", -h-t, -h, "TraceCopper", role="ground")
    m.layer("top", 0., t, "TraceCopper", role="signal")
    m.net("BOARD", "substrate", net_class="reference").box(0., -w/2, length, w)
    m.net("GROUND", "bottom", net_class="reference").box(0., -w/2, length, w)
    line = m.net("FILTER", "top")
    x = 0.
    segments = [(p['lfeed'], p['w50'])] + [(p[f'l{i}'], p['wh'] if i%2 else p['wl']) for i in range(1,6)] + [(p['lfeed'], p['w50'])]
    for i, (size, width) in enumerate(segments):
        line.rect(x, -width/2, size, width, solid_id=f"section_{i}")
        x = x + size
    # The waveguide aperture must contain air above the strip. Ending at the
    # copper surface produces a cutoff/near-zero-impedance mode, not microstrip.
    m.port("P1", 1, "FILTER", "xmin", 0., -w/2, -h-t, 0., w/2, 4*h, reference_net="GROUND")
    m.port("P2", 2, "FILTER", "xmax", length, -w/2, -h-t, length, w/2, 4*h, reference_net="GROUND")
    m.boundaries(xmin="electric", xmax="electric", ymin="electric", ymax="electric", zmin="electric", zmax="expanded open")
    m.mesh(kind="hexahedral", steps_per_wavelength_near=20)
    m.rule("width", "min_width", "layer:top", min_width=.28)
    m.rule("spacing", "min_spacing", "layer:top", min_spacing=.15)
    m.rule("connected", "net_connectivity", "net:FILTER", max_components=1)
    m.rule("no_short", "no_cross_net_short", "layer:top")
    m.rule("containment", "board_containment", "layer:top", reference_net="BOARD")
    m.rule("ports", "port_attachment", "port:*", tolerance=1e-6)
    m.simulation(solver="time_domain", frequency_min=0., frequency_max=7.2,
                 settings={"accuracy_db": "-40", "norming_impedance": 50})
    return m.build()
