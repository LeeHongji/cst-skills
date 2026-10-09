import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
import tomllib
import zipfile
import pytest
import yaml

ROOT=Path(__file__).resolve().parents[1]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


@pytest.fixture
def api():return load(ROOT/'scripts/cst-research.py','research_cli_test')


@pytest.fixture
def workspace(tmp_path,api):
    root=tmp_path/'研究 工作区'
    args=SimpleNamespace(workspace=root,topic='test-study',title='A research study',physics='Microstrip',citation='Internal test specification',clients=['codex','claude-code'])
    api.initialize_workspace(args)
    return root,args


def test_ten_official_skill_contracts_and_local_references():
    folders=[p for p in (ROOT/'skills').iterdir() if (p/'SKILL.md').is_file()]
    assert len(folders)==10
    for folder in folders:
        text=(folder/'SKILL.md').read_text(encoding='utf-8');meta=yaml.safe_load(text.split('---',2)[1])
        assert meta['name']==folder.name and re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',meta['name']) and len(meta['name'])<=64
        assert 0<len(meta['description'])<=1024 and meta['license']=='MIT'
        for ref in re.findall(r'\]\((references/[^)#]+)',text):assert (folder/ref).is_file(),ref


def test_initialize_idempotently_preserves_model_and_configuration(workspace,api):
    root,args=workspace
    model=root/'projects/test-study/designs/user-draft.py';model.write_text('user bytes')
    first=(root/'.codex/config.toml').read_bytes()
    result=api.initialize_workspace(args)
    assert result['configuration']['changed'] is False
    assert (root/'.codex/config.toml').read_bytes()==first and model.read_text()=='user bytes'
    args.title='Changed intent'
    with pytest.raises(ValueError,match='differs'):api.initialize_workspace(args)
    assert model.read_text()=='user bytes'


def test_two_workspaces_are_bound_to_their_own_brain_and_state(workspace,tmp_path,api):
    first,_=workspace
    second=tmp_path/'Second workspace'
    api.initialize_workspace(SimpleNamespace(workspace=second,topic=None,title=None,physics=None,citation=None,clients=['codex','claude-code']))
    for root in [first,second]:
        codex=tomllib.loads((root/'.codex/config.toml').read_text())
        claude=json.loads((root/'.mcp.json').read_text())
        for document,key in [(codex,'mcp_servers'),(claude,'mcpServers')]:
            assert set(document[key])=={'cst-function','cst-brain'}
            for value in document[key].values():
                assert value['env']['CST_BRAIN_ROOT']==str(root/'brain')
                assert value['env']['CST_AUTOMATION_ROOT']==str(root)
    assert not (second/'projects/test-study').exists()


def test_configuration_backup_preserves_other_servers_and_roundtrips(workspace,api):
    root,_=workspace
    codex=root/'.codex/config.toml';claude=root/'.mcp.json'
    codex.write_text('model = "custom-model"\n[mcp_servers.other]\ncommand = "custom"\n',encoding='utf-8')
    claude.write_text(json.dumps({'custom':1,'mcpServers':{'other':{'command':'custom'}}}))
    before=[codex.read_bytes(),claude.read_bytes()]
    changed=api.configure(root,['codex','claude-code'])
    assert tomllib.loads(codex.read_text())['mcp_servers']['other']['command']=='custom'
    assert json.loads(claude.read_text())['custom']==1
    api.restore(root,Path(changed['backup'])/'receipt.json')
    assert [codex.read_bytes(),claude.read_bytes()]==before


def test_malformed_config_does_not_partially_modify_other_config(workspace,api):
    root,_=workspace;first=(root/'.codex/config.toml').read_bytes()
    (root/'.mcp.json').write_text('{broken')
    with pytest.raises(json.JSONDecodeError):api.configure(root,['codex','claude-code'])
    assert (root/'.codex/config.toml').read_bytes()==first


def test_restore_refuses_subsequent_user_edits(workspace,api):
    root,_=workspace
    (root/'.codex/config.toml').write_text('model="custom"\n')
    changed=api.configure(root,['codex'])
    with (root/'.codex/config.toml').open('a') as handle:handle.write('\n# User edit\n')
    with pytest.raises(ValueError,match='subsequent'):api.restore(root,Path(changed['backup'])/'receipt.json')


def test_partial_brain_seed_is_repaired_without_overwriting_user_notes(workspace,api):
    root,args=workspace
    note=root/'brain/wiki/foundations/execution-boundary.md';note.write_text('User knowledge')
    (root/'brain/meta/index.md').unlink()
    api.initialize_workspace(args)
    assert (root/'brain/meta/index.md').is_file() and note.read_text()=='User knowledge'


def test_topic_registration_recovers_after_interruption(workspace,api):
    root,args=workspace
    registry=root/'system/projects.json';registry.write_text(json.dumps({'schema_version':1,'projects':[]}))
    topic=root/'projects/test-study/topic.md';before=topic.read_bytes()
    result=api.initialize_workspace(args)
    assert result['topic']['recovered_registration'] and topic.read_bytes()==before


