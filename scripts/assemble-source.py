"""Import a reviewed CST Automation baseline without private research data.

This maintainer-only tool records source bytes, including uncommitted changes.
It never modifies its input trees and refuses a nonempty destination MCP tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
SKIP = {'.git', '.venv', 'node_modules', '__pycache__', '.pytest_cache',
        '.mypy_cache', '.ruff_cache', 'dist', 'build', 'frontend'}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def eligible(path):
    return not any(part in SKIP or part.endswith('.egg-info') for part in path.parts) and path.suffix not in {'.pyc', '.cst', '.db', '.sqlite3', '.bak', '.lok'} and path.name not in {'.env', 'config.toml'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--automation', type=Path, required=True)
    p.add_argument('--portable', type=Path, required=True)
    args = p.parse_args()
    if (ROOT/'MCP').exists():
        raise FileExistsError('MCP already exists: assembly never overwrites a baseline')
    records = []
    for folder in ['MCP/CST', 'MCP/CST-Lab', 'MCP/CST-CAD', 'MCP/CST-Brain', 'brain/schemas', 'brain/templates', '.agents/skills']:
        for source in sorted((args.portable/folder).rglob('*')):
            relative = source.relative_to(args.portable)
            if not source.is_file() or not eligible(relative):
                continue
            # Unused project examples contain historical paths. Ship a neutral example separately.
            if relative.parts[:3] == ('MCP', 'CST', 'examples'):
                continue
            if relative.parts[:4] == ('MCP','CST-Lab','tests','fixtures'):
                continue  # Historical topic fixture is replaced with a public fixture.
            # Only the vendored runtime scripts and licensing are required. No competing public Skills.
            if 'vendor' in relative.parts and not ('scripts' in relative.parts or source.name == 'LICENSE'):
                continue
            target_relative = Path('skills')/Path(*relative.parts[2:]) if relative.parts[:2] == ('.agents', 'skills') else relative
            target = ROOT/target_relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            original = args.automation/relative
            records.append(dict(path=target_relative.as_posix(), portable_sha256=sha(source),
                                automation_sha256=sha(original) if original.is_file() else None,
                                source_kind='automation-identical' if original.is_file() and sha(original)==sha(source) else 'portable-adaptation'))
    # Runtime must include the same stdio client but no historical validation authorization scripts.
    for name in ['cst-task.py', 'cstlab_data.py']:
        source=args.portable/'scripts'/name
        shutil.copy2(source, ROOT/'scripts'/name)
        records.append(dict(path='scripts/'+name, portable_sha256=sha(source), automation_sha256=None, source_kind='portable-adaptation'))
    model=args.portable.parent/'data/projects/cst-platform-validation/designs/neutral-lowpass/model.py'
    dest=ROOT/'examples/lowpass/model.py';dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(model,dest)
    records.append(dict(path='examples/lowpass/model.py',portable_sha256=sha(model),automation_sha256=None,source_kind='internal-neutral-fixture'))
    def commit(path):
        return subprocess.check_output(['git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
    report=dict(schema_version=1,source_revisions=dict(automation=commit(args.automation),portable=commit(args.portable)),
                notes=['Actual source bytes recorded; Git commit alone is not the baseline.',
                       'Personal workspaces, authorizations, databases and papers are excluded.',
                       'Portable baseline derives from CST Automation; only one executor is shipped.'],files=records)
    out=ROOT/'docs/source-baseline.json';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(files=len(records),bytes=sum((ROOT/r['path']).stat().st_size for r in records))))


if __name__=='__main__':
    main()
