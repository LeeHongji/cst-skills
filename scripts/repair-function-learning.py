"""Replay a finalized job into its workspace Brain; no solver or history rewrite."""
import argparse
import json
import os
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'MCP/CST'),str(ROOT/'MCP/CST-Lab/src'),str(ROOT/'MCP/CST-CAD/src')]
from cst_agent_api import FunctionService
from cst_lab.workspace import settings


def main():
    p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,required=True);p.add_argument('--job',required=True);p.add_argument('--apply',action='store_true');args=p.parse_args()
    root=args.workspace.resolve()
    if not settings(root) or settings(root)['software']!=ROOT:raise ValueError('Wrong workspace/runtime binding')
    os.environ['CST_AUTOMATION_ROOT']=str(root);os.environ['CST_BRAIN_ROOT']=str(root/'brain')
    service=FunctionService(root);job=service.store.get(args.job)
    if job['state'] not in ('completed','failed','blocked'):raise ValueError('Only finalized jobs can publish learning')
    report=dict(job=args.job,state=job['state'],applied=args.apply)
    if args.apply:report['learning']=service._publish_learning(job['request'],job['final_intent']['fact'],args.job)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0 if not args.apply or report['learning']['status']=='published' else 2


if __name__=='__main__':raise SystemExit(main())
