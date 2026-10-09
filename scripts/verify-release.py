"""Verify generated runtime members still match the maintained release source."""
import hashlib
import importlib.util
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[1]


def verify():
    skill=ROOT/'skills/cst-research'
    release=json.loads((skill/'assets/runtime-release.json').read_text())
    spec=importlib.util.spec_from_file_location('release_bootstrap',skill/'scripts/bootstrap.py')
    bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
    bootstrap.validate_archive(skill/'assets/runtime.zip',release)
    for name,record in release['files'].items():
        if hashlib.sha256((ROOT/name).read_bytes()).hexdigest()!=record['sha256']:
            raise ValueError('Bundled source is stale: '+name)
    skills=sorted(path for path in (ROOT/'skills').iterdir() if (path/'SKILL.md').is_file())
    if len(skills)!=10:raise ValueError('Expected ten Skills')
    for directory in skills:
        if (directory/'LICENSE').read_bytes()!=(ROOT/'LICENSE').read_bytes():
            raise ValueError('Copy installation must retain the MIT notice: '+directory.name)
    return dict(status='pass',archive_sha256=release['archive_sha256'],runtime_files=len(release['files']),skills=len(skills))


if __name__=='__main__':print(json.dumps(verify(),indent=2))
