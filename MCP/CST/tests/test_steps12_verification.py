"""Offline regression coverage for the neutral live-test input and evidence."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'MCP/CST-CAD/src'))
from cst_cad import drc, ir, emit_vba


def fixture():
    spec=importlib.util.spec_from_file_location('verification_lowpass', ROOT/'MCP/CST/tools/verification_lowpass.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_lowpass_numeric_sweep_preserves_topology_and_changes_intent():
    model=fixture();base=model.build()
    assert ir.validate(base)==[]
    for length in (13.,13.9312,14.,14.25,14.5,15.):
        changed=model.build({'l3':length})
        assert ir.validate(changed)==[]
        assert drc.run(changed)['summary']['passed']==6
        assert ir.topology_hash(changed)==ir.topology_hash(base)
        if length!=13.9312: assert ir.model_intent_id(changed)!=ir.model_intent_id(base)


def test_hex_and_transient_use_cst_2026_command_dialect():
    blocks={b.title:b.code for b in emit_vba.build_blocks(fixture().build())}
    assert 'CellsPerWavelengthPolicy' not in blocks['mesh']
    assert '.SetMeshType "Hex"' in blocks['mesh']
    assert '.SteadyStateLimit "-40"' in blocks['solver']
    assert '.AccuracyLevel' not in blocks['solver']


def test_public_example_uses_verified_fixture_geometry():
    spec=importlib.util.spec_from_file_location('public_lowpass',ROOT/'examples/lowpass/model.py')
    model=importlib.util.module_from_spec(spec);spec.loader.exec_module(model)
    assert model.build()==fixture().build()


def test_geometry_observation_preserves_signed_bounds_and_parameters():
    from cst_cad.observation import parse
    from cst_cad.verify import normalize_observation
    observed = normalize_observation(parse(
        'SHAPE|c:ground|-1,25|60|0|15|-0,848|-0,813\nPARAM|l3|14,5\n'))
    assert observed['parameters'] == {'l3': 14.5}
    assert observed['entities'][0]['bounding_box']['z0'] == -0.848
    assert observed['entities'][0]['bounding_box']['x0'] == -1.25
