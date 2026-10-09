"""Internal Guardian child for a currently owned Function job."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
for source in ('MCP/CST', 'MCP/CST-Lab/src', 'MCP/CST-CAD/src'):
    sys.path.insert(0, str(ROOT/source))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace-root', required=True, type=Path)
    parser.add_argument('--job', required=True)
    parser.add_argument('--dispatch-sha256', required=True)
    parser.add_argument('--phase',choices=['execute','reopen'],default='execute')
    parser.add_argument('--reopen-sha256')
    args = parser.parse_args()
    from cst_function_executor import worker
    from cst_trace import trace_function
    trace_function(worker)(args.workspace_root, args.job, args.dispatch_sha256,args.phase,args.reopen_sha256)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        sys.stderr.flush()
        os._exit(1)
    sys.stdout.flush()
    sys.stderr.flush()
    # CST Python bindings can retain shutdown callbacks after closing the DE.
    # All receipts/trace writes above finish first; Guardian owns the process tree.
    os._exit(0)
