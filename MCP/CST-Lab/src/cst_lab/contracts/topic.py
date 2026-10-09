"""The ``topic.md`` contract: a research theme."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..paths import LabPaths
from ..validation import load_schema, validate_document
from .frontmatter import read_frontmatter, write_frontmatter

SCHEMA_NAME = "topic.schema.json"


def load_topic(path: Path, paths: LabPaths | None = None) -> tuple[dict[str, Any], str]:
    """Read and validate ``topic.md``, returning its header and prose body."""
    header, body = read_frontmatter(path)
    resolved = paths or LabPaths.resolve()
    validate_document(header, load_schema(resolved.schemas_root, SCHEMA_NAME), resolved.schemas_root)
    directory = Path(path).parent.name
    if header["topic_id"] != directory:
        raise ValueError(
            f"topic_id {header['topic_id']!r} does not match its directory {directory!r}; "
            "the id is how runs, artifacts and Brain notes refer to this topic, so a "
            "mismatch would scatter the same topic across two names"
        )
    return header, body


def write_topic(path: Path, header: dict[str, Any], body: str, paths: LabPaths | None = None) -> Path:
    resolved = paths or LabPaths.resolve()
    validate_document(header, load_schema(resolved.schemas_root, SCHEMA_NAME), resolved.schemas_root)
    return write_frontmatter(path, header, body)
