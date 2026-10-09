"""Fingerprint Git-selected publication files, excluding this manifest itself."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
MANIFEST='docs/distribution-files.json'
FORBIDDEN={'cst_runs','runtime','system','projects','output','tmp','reports','node_modules','.venv'}


def main():
    names=subprocess.check_output(['git','-C',str(ROOT),'ls-files','-z']).decode('utf-8').split('\0')
    records=[]
    for name in sorted(filter(None,names)):
        if name==MANIFEST:continue
        relative=Path(name);path=ROOT/relative
        if relative.parts[0] in FORBIDDEN or path.is_symlink() or path.is_junction():
            raise ValueError('Not a publication source file: '+name)
        if path.suffix.lower() in {'.cst','.pyd','.dll','.sqlite3','.db','.pyc','.lok'} or path.name in {'.env','approval.key'}:
            raise ValueError('Private/native/generated artifact selected: '+name)
        content=path.read_bytes()
        records.append(dict(path=name,bytes=len(content),sha256=hashlib.sha256(content).hexdigest()))
    (ROOT/MANIFEST).write_text(json.dumps(dict(schema_version=1,scope='Git-selected publication sources; excludes this manifest to avoid self-reference',
        files=records),indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(files=len(records),bytes=sum(r['bytes'] for r in records))))


if __name__=='__main__':main()
