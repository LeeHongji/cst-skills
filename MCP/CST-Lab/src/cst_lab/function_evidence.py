"""Immutable analysis, diagnostics and verified simulation publication."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re

from .atomic import atomic_json, process_lock
from .function_contract import digest


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _regular_tree(directory):
    """Reject links/junctions and caches, including empty directories."""
    directory=Path(directory)
    for path in (directory,*directory.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise ValueError('evidence links and junctions are forbidden')
        if any(part.casefold() in ('result','temp') for part in path.relative_to(directory).parts):
            raise ValueError('solver caches cannot be promoted as analysis evidence')


def validate_revision(directory, expected_sha256=None):
    _regular_tree(directory)
    directory=Path(directory).resolve()
    manifest=directory/'manifest.json'
    if expected_sha256 is not None and sha256(manifest)!=expected_sha256:
        raise ValueError('evidence manifest hash changed')
    doc=json.loads(manifest.read_text(encoding='utf-8'))
    if (not isinstance(doc,dict) or set(doc)!={'schema_version','kind','job','files','claim'}
        or type(doc['schema_version']) is not int or doc['schema_version']!=1
        or doc['kind'] not in ('offline-analysis','execution-diagnostic','simulation','cache-reuse','model-audit') or not isinstance(doc['files'],list) or not doc['files']
        or not isinstance(doc['job'],str) or not re.fullmatch(r'job://[0-9a-f]{64}/[0-9a-f]{32}',doc['job'])
        or not isinstance(doc['claim'],str)):
        raise ValueError('unsupported evidence revision')
    seen=set()
    for record in doc['files']:
        if (not isinstance(record,dict) or set(record)!={'path','bytes','sha256'}
            or not isinstance(record['path'],str) or not record['path']
            or type(record['bytes']) is not int or record['bytes']<0
            or not isinstance(record['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',record['sha256'])):
            raise ValueError('invalid evidence file record')
        relative=Path(record['path'])
        path=(directory/relative).resolve()
        if relative.is_absolute() or '..' in relative.parts or not path.is_relative_to(directory) or path==manifest:
            raise ValueError('invalid evidence path')
        key=relative.as_posix().casefold()
        if key in seen: raise ValueError('duplicate evidence path')
        seen.add(key)
        if not path.is_file() or (directory/relative).is_symlink() or path.stat().st_size!=record['bytes'] or sha256(path)!=record['sha256']:
            raise ValueError(f'evidence missing or changed: {relative}')
    actual={p.relative_to(directory).as_posix().casefold() for p in directory.rglob('*') if p.is_file() and p!=manifest}
    if actual!=seen: raise ValueError('revision has unlisted or missing files')
    if doc['kind']=='execution-diagnostic':
        diagnostic=json.loads((directory/'diagnostic.json').read_text(encoding='utf-8'))
        if diagnostic.get('job')!=doc['job'] or diagnostic.get('status') not in ('failed','blocked'):
            raise ValueError('diagnostic evidence requires a failed or blocked job')
        if any(not re.fullmatch(r'.*\.(json|txt|png)',r['path'],re.I) for r in doc['files']):
            raise ValueError('diagnostic archive cannot contain a CST project or solver cache')
    if doc['kind']=='simulation':
        from .function_simulation import validate_simulation
        validate_simulation(directory,doc['job'])
    if doc['kind']=='cache-reuse':
        from .function_cache import validate
        validate(directory,doc['job'])
    if doc['kind']=='model-audit':
        from .function_audit import validate
        validate(directory)
    return doc


def prepare_analysis(stage, job):
    """Seal staging bytes without publishing them ahead of the final job intent."""
    stage=Path(stage)
    _regular_tree(stage)
    files=[]
    for path in sorted(stage.rglob('*')):
        if not path.is_file(): continue
        relative=path.relative_to(stage)
        if relative.as_posix()=='manifest.json':
            raise ValueError('analysis stage is already sealed')
        if path.is_symlink() or not re.fullmatch(r'.*\.(json|csv|png|md|s[0-9]+p)', path.name, re.I):
            raise ValueError('offline revision contains an unexpected file type')
        if any(part.casefold() in ('result','temp') for part in relative.parts):
            raise ValueError('solver caches cannot be promoted as analysis evidence')
        files.append(dict(path=relative.as_posix(),bytes=path.stat().st_size,sha256=sha256(path)))
    manifest=dict(schema_version=1,kind='offline-analysis',job=job,files=files,
                  claim='Source-data analysis only; no new CST solve or human approval')
    atomic_json(stage/'manifest.json',manifest)
    validate_revision(stage)
    return sha256(stage/'manifest.json')


def prepare_diagnostic(stage, job):
    """Seal failure evidence so cst_get can inspect it after finalization."""
    stage=Path(stage)
    _regular_tree(stage)
    if (stage/'manifest.json').exists(): raise ValueError('diagnostic stage is already sealed')
    files=[dict(path=p.relative_to(stage).as_posix(),bytes=p.stat().st_size,sha256=sha256(p))
           for p in sorted(stage.rglob('*')) if p.is_file()]
    atomic_json(stage/'manifest.json',dict(schema_version=1,kind='execution-diagnostic',job=job,
        files=files,claim='Failure diagnostics only; not a completed simulation or reusable cache'))
    validate_revision(stage)
    return sha256(stage/'manifest.json')


def publication_paths(root, attempt, job, stage):
    """Resolve only the current job's evidence destination and a staging subtree."""
    root=Path(root).resolve()
    stage=Path(stage).absolute()
    from .paths import LabPaths
    runs=LabPaths.resolve(root).runs_root
    # A linked ancestor can redirect a nominal cst_runs path outside the root.
    for parent in (stage,*stage.parents):
        if parent==root: break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('publication ancestors must not be linked')
    stage=stage.resolve()
    if not stage.is_relative_to(runs) or stage==runs:
        raise ValueError('publication staging must be below this workspace cst_runs')
    _regular_tree(stage)
    attempt=Path(attempt).absolute()
    for parent in (attempt,*attempt.parents):
        if parent==root: break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('publication attempt must not be linked')
    attempt=attempt.resolve()
    if not attempt.is_relative_to(root/'projects'):
        raise ValueError('publication attempt must belong to this workspace')
    revision='r-'+job.rsplit('/',1)[1]
    destination=attempt.parent/'evidence-revisions'/revision
    for parent in (destination,*destination.parents):
        if parent==root: break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError('publication destination must not be linked')
    return stage,destination


