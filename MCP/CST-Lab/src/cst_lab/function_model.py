"""Resolve and authorize a complete candidate before any CST process is touched."""
from __future__ import annotations
from dataclasses import dataclass
from copy import deepcopy
import hashlib
import ast
import inspect
import importlib.abc
import importlib.machinery
import math
from pathlib import Path
import sys
import types

from .approval import verify_approval,check_effective_parameters,digest
from .contracts.attempt import ApprovalError
from .contracts.design import load_design
from .contracts.iterations import read_iterations
from .function_contract import RunRequest
from .function_evidence import sha256
from .function_setup import resolve_setup,merge_delta,apply_to_ir


@dataclass
class PreparedSimulation:
    document: dict
    execution: dict
    param_delta: dict
    setup_delta: dict
    drc_report: dict
    source_manifest: list
    approval_sha256: str | None  # None only for the internal unaudited regression harness.
    incremental: dict | None = None


class DRCRefusal(ApprovalError):
    def __init__(self,report):
        self.report=report
        super().__init__(f'candidate DRC must pass, got {report["status"]}')


def source_manifest(design):
    records=[]
    for path in sorted(design.rglob('*')):
        relative=path.relative_to(design)
        if any(p in ('attempts','__pycache__','.git') for p in relative.parts) or relative.as_posix()=='design.md':
            continue
        if path.is_symlink() or path.is_junction(): raise ValueError('model source links are unsupported')
        if path.is_file(): records.append(dict(path=relative.as_posix(),sha256=sha256(path)))
    return records


