import json
import os
import signal
from pathlib import Path
import subprocess
import sys
import time

import pytest

from cst_lab.contracts.attempt import write_attempt
from cst_lab.contracts.iterations import iteration_line, read_iterations
from cst_lab.function_contract import RunRequest, RequestError, result
from cst_lab.jobs import JobStore, JobError, JobBusy
from cst_lab.paths import LabPaths

ROOT = Path(__file__).resolve().parents[3]
PATHS = LabPaths.resolve(ROOT)
WORKER = Path(__file__).with_name('job_process.py')


def request(key='request-1', **changes):
    data = dict(topic='test-topic', design='test-design', attempt='a01', request_id=key,
                why='Exercise job protocol without CST', operation='audit', fidelity='offline')
    data.update(changes)
    return RunRequest.parse(data)


@pytest.fixture
def store(tmp_path):
    path = request().attempt_path(tmp_path)
    write_attempt(path, dict(schema_version=1, topic_id='test-topic', design_id='test-design',
        attempt_id='a01', topology_hash='a'*64, baseline_parameters={}, approved_ranges={}, max_iterations=8), PATHS)
    return JobStore(tmp_path, paths=PATHS)


def child(store, mode, argument):
    env = dict(os.environ, PYTHONPATH=str(ROOT/'MCP/CST-Lab/src'))
    return subprocess.Popen([sys.executable, str(WORKER), mode, str(store.root), str(ROOT), argument],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, text=True, env=env)


def completed(process, expected=0):
    out, err = process.communicate(timeout=20)
    assert process.returncode == expected, (out, err)
    return out


def fact(job, **changes):
    data = iteration_line(iter_number=job['iteration'], parent=job['request']['parent'], status='completed',
        audited=False, provenance='native', duration_s=.2, execution_kind='offline', cache_hit=False,
        acceptance={'status':'fail', 'gates':[]})
    data.update(changes)
    return data


def test_aliases_are_explicit_and_have_identical_idempotent_content():
    old = request(parameters={'length':[1, 2]}, setup={'mesh':{'cells':8}})
    new = request(param_delta={'length':[1, 2]}, setup_delta={'mesh':{'cells':8}})
    assert old.sha256 == new.sha256
    assert old.converted_aliases == ('parameters->param_delta', 'setup->setup_delta')
    assert old.document['param_delta']['length'] == [1.,2.]


@pytest.mark.parametrize('change', [
    {'parameters':{}, 'param_delta':{}}, {'param_delta':{'x':True}}, {'param_delta':{'x':'1'}},
    {'param_delta':{'x':float('nan')}}, {'setup_delta':{'mesh':float('inf')}},
    {'request_id':''}, {'why':''}, {'parent':True}, {'attempt':'../a'}, {'cst_version':'fake'},
    {'approved_by':'agent'}, {'operation':'simulate', 'fidelity':'offline'},
    {'operation':'analyze', 'inputs':[]}, {'operation':'compare', 'inputs':['one']},
    {'operation':'analyze', 'inputs':['one'], 'param_delta':{'x':1}},
])
def test_request_refuses_ambiguous_or_untrusted_fields(change):
    with pytest.raises(RequestError):
        request(**change)


def test_result_does_not_confuse_acceptance_with_execution():
    r = result(status='completed', job='example', job_status='completed', fidelity='screen',
               acceptance={'status':'fail','gates':[]}, cache_hit=True)
    assert r['status']=='completed' and r['acceptance']['status']=='fail' and r['fidelity']=='screen'
    assert 'duration_s' in r and 'duration' not in r
    with pytest.raises(RequestError):
        result(status='completed', job='x', job_status='running', fidelity='screen')


def test_idempotent_retry_and_changed_content_refusal(store):
    ref = store.submit(request())
    assert store.submit(request()) == ref
    with pytest.raises(JobError, match='different content'):
        store.submit(request(why='different'))
    assert not (request().attempt_path(store.root).parent/'iterations.jsonl').exists()


def test_process_budget_reservations_and_order(store):
    path = request().attempt_path(store.root)
    doc = json.loads(path.read_text()); doc['max_iterations']=3; write_attempt(path,doc,PATHS)
    processes = [child(store,'submit',json.dumps(request(f'req-{i}').document)) for i in range(8)]
    outputs = [p.communicate(timeout=20)[0] for p in processes]
    accepted = [json.loads(out)['ref'] for p,out in zip(processes,outputs) if p.returncode==0]
    assert len(accepted)==3
    assert sorted(store.get(ref)['iteration'] for ref in accepted)==[0,1,2]
    assert all(p.returncode in (0,2) for p in processes)
    ordered = sorted(accepted,key=lambda r:store.get(r)['iteration'])
    with pytest.raises(JobBusy):
        with store.claim(ordered[-1]): pass
    for ref in ordered:
        completed(child(store,'finish',ref))
    rows = read_iterations(path.parent/'iterations.jsonl', PATHS)
    assert [r['iter'] for r in rows]==[0,1,2]
    assert all(r['status']=='completed' and r['acceptance']['status']=='fail' for r in rows)


