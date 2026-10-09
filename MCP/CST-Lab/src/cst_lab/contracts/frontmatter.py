"""YAML frontmatter for the two Markdown contracts.

``topic.md`` and ``design.md`` are read by people and by tooling, so the
machine-readable part sits in a frontmatter block and the prose follows it.  The
parser is strict on purpose: a document whose frontmatter is missing, unterminated,
or not a mapping is an error rather than an empty header, because a silently empty
header would mean a design with no acceptance gates -- and a design with no gates
would let every iteration report ``not_evaluated`` while looking like it ran.
"""

from __future__ import annotations

import datetime as _datetime
from pathlib import Path
from typing import Any

import yaml

DELIMITER = "---"


def _iso_dates(value: Any) -> Any:
    """Render YAML's native dates back as ISO strings, recursively.

    ``created: 2026-09-10`` is the natural way to write a date in YAML and
    ``yaml.safe_load`` turns it into a ``datetime.date``.  The schemas ask for a
    string with ``format: date``, so the natural spelling was rejected while the
    quoted one was accepted -- a contract that refuses the obvious spelling of a
    field it defines is a defect in the contract, not in the document.  Converting
    here rather than loosening the schema keeps one representation downstream: every
    consumer sees a string, and a date is still checked for being a real date by YAML
    itself before it ever gets here.
    """
    if isinstance(value, _datetime.datetime):
        return value.isoformat()
    if isinstance(value, _datetime.date):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _iso_dates(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_iso_dates(item) for item in value]
    return value


class FrontmatterError(ValueError):
    """Raised when a Markdown contract's frontmatter cannot be trusted."""


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split ``text`` into its frontmatter mapping and its prose body."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != DELIMITER:
        raise FrontmatterError(f"document must begin with a {DELIMITER!r} frontmatter block")
    for index in range(1, len(lines)):
        if lines[index].strip() == DELIMITER:
            header = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :]).lstrip("\n")
            break
    else:
        raise FrontmatterError(f"frontmatter block is never closed with {DELIMITER!r}")

    try:
        loaded = yaml.safe_load(header) if header.strip() else None
    except yaml.YAMLError as exc:
        raise FrontmatterError(f"frontmatter is not valid YAML: {exc}") from exc
    if loaded is None:
        raise FrontmatterError("frontmatter block is empty")
    if not isinstance(loaded, dict):
        raise FrontmatterError(f"frontmatter must be a mapping, got {type(loaded).__name__}")
    return _iso_dates(loaded), body


def read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    return split_frontmatter(Path(path).read_text(encoding="utf-8"))


def write_frontmatter(path: Path, header: dict[str, Any], body: str) -> Path:
    """Write a Markdown contract, keeping the header key order as given.

    ``sort_keys=False`` matters for review: these files are read by people, and a
    design whose gates reorder themselves alphabetically on every write produces
    diff noise that hides the change that was actually made.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    dumped = yaml.safe_dump(header, sort_keys=False, allow_unicode=True, default_flow_style=False)
    text = f"{DELIMITER}\n{dumped}{DELIMITER}\n\n{body.strip()}\n"
    target.write_text(text, encoding="utf-8")
    return target
