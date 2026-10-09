"""Classic WR-90 TE10 straight: exact PEC/vacuum reference for Guardian tests.

Dimensions: Eravant Flange Standards, WR-90 (0.900 x 0.400 inch).
Dispersion: NTU J. F. Kiang rectangular-waveguide teaching demonstration.
The side walls are electric simulation boundaries; end planes are modal ports.
"""
import cmath
import math
from cst_cad.dsl import ModelBuilder

C0 = 299792458.0
WIDTH_MM = 22.86
HEIGHT_MM = 10.16


def build(overrides=None):
    m = ModelBuilder(model_id="wr90-te10", title="WR-90 TE10 classic waveguide",
                     source={"kind":"internal", "reference":"Eravant WR-90 dimensions; NTU TE10 dispersion"},
                     overrides=overrides)
    m.units(length="mm", frequency="GHz")
    a = m.param("a", WIDTH_MM, provenance="synthesized", unit="mm", source="WR-90 standard 0.900 inch")
    b = m.param("b", HEIGHT_MM, provenance="synthesized", unit="mm", source="WR-90 standard 0.400 inch")
    length = m.param("length", 40., provenance="synthesized", unit="mm", tunable=True,
                     source="Chosen validation length; independent of transverse WR-90 dimensions")
    m.material("GuideVacuum", epsilon=1., mu=1., tan_delta=0.)
    m.layer("volume", 0., length, "GuideVacuum", role="substrate")
    m.net("AIR", "volume", net_class="reference").box(0., 0., a, b)
    m.port("P1", 1, "AIR", "zmin", 0., 0., 0., a, b, 0., impedance=None)
    m.port("P2", 2, "AIR", "zmax", 0., 0., length, a, b, length, impedance=None)
    m.boundaries(xmin="electric", xmax="electric", ymin="electric", ymax="electric",
                 zmin="electric", zmax="electric")
    m.mesh(kind="hexahedral", steps_per_wavelength_near=30., cells_per_max_cell_near=30.)
    m.rule("clear_aperture", "min_width", "net:AIR", min_width=10.)
    m.simulation(solver="time_domain", frequency_min=8.2, frequency_max=12.4,
                 settings={"accuracy_db":"-50", "auto_norm_impedance":False})
    return m.build()


def cutoff_ghz(m=1, n=0):
    return .5*C0*math.sqrt((m/(WIDTH_MM*.001))**2+(n/(HEIGHT_MM*.001))**2)/1e9


def transmission(frequency_hz, length_mm):
    beta = math.sqrt((2*math.pi*frequency_hz/C0)**2-(math.pi/(WIDTH_MM*.001))**2)
    return cmath.exp(-1j*beta*length_mm*.001)
