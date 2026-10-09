"""cst_runtime.core — CST path auto-detection at import time."""
from __future__ import annotations

import sys
import warnings
import os
from pathlib import Path
from typing import Any

_CST_SEARCH_PATHS: list[str] = [
    str(Path(os.environ["CST_INSTALL_ROOT"]) / "AMD64" / "python_cst_libraries")
    if os.environ.get("CST_INSTALL_ROOT")
    else r"C:\CST\AMD64\python_cst_libraries",
    r"C:\CST\AMD64\python_cst_libraries",
    r"C:\Program Files\CST Studio Suite 2026\AMD64\python_cst_libraries",
    r"C:\Program Files\CST Studio Suite 2025\AMD64\python_cst_libraries",
    r"C:\Program Files (x86)\CST Studio Suite 2026\AMD64\python_cst_libraries",
]

_cst_found = False
try:
    _pp = Path.cwd().resolve() / "pyproject.toml"
    if _pp.exists():
        import tomllib
        _src = tomllib.loads(_pp.read_text(encoding="utf-8")).get("tool", {}).get("uv", {}).get("sources", {}).get("cst-studio-suite-link", {})
        if isinstance(_src, dict) and _src.get("path"):
            _p = Path(_src["path"]).resolve()
            if str(_p) not in sys.path:
                sys.path.insert(0, str(_p))
                _cst_found = True
except Exception:
    pass

if not _cst_found:
    _probe_roots = [
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
    ]
    for _root in _probe_roots:
        if not _root.is_dir():
            continue
        try:
            for _child in _root.iterdir():
                if _child.is_dir() and "CST Studio Suite" in _child.name:
                    _pypath = _child / "AMD64" / "python_cst_libraries"
                    if _pypath.is_dir() and str(_pypath) not in sys.path:
                        sys.path.insert(0, str(_pypath))
                        _cst_found = True
                        break
        except PermissionError:
            continue
        if _cst_found:
            break

if not _cst_found:
    for _p in _CST_SEARCH_PATHS:
        if Path(_p).is_dir() and str(_p) not in sys.path:
            sys.path.insert(0, _p)
            break

warnings.filterwarnings("ignore", category=DeprecationWarning)