def load_model(script,overrides):
    """Execute current model bytes, avoiding timestamp-based stale .pyc reuse."""
    from cst_cad import ir
    script=Path(script).resolve()
    if script.suffix!='.py': raise ValueError('model must be a Python build() source')
    module_name='cst_function_model_'+hashlib.sha256(str(script).encode()).hexdigest()[:16]
    module=types.ModuleType(module_name);module.__file__=str(script)
    def local_module(item):
        origin=getattr(item,'__file__',None)
        return bool(origin and Path(origin).resolve().is_relative_to(script.parent))
    saved={name:item for name,item in list(sys.modules.items()) if local_module(item)}
    for name in saved: sys.modules.pop(name,None)
    class FreshLoader(importlib.machinery.SourceFileLoader):
        def get_code(self,fullname):
            return compile(Path(self.path).read_bytes(),self.path,'exec')
    class LocalFinder(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            spec=importlib.machinery.PathFinder.find_spec(fullname,path)
            if spec and spec.origin and Path(spec.origin).suffix=='.py' and Path(spec.origin).resolve().is_relative_to(script.parent):
                spec.loader=FreshLoader(fullname,spec.origin)
                return spec
            return None
    finder=LocalFinder();sys.meta_path.insert(0,finder)
    sys.modules[module_name]=module
    old_path=sys.path[:]
    try:
        sys.path.insert(0,str(script.parent))
        exec(compile(script.read_bytes(),str(script),'exec'),module.__dict__)
        function=getattr(module,'build',None)
        if not callable(function): raise ValueError('model must define build(overrides=None)')
        if overrides:
            try: inspect.signature(function).bind(overrides=overrides)
            except TypeError: raise ValueError('model build() does not accept explicit overrides') from None
            document=function(overrides=deepcopy(overrides))
        else: document=function()
        ir.require_valid(document)
        verify_geometry_expressions(document)
        return document
    finally:
        sys.path[:]=old_path
        sys.meta_path.remove(finder)
        for name,item in list(sys.modules.items()):
            if local_module(item): sys.modules.pop(name,None)
        sys.modules.update(saved)


def _values(document):
    return {p['name']:p['value'] for p in document['parameters']}


def verify_geometry_expressions(document):
    """The numbers drawn/checked offline must match the expressions emitted."""
    from cst_cad.expressions import evaluate
    values=_values(document)
    dependencies={p['name']:{node.id for node in ast.walk(ast.parse(p['expression'].replace('^','**'),mode='eval'))
        if isinstance(node,ast.Name) and node.id in values} if p.get('expression') else set() for p in document['parameters']}
    remaining=set(dependencies);resolved=set()
    while remaining:
        ready={name for name in remaining if dependencies[name]<=resolved}
        if not ready: raise ValueError('cyclic parameter expressions cannot be emitted')
        resolved.update(ready);remaining.difference_update(ready)
    def check(expressions,numbers,label):
        for name,expression in expressions.items():
            try: actual=evaluate(expression,values)
            except (ValueError,KeyError,SyntaxError,ZeroDivisionError,OverflowError) as exc:
                raise ValueError(f'geometry expression cannot be resolved: {label}.{name}') from exc
            if name not in numbers or not math.isclose(actual,numbers[name],rel_tol=1e-10,abs_tol=1e-9):
                raise ValueError(f'geometry/expression mismatch: {label}.{name}')
    for net in document.get('nets',[]):
        for solid in net['solids']:
            if solid['kind']=='box': numbers=solid['box']
            elif solid['kind']=='extrude_polygon':
                shape=solid['extrude_polygon']
                numbers=dict(z0=shape['z0'],z1=shape['z1'])
                numbers.update({f'p{i}{axis}':point[j] for i,point in enumerate(shape['points']) for j,axis in enumerate(('x','y'))})
            else: continue  # emitter capability checks refuse unsupported shapes.
            check(solid.get('expressions',{}),numbers,net['name']+':'+solid['id'])
    for port in document.get('ports',[]): check(port.get('expressions',{}),port['extent'],port['name'])


def prepare_simulation(request,paths,authority):
    from cst_cad import ir,drc,emit_vba
    request=RunRequest.parse(request)
    if request.document['operation']!='simulate': raise ValueError('simulation preparation requires simulate')
    data=request.document
    if data['inputs']: raise ValueError('simulate does not accept source-curve inputs; use analyze or compare')
    attempt_path=request.attempt_path(paths.workspace_root)
    attempt=verify_approval(attempt_path,authority=authority)
    if attempt.get('status') not in ('running','met'): raise ApprovalError('attempt is not active for simulation')
    design_dir=attempt_path.parents[2]
    header,_,_=load_design(design_dir/'design.md',paths)
    if header['topic_id']!=data['topic'] or header['design_id']!=data['design']:
        raise ValueError('design identity differs from request')
    script=(design_dir/header['model']).resolve()
    if not script.is_relative_to(design_dir.resolve()) or not script.is_file(): raise ValueError('model source is missing or outside design')
    sources=source_manifest(design_dir)
    default=load_model(script,{})
    definitions={p['name']:p for p in default['parameters']}
    baseline=attempt['baseline_parameters']
    if set(definitions)!=set(baseline): raise ApprovalError('model parameter set differs from audited baseline')
    tunable={name for name,p in definitions.items() if p.get('tunable') and not p.get('expression')}
    # Recreate the audited numerical baseline first. A changed fixed dimension or
    # material may leave topology_hash unchanged, but must not inherit approval.
    baseline_ir=load_model(script,{k:baseline[k] for k in tunable})
    if _values(baseline_ir)!=baseline or baseline_ir['model_intent_id']!=attempt['model_intent_id']:
        raise ApprovalError('current model cannot reproduce the exact audited baseline')
    check_effective_parameters(attempt,baseline_ir)
    rows=read_iterations(attempt_path.parent/'iterations.jsonl',paths)
    previous_values=baseline
    inherited={}
    previous_setup=resolve_setup(baseline_ir,{},data['fidelity'])
    parent=None
    if data['parent'] is not None:
        parent=next((row for row in rows if row['iter']==data['parent']),None)
        if not parent or parent.get('status')!='completed' or parent.get('provenance')!='native' or not parent.get('execution'):
            raise ValueError('parent must be a completed native model execution with resolved context')
        context=parent['execution']
        if digest(context['setup'])!=context['setup_sha256']: raise ValueError('parent effective setup hash changed')
        previous_values=context['parameters'];inherited=context['setup_overrides']
        if set(previous_values)!=set(baseline): raise ValueError('parent full parameter set differs')
        parent_ir=load_model(script,{k:previous_values[k] for k in tunable})
        check_effective_parameters(attempt,parent_ir)
        if _values(parent_ir)!=previous_values: raise ValueError('parent derived/fixed values cannot be rebuilt')
        previous_setup=resolve_setup(parent_ir,inherited,parent['fidelity'])
        if previous_setup!=context['setup'] or apply_to_ir(parent_ir,previous_setup)['model_intent_id']!=context['model_intent_id']:
            raise ValueError('parent model/setup no longer reproduces its recorded identity')
    wanted={k:previous_values[k] for k in tunable}
    for name,value in data['param_delta'].items():
        if name not in tunable: raise ApprovalError(f'{name} is not an independent tunable parameter')
        if isinstance(value,list):
            if value[0]!=previous_values[name]: raise ValueError(f'{name} old-value precondition differs from parent')
            value=value[1]
        wanted[name]=value
    candidate=load_model(script,wanted)
    check_effective_parameters(attempt,candidate)
    values=_values(candidate)
    if any(values[name]!=value for name,value in wanted.items()): raise ValueError('model ignored requested parameter overrides')
    report=drc.run(candidate)
    if report['status']!='pass': raise DRCRefusal(report)
    if header.get('ports')!=len(candidate.get('ports',[])): raise ValueError('design port count differs from rebuilt model')
    overrides=merge_delta(inherited,data['setup_delta'],previous_setup)
    setup=resolve_setup(candidate,overrides,data['fidelity'])
    executed=apply_to_ir(candidate,setup)
    ir.require_valid(executed)
    blocks=emit_vba.build_blocks(executed)
    if source_manifest(design_dir)!=sources: raise ValueError('model source changed during preparation')
    # Approval might have changed during import or DRC; recheck at the boundary.
    fresh=verify_approval(attempt_path,authority=authority)
    if fresh!=attempt: raise ApprovalError('approval/attempt changed during preparation')
    from .function_incremental import plan as incremental_plan
    incremental=incremental_plan(attempt_path,parent,executed,sources,digest(attempt['approval']))
    return PreparedSimulation(document=executed,
        execution=dict(schema_version=1,parameters=values,model_intent_id=executed['model_intent_id'],
            topology_hash=ir.topology_hash(executed),setup=setup,setup_sha256=digest(setup),
            setup_overrides=overrides,model_source_sha256=digest(sources),
            emitted_sha256=digest([dict(title=b.title,code=b.code) for b in blocks])),
        param_delta={k:[previous_values[k],v] for k,v in values.items() if v!=previous_values[k]},
        setup_delta={k:[previous_setup.get(k),v] for k,v in setup.items() if v!=previous_setup.get(k)},
        drc_report=report,source_manifest=sources,approval_sha256=digest(attempt['approval']),incremental=incremental)