def test_process_same_request_exactly_one_reservation(store):
    processes = [child(store,'submit',json.dumps(request().document)) for _ in range(6)]
    refs = [json.loads(completed(p))['ref'] for p in processes]
    assert len(set(refs))==1
    assert store.get(refs[0])['iteration']==0


def test_actual_terminated_worker_recovery_preserves_prefix(store):
    first = store.submit(request('first'))
    with store.claim(first) as session:
        session.finish(fact(store.get(first)))
    history = request().attempt_path(store.root).parent/'iterations.jsonl'
    prefix = history.read_bytes()
    ref = store.submit(request(parent=0))
    process = child(store,'hold',ref)
    try:
        deadline=time.monotonic()+10
        while not (store.root/'claimed').exists():
            assert process.poll() is None
            assert time.monotonic()<deadline
            time.sleep(.02)
        assert process.poll() is None
        assert store.recover(ref)=='live'
        assert history.read_bytes()==prefix
        # Windows venv python.exe can be a launcher; terminate the PID reported
        # by our actual worker, never infer worker death from the launcher alone.
        worker_pid=int((store.root/'claimed').read_text())
        os.kill(worker_pid, signal.SIGTERM)
        process.wait(timeout=10)
        assert store.recover(ref)=='failed'
        after=history.read_bytes()
        assert after.startswith(prefix)
        assert store.recover(ref)=='failed'
        assert history.read_bytes()==after
        rows=read_iterations(history,PATHS)
        assert len(rows)==2 and rows[-1]['parent']==0 and rows[-1]['status']=='failed'
        assert rows[-1]['audited'] is False
    finally:
        if process.poll() is None:
            process.kill(); process.wait(timeout=10)


@pytest.mark.parametrize('window', ['partial', 'appended'])
def test_abrupt_death_in_finalization_appends_only_missing_bytes(store,window):
    ref=store.submit(request())
    completed(child(store,window,ref),expected=73)
    assert store.get(ref)['state']=='finalizing'
    history=request().attempt_path(store.root).parent/'iterations.jsonl'
    before=history.read_bytes()
    assert store.recover(ref)=='completed'
    after=history.read_bytes()
    assert after.startswith(before)
    assert len(read_iterations(history,PATHS))==1
    assert store.recover(ref)=='completed'
    assert history.read_bytes()==after
    assert store.response(ref)['acceptance']['status']=='fail'


def test_recovery_refuses_unrelated_tail_corruption(store):
    ref=store.submit(request())
    completed(child(store,'partial',ref),expected=73)
    history=request().attempt_path(store.root).parent/'iterations.jsonl'
    with history.open('ab') as f: f.write(b'UNRELATED')
    before=history.read_bytes()
    with pytest.raises(JobError,match='tail differs'):
        store.recover(ref)
    assert history.read_bytes()==before


def test_existing_iteration_writer_is_also_process_safe(store):
    processes=[child(store,'append','unused') for _ in range(6)]
    outputs=[p.communicate(timeout=20) for p in processes]
    assert [p.returncode for p in processes].count(0)==1,outputs
    assert len(read_iterations(store.root/'race.jsonl',PATHS))==1


def test_failed_scope_exit_and_parent_refusal(store):
    with pytest.raises(JobError,match='parent'):
        store.submit(request(parent=99))
    ref=store.submit(request())
    with store.claim(ref): pass
    assert store.get(ref)['state']=='failed'
    assert store.submit(request())==ref
    with pytest.raises(JobError,match='conflicts'):
        second=store.submit(request('second'))
        with store.claim(second) as session:
            session.finish(fact(store.get(second),fidelity='confirm'))
    assert store.get(second)['state']=='failed'


def test_progress_and_timeout_do_not_become_iteration_running_rows(store):
    ref=store.submit(request())
    with pytest.raises(TimeoutError,match='synthetic execution timeout'):
        with store.claim(ref) as session:
            session.progress('routing', {'route':'offline'})
            assert store.get(ref)['progress']['phase']=='routing'
            assert store.response(ref)['status']=='running'
            assert not (request().attempt_path(store.root).parent/'iterations.jsonl').exists()
            raise TimeoutError('synthetic execution timeout')
    assert store.get(ref)['state']=='failed'
    assert not list((store.root/'projects').rglob('*.lock'))
