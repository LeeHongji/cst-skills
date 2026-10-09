"""Non-destructive CSTLab data initialization and content-verified project import."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import uuid

SOFTWARE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SOFTWARE/'MCP/CST-Lab/src'))
from cst_lab.atomic import atomic_json, process_lock
from cst_lab.workspace import registered_projects, settings


def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''): h.update(block)
    return h.hexdigest()


def inventory(root):
    root = Path(root).resolve(); records = []
    for base, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            p = Path(base)/name
            if p.is_symlink() or p.is_junction(): raise ValueError('linked data cannot be imported: '+str(p))
        dirs[:] = sorted(d for d in dirs if d not in {'__pycache__', '.git'})
        if any(d.lower() in {'result','temp','modelcache'} for d in dirs):
            raise ValueError('project contains solver caches; promote clean evidence first')
        for name in sorted(files):
            p = Path(base)/name
            if p.suffix.lower() in {'.lok','.lck'}: raise ValueError('project contains a lock: '+str(p))
            with p.open('rb') as f:
                if f.read(100).startswith(b'version https://git-lfs.github.com/spec/'):
                    raise ValueError('LFS content must be materialized before import: '+str(p))
            records.append(dict(path=p.relative_to(root).as_posix(),bytes=p.stat().st_size,sha256=sha(p)))
    return sorted(records,key=lambda x:x['path'])


def initialize(root, software=SOFTWARE, seed_brain=False):
    root = Path(root).resolve(); software = Path(software).resolve()
    if root == software or root.is_relative_to(software) or software.is_relative_to(root):
        raise ValueError('software and data must be separate sibling trees')
    for folder in ['projects','brain','system/lab','runtime','logs','backups','system/migrations']:
        (root/folder).mkdir(parents=True,exist_ok=True)
    marker = root/'workspace.json'
    try: software_ref=os.path.relpath(software,root).replace('\\','/')
    except ValueError: software_ref=software.as_posix()  # Different Windows volumes.
    wanted = dict(schema_version=1,layout='cstlab',software_root=software_ref)
    if marker.exists():
        if json.loads(marker.read_text()) != wanted: raise ValueError('existing workspace configuration differs')
    else: atomic_json(marker,wanted)
    registry = root/'system/projects.json'
    if not registry.exists(): atomic_json(registry,dict(schema_version=1,projects=[]))
    if seed_brain:
        # Resume a partial seed copy, without rewriting user knowledge or state.
        for source in sorted((software/'brain').rglob('*')):
            relative=source.relative_to(software/'brain')
            if not source.is_file() or any(part in {'.state','.locks','.trash','.obsidian','__pycache__'} for part in relative.parts):
                continue
            target=root/'brain'/relative
            if not target.exists():
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    settings(root)
    return wanted


def import_project(root, identity, source, apply=False):
    root=Path(root).resolve();source=Path(source).resolve()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*',identity): raise ValueError('invalid project ID')
    if not source.is_dir() or not (source/'topic.md').is_file(): raise ValueError('source requires topic.md')
    records=inventory(source)
    report=dict(schema_version=1,id=identity,source=str(source),destination=f'projects/{identity}',files=records,
        file_count=len(records),bytes=sum(f['bytes'] for f in records),excluded=['__pycache__','.git'])
    if not apply:return report
    if not settings(root): raise ValueError('initialize data root first')
    target=root/'projects'/identity
    if target==source or source.is_relative_to(target) or target.is_relative_to(source):raise ValueError('source and target overlap')
    with process_lock(root/'system/migration.lock'):
        registry=json.loads((root/'system/projects.json').read_text())
        existing=next((p for p in registry['projects'] if p['id'].casefold()==identity.casefold()),None)
        if existing and (existing['id']!=identity or existing.get('source')!=str(source)):
            raise ValueError('project ID already belongs to another source')
        if target.exists():
            if inventory(target)!=records: raise ValueError('target differs; never overwrite project data')
        else:
            stage=root/'system/migrations'/('pending-'+uuid.uuid4().hex)
            stage.mkdir()
            for record in records:
                a=source/record['path'];b=stage/record['path'];b.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(a,b)
            if inventory(stage)!=records or inventory(source)!=records:raise ValueError('source changed or copied bytes failed verification')
            stage.replace(target)
        manifest=root/'system/migrations'/(identity+'.json')
        if manifest.exists() and json.loads(manifest.read_text())!=report:raise ValueError('migration receipt collision')
        atomic_json(manifest,report)
        if not existing:
            registry['projects'].append(dict(id=identity,source=str(source),migration=manifest.relative_to(root).as_posix()))
            atomic_json(root/'system/projects.json',registry)
        registered_projects(root)
    return report


def verify(root,identity):
    root=Path(root).resolve()
    # IDs are looked up, not interpreted as filesystem paths.
    registered_projects(root)
    registry=json.loads((root/'system/projects.json').read_text())
    entry=next(p for p in registry['projects'] if p['id']==identity)
    report=json.loads((root/entry['migration']).read_text())
    current=inventory(root/'projects'/identity)
    by_path={x['path']:x for x in current}
    patches_path=root/'system/migrations/model-import-patches.json'
    patches=json.loads(patches_path.read_text()) if patches_path.exists() else []
    applied={x['path']:x for x in patches if x['id']==identity}
    def expected(record):
        if record['path'] not in applied:return by_path.get(record['path'])==record
        patch=applied[record['path']]
        return patch['before_sha256']==record['sha256'] and patch['geometry_unchanged'] is True and by_path.get(record['path'],{}).get('sha256')==patch['after_sha256']
    return dict(id=identity,source_unchanged=inventory(Path(report['source']))==report['files'],
                destination_matches=all(by_path.get(x['path'])==x for x in report['files']),
                destination_expected=all(expected(x) for x in report['files']),documented_source_adaptations=len(applied),
                destination_exact=current==report['files'],new_files=len(current)-report['file_count'],file_count=report['file_count'])


def unregister(root,identity):
    """Rollback discovery only; source and imported evidence are never deleted."""
    root=Path(root).resolve()
    with process_lock(root/'system/migration.lock'):
        registry=json.loads((root/'system/projects.json').read_text())
        if identity not in [p['id'] for p in registry['projects']]:raise ValueError('unknown project')
        atomic_json(root/'backups'/('registry-'+uuid.uuid4().hex+'.json'),registry)
        registry['projects']=[p for p in registry['projects'] if p['id']!=identity]
        atomic_json(root/'system/projects.json',registry)
    return dict(unregistered=identity,data_preserved=True)


def create_project(root, identity, title, physics, citation):
    from cst_lab.topic_workspace import init_topic
    root=Path(root).resolve()
    if not settings(root):raise ValueError('initialize data root first')
    with process_lock(root/'system/migration.lock'):
        registry=json.loads((root/'system/projects.json').read_text())
        if identity.casefold() in {p['id'].casefold() for p in registry['projects']}:
            raise ValueError('project ID already registered')
        project=root/'projects'/identity
        if project.exists():
            from cst_lab.contracts.topic import load_topic
            from cst_lab.topic_workspace import validate_topic_workspace
            header,_=load_topic(project/'topic.md')
            if header['title']!=title or header['shared_physics']!=[physics] or header['sources']!=[dict(kind='internal',citation=citation)] or validate_topic_workspace(project)['status']!='valid':
                raise ValueError('unregistered topic differs or is incomplete; preserve it for manual recovery')
            registry['projects'].append(dict(id=identity,kind='created'))
            atomic_json(root/'system/projects.json',registry)
            return dict(id=identity,path=str(project),registered=True,recovered_registration=True)
        project=init_topic(root,topic_id=identity,title=title,shared_physics=[physics],
                           sources=[dict(kind='internal',citation=citation)])
        (project/'OPERATIONS.md').write_text(
            '# CST research project\n\nThis is research data, not a platform Git worktree.\n'
            'Read workspace/system/deployment.json for the bound runtime Python.\n'
            'Use only the configured cst_run/cst_get/cst_approve Function facade.\n'
            'Working copies: workspace/runtime; evidence: this project; registry: workspace/system/lab.\n'
            'Initialize designs with machine-readable gates before requesting an audit.\n',encoding='utf8')
        instructions=project/'AGENTS.md'
        instructions.write_text(instructions.read_text().replace('`cst_runs/`','`<workspace>/runtime/`').replace('A CST write must use the Guardian worker.','Production writes must use cst_run/cst_get/cst_approve; Guardian is internal.'),encoding='utf8')
        registry['projects'].append(dict(id=identity,kind='created'))
        atomic_json(root/'system/projects.json',registry)
    return dict(id=identity,path=str(project),registered=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data',type=Path,required=True)
    sub=parser.add_subparsers(dest='command',required=True)
    sub.add_parser('init')
    imp=sub.add_parser('import');imp.add_argument('id');imp.add_argument('source',type=Path);imp.add_argument('--apply',action='store_true')
    ver=sub.add_parser('verify');ver.add_argument('id')
    un=sub.add_parser('unregister');un.add_argument('id')
    new=sub.add_parser('create');new.add_argument('id');new.add_argument('--title',required=True);new.add_argument('--physics',required=True);new.add_argument('--citation',required=True)
    a=parser.parse_args()
    if a.command=='init':result=initialize(a.data,seed_brain=True)
    elif a.command=='import':result=import_project(a.data,a.id,a.source,a.apply)
    elif a.command=='verify':result=verify(a.data,a.id)
    elif a.command=='create':result=create_project(a.data,a.id,a.title,a.physics,a.citation)
    else:result=unregister(a.data,a.id)
    if 'files' in result:result={k:v for k,v in result.items() if k!='files'}
    print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
