from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource


class SchemaValidationError(ValueError):
    pass


def load_schema(schemas_root: Path, name: str) -> dict[str, Any]:
    path = schemas_root / name
    return json.loads(path.read_text(encoding="utf-8"))


def validate_document(
    document: dict[str, Any], schema: dict[str, Any], schemas_root: Path | None = None
) -> None:
    registry = Registry()
    if schemas_root is not None:
        for path in schemas_root.glob("*.schema.json"):
            candidate = json.loads(path.read_text(encoding="utf-8"))
            if "$id" in candidate:
                registry = registry.with_resource(candidate["$id"], Resource.from_contents(candidate))
    validator = Draft202012Validator(schema, registry=registry)
    errors = sorted(validator.iter_errors(document), key=lambda error: list(error.path))
    if not errors:
        return
    messages = []
    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "$"
        messages.append(f"{location}: {error.message}")
    raise SchemaValidationError("; ".join(messages))
