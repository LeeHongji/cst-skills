"""Resolve the supported solver settings before hashing or entering CST.

This is an executable configuration contract, not a bag of arbitrary metadata.
The Guardian adapter must apply/read back every resolved field before solving.
"""
from copy import deepcopy
import math

from .function_contract import digest

SETUP_VERSION='cst-function-setup-1'
SECTIONS={'solver','frequency','mesh','convergence','settings','monitors'}


def merge_delta(original,delta,previous=None,path='setup'):
    """Deep merge leaves, checking optional [old,new] preconditions."""
    if not isinstance(delta,dict): raise ValueError(f'{path} delta must be an object')
    merged=deepcopy(original)
    for name,value in delta.items():
        old=(previous or {}).get(name)
        if isinstance(value,dict):
            if not isinstance(merged.get(name,{}),dict): raise ValueError(f'{path}.{name} is not a section')
            merged[name]=merge_delta(merged.get(name,{}),value,old if isinstance(old,dict) else {},path+'.'+name)
        elif isinstance(value,list):
            if len(value)!=2 or value[0]!=old or isinstance(value[0],bool)!=isinstance(old,bool):
                raise ValueError(f'{path}.{name} old-value precondition differs from effective parent')
            merged[name]=deepcopy(value[1])
        else: merged[name]=value
    return merged


def _keys(value,allowed,label):
    if not isinstance(value,dict): raise ValueError(f'{label} must be an object')
    if unknown:=set(value)-set(allowed): raise ValueError(f'unsupported {label} fields: {sorted(unknown)}')


def _number(value,label,low=None,high=None,integer=False):
    if type(value) not in (int,float) or not math.isfinite(value): raise ValueError(f'{label} must be finite numeric')
    if integer and (type(value) is not int): raise ValueError(f'{label} must be an integer')
    if low is not None and value<low or high is not None and value>high: raise ValueError(f'{label} outside supported bounds')
    return value if integer else float(value)


def resolve_setup(document,overrides,fidelity):
    from cst_cad.expressions import evaluate
    if fidelity not in ('screen','confirm'): raise ValueError('solver setup requires screen or confirm')
    _keys(overrides,SECTIONS,'setup')
    simulation=deepcopy(document.get('simulation') or {})
    _keys(simulation,SECTIONS-{'mesh'},'model simulation')
    raw=deepcopy(simulation);raw['mesh']=deepcopy(document.get('mesh_hints') or {})
    # Overrides have already had [old,new] expanded; do not reinterpret lists.
    for key,value in overrides.items():
        if isinstance(value,dict):
            raw[key]={**raw.get(key,{}),**deepcopy(value)}
        else: raw[key]=deepcopy(value)
    solver=raw.get('solver')
    if solver not in ('frequency_domain','time_domain'): raise ValueError('function executor supports frequency_domain or time_domain')
    parameters={p['name']:p['value'] for p in document['parameters']}
    frequency=raw.get('frequency',{})
    _keys(frequency,{'min','max','center'},'frequency')
    if not {'min','max'}<=frequency.keys(): raise ValueError('explicit frequency min and max are required')
    try:
        frequency={k:(evaluate(v,parameters) if isinstance(v,str) else v) for k,v in frequency.items() if v is not None}
    except (ValueError,KeyError,SyntaxError,ZeroDivisionError,OverflowError) as exc:
        raise ValueError(f'frequency expression cannot be resolved: {exc}') from exc
    frequency.setdefault('center',(frequency['min']+frequency['max'])/2)
    frequency={k:_number(v,'frequency.'+k,0) for k,v in frequency.items()}
    if not frequency['min']<frequency['max'] or not frequency['min']<=frequency['center']<=frequency['max']:
        raise ValueError('frequency range/center is inconsistent')
    if document['units']['frequency']!='GHz': raise ValueError('function executor currently requires IR frequency units GHz')
    mesh=dict(kind='tetrahedral' if solver=='frequency_domain' else 'hexahedral',
        steps_per_wavelength_near=8. if fidelity=='screen' else 15.,
        cells_per_max_cell_near=10. if fidelity=='screen' else 20.)
    supplied_mesh=raw.get('mesh',{})
    _keys(supplied_mesh,mesh.keys(),'mesh')
    mesh.update(supplied_mesh)
    expected='tetrahedral' if solver=='frequency_domain' else 'hexahedral'
    if mesh['kind']!=expected: raise ValueError('mesh kind is incompatible with the supported solver method')
    for key in ('steps_per_wavelength_near','cells_per_max_cell_near'):
        mesh[key]=_number(mesh[key],'mesh.'+key,1)
    convergence=dict(adaptive_mesh=solver=='frequency_domain',min_passes=3 if fidelity=='screen' else 6,
        max_passes=6 if fidelity=='screen' else 12,max_delta_s=.02 if fidelity=='screen' else .01,
        increment_percent=5.,checks=2)
    _keys(raw.get('convergence',{}),convergence.keys(),'convergence')
    convergence.update(raw.get('convergence',{}))
    if type(convergence['adaptive_mesh']) is not bool: raise ValueError('adaptive_mesh must be boolean')
    if solver=='time_domain' and convergence['adaptive_mesh']: raise ValueError('adaptive TD execution has not been implemented')
    for key in ('min_passes','max_passes','checks'):
        convergence[key]=_number(convergence[key],'convergence.'+key,1,integer=True)
    if convergence['min_passes']>convergence['max_passes']: raise ValueError('min_passes exceeds max_passes')
    convergence['max_delta_s']=_number(convergence['max_delta_s'],'max_delta_s',1e-12,1.)
    convergence['increment_percent']=_number(convergence['increment_percent'],'increment_percent',.01,100.)
    if solver=='frequency_domain':
        settings=dict(method='Tetrahedral',method_variant='Fast reduced order model',order_tet='Second',order_srf='First',
            norming_impedance=50.,accuracy_tet=1e-6,accuracy_rom=1e-4 if fidelity=='screen' else 1e-5,
            result_samples=801,store_all_results=True)
    else:
        settings=dict(accuracy_db=-35. if fidelity=='screen' else -45.,auto_norm_impedance=True,norming_impedance=50.)
    _keys(raw.get('settings',{}),settings.keys(),'settings')
    settings.update(raw.get('settings',{}))
    for key in ('norming_impedance','accuracy_tet','accuracy_rom','accuracy_db'):
        if key in settings:
            value=settings[key]
            # Legacy DSL uses numeric text for the CST API. Normalize before hashing.
            if isinstance(value,str):
                try: value=float(value)
                except ValueError: raise ValueError(f'{key} must be a numeric literal') from None
            settings[key]=_number(value,key)
    if settings['norming_impedance']<=0: raise ValueError('norming_impedance must be positive')
    if solver=='frequency_domain':
        for key,expected in [('method','Tetrahedral'),('method_variant','Fast reduced order model'),('order_tet','Second'),('order_srf','First')]:
            if settings[key]!=expected: raise ValueError(f'unsupported FD {key}')
        for key in ('accuracy_tet','accuracy_rom'):
            if not 0<settings[key]<1: raise ValueError(f'{key} must lie between zero and one')
        settings['result_samples']=_number(settings['result_samples'],'result_samples',5,integer=True)
        if type(settings['store_all_results']) is not bool: raise ValueError('store_all_results must be boolean')
    else:
        if not -100<=settings['accuracy_db']<0: raise ValueError('accuracy_db must be negative dB in [-100,0)')
        if type(settings['auto_norm_impedance']) is not bool: raise ValueError('auto_norm_impedance must be boolean')
    if raw.get('monitors'): raise ValueError('field-monitor execution/readback is not yet supported by the function executor')
    return dict(schema_version=1,version=SETUP_VERSION,fidelity=fidelity,solver=solver,frequency=frequency,
        mesh=mesh,convergence=convergence,settings=settings,monitors=[],
        units=deepcopy(document['units']),ports=deepcopy(document.get('ports',[])),
        boundaries=deepcopy(document.get('boundaries',{})))


