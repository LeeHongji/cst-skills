"""Analysis of exported source data: no model import, DRC, approval or CST import."""
from __future__ import annotations
import csv
from dataclasses import asdict
from pathlib import Path
import shutil
import re

from .atomic import atomic_json
from .contracts.design import load_design
from .contracts.gates import evaluate_gates, _values_for, _band_samples
from .contracts.touchstone import read_touchstone, curve
from .function_evidence import sha256
from .function_contract import digest

EVALUATOR_VERSION='gates-2-explicit-phase-order'


def analyze(request, attempt, stage, paths, progress):
    design_path=Path(attempt).parents[2]/'design.md'
    stage=Path(stage);stage.mkdir(parents=True,exist_ok=False)
    # Copy before evaluation, so exported metrics bind the reviewed design bytes.
    frozen_design=stage/'contract'/request['design']/'design.md'
    frozen_design.parent.mkdir(parents=True)
    shutil.copy2(design_path,frozen_design)
    header,gates,_=load_design(frozen_design,paths)
    if sha256(design_path)!=sha256(frozen_design):
        raise ValueError('design changed during snapshot')
    if header['topic_id']!=request['topic'] or header['design_id']!=request['design']:
        raise ValueError('design identity differs from request')
    entries=[]
    progress('analyzing',{'input_count':len(request['inputs'])})
    for index,reference in enumerate(request['inputs']):
        source=(paths.workspace_root/reference).resolve()
        if not any(source.is_relative_to(p.resolve()) for p in (paths.workspace_root/'projects',paths.runs_root)):
            raise ValueError('source must be an existing exported curve under projects or cst_runs')
        if not re.fullmatch(r'\.s[1-9][0-9]*p',source.suffix,re.I):
            raise ValueError('source evidence must be Touchstone SNP')
        target=stage/f'source-{index:02d}{source.suffix.lower()}'
        shutil.copy2(source,target)
        source_hash=sha256(source)
        if sha256(target)!=source_hash: raise ValueError('source changed while copying')
        data=read_touchstone(target)
        if header.get('ports') is not None and data.ports!=header['ports']:
            raise ValueError('exported port count differs from design contract')
        report=evaluate_gates(gates,data).to_json()
        columns={'frequency_ghz':[f/1e9 for f in data.frequencies_hz]}
        for pair,values in data.s.items():
            name=f's{pair[0]}_{pair[1]}'
            columns[name+'_real']=[v.real for v in values]
            columns[name+'_imag']=[v.imag for v in values]
            columns[name+'_db']=curve(data,*pair,'db')
            columns[name+'_deg']=curve(data,*pair,'deg')
        with (stage/f'curves-{index:02d}.csv').open('w',newline='',encoding='utf-8') as handle:
            writer=csv.writer(handle);writer.writerow(columns);writer.writerows(zip(*columns.values()))
        _export_gate_samples(stage/f'acceptance-samples-{index:02d}.csv',data,gates)
        _plot(stage/f'response-{index:02d}.png',data,gates)
        entries.append(dict(input=reference,source_sha256=source_hash,ports=data.ports,
            samples=len(data),acceptance=report,metrics={g['id']:g['measured'] for g in report['gates']}))
    analysis=dict(schema_version=1,operation=request['operation'],fidelity='offline',audited=False,
        evaluator_version=EVALUATOR_VERSION,design_sha256=sha256(frozen_design),
        gates_sha256=digest([asdict(g) for g in gates]),inputs=entries,
        claim='Source data analysis; no new solver execution or model validation')
    if request['operation']=='compare':
        baseline=entries[0]['metrics']
        baseline_acceptance=entries[0]['acceptance']
        baseline_states={g['id']:g['status'] for g in baseline_acceptance.get('gates',[])}
        analysis['comparison']=[dict(
            input=e['input'],
            metric_delta={k:None if v is None or baseline.get(k) is None else v-baseline[k] for k,v in e['metrics'].items()},
            acceptance_change={
                'from':baseline_acceptance.get('status'),
                'to':e['acceptance'].get('status'),
                'gate_status':{g['id']:{'from':baseline_states.get(g['id']),'to':g['status']} for g in e['acceptance'].get('gates',[])},
            },
            parameter_delta={},
            setup_delta={},
            same_setup=None,
            sensitivity_eligible=False,
            causality_note='Offline source comparison has no model/setup identity; numerical deltas are descriptive only.'
        ) for e in entries[1:]]
        analysis['comparison_note']='Numerical source comparison only; model/setup equivalence and causal sensitivity are not established.'
    atomic_json(stage/'analysis.json',analysis)
    # One input has ordinary gate IDs; comparisons retain input qualification.
    metrics=entries[0]['metrics'] if len(entries)==1 else {f'input_{i}_{k}':v for i,e in enumerate(entries) for k,v in e['metrics'].items()}
    gates_out=[dict(g,id=g['id'] if len(entries)==1 else f'input_{i}_{g["id"]}') for i,e in enumerate(entries) for g in e['acceptance']['gates']]
    states=[e['acceptance']['status'] for e in entries]
    acceptance=dict(status='error' if 'error' in states else 'fail' if 'fail' in states else 'pass',gates=gates_out)
    return analysis,metrics,acceptance


