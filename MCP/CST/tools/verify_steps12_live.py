#!/usr/bin/env python3
"""Explicit opt-in, bounded Step 1/2 live validation with a neutral low-pass.

Run with MCP/CST/.venv/Scripts/python.exe. All model/solve operations are
supervised workers pinned to a newly launched test instance. This is not the
Step 4 production facade and does not reopen legacy MCP write tools.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[3]
for part in ("MCP/CST", "MCP/CST-CAD/src", "MCP/CST-Lab/src"):
    sys.path.insert(0, str(ROOT / part))
import verify_guardian_live as live
from verification_lowpass import build
from cst_cad import ir, drc
from cst_guardian import run_guarded, cst_instance_pids, enumerate_dialogs
from cst_lab import LabOperations, LabPaths
from cst_lab.contracts import read_touchstone, parse_gates, evaluate_gates, curve
from cst_trace import trace_function


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def gates():
    return [dict(id="passband", metric="s2_1_db", band_ghz=[.1, 1.5], comparator=">", threshold=-1., mode="pointwise", min_samples=10),
            dict(id="stopband", metric="s2_1_db", band_ghz=[3.6, 4.2], comparator="<", threshold=-10., mode="pointwise", min_samples=10)]


def l0(output):
    """Exercise a clean fixture and an explicit unintended overlapping net."""
    doc = build()
    dirty = copy.deepcopy(doc)
    other = copy.deepcopy(next(n for n in dirty['nets'] if n['name'] == 'FILTER'))
    other['name'] = 'UNINTENDED_CONDUCTOR'
    dirty['nets'].append(other)
    clean = drc.run(doc); failed = drc.run(dirty)
    write(output/'geometry-ir.json', doc)
    write(output/'drc-clean.json', clean)
    write(output/'drc-overlap.json', failed)
    return {'scenario': 'L0-neutral-DRC', 'status': 'pass' if clean['status']=='pass' and failed['status']=='fail' else 'fail',
            'clean': clean['summary'], 'overlap': failed['summary'], 'cst_launched': False}


def worker(output, pid, command, *args, expected="completed", timeout=180):
    outcome = run_guarded(live._worker_argv(pid, command, *map(str,args)), log_dir=output,
                          timeout_s=timeout, cst_pid_roots=[pid], require_clean_start=False)
    result = live._worker_json(output, stage="after")
    write(output/'outcome.json', outcome.to_json())
    if outcome.outcome != expected:
        raise RuntimeError(f"{command}: expected {expected}, got {outcome.outcome}; {live._worker_records(output)[-2:]}")
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--source', type=Path, required=True, help='Registered reference, never modified')
    ap.add_argument('--solve-timeout', type=float, default=300)
    args=ap.parse_args()
    source=args.source.resolve()
    source.relative_to(ROOT/'cst_runs')
    original_hash=digest(source)
    ops=LabOperations(LabPaths.resolve(ROOT))
    project=ops.register_project(str(source)); revision=ops.snapshot_model(project['project_id'])
    spec={'schema_version':2,'title':'Step 1 2 Guardian neutral lowpass revalidation',
          'project_revision_id':revision['revision_id'],
          'hypothesis':'Task-scoped Guardian survives timeout and dialog recovery and repeatedly builds/solves a lowpass with durable curves.',
          'parameters':[{'name':'l3','kind':'continuous','low':13.,'high':15.,'unit':'mm'}],
          'objectives':[{'name':'passband_s21_min_db','signal':'S2,1','representation':'db20','unit':'dB','domain':'frequency',
                         'frequency_window':{'start':.1,'stop':1.5,'unit':'GHz'},'aggregation':'min','direction':'maximize',
                         'missing_data_policy':'invalid','quality_gates':['frequency-window-covered','finite-complex-data']}],
          'constraints':[], 'fidelity_plan':{'stages':[{'name':'baseline'},{'name':'parameter-update'},{'name':'independent-repeat'}]},
          'evaluation_budget':{'max_trials':3,'max_solver_minutes':15},
          'approval_policy':{'before_solver':False,'before_source_change':True,'authorization':'User explicitly requested simple-model full Step 1/2 live revalidation; no Step 3 geometry approval claimed.'},
          'stop_conditions':[{'kind':'three-valid-solves-or-first-unexpected-failure'}], 'tags':['platform-validation','guardian','step1','step2']}
    experiment=ops.create_experiment(spec); eid=experiment['experiment_id']; output=Path(experiment['run_path'])
    ops.validate_experiment(eid); ops.transition_experiment(eid,'queued'); ops.transition_experiment(eid,'running')
    os.environ['CST_TRACE_ROOT']=str(output/'native-traces')
    os.environ['CST_TRACE_ID']='steps12-live'
    os.environ['CST_AGENT_NAME']='codex-step12-verification'
    report={'experiment_id':eid,'project_id':project['project_id'],'revision_id':revision['revision_id'],
            'run_directory':str(output),'source':str(source),'source_sha256_before':original_hash,
            'scenarios':[], 'trials':[], 'task_pids':[], 'scope':'Step 1/2 verification, not production facade',
            'dialog_fixture_limit':'L3/L4 use CST-owned VBA MsgBox fixtures; actual stale results are separately exercised by post-solve parameter updates in quiet mode.'}
    print('RUN_DIRECTORY='+str(output),flush=True)
    write(output/'verification-report.json',report)
    lock=False; current_trial=None
    def record(item):
        report['scenarios'].append(item);write(output/'verification-report.json',report)
        print(json.dumps(item,ensure_ascii=False),flush=True)
        if item.get('status') != 'pass': raise RuntimeError('Scenario failed: '+item['scenario'])
    try:
        ops.acquire_project_lock(project['project_id'],eid,ttl_minutes=60);lock=True
        record(l0(output/'l0'))
        with live.dedicated_instance() as pid:
            report['task_pids'].append(pid)
            record(live.scenario_l1(output,pid));record(live.scenario_l2(output,pid))
            for seq,value in enumerate((13.9312,14.5)):
                current_trial=ops.create_trial(eid,{'l3':value});tid=current_trial['trial_id'];td=Path(current_trial['run_path'])
                ops.transition_trial(tid,'queued');ops.transition_trial(tid,'running')
                doc=build({'l3':value});write(td/'geometry-ir.json',doc);write(td/'drc-report.json',drc.run(doc))
                model=td/'working'/'lowpass.cst'
                if seq==0:
                    built=worker(td/'build',pid,'build-ir','--ir',td/'geometry-ir.json','--project',model)
                    record({'scenario':'fresh-IR-build','status':'pass','blocks':built['blocks'],'shape_count':built['shape_count'],'parameter_count':len(built['parameters'])})
                else:
                    live.copy_project(Path(report['trials'][0]['project']),model.parent)
                    record(live.scenario_l3(output,model,pid));record(live.scenario_l4(output,model,pid))
                    worker(td/'recovery-probe',pid,'probe')
                    record(live.scenario_guards(output,model,pid))
                    record(live.scenario_iterate(output,model,pid,'l3',['14.0','14.25','14.5','14.25','14.0','14.25','14.5']))
                solved=trace_function(live.scenario_solve)(td,model,pid,args.solve_timeout)
                record({**solved,'scenario':f'solve-{seq}'})
                result=finish_trial(ops,tid,td,model,value)
                report['trials'].append(result);current_trial=None
                record({'scenario':f'curve-gates-{seq}','status':result['acceptance']['status']})
            left=[d.to_json() for p in cst_instance_pids(pid) for d in enumerate_dialogs(p)]
            record({'scenario':'no-leftover-dialogs','status':'pass' if not left else 'fail','dialogs':left})
        # Rebuild independently at the final parameters, in a new instance.
        with live.dedicated_instance() as pid:
            report['task_pids'].append(pid)
            current_trial=ops.create_trial(eid,{'l3':14.5});tid=current_trial['trial_id'];td=Path(current_trial['run_path'])
            ops.transition_trial(tid,'queued');ops.transition_trial(tid,'running')
            doc=build({'l3':14.5});write(td/'geometry-ir.json',doc);write(td/'drc-report.json',drc.run(doc))
            model=td/'working'/'lowpass.cst'
            worker(td/'build',pid,'build-ir','--ir',td/'geometry-ir.json','--project',model)
            record({**trace_function(live.scenario_solve)(td,model,pid,args.solve_timeout),'scenario':'independent-rebuild-solve'})
            result=finish_trial(ops,tid,td,model,14.5);report['trials'].append(result);current_trial=None
            record({'scenario':'independent-curve-gates','status':result['acceptance']['status']})
        a=read_touchstone(report['trials'][1]['touchstone']);b=read_touchstone(report['trials'][2]['touchstone'])
        same_grid=a.frequencies_hz==b.frequencies_hz
        delta=max(abs(x-y) for key in a.s for x,y in zip(a.s[key],b.s[key])) if same_grid else None
        record({'scenario':'independent-reproducibility','status':'pass' if delta is not None and delta<.01 else 'fail', 'max_complex_s_delta':delta,'limit':.01,'same_frequency_grid':same_grid})
        report['all_passed']=True
        ops.transition_experiment(eid,'validating')
        # Final completed status waits for promotion/reopen validation outside this driver.
        report['completion_pending']='Durable topic promotion and cache-free reopen/IR comparison'
    except Exception as exc:
        report['all_passed']=False;report['error']=repr(exc)
        if current_trial:
            ops.transition_trial(current_trial['trial_id'],'failed',error={'type':type(exc).__name__,'message':str(exc)})
        ops.transition_experiment(eid,'failed',reason=str(exc))
        print('FAILED '+repr(exc),flush=True)
    finally:
        report['source_sha256_after']=digest(source)
        report['source_unchanged']=report['source_sha256_after']==original_hash
        if lock: ops.release_project_lock(project['project_id'],eid)
        report['project_lock_released']=True
        write(output/'verification-report.json',report)
        write(ROOT/'tmp/steps12-latest-run.json',{'run_directory':str(output),'experiment_id':eid})
    return 0 if report.get('all_passed') and report['source_unchanged'] else 1


def finish_trial(ops,tid,td,model,value):
    path=next((td/'task-solve').glob('s-parameters.s*p'))
    data=read_touchstone(path)
    acceptance=evaluate_gates(parse_gates({'acceptance':gates()}),data).to_json()
    write(td/'acceptance.json',acceptance)
    if acceptance['status'] != 'pass':
        raise RuntimeError(f"Low-pass curve acceptance failed: {acceptance}")
    signal=curve(data,2,1,'db')
    metric=min(v for f,v in zip(data.frequencies_hz,signal) if .1e9<=f<=1.5e9)
    ops.transition_trial(tid,'validating')
    ops.transition_trial(tid,'completed',objectives={'passband_s21_min_db':metric},constraints={})
    return {'trial_id':tid,'project':str(model),'touchstone':str(path),'l3':value,
            'acceptance':acceptance,'passband_s21_min_db':metric,'samples':len(data)}


if __name__=='__main__':
    raise SystemExit(main())
