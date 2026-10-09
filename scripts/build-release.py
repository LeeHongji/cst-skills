"""Deterministically bundle the one CST runtime into the research entry Skill."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]
VERSION='0.1.0'
SKIP={'.venv','.git','__pycache__','.pytest_cache','node_modules','dist','build'}


def main():
    files=[]
    for folder in ['MCP','brain','examples']:
        files.extend(p for p in (ROOT/folder).rglob('*') if p.is_file())
    files.extend(ROOT/'scripts'/name for name in ['cst-research.py','cstlab_data.py','cst-task.py','protocol-check.py','run-core-tests.py','verify-live.py','plot-review.py','repair-function-learning.py'])
    files.extend((ROOT/'scripts/validation').glob('*.py'))
    files.extend(ROOT/name for name in ['requirements-lock.txt','requirements-dev.txt','LICENSE','THIRD_PARTY_NOTICES'])
    files.extend([ROOT/'docs/source-baseline.json',ROOT/'docs/source-adaptations.json',ROOT/'docs/verification-helper-origins.json'])
    files=[p for p in files if not any(part in SKIP or part.endswith('.egg-info') for part in p.relative_to(ROOT).parts) and p.suffix!='.pyc']
    assets=ROOT/'skills/cst-research/assets';assets.mkdir(parents=True,exist_ok=True)
    archive=assets/'runtime.zip';records={}
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for path in sorted(files):
            name=path.relative_to(ROOT).as_posix();content=path.read_bytes()
            info=zipfile.ZipInfo(name,date_time=(2026,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=(0o100644<<16)
            z.writestr(info,content)
            records[name]=dict(bytes=len(content),sha256=hashlib.sha256(content).hexdigest())
    report=dict(schema_version=1,version=VERSION,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),files=records)
    (assets/'runtime-release.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(version=VERSION,files=len(records),archive_bytes=archive.stat().st_size,sha256=report['archive_sha256'])))


if __name__=='__main__':
    main()
