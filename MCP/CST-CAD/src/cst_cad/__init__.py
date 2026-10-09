"""CST-CAD: design-first parametric geometry plane for CST Automation.

Geometry lives here as a text IR under version control; the ``.cst`` binary is
a regenerable solver input produced from it.
"""

from __future__ import annotations

from . import audit, drc, dsl, emit_step, emit_vba, ir, verify
from .dsl import Expr, ModelBuilder, NetBuilder
from .paths import CadPaths

__all__ = [
    "CadPaths",
    "Expr",
    "ModelBuilder",
    "NetBuilder",
    "audit",
    "drc",
    "dsl",
    "emit_step",
    "emit_vba",
    "ir",
    "verify",
]

__version__ = "0.1.0"
