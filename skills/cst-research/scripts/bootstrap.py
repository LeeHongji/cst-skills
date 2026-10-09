"""Deploy the bundled CST runtime, then initialize an independent workspace.

Python 3.13 is required. Nothing in this script starts CST or grants approval.
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import uuid
import venv
import zipfile

SKILL = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


@contextmanager
def installation_lock(cache):
    """OS-owned lock: crash recovery never requires deleting a lock file."""
    import msvcrt
    cache.mkdir(parents=True,exist_ok=True)
    with (cache/'.bootstrap.lock').open('a+b') as handle:
        if handle.tell()==0:
            handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as exc:
            raise RuntimeError('Another bootstrap owns this runtime home; retry after it finishes') from exc
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)


def validate_archive(archive, release):
    if sha(archive) != release['archive_sha256']:
        raise ValueError('Runtime archive checksum mismatch')
    with zipfile.ZipFile(archive) as z:
        names=set()
        for item in z.infolist():
            name=PurePosixPath(item.filename)
            if name.is_absolute() or '..' in name.parts or '\\' in item.filename or ':' in item.filename or stat.S_ISLNK(item.external_attr >> 16):
                raise ValueError('Unsafe runtime archive member')
            if item.filename.casefold() in names:
                raise ValueError('Duplicate runtime archive member')
            names.add(item.filename.casefold())
            record=release['files'].get(item.filename)
            if not record or hashlib.sha256(z.read(item)).hexdigest()!=record['sha256']:
                raise ValueError('Runtime member checksum mismatch: '+item.filename)
        if len(names)!=len(release['files']):
            raise ValueError('Incomplete runtime archive')


def deploy(archive, release, cache):
    validate_archive(archive,release)
    target=cache/(release['version']+'-'+release['archive_sha256'][:12])
    if target.exists():
        if target.is_symlink() or target.is_junction():
            raise ValueError('Runtime installation must not be a link')
        for name,record in release['files'].items():
            path=target/name
            if not path.is_file() or path.is_symlink() or sha(path)!=record['sha256']:
                raise ValueError('Existing versioned runtime changed: '+name)
        return target
    cache.mkdir(parents=True,exist_ok=True)
    stage=cache/('.pending-'+uuid.uuid4().hex)
    stage.mkdir()
    try:
        with zipfile.ZipFile(archive) as z:
            z.extractall(stage)
        (stage/'runtime-release.json').write_text(json.dumps(release,indent=2)+'\n',encoding='utf-8')
        stage.replace(target)
    except Exception:
        # Remove only our own fresh staging tree. Keep any preexisting data untouched.
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return target


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--runtime-home',type=Path)
    parser.add_argument('--topic')
    parser.add_argument('--title')
    parser.add_argument('--physics')
    parser.add_argument('--citation')
    parser.add_argument('--clients',nargs='+',choices=['codex','claude-code'],default=['codex','claude-code'])
    args=parser.parse_args()
    if sys.version_info[:2]!=(3,13):
        parser.error('Use Python 3.13; specify its executable explicitly if necessary')
    if os.name!='nt':
        parser.error('This first runtime release supports Windows CST execution')
    if args.topic and not all([args.title,args.physics,args.citation]):
        parser.error('--topic requires --title, --physics and --citation')
    archive=SKILL/'assets/runtime.zip'
    release=json.loads((SKILL/'assets/runtime-release.json').read_text(encoding='utf-8'))
    cache=(args.runtime_home or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'CSTSkills/runtimes').resolve()
    workspace=args.workspace.resolve()
    if workspace==cache or workspace.is_relative_to(cache) or cache.is_relative_to(workspace):
        parser.error('Runtime home and research workspace must be separate trees')
    with installation_lock(cache):
        runtime,python=install_runtime(archive,release,cache)
    command=[str(python),str(runtime/'scripts/cst-research.py'),'init','--workspace',str(workspace),'--clients',*args.clients]
    if args.topic:
        command.extend(['--topic',args.topic,'--title',args.title,'--physics',args.physics,'--citation',args.citation])
    subprocess.run(command,check=True)
    print(json.dumps(dict(runtime=str(runtime),workspace=str(workspace),python=str(python),
                         next='Open the workspace in your Agent; trust/reload MCP and invoke cst-research.'),ensure_ascii=False))


def install_runtime(archive,release,cache):
    runtime=deploy(archive,release,cache)
    python=runtime/'.venv/Scripts/python.exe'
    if not python.is_file():
        venv.EnvBuilder(with_pip=True).create(runtime/'.venv')
    installed=runtime/'.venv/cst-skills-installed.json'
    if not installed.is_file():
        print('Installing pinned Python dependencies...',flush=True)
        subprocess.run([str(python),'-m','pip','install','-r',str(runtime/'requirements-lock.txt')],check=True)
        for component in ['CST','CST-Lab','CST-CAD','CST-Brain']:
            subprocess.run([str(python),'-m','pip','install','--no-deps','-e',str(runtime/'MCP'/component)],check=True)
        subprocess.run([str(python),'-m','pip','check'],check=True)
        installed.write_text(json.dumps(dict(archive_sha256=release['archive_sha256']))+'\n',encoding='utf-8')
    elif json.loads(installed.read_text())['archive_sha256']!=release['archive_sha256']:
        raise ValueError('Installed environment belongs to a different runtime archive')
    return runtime,python


if __name__=='__main__':
    main()
