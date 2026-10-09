from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CadPaths:
    workspace_root: Path
    schemas_root: Path
    projects_root: Path
    runs_root: Path

    @classmethod
    def resolve(cls, workspace_root: str | Path | None = None) -> "CadPaths":
        configured = workspace_root or os.environ.get("CST_AUTOMATION_ROOT")
        if configured:
            root = Path(configured).expanduser().resolve()
        else:
            root = Path(__file__).resolve().parents[4]
        marker = root / 'workspace.json'
        if marker.is_file():
            from cst_lab.paths import LabPaths
            lab = LabPaths.resolve(root)
            schemas, runs = lab.schemas_root, lab.runs_root
        else:
            schemas, runs = root / 'brain' / 'schemas', root / 'cst_runs'
        return cls(
            workspace_root=root,
            schemas_root=schemas,
            projects_root=root / "projects",
            runs_root=runs,
        )

    @property
    def geometry_ir_schema(self) -> Path:
        return self.schemas_root / "geometry-ir.schema.json"

    def project_dir(self, model_id: str) -> Path:
        return self.projects_root / model_id
