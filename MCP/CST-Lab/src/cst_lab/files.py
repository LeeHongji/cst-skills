from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


IGNORED_COMPANION_PARTS = {"temp", "cache", "locks", "logfiles"}
IGNORED_COMPANION_SUFFIXES = {".lok", ".lck", ".tmp", ".bak"}


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def companion_inventory(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.is_dir():
        return None
    files: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for item in sorted(path.rglob("*"), key=lambda p: p.as_posix().lower()):
        if not item.is_file():
            continue
        relative = item.relative_to(path)
        if any(part.lower() in IGNORED_COMPANION_PARTS for part in relative.parts):
            continue
        if item.suffix.lower() in IGNORED_COMPANION_SUFFIXES:
            skipped.append({"path": relative.as_posix(), "reason": "volatile-or-lock-file"})
            continue
        try:
            stat = item.stat()
            files.append(
                {
                    "path": relative.as_posix(),
                    "size": stat.st_size,
                    "sha256": sha256_file(item),
                }
            )
        except OSError as exc:
            skipped.append({"path": relative.as_posix(), "reason": type(exc).__name__})
    return {
        "file_count": len(files),
        "total_size": sum(item["size"] for item in files),
        "sha256": sha256_json(files),
        "files": files,
        "skipped": skipped,
    }


def read_json_if_present(path: Path) -> Any | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return None


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()
