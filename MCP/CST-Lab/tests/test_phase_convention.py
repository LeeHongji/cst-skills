from pathlib import Path
import pytest
from cst_lab.contracts.design import parse_gates
from cst_lab.contracts.gates import evaluate_gates
from cst_lab.contracts.touchstone import Touchstone


def gate(**changes):
    value=dict(id='phase',metric='phase_deviation_deg',main=[2,1],reference=[4,3],
               target=90,anchor_ghz=3,band_ghz=[2.9,3.1],comparator='<',threshold=2,mode='pointwise')
    value.update(changes)
    return value


def test_90_degree_direction_is_explicit_not_hidden_by_branch_unwrap():
    data=Touchstone(Path('synthetic.s4p'),4,(2.9e9,2.95e9,3e9,3.05e9,3.1e9),
                    {(2,1):(-1j,)*5,(4,3):(1+0j,)*5})
    direct=evaluate_gates(parse_gates({'acceptance':[gate(phase_convention='reference-minus-main')]}),data)
    legacy=evaluate_gates(parse_gates({'acceptance':[gate()]}),data)
    assert direct.status=='pass' and direct.gates[0].measured==pytest.approx(0)
    assert legacy.status=='fail' and legacy.gates[0].measured==pytest.approx(180)


@pytest.mark.parametrize('metric',['s2_1_deg','amplitude_imbalance_db'])
def test_ignored_convention_is_refused(metric):
    with pytest.raises(ValueError):
        parse_gates({'acceptance':[gate(metric=metric,phase_convention='reference-minus-main')]})
