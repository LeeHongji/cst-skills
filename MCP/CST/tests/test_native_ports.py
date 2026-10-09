"""Port inventory and corrupt/mismatched native observation regressions."""
from pathlib import Path
import re
from types import SimpleNamespace

import pytest

from cst_guardian.native_ports import read_ports
from test_function_execution import FakeBackend, prepared, execute


def model(count=2, consecutive=True, center='0\n1.5\n2.5\n'):
    calls = []

    def macro(code):
        calls.append(code)
        Path(re.search(r'Open "([^"]+)"', code)[1]).write_text(
            str(consecutive) if 'ArePortsSubsequentlyNamed' in code else center)

    return SimpleNamespace(
        Solver=SimpleNamespace(GetNumberOfPorts=lambda: count,
                               ArePortsSubsequentlyNamed=lambda: consecutive),
        Port=SimpleNamespace(GetType=lambda n: 'Waveguide',
                             GetLabel=lambda n: f'Actual-{n}', GetNumberOfModes=lambda n: 2),
        _execute_vba_code=macro), calls


def test_native_values_do_not_require_or_echo_requested_ports(tmp_path):
    native, calls = model()
    actual = read_ports(native, tmp_path)
    assert actual['ports.count']['value'] == 2
    assert actual['ports.2.label']['value'] == 'Actual-2'
    assert actual['ports.1.modes']['value'] == 2
    assert actual['ports.1.center.y']['value'] == 1.5
    assert len(calls) == 3
    assert 'ports' not in actual  # A center cannot verify a complete aperture.


@pytest.mark.parametrize('count', [-1, True, 2.5, 1025])
def test_invalid_native_count_cannot_trigger_port_queries(tmp_path, count):
    native, calls = model(count=count)
    actual = read_ports(native, tmp_path)
    assert 'error' in actual['ports.count'] and calls == []


def test_nonconsecutive_inventory_is_not_guessed(tmp_path):
    native, calls = model(consecutive=False)
    actual = read_ports(native, tmp_path)
    assert actual['ports.consecutive']['value'] is False
    assert not any(k.startswith('ports.1.') for k in actual)
    assert len(calls) == 1 and 'ArePortsSubsequentlyNamed' in calls[0]


def test_zero_count_proves_empty_port_inventory(tmp_path):
    native, calls = model(count=0)
    assert read_ports(native, tmp_path)['ports']['value'] == []
    assert calls == []


@pytest.mark.parametrize('center', ['0\n1\n', '0\nnan\n1\n', '0\n1\ninf\n'])
def test_truncated_or_nonfinite_centers_are_unavailable(tmp_path, center):
    native, calls = model(center=center)
    actual = read_ports(native, tmp_path)
    assert all('error' in actual[f'ports.1.center.{axis}'] for axis in 'xyz')


def test_stale_center_is_never_accepted(tmp_path):
    native, calls = model(count=1)
    (tmp_path/'port-1-center.txt').write_text('0\n1\n2\n')
    assert 'error' in read_ports(native, tmp_path)['ports.1.center.x']
    assert len(calls) == 1 and 'ArePortsSubsequentlyNamed' in calls[0]


@pytest.mark.parametrize('field,value', [
    ('ports.count', 3), ('ports.consecutive', False),
    ('ports.1.kind', 'discrete'), ('ports.1.label', 'wrong'),
    ('ports.1.modes', 2), ('ports.1.center.z', .1),
])
def test_real_port_mismatch_blocks_even_if_legacy_port_list_matches(tmp_path, prepared, field, value):
    backend = FakeBackend(prepared)
    backend.actual[field]['value'] = value
    result = execute(tmp_path, prepared, backend)
    assert result['status'] == 'blocked' and field in result['error']
    assert 'solve' not in backend.events


def test_partial_port_getters_prove_only_core_scope(tmp_path, prepared):
    from cst_guardian.function_execution import verify_readback
    backend = FakeBackend(prepared)
    backend.actual.pop('ports')
    report = verify_readback(prepared.document, backend.observation, prepared.execution['setup'], backend.actual)
    assert report['status'] == 'verified' and report['scope'] == 'core'
    assert report['full_settings_status'] == 'incomplete' and report['deferred'] == ['ports']
    full = verify_readback(prepared.document, backend.observation, prepared.execution['setup'], backend.actual, scope='full')
    assert full['status'] == 'incomplete' and 'ports' in full['unresolved']


def test_detailed_getter_absence_is_deferred_but_wrong_value_blocks(prepared):
    from cst_guardian.function_execution import verify_readback
    backend = FakeBackend(prepared)
    backend.actual.pop('settings.accuracy_db')
    report = verify_readback(prepared.document, backend.observation, prepared.execution['setup'], backend.actual)
    assert report['status'] == 'verified' and 'settings.accuracy_db' in report['deferred']
    backend.actual['settings.accuracy_db'] = dict(value=-1., method='test wrong actual value')
    report = verify_readback(prepared.document, backend.observation, prepared.execution['setup'], backend.actual)
    assert report['status'] == 'incomplete' and 'settings.accuracy_db' in report['unresolved']
