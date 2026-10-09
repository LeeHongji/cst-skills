"""Opt-in Step 1 WR-90 end-to-end verification; invoke with --source seed.cst.

The source is prepared by the guarded IR builder and is never changed here.
Three bounded trials exercise incremental length change and a fresh rebuild.
"""
from __future__ import annotations
import argparse
import cmath
import csv
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/p) for p in ('MCP/CST', 'MCP/CST-CAD/src', 'MCP/CST-Lab/src')]
from cst_lab import LabOperations, LabPaths
from cst_lab.contracts import read_touchstone
from cst_cad import drc, verify
from cst_guardian import cst_instance_pids, enumerate_dialogs
from verify_steps12_live import worker, write, digest
from verification_waveguide import build, transmission, cutoff_ghz
import verify_guardian_live as live


LIMITS = dict(reflection_db=-30., transmission_abs_db=.1, phase_error_deg=2.,
              reciprocity_complex=.002, power_balance_error=.02,
              differential_phase_error_deg=2., repeat_complex=.001)


def evaluate(path, length, output):
    data = read_touchstone(path)
    f = data.frequencies_hz
    if len(f)<500 or f[0]>8.2e9+1000 or f[-1]<12.4e9-1000:
        raise ValueError('Incomplete frequency coverage or insufficient samples')
    rows=[]
    for i,freq in enumerate(f):
        s11,s21,s12,s22 = [data.s[k][i] for k in [(1,1),(2,1),(1,2),(2,2)]]
        ref=transmission(freq,length)
        phase=math.degrees(cmath.phase(s21/ref))
        rows.append([freq/1e9,20*math.log10(max(abs(s11),1e-15)),20*math.log10(max(abs(s22),1e-15)),
                     20*math.log10(max(abs(s21),1e-15)),phase,s21.real,s21.imag,ref.real,ref.imag])
    metrics=dict(reflection_max_db=max(max(row[1],row[2]) for row in rows),
                 transmission_max_abs_db=max(abs(row[3]) for row in rows),
                 phase_max_error_deg=max(abs(row[4]) for row in rows),
                 reciprocity_max_complex=max(abs(a-b) for a,b in zip(data.s[(2,1)],data.s[(1,2)])),
                 power_balance_max_error=max(abs(abs(a)**2+abs(b)**2-1) for a,b in zip(data.s[(1,1)],data.s[(2,1)])))
    pairs=[('reflection_max_db','reflection_db'),('transmission_max_abs_db','transmission_abs_db'),
           ('phase_max_error_deg','phase_error_deg'),('reciprocity_max_complex','reciprocity_complex'),
           ('power_balance_max_error','power_balance_error')]
    gates=[dict(id=k,status='pass' if metrics[k]<LIMITS[lim] else 'fail',value=metrics[k],limit=LIMITS[lim]) for k,lim in pairs]
    result=dict(status='pass' if all(g['status']=='pass' for g in gates) else 'fail',gates=gates,metrics=metrics,samples=len(f),
                band_ghz=[f[0]/1e9,f[-1]/1e9],length_mm=length,normalization='native modal ports; no 50-ohm renormalization')
    write(output/'acceptance.json',result)
    with (output/'theory-comparison.csv').open('w',encoding='utf-8',newline='') as fp:
        writer=csv.writer(fp);writer.writerow(['frequency_ghz','s11_db','s22_db','s21_db','phase_error_deg','s21_real','s21_imag','theory_real','theory_imag']);writer.writerows(rows)
    return result


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--source',type=Path,required=True);args=ap.parse_args()
    source=args.source.resolve();source.relative_to(ROOT/'cst_runs');source_hash=digest(source)
    ops=LabOperations(LabPaths.resolve(ROOT));p=ops.register_project(str(source));rev=ops.snapshot_model(p['project_id'])
    objective=dict(name='phase_max_error_deg',signal='S2,1 / analytic TE10 transmission',representation='phase_deg',unit='deg',domain='frequency',frequency_window=dict(start=8.2,stop=12.4,unit='GHz'),aggregation='custom',direction='minimize',missing_data_policy='invalid',quality_gates=['1001-frequency-samples','finite-data','two-port-energy-convergence','all-point-phase-error'])
    spec=dict(schema_version=2,title='Step 1 classic WR90 TE10 end-to-end verification',project_revision_id=rev['revision_id'],
        hypothesis='Uniform PEC WR90 has near-zero modal reflection and exp(-j beta L) transmission; length change and independent rebuild agree with analytic dispersion.',
        parameters=[dict(name='length',kind='continuous',low=40.,high=60.,unit='mm')],objectives=[objective],constraints=[],
        fidelity_plan=dict(stages=[dict(name=x) for x in ['40mm-baseline','60mm-incremental','60mm-independent']]),
        evaluation_budget=dict(max_trials=3,max_solver_minutes=15),approval_policy=dict(before_solver=False,before_source_change=True,authorization='User explicitly requested classic-model CST end-to-end Step 1 verification; not a Step 3 geometry approval.'),stop_conditions=[dict(kind='all-three-trials-and-theory-pass',limits=LIMITS)],tags=['step1','wr90','te10','platform-validation'])
    experiment=ops.create_experiment(spec);eid=experiment['experiment_id'];out=Path(experiment['run_path'])
    ops.validate_experiment(eid);ops.transition_experiment(eid,'queued');ops.transition_experiment(eid,'running')
    os.environ['CST_TRACE_ROOT']=str(out/'native-traces');os.environ['CST_TRACE_ID']='wr90-live'
    report=dict(experiment_id=eid,project_id=p['project_id'],revision_id=rev['revision_id'],source=str(source),source_sha256=source_hash,
                run_directory=str(out),limits=LIMITS,cutoff_ghz=dict(TE10=cutoff_ghz(),TE20=cutoff_ghz(2,0),TE01=cutoff_ghz(0,1)),scenarios=[],trials=[],task_pids=[])
    write(ROOT/'tmp/wr90-latest.json',dict(run_directory=str(out),experiment_id=eid));print(str(out),flush=True)
    current=None;locked=False
    def record(item):
        report['scenarios'].append(item);write(out/'verification-report.json',report);print(json.dumps(item,ensure_ascii=False),flush=True)
        if item['status']!='pass':raise RuntimeError('Scenario failed: '+item['scenario'])
    try:
        ops.acquire_project_lock(p['project_id'],eid,ttl_minutes=30);locked=True
        for independent in [False,True]:
            with live.dedicated_instance() as pid:
                report['task_pids'].append(pid)
                if not independent:
                    record(live.scenario_l1(out,pid));record(live.scenario_l2(out,pid))
                for seq in ([2] if independent else [0,1]):
                    length=40. if seq==0 else 60.;current=ops.create_trial(eid,dict(length=length));tid=current['trial_id'];td=Path(current['run_path'])
                    ops.transition_trial(tid,'queued');ops.transition_trial(tid,'running')
                    doc=build(dict(length=length));write(td/'geometry-ir.json',doc);write(td/'drc-report.json',drc.run(doc));model=td/'working/wr90.cst'
                    if seq==1:
                        live.copy_project(Path(report['trials'][0]['project']),model.parent)
                        record(live.scenario_l3(out,model,pid));record(live.scenario_l4(out,model,pid));worker(td/'recovery',pid,'probe')
                        record(live.scenario_iterate(td,model,pid,'length',['45','50','55','60']))
                    else:
                        result=worker(td/'build',pid,'build-ir','--ir',td/'geometry-ir.json','--project',model)
                        record(dict(scenario=f'build-{seq}',status='pass',blocks=result['blocks'],shapes=result['shape_count'],parameters=result['parameters']))
                    worker(td/'observe',pid,'inspect',model,'--observation',td/'observation.json')
                    comparison=verify.compare(doc,verify.read_observation(td/'observation.json'));write(td/'ir-comparison.json',comparison)
                    record(dict(scenario=f'geometry-readback-{seq}',status='pass' if comparison['status']=='match' else 'fail',summary=comparison['summary']))
                    solved=worker(td/'solve',pid,'solve','--project',model,'--export',td/'solve/response.s2p','--native-port-impedance',timeout=300)
                    reciprocal = any('calculation due to two-port reciprocity' in m.lower() for m in solved['messages_tail'])
                    count = solved.get('energy_criterion_count',0)
                    sufficient = count==2 or (count==1 and reciprocal)
                    record(dict(scenario=f'solve-{seq}',status='pass' if solved.get('converged') and sufficient else 'fail',seconds=solved['solve_s'],energy_criterion_count=count,second_port_from_reciprocity=reciprocal))
                    curve=next((td/'solve').glob('*.s2p'));result=evaluate(curve,length,td)
                    record(dict(scenario=f'theory-{seq}',status=result['status'],metrics=result['metrics']))
                    ops.transition_trial(tid,'validating');ops.transition_trial(tid,'completed',objectives={'phase_max_error_deg':result['metrics']['phase_max_error_deg']},constraints={})
                    report['trials'].append(dict(trial_id=tid,project=str(model),touchstone=str(curve),length_mm=length,result=result,solve_seconds=solved['solve_s']));current=None
                dialogs=[d.to_json() for p in cst_instance_pids(pid) for d in enumerate_dialogs(p)]
                record(dict(scenario='instance-dialog-clean-'+str(pid),status='pass' if not dialogs else 'fail',dialogs=dialogs))
        a,b,c=[read_touchstone(t['touchstone']) for t in report['trials']]
        assert a.frequencies_hz==b.frequencies_hz==c.frequencies_hz
        delta=max(abs(x-y) for k in b.s for x,y in zip(b.s[k],c.s[k]))
        phase=max(abs(math.degrees(cmath.phase(y/x/transmission(f,20.)))) for f,x,y in zip(a.frequencies_hz,a.s[(2,1)],b.s[(2,1)]))
        record(dict(scenario='independent-repeat',status='pass' if delta<LIMITS['repeat_complex'] else 'fail',max_complex_delta=delta))
        record(dict(scenario='20mm-length-phase-difference',status='pass' if phase<LIMITS['differential_phase_error_deg'] else 'fail',max_error_deg=phase))
        report['all_passed']=True;report['completion_pending']='promotion and cache-free reopen';ops.transition_experiment(eid,'validating')
    except Exception as exc:
        report['all_passed']=False;report['error']=repr(exc)
        if current:ops.transition_trial(current['trial_id'],'failed',error=dict(type=type(exc).__name__,message=str(exc)))
        ops.transition_experiment(eid,'failed',reason=str(exc));print('FAILED '+repr(exc),flush=True)
    finally:
        report['source_unchanged']=digest(source)==source_hash
        if locked:ops.release_project_lock(p['project_id'],eid)
        report['lock_released']=True;write(out/'verification-report.json',report)
    return 0 if report.get('all_passed') and report['source_unchanged'] else 1


if __name__=='__main__':raise SystemExit(main())
