"""The ``iterations.jsonl`` contract: append-only single source of truth.

Append-only is enforced here rather than trusted.  Every write validates the line
against the schema first and then appends it, and :func:`append_iteration` refuses
an iteration number that already exists.  A rewritten history would make the file
useless for the two things it is for: reconstructing what was actually run, and
answering "what did changing this parameter do" without re-solving anything.
"""

from __future__ import annotations

import json
import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from ..paths import LabPaths
from ..atomic import process_lock
from ..validation import load_schema, validate_document

SCHEMA_NAME = "iteration.schema.json"
SCHEMA_VERSION = 1


def iteration_lock_path(path: Path, paths: LabPaths) -> Path:
    """Operational locks never belong in a durable projects/ evidence package."""
    identity = os.path.normcase(str(Path(path).resolve()))
    return paths.registry_root / 'contract-locks' / (hashlib.sha256(identity.encode('utf-8')).hexdigest()+'.lock')


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def iteration_line(
    *,
    iter_number: int,
    param_delta: Mapping[str, Any] | None = None,
    setup_delta: Mapping[str, Any] | None = None,
    drc: str = "skipped",
    parent: int | None = None,
    ts: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build one iteration record with the required fields present.

    ``param_delta`` and ``setup_delta`` are always written, empty dicts included.
    An absent key would be indistinguishable from "nothing changed", and the
    difference between those two is what tells a geometry study apart from a mesh
    convergence study when the file is read back months later.
    """
    line: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "iter": int(iter_number),
        "ts": ts or _now(),
        "parent": parent,
        "param_delta": dict(param_delta or {}),
        "setup_delta": dict(setup_delta or {}),
        "drc": drc,
    }
    line.update(extra)
    return line


def _check_order(document: Mapping[str, Any], existing: list[dict[str, Any]]) -> None:
    """Numbers increase (gaps are allowed); parents name an earlier local row."""
    number = document["iter"]
    seen = {row["iter"] for row in existing}
    if number in seen:
        raise ValueError(f"iteration {number} is already recorded; history is append-only")
    if existing and number <= existing[-1]["iter"]:
        raise ValueError("iteration numbers must be strictly increasing (append-only)")
    parent = document.get("parent")
    if parent is not None and parent not in seen:
        raise ValueError(f"parent iteration {parent} must refer to an earlier recorded iteration")
    if document.get("provenance") == "legacy" and document.get("audited") is not False:
        raise ValueError("legacy iterations must explicitly carry audited: false")


def read_iterations(path: Path, paths: LabPaths | None = None) -> list[dict[str, Any]]:
    """Read every line, failing loudly on a corrupt one.

    Skipping an unparseable line would quietly shorten the history and make a
    sensitivity table computed from it wrong in a way nobody would notice.
    """
    target = Path(path)
    if not target.exists():
        return []
    resolved = paths or LabPaths.resolve()
    schema = load_schema(resolved.schemas_root, SCHEMA_NAME)
    records = []
    for number, text in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        if not text.strip():
            continue
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{target}:{number}: corrupt iteration line: {exc}") from exc
        try:
            validate_document(document, schema, resolved.schemas_root)
            _check_order(document, records)
        except ValueError as exc:
            raise ValueError(f"{target}:{number}: invalid iteration: {exc}") from exc
        records.append(document)
    return records


def iterate_records(path: Path) -> Iterator[dict[str, Any]]:
    yield from read_iterations(path)


def next_iteration_number(path: Path) -> int:
    existing = read_iterations(path)
    return max((int(record["iter"]) for record in existing), default=-1) + 1


def append_iteration(
    path: Path, line: Mapping[str, Any], paths: LabPaths | None = None
) -> dict[str, Any]:
    """Validate and append one iteration, refusing to overwrite history."""
    resolved = paths or LabPaths.resolve()
    document = dict(line)
    validate_document(document, load_schema(resolved.schemas_root, SCHEMA_NAME), resolved.schemas_root)

    target = Path(path)
    with process_lock(iteration_lock_path(target, resolved)):
        existing = read_iterations(target, resolved)
        _check_order(document, existing)
        target.parent.mkdir(parents=True, exist_ok=True)
        needs_separator = target.exists() and target.stat().st_size and not target.read_bytes().endswith(b'\n')
        with target.open("a", encoding="utf-8", newline="\n") as handle:
            if needs_separator:
                handle.write('\n')
            handle.write(json.dumps(document, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    return document
