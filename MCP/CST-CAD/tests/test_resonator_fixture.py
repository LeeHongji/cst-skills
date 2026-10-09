import csv,math,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/p) for p in ('scripts/validation','MCP/CST/tools','MCP/CST-Lab/src','MCP/CST-CAD/src')]
from verification_resonator import build
from prepare_resonator import analytic
from verify_resonator_physics import notch,compare
from cst_cad import drc,ir
from cst_lab.function_model import verify_geometry_expressions


def test_length_delta_preserves_board_ports_topology_and_connected_open_tip():
    base=build();long=build({'stub_l':16.5})
    for doc in (base,long):
        verify_geometry_expressions(doc)
        assert drc.run(doc)['status']=='pass'
        signal=next(n for n in doc['nets'] if n['name']=='SIGNAL')
        through,stub=[s['box'] for s in signal['solids']]
        assert stub['y0']<0<through['y1']<stub['y1']
        assert through['x0']<stub['x0']<stub['x1']<through['x1']
        assert all(p['extent']['z1']>doc['stackup'][-1]['z1'] for p in doc['ports'])
    assert ir.topology_hash(base)==ir.topology_hash(long)
    assert base['ports']==long['ports']
    assert base['nets'][:2]==long['nets'][:2]
    with pytest.raises(ValueError):build({'stub_l':18})


def curve(path,center=2.9,count=401,reverse=False,nan=False):
    rows=[]
    for i in range(count):
        f=2.+2*i/(count-1);x=(f-center)/.1
        s=complex(x,.005)/complex(x,1.)
        rows.append((f,s.real,s.imag))
    if reverse:rows.reverse()
    if nan:rows[count//2]=(float('nan'),1.,0.)
    with path.open('w',newline='') as f:
        w=csv.writer(f);w.writerow(['frequency_ghz','s2_1_real','s2_1_imag']);w.writerows(rows)


def test_independent_notch_resolves_known_complex_response(tmp_path):
    path=tmp_path/'s.csv';curve(path)
    result=notch(path)
    assert result['frequency_ghz']==pytest.approx(2.9)
    assert result['depth_db']==pytest.approx(20*math.log10(.005))


@pytest.mark.parametrize('kwargs',[{'center':2.3},{'count':30},{'reverse':True},{'nan':True}])
def test_unresolved_or_invalid_notches_are_rejected(tmp_path,kwargs):
    path=tmp_path/'s.csv';curve(path,**kwargs)
    with pytest.raises(ValueError):notch(path)


def test_physics_trend_rejects_wrong_direction_and_half_wave_formula():
    oracle=dict(points=[analytic(v) for v in (15.,16.5)],max_relative_frequency_error=.1,max_relative_ratio_error=.05)
    measured=[dict(frequency_ghz=p['corrected_quarter_wave_ghz']) for p in oracle['points']]
    assert compare(measured,oracle)['status']=='passed'
    assert compare(list(reversed(measured)),oracle)['status']=='failed'
    assert compare([dict(frequency_ghz=p['frequency_ghz']*2) for p in measured],oracle)['status']=='failed'
