"""Workspace scaffolding and deployment maintenance, never a solver write path."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tomllib
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'scripts'),str(ROOT/'MCP/CST-Lab/src'),str(ROOT/'MCP/CST-CAD/src'),str(ROOT/'MCP/CST')]
from cst_lab.atomic import atomic_json, process_lock
from cst_lab.workspace import settings, registered_projects
from cst_lab.paths import LabPaths
from cst_lab.topic_workspace import init_design, validate_topic_workspace
from cst_lab.contracts.topic import load_topic
from cst_lab.contracts.attempt import write_attempt
from cst_lab.function_model import load_model
from cst_cad import ir, drc
from cstlab_data import initialize, create_project

OWNED={'cst-function','cst-brain'}
WORKSPACE_GUIDE='''# CST research workspace / CST 研究工作区

Use cst-research to resume a topic. Read projects/<id>/README.md, topic.md,
design.md, attempt.json and append-only iterations.jsonl before changing it.
Production CST execution uses only cst_run, cst_get and cst_approve. Brain is
a separate knowledge MCP; CAD, Lab and Guardian are internal dependencies.
Use the installed runtime Python listed in system/deployment.json. Never infer
the runtime location from the current Skill directory or a legacy checkout.
Keep sources unchanged; working copies are in runtime/, durable evidence in
projects/. No Result/ or Temp/ under projects/. No old approvals are imported.
Ask for real artifact-bound approval before solving, or honor an explicitly
scoped current user delegation. Never fabricate review or confirmation input.
Keep rules in Skills, facts in Brain, state in Lab and events in traces.
Run the workspace doctor and validate-topic before and after research sessions.
'''


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require_workspace(root):
    root=Path(root).resolve()
    if not settings(root):
        raise ValueError('Initialize this workspace first')
    if settings(root)['software']!=ROOT:
        raise ValueError('Use the runtime version bound to this workspace')
    registered_projects(root)
    return root


def model_attempt(root,topic,design,attempt,max_iterations=12):
    root=require_workspace(root)
    for value in [topic,design,attempt]:
        if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',value):
            raise ValueError('IDs must be lowercase kebab-case')
    project=registered_projects(root).get(topic)
    if project is None:raise ValueError('Unknown topic')
    design_dir=project/'designs'/design
    from cst_lab.contracts.design import load_design
    header,_,_=load_design(design_dir/'design.md',LabPaths.resolve(root))
    script=(design_dir/header['model']).resolve()
    if not script.is_relative_to(design_dir.resolve()):raise ValueError('Model escapes design')
    document=load_model(script,{})
    report=drc.run(document)
    if report['status']!='pass':raise ValueError('Fix DRC before creating an attempt: '+json.dumps(report))
    target=design_dir/'attempts'/attempt
    with process_lock(root/'system/scaffold.lock'):
        if target.exists():raise FileExistsError('Attempt exists; preserve its audit and history')
        stage=target.parent/('.pending-'+uuid.uuid4().hex);stage.mkdir(parents=True)
        try:
            write_attempt(stage/'attempt.json',dict(schema_version=1,topic_id=topic,design_id=design,
                attempt_id=attempt,topology_hash=ir.topology_hash(document),model_intent_id=document['model_intent_id'],
                baseline_parameters={p['name']:p['value'] for p in document['parameters']},approved_ranges={},
                max_iterations=max_iterations),LabPaths.resolve(root))
            ir.write(document,stage/'geometry-ir.json')
            atomic_json(stage/'drc-report.json',report)
            (stage/'iterations.jsonl').touch()
            stage.replace(target)
        except Exception:
            if stage.exists():shutil.rmtree(stage)
            raise
    return dict(attempt=str(target/'attempt.json'),next='cst_run(operation=audit, fidelity=offline), then review and cst_approve')


def server(root,service):
    entry=ROOT/('MCP/CST/agent_mcp_server.py' if service=='function' else 'MCP/CST-Brain/mcp_server.py')
    return dict(command=sys.executable,args=[str(entry)],cwd=str(ROOT/'MCP'/('CST' if service=='function' else 'CST-Brain')),
                env=dict(CST_AUTOMATION_ROOT=str(root),CST_BRAIN_ROOT=str(root/'brain'),
                         CST_TRACE_ROOT=str(root/'runtime/_mcp_traces'),PYTHONUTF8='1'))


def config_payloads(root,clients):
    updates=[]
    if 'codex' in clients:
        path=root/'.codex/config.toml'
        previous=path.read_text(encoding='utf-8-sig') if path.exists() else ''
        tomllib.loads(previous)
        kept=[];skip=False
        for line in previous.splitlines(keepends=True):
            if line.lstrip().startswith('['):
                match=re.match(r'\s*\[\[?mcp_servers\.([\w-]+)(?:\.|\])',line)
                skip=bool(match and match[1] in OWNED)
            if not skip:kept.append(line)
        text=''.join(kept).rstrip()+'\n\n'
        for name,mode in [('cst-function','function'),('cst-brain','brain')]:
            data=server(root,mode)
            text+=f'[mcp_servers.{name}]\n'
            for key in ['command','args','cwd']:
                text+=key+' = '+json.dumps(data[key],ensure_ascii=True)+'\n'
            text+='startup_timeout_sec = 30\ntool_timeout_sec = 7200\n'
            text+=f'[mcp_servers.{name}.env]\n'
            text+=''.join(key+' = '+json.dumps(value)+'\n' for key,value in data['env'].items())+'\n'
        tomllib.loads(text)
        updates.append((path,text.encode('utf-8')))
    if 'claude-code' in clients:
        path=root/'.mcp.json'
        data=json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
        if not isinstance(data,dict) or not isinstance(data.get('mcpServers',{}),dict):raise ValueError('Invalid Claude MCP configuration')
        servers=data.setdefault('mcpServers',{})
        for name,mode in [('cst-function','function'),('cst-brain','brain')]:
            definition=server(root,mode)
            definition.pop('cwd')  # Absolute script paths and explicit roots make cwd unnecessary.
            servers[name]={'type':'stdio',**definition}
        updates.append((path,(json.dumps(data,ensure_ascii=False,indent=2)+'\n').encode('utf-8')))
    return updates


def configure(root,clients):
    root=require_workspace(root)
    with process_lock(root/'system/configuration.lock'):
        updates=config_payloads(root,clients)  # Validate ALL files before the first mutation.
        changed=[(path,data) for path,data in updates if not path.exists() or path.read_bytes()!=data]
        if not changed:return dict(changed=False)
        backup=root/'backups/configuration'/uuid.uuid4().hex;backup.mkdir(parents=True)
        records=[]
        for index,(path,data) in enumerate(changed):
            existed=path.exists()
            before=path.read_bytes() if existed else b''
            (backup/f'{index}.before').write_bytes(before)
            records.append(dict(path=path.relative_to(root).as_posix(),existed=existed,
                                before_sha256=hashlib.sha256(before).hexdigest(),after_sha256=hashlib.sha256(data).hexdigest(),backup=f'{index}.before'))
        atomic_json(backup/'receipt.json',dict(schema_version=1,files=records))
        try:
            for path,data in changed:
                path.parent.mkdir(parents=True,exist_ok=True)
                temporary=path.with_name(path.name+'.pending-'+uuid.uuid4().hex)
                temporary.write_bytes(data);temporary.replace(path)
        except Exception:
            for record in records:
                path=root/record['path']
                if record['existed']:path.write_bytes((backup/record['backup']).read_bytes())
                elif path.exists():path.unlink()
            raise
    return dict(changed=True,backup=str(backup),clients=clients)


def restore(root,receipt_path):
    root=require_workspace(root);receipt_path=receipt_path.resolve()
    if not receipt_path.is_relative_to(root/'backups/configuration'):raise ValueError('Receipt must belong to this workspace')
    doc=json.loads(receipt_path.read_text(encoding='utf-8'));allowed={'.codex/config.toml','.mcp.json'}
    with process_lock(root/'system/configuration.lock'):
        for item in doc['files']:
            if item['path'] not in allowed or Path(item['backup']).name!=item['backup']:raise ValueError('Invalid configuration receipt')
            path=root/item['path'];before=receipt_path.parent/item['backup']
            if sha(before)!=item['before_sha256'] or not path.is_file() or sha(path)!=item['after_sha256']:
                raise ValueError('Configuration or backup changed; refusing to overwrite subsequent edits')
        for item in doc['files']:
            path=root/item['path']
            if item['existed']:path.write_bytes((receipt_path.parent/item['backup']).read_bytes())
            else:path.unlink()
    return dict(restored=True,receipt=str(receipt_path))


def initialize_workspace(args):
    root=args.workspace.resolve()
    initialize(root,ROOT,seed_brain=True)
    for name,content in [('AGENTS.md',WORKSPACE_GUIDE),('CLAUDE.md','Read AGENTS.md and invoke cst-research.\n')]:
        path=root/name
        if not path.exists():path.write_text(content,encoding='utf-8')
    result=dict(workspace=str(root))
    if args.topic:
        if not all([args.title,args.physics,args.citation]):raise ValueError('Topic requires title, physics and citation')
        current=registered_projects(root)
        if args.topic in current:
            header,_=load_topic(current[args.topic]/'topic.md')
            if header['title']!=args.title or header['shared_physics']!=[args.physics] or header['sources']!=[dict(kind='internal',citation=args.citation)]:
                raise ValueError('Existing topic differs; initialization never rewrites it')
            result['topic']='unchanged'
        else:result['topic']=create_project(root,args.topic,args.title,args.physics,args.citation)
    result['configuration']=configure(root,args.clients)
    deployment=dict(schema_version=1,runtime_root=str(ROOT),python=sys.executable,clients=args.clients,
                    version='0.1.0',archive_sha256=json.loads((ROOT/'runtime-release.json').read_text())['archive_sha256'] if (ROOT/'runtime-release.json').is_file() else None)
    atomic_json(root/'system/deployment.json',deployment)
    return result


def doctor(root):
    root=require_workspace(root)
    checks=dict(python_313=sys.version_info[:2]==(3,13),data_layout=True)
    modules={}
    for name in ['cst_agent_api','cst_lab','cst_cad','cst_brain']:
        module=__import__(name);modules[name]=str(Path(module.__file__).resolve())
        checks[name+'_local']=Path(module.__file__).resolve().is_relative_to(ROOT)
    reports={identity:validate_topic_workspace(path) for identity,path in registered_projects(root).items()}
    from cst_brain.operations import BrainOperations
    from cst_brain.paths import BrainPaths
    lint=BrainOperations(BrainPaths.resolve(root/'brain')).lint()
    checks['brain_lint']=not lint['issues']
    from cst_guardian.paths import ensure_cst_paths
    # Normal executable/API discovery only. No DLL company or provenance heuristics.
    try:cst=ensure_cst_paths()
    except Exception as exc:cst={'available':False,'reason':str(exc)}
    return dict(status='pass' if all(checks.values()) and all(r.get('status')=='valid' for r in reports.values()) else 'needs-attention',
                checks=checks,modules=modules,topics=reports,brain_lint=lint,cst_discovery=str(cst),
                note='Discovery does not launch CST or prove solver coverage. Client approval/load verification is separate.')


def example(root,topic):
    root=require_workspace(root)
    project=registered_projects(root).get(topic)
    if project is None:raise ValueError('Create/register the topic first')
    if (project/'designs/lowpass').exists():raise FileExistsError('Example design already exists')
    gates=[dict(id='passband',metric='s2_1_db',band_ghz=[.1,1.5],comparator='>',threshold=-1.,mode='pointwise',min_samples=10),
           dict(id='stopband',metric='s2_1_db',band_ghz=[3.6,4.2],comparator='<',threshold=-10.,mode='pointwise',min_samples=10)]
    design=init_design(project,design_id='lowpass',title='Stepped-impedance lowpass / 阶梯阻抗低通',ports=2,acceptance=gates)
    shutil.copy2(ROOT/'examples/lowpass/model.py',design/'model.py')
    return model_attempt(root,topic,'lowpass','a01')


def main():
    p=argparse.ArgumentParser(description=__doc__);subs=p.add_subparsers(dest='action',required=True)
    for name in ['init','configure','restore-config','doctor','example','design','attempt','protocol-check']:
        sub=subs.add_parser(name);sub.add_argument('--workspace',type=Path,required=True)
        if name in ['init','configure']:sub.add_argument('--clients',nargs='+',choices=['codex','claude-code'],default=['codex','claude-code'])
        if name=='init':
            for value in ['topic','title','physics','citation']:sub.add_argument('--'+value)
        if name=='restore-config':sub.add_argument('--receipt',type=Path,required=True)
        if name in ['example','design','attempt']:sub.add_argument('--topic',required=True)
        if name in ['design','attempt']:sub.add_argument('--design',required=True)
        if name=='design':
            sub.add_argument('--title',required=True);sub.add_argument('--ports',type=int,required=True);sub.add_argument('--gates',type=Path,required=True)
        if name=='attempt':sub.add_argument('--attempt',required=True);sub.add_argument('--max-iterations',type=int,default=12)
    args=p.parse_args()
    if args.action=='init':result=initialize_workspace(args)
    elif args.action=='configure':result=configure(args.workspace,args.clients)
    elif args.action=='restore-config':result=restore(args.workspace,args.receipt)
    elif args.action=='doctor':result=doctor(args.workspace)
    elif args.action=='example':result=example(args.workspace,args.topic)
    elif args.action=='attempt':result=model_attempt(args.workspace,args.topic,args.design,args.attempt,args.max_iterations)
    elif args.action=='protocol-check':
        subprocess.run([sys.executable,str(ROOT/'scripts/protocol-check.py'),'--workspace',str(require_workspace(args.workspace))],check=True);return
    else:
        root=require_workspace(args.workspace);project=registered_projects(root).get(args.topic)
        if project is None:raise ValueError('Unknown topic')
        with process_lock(root/'system/scaffold.lock'):
            result=dict(design=str(init_design(project,design_id=args.design,title=args.title,ports=args.ports,
                          acceptance=json.loads(args.gates.read_text(encoding='utf-8-sig')))))
    print(json.dumps(result,ensure_ascii=False,indent=2,default=str))
    if isinstance(result,dict) and result.get('status')=='needs-attention':raise SystemExit(2)


if __name__=='__main__':
    main()
