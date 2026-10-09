"""Background Function dispatcher; does not import a CST session on offline routes."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cst_agent_api import FunctionService


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace-root',required=True)
    parser.add_argument('--job',required=True)
    args=parser.parse_args()
    FunctionService(args.workspace_root).work(args.job)


if __name__=='__main__':
    main()
