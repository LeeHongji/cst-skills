from copy import deepcopy
import pytest
from cst_lab.function_setup import resolve_setup,merge_delta


def model():
    return dict(units={'frequency':'GHz','length':'mm'},parameters=[{'name':'f0','value':3.}],
        simulation={'solver':'frequency_domain','frequency':{'min':'f0*.8','max':'f0*1.2','center':'f0'}})


def test_fd_defaults_are_complete_resolved_and_fidelity_specific():
    screen=resolve_setup(model(),{},'screen');confirm=resolve_setup(model(),{},'confirm')
    assert screen['frequency']['min']==pytest.approx(2.4)
    assert screen['frequency']['max']==pytest.approx(3.6)
    assert screen['frequency']['center']==3
    assert screen['convergence']['max_delta_s']==.02
    assert confirm['convergence']['max_delta_s']==.01
    assert screen['settings']['accuracy_rom']==.0001
    assert confirm['settings']['accuracy_rom']==.00001
    assert set(screen['settings'])=={'method','method_variant','order_tet','order_srf','norming_impedance',
        'accuracy_tet','accuracy_rom','result_samples','store_all_results'}


@pytest.mark.parametrize('overrides',[
    {'solver':'eigenmode'}, {'solver':'integral'},
    {'mesh':{'kind':'hexahedral'}}, {'mesh':{'local_refinements':[]}},
    {'mesh':{'steps_per_wavelength_near':True}},
    {'settings':{'result_samples':801.0}}, {'settings':{'accuracy_tet':'not-a-number'}},
    {'settings':{'accuracy_rom':float('nan')}}, {'settings':{'store_all_results':'False'}},
    {'settings':{'method_variant':'invented method'}},
    {'frequency':{'center':20}}, {'frequency':{'max':'missing_parameter'}},
    {'convergence':{'min_passes':8,'max_passes':3}}, {'convergence':{'checks':True}},
    {'convergence':{'adaptive_mesh':'True'}}, {'convergence':{'max_delta_s':0}},
    {'monitors':[{'name':'field','kind':'Efield'}]}, {'model_intent_id':'fake'},
])
def test_unsupported_and_ambiguous_effective_settings_refused(overrides):
    with pytest.raises((ValueError,KeyError)): resolve_setup(model(),overrides,'screen')


def test_numeric_cst_text_normalizes_to_same_configuration():
    a=resolve_setup(model(),{'settings':{'accuracy_rom':'1e-4'}},'screen')
    b=resolve_setup(model(),{'settings':{'accuracy_rom':.0001}},'screen')
    assert a==b


def test_delta_is_not_an_arbitrary_request_replacement():
    with pytest.raises(ValueError,match='old-value'): merge_delta({}, {'mesh':{'steps_per_wavelength_near':[True,20]}},{'mesh':{'steps_per_wavelength_near':1}})
    original={'settings':{'accuracy_rom':.001}}
    changed=merge_delta(original,{'settings':{'accuracy_rom':[.001,.0001]}},original)
    assert original['settings']['accuracy_rom']==.001
    assert changed['settings']['accuracy_rom']==.0001
