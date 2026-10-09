import importlib.util
from pathlib import Path
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'MCP/CST'), str(ROOT/'MCP/CST-Lab/src')]
from cst_workspace import WorkspaceRouter
from cst_lab.jobs import JobStore
from cst_lab.function_contract import RunRequest


def test_topic_selection_and_ambiguity(tmp_path):
    a, b = tmp_path/'a', tmp_path/'b'
    (a/'projects/one').mkdir(parents=True)
    (b/'projects/two').mkdir(parents=True)
    router = WorkspaceRouter([a, b])
    assert router.topic_root('two') == b
    assert router.attempt_root('projects/one/designs/d/attempts/a/attempt.json') == a
    with pytest.raises(ValueError): router.topic_root('../one')
    with pytest.raises(ValueError): router.attempt_root('projects/one/designs/../attempts/a/attempt.json')
    with pytest.raises(ValueError, match='not found'): router.topic_root('missing')
    (b/'projects/one').mkdir()
    with pytest.raises(ValueError, match='ambiguous'): router.topic_root('one')


def test_reference_routes_exact_job_and_artifacts(tmp_path):
    import shutil
    from cst_lab.contracts.attempt import write_attempt
    from cst_lab.paths import LabPaths
    roots = [tmp_path/'a', tmp_path/'b']
    for root in roots: root.mkdir()
    request = RunRequest.parse(dict(topic='two', design='d', attempt='a', request_id='one',
                                   operation='audit', fidelity='offline', why='routing test'))
    store = JobStore(roots[1])
    shutil.copytree(ROOT/'brain/schemas', roots[1]/'brain/schemas')
    write_attempt(request.attempt_path(roots[1]), dict(schema_version=1,
        topic_id='two', design_id='d', attempt_id='a', topology_hash='0'*64,
        baseline_parameters={}, approved_ranges={}, max_iterations=5), LabPaths.resolve(roots[1]))
    ref = store.submit(request)
    router = WorkspaceRouter(roots)
    assert router.ref_root(ref) == roots[1]
    assert router.ref_root(ref.replace('job://', 'artifact://')+'/manifest.json') == roots[1]
    with pytest.raises(ValueError): router.ref_root(ref+'/extra')
    with pytest.raises(ValueError, match='not found'): router.ref_root(ref[:-32]+'0'*32)
    shutil.copytree(roots[1]/'cst_runs', roots[0]/'cst_runs')
    with pytest.raises(ValueError, match='ambiguous'): router.ref_root(ref)


def test_generated_config_preserves_unrelated_settings_and_relocates(tmp_path,monkeypatch):
    spec = importlib.util.spec_from_file_location('configure_cst', ROOT/'scripts/cst-research.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    previous = 'model = "test"\n[mcp_servers.other]\ncommand="other"\n[mcp_servers.cst-function]\ncommand="old"\n'
    workspace=tmp_path/'topic';path=workspace/'.codex/config.toml';path.parent.mkdir(parents=True);path.write_text(previous)
    monkeypatch.setattr(module,'ROOT',tmp_path/'platform with spaces')
    _,content=module.config_payloads(workspace,['codex'])[0];generated=content.decode('utf-8')
    config = tomllib.loads(generated)
    assert config['model'] == 'test'
    assert set(config['mcp_servers']) == {'other', 'cst-function', 'cst-brain'}
    assert str(tmp_path/'platform with spaces'/'MCP/CST/agent_mcp_server.py') in config['mcp_servers']['cst-function']['args']
    path.write_text(generated)
    assert module.config_payloads(workspace,['codex'])[0][1]==content