def test_example_drc_and_attempt_refuse_overwrite(workspace,api):
    root,_=workspace;result=api.example(root,'test-study')
    attempt=Path(result['attempt']);before=attempt.read_bytes()
    doc=json.loads(before);assert doc['approved_ranges']=={} and 'approval' not in doc
    assert not (attempt.parent/'evidence').exists()
    assert (attempt.parent/'iterations.jsonl').read_text()==''
    with pytest.raises(FileExistsError):api.example(root,'test-study')
    assert attempt.read_bytes()==before


def test_design_template_has_the_production_builder_signature(workspace,api):
    from cst_lab.topic_workspace import init_design
    root,_=workspace
    target=init_design(root/'projects/test-study',design_id='draft',title='Draft',ports=2,
        acceptance=[dict(id='s21',metric='s2_1_db',band_ghz=[1,2],comparator='>',threshold=-1,mode='pointwise')])
    assert 'def build(overrides=None):' in (target/'model.py').read_text()
    with pytest.raises(NotImplementedError):api.model_attempt(root,'test-study','draft','a01')
    assert not (target/'attempts/a01').exists()


def test_catalog_refuses_duplicate_ids(workspace,api):
    from cst_lab.workspace import registered_projects
    root,_=workspace;registry=root/'system/projects.json'
    doc=json.loads(registry.read_text());doc['projects'].append(doc['projects'][0]);registry.write_text(json.dumps(doc))
    with pytest.raises(ValueError,match='duplicate'):registered_projects(root)


def test_bootstrap_serializes_installation_and_releases_lock(tmp_path):
    bootstrap=load(ROOT/'skills/cst-research/scripts/bootstrap.py','bootstrap_lock')
    with bootstrap.installation_lock(tmp_path):
        with pytest.raises(RuntimeError,match='Another bootstrap'):
            with bootstrap.installation_lock(tmp_path):pass
    with bootstrap.installation_lock(tmp_path):pass


def test_archive_hash_and_member_hash_are_verified(tmp_path):
    bootstrap=load(ROOT/'skills/cst-research/scripts/bootstrap.py','bootstrap_test')
    archive=tmp_path/'runtime.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('MCP/test.py',b'content')
    release=dict(version='test',archive_sha256=bootstrap.sha(archive),files={'MCP/test.py':dict(sha256=hashlib.sha256(b'content').hexdigest())})
    first=bootstrap.deploy(archive,release,tmp_path/'cache');assert bootstrap.deploy(archive,release,tmp_path/'cache')==first
    (first/'MCP/test.py').write_text('tampered')
    with pytest.raises(ValueError,match='changed'):bootstrap.deploy(archive,release,tmp_path/'cache')
    release['archive_sha256']='0'*64
    with pytest.raises(ValueError,match='checksum'):bootstrap.validate_archive(archive,release)


@pytest.mark.parametrize('member',['../escape.py','/absolute','C:/absolute','unsafe\\path'])
def test_archive_cannot_escape_runtime_home(tmp_path,member):
    bootstrap=load(ROOT/'skills/cst-research/scripts/bootstrap.py','bootstrap_traversal')
    archive=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr(member,b'content')
    release=dict(archive_sha256=bootstrap.sha(archive),files={member:dict(sha256=hashlib.sha256(b'content').hexdigest())})
    with pytest.raises(ValueError,match='Unsafe|checksum'):bootstrap.validate_archive(archive,release)


def test_runtime_cad_paths_use_registered_workspace_layout(workspace):
    from cst_cad.paths import CadPaths
    root,_=workspace;paths=CadPaths.resolve(root)
    assert paths.runs_root==root/'runtime' and paths.schemas_root==ROOT/'brain/schemas'


def test_public_payload_contains_no_private_state_or_user_paths():
    for base in ['MCP','brain','skills','examples']:
        for path in (ROOT/base).rglob('*'):
            if not path.is_file() or any(part in {'__pycache__','.pytest_cache'} or part.endswith('.egg-info') for part in path.parts):continue
            assert path.name not in {'approval.key','.env','cst-lab.sqlite3'}
            if path.suffix in {'.py','.md','.json','.toml','.yaml','.txt'}:
                text=path.read_text(encoding='utf-8',errors='replace')
                assert 'C:/CSTLab' not in text
                assert not re.search(r'[A-Z]:[/\\]Users[/\\][^/\\\s]+',text,re.IGNORECASE)


def test_seed_brain_has_no_unbacked_validated_claims():
    from cst_brain.operations import BrainOperations
    from cst_brain.paths import BrainPaths
    # Avoid indexing/mutating the release seed: test copied seed pages only.
    for path in (ROOT/'brain/wiki').rglob('*.md'):
        assert yaml.safe_load(path.read_text().split('---',2)[1])['status']=='seed'
