from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class BrainPaths:
    root: Path

    @classmethod
    def resolve(cls, root: str | Path | None = None) -> "BrainPaths":
        if root:
            resolved = Path(root).expanduser().resolve()
        elif os.environ.get("CST_BRAIN_ROOT"):
            resolved = Path(os.environ["CST_BRAIN_ROOT"]).expanduser().resolve()
        else:
            workspace = Path(__file__).resolve().parents[4]
            resolved = (workspace / "brain").resolve()
        return cls(resolved)

    @property
    def workspace(self) -> Path:
        return self.root.parent

    @property
    def wiki(self) -> Path:
        return self.root / "wiki"

    @property
    def inbox(self) -> Path:
        return self.root / "inbox"

    @property
    def raw(self) -> Path:
        return self.root / "raw"

    @property
    def meta(self) -> Path:
        return self.root / "meta"

    @property
    def state(self) -> Path:
        return self.root / ".state"

    @property
    def index_file(self) -> Path:
        return self.state / "bm25" / "index.json"

    @property
    def raw_manifest(self) -> Path:
        return self.raw / "manifest.json"

    def ensure(self) -> None:
        for path in (
            self.root,
            self.wiki,
            self.inbox,
            self.raw / "sources",
            self.raw / "trace-snapshots",
            self.meta,
            self.state / "bm25",
        ):
            path.mkdir(parents=True, exist_ok=True)

    def logical_uri(self, path: str | Path) -> str:
        value = Path(path).resolve()
        try:
            return f"brain://{value.relative_to(self.root).as_posix()}"
        except ValueError:
            pass
        runs = (self.workspace / ("runtime" if (self.workspace / "workspace.json").is_file() else "cst_runs")).resolve()
        try:
            return f"run://{value.relative_to(runs).as_posix()}"
        except ValueError:
            return f"source://{value.name}"

