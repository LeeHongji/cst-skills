"""Select and freeze a parent model for conservative parametric CST updates.

Only parameter-value changes with byte-identical remaining History blocks are
eligible. Changed setup/geometry emission rebuilds normally. A referenced but
corrupted parent revision is an error, never an excuse to silently rebuild.
"""
import json
from pathlib import Path
import shutil

from .function_contract import digest
from .function_evidence import validate_revision
from .project_package import model_snapshot


def plan(attempt_path,parent,document,sources,approval_sha256):
    if not parent or parent.get('evidence',{}).get('kind')!='simulation':return None
    binding=parent['evidence'];base=Path(attempt_path).parent/'evidence-revisions'
    folder=(base/binding['revision']).resolve()
    if folder.parent!=base.resolve():raise ValueError('parent revision escapes attempt')
    validate_revision(folder,binding['manifest_sha256'])
    summary=json.loads((folder/'simulation.json').read_text(encoding='utf-8'))
    if summary['execution']!=parent['execution'] or summary['job']!=parent['job_id']:
        raise ValueError('parent iteration differs from its immutable simulation')
    if summary['approval_sha256']!=approval_sha256 or summary['model_sources']!=sources:return None
    previous=json.loads((folder/'model-ir.json').read_text(encoding='utf-8'))
    from cst_cad import emit_vba,ir
    if ir.topology_hash(previous)!=ir.topology_hash(document):return None
    old_blocks={b.title:b.code for b in emit_vba.build_blocks(previous) if b.title!='parameters'}
    new_blocks={b.title:b.code for b in emit_vba.build_blocks(document) if b.title!='parameters'}
    if old_blocks!=new_blocks:return None
    old={p['name']:p for p in previous['parameters']}
    new={p['name']:p for p in document['parameters']}
    if old.keys()!=new.keys():return None
    updates={}
    for name,p in new.items():
        # Parameter definitions, limits and expressions must remain identical.
        if {k:v for k,v in p.items() if k!='value'}!={k:v for k,v in old[name].items() if k!='value'}:return None
        if p['value']!=old[name]['value'] and not p.get('expression'):
            if not p.get('tunable'):return None
            updates[name]=[old[name]['value'],p['value']]
    if not updates:return None
    source=folder/'selected.cst'
    receipt=json.loads((folder/'execution-receipt.json').read_text(encoding='utf-8'))
    return dict(schema_version=1,parent_iteration=parent['iter'],parent_job=parent['job_id'],
        revision=str(folder),manifest_sha256=binding['manifest_sha256'],source=str(source),
        model_snapshot_sha256=digest(model_snapshot(source)),document=previous,
        setup=parent['execution']['setup'],cst_version=receipt['runtime']['cst_version'],updates=updates,
        eligibility='Only independent parameter values change; all non-parameter History blocks identical')


def copy_parent(binding,target):
    """Copy only hash-verified selected CST+Model; never write to the parent."""
    folder=Path(binding['revision']);source=Path(binding['source']);target=Path(target)
    if source!=folder/'selected.cst':raise ValueError('incremental source is not selected parent evidence')
    validate_revision(folder,binding['manifest_sha256'])
    expected=binding['model_snapshot_sha256']
    if digest(model_snapshot(source))!=expected:raise ValueError('incremental parent model changed')
    if target.exists() or target.with_suffix('').exists():raise FileExistsError('incremental target already exists')
    for path in (target,*target.parents):
        if path.is_symlink() or path.is_junction():raise ValueError('incremental target traverses a link')
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(source,target)
    shutil.copytree(source.with_suffix('')/'Model',target.with_suffix('')/'Model')
    if digest(model_snapshot(source))!=expected or digest(model_snapshot(target))!=expected:
        raise ValueError('incremental parent changed while copying')
    return target
