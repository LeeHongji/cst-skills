from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'scripts/validation'),str(ROOT/'MCP/CST-CAD/src')]
from cst_cad import drc,ir
from prepare_visual_cases import primitives,multilayer,failed_spacing

def test_geometric_visual_controls_include_a_real_negative_case():
    for doc in (primitives(),multilayer(),failed_spacing()):
        assert ir.validate(doc)==[]
    assert drc.run(primitives())['status']=='pass'
    assert drc.run(multilayer())['status']=='pass'
    failure=drc.run(failed_spacing())
    assert failure['status']=='fail'
    assert failure['checks'][0]['measured']==pytest.approx(.1)
    assert failure['checks'][0]['violations']
