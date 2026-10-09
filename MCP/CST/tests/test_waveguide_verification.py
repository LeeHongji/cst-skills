"""Independent analytical and negative-data checks for WR-90 acceptance."""
import cmath
import math
from pathlib import Path
import sys
import importlib.util
import numpy as np
import pytest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'MCP/CST/tools'))
sys.path.insert(0,str(ROOT/'MCP/CST-CAD/src'))
from verification_waveguide import cutoff_ghz,transmission,build
from verify_waveguide_live import evaluate
from cst_cad import ir,drc,emit_vba


def test_wr90_cutoff_and_length_composition():
    assert cutoff_ghz()==pytest.approx(6.5571403762)
    assert cutoff_ghz(2,0)>12.4
    assert cutoff_ghz(0,1)>12.4
    assert transmission(10e9,60)==pytest.approx(transmission(10e9,40)*transmission(10e9,20))
    a,b=build(),build({'length':60.})
    assert ir.validate(a)==[] and ir.validate(b)==[]
    assert ir.topology_hash(a)==ir.topology_hash(b)
    assert drc.run(a)['checks'][0]['solids_evaluated']==1
    solver=next(x.code for x in emit_vba.build_blocks(a) if x.title=='solver')
    assert '.AutoNormImpedance "False"' in solver


@pytest.mark.parametrize('phase_offset,expected',[(0.,'pass'),(5.,'fail')])
def test_phase_gate_detects_wrong_electrical_length(tmp_path,phase_offset,expected):
    path=tmp_path/'analytic.s2p'
    lines=['# Hz S RI R 50']
    for i in range(1001):
        f=8.2e9+i*4.2e6;s=transmission(f,40)*cmath.exp(1j*math.radians(phase_offset))
        lines.append(f'{f} 0 0 {s.real} {s.imag} {s.real} {s.imag} 0 0')
    path.write_text('\n'.join(lines),encoding='utf-8')
    result=evaluate(path,40,tmp_path)
    assert result['status']==expected
    assert result['metrics']['phase_max_error_deg']==pytest.approx(phase_offset,abs=1e-10)


def test_truncated_curve_cannot_pass(tmp_path):
    path=tmp_path/'truncated.s2p';path.write_text('# GHz S RI R 50\n10 0 0 1 0 1 0 0 0\n',encoding='utf-8')
    with pytest.raises(ValueError,match='coverage'):
        evaluate(path,40,tmp_path)


def test_saved_result_plotting_allows_roundoff_but_rejects_missing_band():
    spec=importlib.util.spec_from_file_location('plot_cst_filter_response',ROOT/'scripts/validation/sample_window.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    f=np.asarray([8.2,10.,12.4],dtype=np.float32).astype(float)
    x,y=module.sample_window(f,np.asarray([-50.,-45.,-40.]),8.2,12.4)
    assert x[0]==8.2 and x[-1]==12.4
    assert max(y)==-40.
    with pytest.raises(ValueError,match='coverage'):
        module.sample_window(np.asarray([8.2,10.,12.39]),np.asarray([-50.,-45.,-40.]),8.2,12.4)
