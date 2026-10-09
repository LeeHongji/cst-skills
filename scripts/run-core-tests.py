"""Run independent component suites without pytest module-name collisions."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    reports=[]
    for name in ['CST','CST-Lab','CST-CAD','CST-Brain']:
        target=ROOT/'MCP'/name
        env={k:v for k,v in os.environ.items() if k not in {'CST_AUTOMATION_ROOT','CST_BRAIN_ROOT','CST_TRACE_ROOT','PYTHONPATH'}}
        env['PYTHONUTF8']='1'
        # Editable packages in the invoking interpreter may point at a different
        # released runtime. Always exercise this checkout and its dependencies.
        env['PYTHONPATH']=os.pathsep.join(str(p) for p in [
            ROOT/'MCP/CST',ROOT/'MCP/CST-Lab/src',ROOT/'MCP/CST-CAD/src',
            ROOT/'MCP/CST-Brain/src',ROOT/'scripts'])
        command=[sys.executable,'-m','pytest','tests','-q','--junitxml='+str((args.output/(name+'.xml')).resolve())]
        with (args.output/(name+'.log')).open('w',encoding='utf-8') as log:
            completed=subprocess.run(command,cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT)
        reports.append(dict(component=name,exit_code=completed.returncode))
        print(json.dumps(reports[-1]),flush=True)
    (args.output/'summary.json').write_text(json.dumps(reports,indent=2)+'\n',encoding='utf-8')
    return 0 if all(r['exit_code']==0 for r in reports) else 1


if __name__=='__main__':raise SystemExit(main())
