from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from .workspace import default_workspace, settings

_EXTENDED_PREFIX = "\\\\?\\"


def long_path(path: Path) -> Path:
    """Return a form of ``path`` that survives the Windows 260-character limit.

    Deep CST export trees routinely exceed ``MAX_PATH``. Without the
    extended-length prefix, ``stat``/``open``/``unlink`` report such a file as
    missing, which would make the catalog prune real evidence and would make the
    reclamation safety re-checks unreliable. ``os.scandir`` traversal is
    unaffected, so only absolute-path operations need this.
    """

    if sys.platform != "win32":
        return path
    text = str(path)
    if text.startswith(_EXTENDED_PREFIX):
        return path
    absolute = os.path.abspath(text)
    if absolute.startswith("\\\\"):
        return Path(f"{_EXTENDED_PREFIX}UNC\\{absolute.lstrip(chr(92))}")
    return Path(f"{_EXTENDED_PREFIX}{absolute}")


@dataclass(frozen=True)
class LabPaths:
    workspace_root: Path
    registry_root: Path
    database: Path
    schemas_root: Path

    @classmethod
    def resolve(cls, workspace_root: str | Path | None = None) -> "LabPaths":
        configured = workspace_root or os.environ.get("CST_AUTOMATION_ROOT")
        if configured:
            root = Path(configured).expanduser().resolve()
        else:
            root = default_workspace(Path(__file__).resolve().parents[4])
        layout = settings(root)
        registry = root / "system/lab" if layout else root / "cst_runs/_registry"
        return cls(
            workspace_root=root,
            registry_root=registry,
            database=registry / "cst-lab.sqlite3",
            schemas_root=(layout["software"] if layout else root) / "brain/schemas",
        )

    @property
    def runs_root(self) -> Path:
        return self.workspace_root / ("runtime" if settings(self.workspace_root) else "cst_runs")

    def ensure(self) -> None:
        self.registry_root.mkdir(parents=True, exist_ok=True)
