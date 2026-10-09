"""Minimal bootstrap: deploy cst_runtime to workspace and run uv sync.

Usage:
  uv run python bootstrap.py --skill-path <skill-root>\\scripts

Agent flow:
  1. Read this file from skill -> Write as bootstrap.py at workspace root
  2. uv run python bootstrap.py --skill-path <skill-root>\\scripts
  3. If status=need_fallback: agent writes files manually -> retry
  4. On status=ready: delete bootstrap.py

After success:
  uv run python -m cst_runtime init-workspace ...
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ws = Path.cwd().resolve()
    dst = ws / ".cst_runtime"

    skill_scripts = None
    for i, arg in enumerate(sys.argv[1:], 1):
        if arg == "--skill-path" and i + 1 < len(sys.argv):
            skill_scripts = Path(sys.argv[i + 1]).resolve()
            break

    if skill_scripts:
        src_mod = skill_scripts / "cst_runtime"
        if not src_mod.is_dir():
            print("status=error")
            print("message=--skill-path must point to scripts/ dir containing cst_runtime/")
            return 1
        dst.mkdir(parents=True, exist_ok=True)
        dst_mod = dst / "cst_runtime"
        if dst_mod.exists():
            shutil.rmtree(dst_mod)
        try:
            shutil.copytree(src_mod, dst_mod, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        except PermissionError:
            print("status=need_fallback")
            print(f"message=Permission denied. Agent: read cst_runtime/ files from skill and write to {dst_mod}")
            return 1

        ref_src = skill_scripts.parent / "references"
        if ref_src.exists():
            dst_ref = dst / "references"
            if dst_ref.exists():
                shutil.rmtree(dst_ref)
            shutil.copytree(ref_src, dst_ref, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

        (dst / "pyproject.toml").write_text(
            "[project]\n"
            'name = "cst-runtime"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.12"\n'
            "\n"
            "[build-system]\n"
            'requires = ["setuptools"]\n'
            'build-backend = "setuptools.build_meta"\n'
            "\n"
            "[tool.setuptools.packages.find]\n"
            'where = ["."]\n',
            encoding="utf-8",
        )

    if not (dst / "cst_runtime").is_dir():
        print("status=error")
        print("message=.cst_runtime/cst_runtime/ not found. Provide --skill-path or run fallback first.")
        return 1

    # Workspace pyproject.toml
    pyproject = ws / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(
            "[project]\n"
            'name = "cst-workspace"\n'
            'version = "0.1.0"\n'
            'requires-python = ">=3.12"\n'
            'dependencies = ["cst-runtime"]\n'
            "\n"
            "[tool.uv.sources]\n"
            'cst-runtime = { path = ".cst_runtime", editable = true }\n',
            encoding="utf-8",
        )

    # uv sync
    env = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    try:
        r = subprocess.run(["uv", "sync"], cwd=ws, capture_output=True, text=True, timeout=300, env=env)
        if r.returncode != 0:
            print("status=error")
            err = r.stderr.strip()[:500]
            print(f"message=uv sync failed: {err}")
            return 1
    except Exception as exc:
        print("status=error")
        print(f"message={exc}")
        return 1

    print("status=ready")
    return 0


if __name__ == "__main__":
    sys.exit(main())