def _export_gate_samples(path,data,gates):
    """Export the exact judged values, including interpolated band edges."""
    frequencies=[f/1e9 for f in data.frequencies_hz]
    with path.open('w',newline='',encoding='utf-8') as handle:
        writer=csv.writer(handle)
        writer.writerow(['gate','frequency_ghz','value','unit','interpolated_edge'])
        for gate in gates:
            try: values=_values_for(gate,data)
            except ValueError: continue
            band_f,band_v,_=_band_samples(frequencies,values,*gate.band_ghz)
            writer.writerows((gate.id,f,v,gate.unit,f not in frequencies) for f,v in zip(band_f,band_v))


def _plot(path,data,gates):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    groups={}
    for gate in gates:
        try: values=_values_for(gate,data)
        except ValueError: continue
        group=(gate.derived.name if gate.derived else
               'reflection' if gate.out_port==gate.in_port else 'transmission',gate.unit)
        groups.setdefault(group,[]).append((gate,values))
    if not groups:
        groups[('No evaluable curves; see analysis.json','db')]=[]
    figure,axes=plt.subplots(len(groups),1,figsize=(9,3.5*len(groups)),squeeze=False,layout='constrained')
    for ax,((name,unit),items) in zip(axes[:,0],groups.items()):
        for gate,values in items:
            ax.plot([f/1e9 for f in data.frequencies_hz],values,label=gate.id,linewidth=1.4)
            ax.plot(gate.band_ghz,[gate.threshold]*2,'--',linewidth=.8,color='gray')
        if items:
            low=min(g.band_ghz[0] for g,_ in items);high=max(g.band_ghz[1] for g,_ in items)
            margin=max((high-low)*.05,.005)
            ax.set_xlim(max(data.frequencies_hz[0]/1e9,low-margin),min(data.frequencies_hz[-1]/1e9,high+margin))
            ax.axvspan(low,high,color='#dceaf5',alpha=.4,zorder=-1)
            shown=[v for g,values in items for f,v in zip(data.frequencies_hz,values) if low-margin<=f/1e9<=high+margin]
            shown.extend(g.threshold for g,_ in items)
            if shown:
                pad=max((max(shown)-min(shown))*.08,.02)
                ax.set_ylim(min(shown)-pad,max(shown)+pad)
            ax.legend(fontsize=8)
        ax.set(title=name.replace('_',' '),xlabel='Frequency (GHz)',ylabel='dB' if unit=='db' else 'Degrees')
        ax.grid(alpha=.2)
    figure.suptitle('Exported source response · offline analysis',fontsize=12)
    figure.savefig(path,dpi=150);plt.close(figure)