def apply_to_ir(document,setup):
    from cst_cad import ir
    result=deepcopy(document)
    result['mesh_hints']=deepcopy(setup['mesh'])
    result['simulation']={k:deepcopy(setup[k]) for k in ('solver','frequency','convergence','settings','monitors')}
    return ir.stamp(result)


def cache_identity(document,setup,runtime):
    """Runtime comes from the owned executor, never from cst_run arguments."""
    from cst_cad import ir
    ir.require_valid(document)
    if (document.get('mesh_hints')!=setup['mesh'] or
        document.get('simulation')!={k:setup[k] for k in ('solver','frequency','convergence','settings','monitors')} or
        any(document.get(k,{})!=setup[k] for k in ('units','boundaries')) or document.get('ports',[])!=setup['ports']):
        raise ValueError('cache setup differs from the effective model passed to the executor')
    required={'cst_version','executor_sha256'}
    if not isinstance(runtime,dict) or set(runtime) not in (required,required|{'cst_binary_sha256'}): raise ValueError('trusted runtime version and executor fingerprint required')
    import re
    # GetApplicationVersion returns e.g. "Version 2026.2 - Nov 28 2025".
    # Retain its build date in identity rather than collapsing distinct builds.
    if not isinstance(runtime['cst_version'],str) or not re.fullmatch(
        r'(?:Version )?\d+(?:\.\d+){1,3}(?: - [A-Za-z]{3} \d{1,2} \d{4})?',runtime['cst_version']):
        raise ValueError('actual CST version is missing')
    if not isinstance(runtime['executor_sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',runtime['executor_sha256']):
        raise ValueError('executor fingerprint is missing')
    if 'cst_binary_sha256' in runtime and not re.fullmatch(r'[0-9a-f]{64}',str(runtime['cst_binary_sha256'])):
        raise ValueError('CST binary fingerprint is invalid')
    identity=dict(schema_version=1,model_intent_id=document['model_intent_id'],
        parameters={p['name']:p['value'] for p in document['parameters']},setup_sha256=digest(setup),runtime=deepcopy(runtime))
    return identity,digest(identity)