def complete_publication(root, attempt, job, intent, paths):
    """Idempotently finish a durable intent; a byte mismatch never overwrites it."""
    if not isinstance(intent,dict) or set(intent)!={'stage','manifest_sha256'}:
        raise ValueError('invalid publication intent')
    relative=Path(intent['stage'])
    if relative.is_absolute() or '..' in relative.parts:
        raise ValueError('invalid publication staging path')
    stage,destination=publication_paths(root,attempt,job,Path(root)/relative)
    expected=intent['manifest_sha256']
    with process_lock(paths.registry_root/'promotion-locks'/(digest(str(destination.resolve()))+'.lock')):
        if destination.exists():
            manifest=validate_revision(destination,expected)
        else:
            manifest=validate_revision(stage,expected)
            if manifest['job']!=job:
                raise ValueError('evidence belongs to a different job')
            destination.parent.mkdir(parents=True,exist_ok=True)
            os.rename(stage,destination)
        if manifest['job']!=job:
            raise ValueError('evidence belongs to a different job')
        validate_revision(destination,expected)
    return destination,sha256(destination/'manifest.json')


def publish_analysis(stage, attempt, job, paths):
    """Legacy direct publisher. Task execution must use JobSession.finish(stage=)."""
    manifest_hash=prepare_analysis(stage,job)
    root=Path(paths.workspace_root)
    source,_=publication_paths(root,attempt,job,stage)
    return complete_publication(root,attempt,job,dict(stage=source.relative_to(root).as_posix(),
                                manifest_sha256=manifest_hash),paths)
