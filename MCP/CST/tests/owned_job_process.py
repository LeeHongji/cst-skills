"""Native lifetime test helper. It launches Python only, never CST."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def record(path,document):
    temporary=path.with_suffix('.pending')
    temporary.write_text(json.dumps(document),encoding='utf-8')
    os.replace(temporary,path)


def main():
    mode=sys.argv[1];root=Path(sys.argv[2])
    if mode=='supervise':
        from cst_guardian.supervisor import run_guarded
        record(root/'supervisor.json',dict(pid=os.getpid()))
        run_guarded([sys.executable,__file__,'worker',str(root)],log_dir=root/'guardian',
                    scope_worker_descendants=True,timeout_s=30,poll_interval_s=.02)
    elif mode=='worker':
        child=subprocess.Popen([sys.executable,__file__,'grandchild',str(root)],
            creationflags=subprocess.CREATE_NO_WINDOW,stdin=subprocess.DEVNULL)
        record(root/'worker.json',dict(pid=os.getpid(),launcher_pid=child.pid))
        time.sleep(30)
    elif mode=='grandchild':
        record(root/'grandchild.json',dict(pid=os.getpid()))
        time.sleep(30)


if __name__=='__main__':main()
