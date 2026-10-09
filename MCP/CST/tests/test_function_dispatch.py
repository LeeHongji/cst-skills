from dataclasses import dataclass
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[3]
for source in ('MCP/CST','MCP/CST-Lab/src','MCP/CST-CAD/src'):
    sys.path.insert(0,str(ROOT/source))
import cst_function_executor as executor
from cst_lab.function_evidence import validate_revision
from cst_lab.atomic import atomic_json


@dataclass
class Prepared:
    document:dict


@pytest.mark.parametrize('outcome',['blocked','timeout','raise','executed'])
def test_guardian_dispatch_is_scoped_and_diagnostics_do_not_expose_credentials(tmp_path,monkeypatch,outcome):
    import cst_guardian.supervisor
    ref='job://'+'a'*64+'/'+'b'*32
    session=SimpleNamespace(store=SimpleNamespace(root=tmp_path),ref=ref,token='owner-secret',progress=lambda *args:None)
    calls=[]
    def guarded(argv,**options):
        calls.append((argv,options))
        assert options['scope_worker_descendants'] is True and options['timeout_s']>0
        assert '--dispatch-sha256' in argv and 'owner-secret' not in argv
        if outcome=='raise':raise OSError('synthetic process creation failure')
        directory=executor.execution_directory(tmp_path,ref)
        (directory/'execution').mkdir(parents=True)
        atomic_json(directory/'execution/execution-receipt.json',dict(
            status='executed' if outcome=='executed' else 'blocked',error='readback unavailable',solver_started=False))
        return SimpleNamespace(to_json=lambda:dict(ok=outcome!='timeout',outcome='timeout' if outcome=='timeout' else 'completed'))
    monkeypatch.setattr(cst_guardian.supervisor,'run_guarded',guarded)
    result=executor.execute(session,Prepared({}))
    assert len(calls)==1
    assert result['status']==('blocked' if outcome=='blocked' else 'failed')
    assert validate_revision(result['stage'],result['manifest_sha256'])['kind']=='execution-diagnostic'
    assert not (result['stage']/'dispatch.json').exists()
    assert all('owner-secret' not in p.read_text() for p in result['stage'].iterdir())
    if outcome=='raise':
        diagnostic=json.loads((result['stage']/'diagnostic.json').read_text())
        assert diagnostic['solver_started'] is None and diagnostic['solver_start_observation']=='unknown'


@pytest.mark.parametrize('ref',['job://../../outside','job://a/b','artifact://'+'a'*64+'/'+'b'*32])
def test_dispatch_rejects_unsafe_job_paths(tmp_path,ref):
    with pytest.raises(ValueError):executor.execution_directory(tmp_path,ref)


def test_duplicate_dispatch_refuses_to_replace_partial_working_copy(tmp_path,monkeypatch):
    ref='job://'+'a'*64+'/'+'b'*32
    directory=executor.execution_directory(tmp_path,ref);directory.mkdir(parents=True)
    sentinel=directory/'dispatch.json';sentinel.write_text('existing bytes')
    session=SimpleNamespace(store=SimpleNamespace(root=tmp_path),ref=ref,token='secret')
    with pytest.raises(FileExistsError):executor.execute(session,Prepared({}))
    assert sentinel.read_text()=='existing bytes'


@pytest.mark.skipif(sys.platform!='win32',reason='native Windows process containment')
def test_actual_guardian_child_can_verify_its_outer_kernel_job(tmp_path):
    from cst_guardian.windows_job import WindowsJobProcess
    code='from cst_guardian.windows_job import require_current_job_containment; print(require_current_job_containment())'
    with (tmp_path/'stdout.txt').open('wb') as out,(tmp_path/'stderr.txt').open('wb') as err:
        process=WindowsJobProcess([sys.executable,'-c',code],stdout=out,stderr=err,cwd=ROOT/'MCP/CST')
        try:
            assert process.wait(timeout=15)==0
        finally:process.close()
    assert "'kill_on_job_close': True" in (tmp_path/'stdout.txt').read_text()
