"""Small process-safe primitives shared by approval and job state."""
from contextlib import contextmanager
import errno
import json
import os
from pathlib import Path
import tempfile
import time


@contextmanager
def process_lock(path: Path, timeout: float = 10.):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        if path.stat().st_size == 0:
            handle.write(b'0'); handle.flush()
        end = time.monotonic()+timeout
        while True:
            try:
                handle.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= end:
                    raise TimeoutError(f'process lock busy: {path}')
                time.sleep(.05)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def _replace_retry(source, target, timeout=2.):
    """Windows readers can briefly deny rename; keep the old file intact.

    Retry only Windows access/sharing violations. Never fall back to an in-place
    write or remove the destination, which would expose partial/missing JSON.
    """
    deadline=time.monotonic()+timeout
    delay=.01
    while True:
        try:
            os.replace(source,target)
            return
        except PermissionError as exc:
            if getattr(exc,'winerror',None) not in (5,32,33) or time.monotonic()>=deadline:
                raise
            time.sleep(delay)
            delay=min(delay*2,.1)


def atomic_json(path: Path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name+'.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
        _replace_retry(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def read_json(path: Path, timeout=2.):
    """Read one complete snapshot despite a brief Windows replace conflict.

    Missing or malformed files and non-Windows permission errors are not
    contention. Propagate them; never return a stale snapshot or empty state.
    """
    path=Path(path)
    deadline=time.monotonic()+timeout
    delay=.01
    while True:
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except PermissionError as exc:
            # CPython's CRT file open reports a real Windows sharing violation
            # as EACCES without winerror. An enduring ACL denial still raises
            # after the same bounded wait; it never becomes an empty snapshot.
            windows_conflict=(getattr(exc,'winerror',None) in (5,32,33) or
                os.name=='nt' and getattr(exc,'winerror',None) is None and exc.errno==errno.EACCES)
            if not windows_conflict or time.monotonic()>=deadline:
                raise
            time.sleep(delay)
            delay=min(delay*2,.1)
