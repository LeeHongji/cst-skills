"""T2: quarter-wave open shunt stub, explicitly not a floating half-wave line.

The tunable length is measured from the through-line centre to the open tip.
The finite-width tee is solved in CST; its loading is not hidden in the analytic
estimate. Board and ports stay fixed when the stub length changes.
"""
from cst_cad.dsl import ModelBuilder


def build(overrides=None):
    m=ModelBuilder(model_id='t2-open-shunt-stub',
        title='四分之一波长开路支节 / Quarter-wave open shunt stub',
        source=dict(kind='internal',reference='T2 independent canonical transmission-line fixture; see model-notes.md'),
        overrides=overrides)
    m.units(length='mm',frequency='GHz')
    values=dict(sub_h=.813,cu_t=.035,line_w=1.8332,stub_w=1.8332,
        line_l=40.,board_ymin=-6.,board_ymax=24.,port_half_width=5.,stub_l=15.)
    p={k:m.param(k,v,unit='mm',provenance='assumption',source='Explicit internal T2 fixture dimensions',
        tunable=k=='stub_l',minimum=13.5 if k=='stub_l' else None,
        maximum=17. if k=='stub_l' else None,
        description='从直通线中心 y=0 到开路端 / Through-line centre to open tip' if k=='stub_l' else None)
        for k,v in values.items()}
    h,t=p['sub_h'],p['cu_t']
    m.material('RO4003C',epsilon=3.55,mu=1.,tan_delta=.0027)
    m.material('TraceCopper',kind='lossy_metal',conductivity=5.8e7)
    m.layer('substrate',-h,0.,'RO4003C',role='substrate')
    m.layer('ground',-h-t,-h,'TraceCopper',role='ground')
    m.layer('top',0.,t,'TraceCopper',role='signal')
    m.net('BOARD','substrate',net_class='reference').box(0.,p['board_ymin'],p['line_l'],p['board_ymax'])
    m.net('GROUND','ground',net_class='reference').box(0.,p['board_ymin'],p['line_l'],p['board_ymax'])
    signal=m.net('SIGNAL','top')
    signal.box(0.,-p['line_w']/2,p['line_l'],p['line_w']/2,solid_id='through')
    signal.box((p['line_l']-p['stub_w'])/2,-p['line_w']/2,
        (p['line_l']+p['stub_w'])/2,p['stub_l'],solid_id='open_stub',
        note='Open tip at y=stub_l. Connected tee at y=0; no ground via or shorting wall.')
    for name,number,side,x in [('P1',1,'xmin',0.),('P2',2,'xmax',p['line_l'])]:
        m.port(name,number,'SIGNAL',side,x,-p['port_half_width'],-h-t,
            x,p['port_half_width'],4*h,reference_net='GROUND')
    m.boundaries(xmin='electric',xmax='electric',ymin='expanded open',ymax='expanded open',
        zmin='electric',zmax='expanded open')
    m.mesh(kind='hexahedral',steps_per_wavelength_near=20,cells_per_max_cell_near=15)
    m.rule('width','min_width','layer:top',min_width=.3)
    m.rule('connected','net_connectivity','net:SIGNAL',max_components=1)
    m.rule('containment','board_containment','layer:top',reference_net='BOARD')
    m.rule('ports','port_attachment','port:*',tolerance=1e-6)
    m.simulation(solver='time_domain',frequency_min=.5,frequency_max=4.5,
        settings={'accuracy_db':'-40','norming_impedance':50})
    return m.build()
