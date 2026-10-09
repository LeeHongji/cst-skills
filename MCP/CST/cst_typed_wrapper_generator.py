from __future__ import annotations

import keyword
import sys
from pathlib import Path
from typing import Any

from cst_runtime_cli_bridge import PROJECT_ROOT, RUNTIME_SCRIPT_ROOT


def _ensure_runtime_import_path() -> None:
    runtime_root = str(RUNTIME_SCRIPT_ROOT)
    if runtime_root not in sys.path:
        sys.path.insert(0, runtime_root)


def load_runtime_schema_catalog(category: str | None = None) -> dict[str, Any]:
    """Load the vendored runtime command catalog without spawning the CLI."""
    _ensure_runtime_import_path()
    from cst_runtime.tools import all_defs, build_args_templates, build_json_schemas

    definitions = all_defs()
    schemas = build_json_schemas()
    templates = build_args_templates()
    tools: dict[str, Any] = {}
    for name, definition in sorted(definitions.items()):
        if category and definition.get("category") != category:
            continue
        tools[name] = {
            "name": name,
            "function_name": tool_name_to_function(name),
            "category": definition.get("category"),
            "risk": definition.get("risk"),
            "description": definition.get("description", ""),
            "json_schema": schemas.get(name, {}),
            "args_template": templates.get(name, {}),
        }
    return {"ok": True, "count": len(tools), "tools": tools}


def tool_name_to_function(tool_name: str) -> str:
    result = []
    for char in tool_name.replace("-", "_"):
        result.append(char if char.isalnum() or char == "_" else "_")
    name = "".join(result).strip("_") or "tool"
    if name[0].isdigit():
        name = f"tool_{name}"
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def _param_name(name: str) -> str:
    result = []
    for char in name:
        result.append(char if char.isalnum() or char == "_" else "_")
    py_name = "".join(result).strip("_") or "value"
    if py_name[0].isdigit():
        py_name = f"arg_{py_name}"
    if keyword.iskeyword(py_name):
        py_name = f"{py_name}_"
    return py_name


def _annotation(prop: dict[str, Any]) -> str:
    ptype = prop.get("type", "string")
    if isinstance(ptype, list):
        ptype = next((item for item in ptype if item != "null"), "string")
    return {
        "string": "str",
        "number": "float",
        "integer": "int",
        "boolean": "bool",
        "array": "list[Any]",
        "object": "dict[str, Any]",
    }.get(str(ptype), "Any")


def _default_expr(prop: dict[str, Any]) -> str:
    if "default" in prop:
        return repr(prop["default"])
    if prop.get("type") == "array":
        return "None"
    if prop.get("type") == "object":
        return "None"
    return "None"


def _function_source(tool_name: str, record: dict[str, Any]) -> str:
    schema = record.get("json_schema", {})
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    mappings: list[tuple[str, str, bool, dict[str, Any]]] = []
    used: set[str] = set()
    for field, prop in properties.items():
        py_name = _param_name(field)
        while py_name in used or py_name in {"extra", "workspace", "timeout_seconds"}:
            py_name = f"{py_name}_"
        used.add(py_name)
        mappings.append((field, py_name, field in required, prop))

    required_params = [item for item in mappings if item[2]]
    optional_params = [item for item in mappings if not item[2]]
    params = []
    for _, py_name, _, prop in required_params:
        params.append(f"{py_name}: {_annotation(prop)}")
    for _, py_name, _, prop in optional_params:
        params.append(f"{py_name}: {_annotation(prop)} | None = {_default_expr(prop)}")
    params.extend(["workspace: str | None = None", "timeout_seconds: float | None = None", "**extra: Any"])
    signature = ", ".join(params)
    description = (record.get("description") or f"Invoke {tool_name}.").replace('"""', '\\"\\"\\"')

    lines = [f"def {tool_name_to_function(tool_name)}(*, {signature}) -> dict[str, Any]:",
             f'    """{description}"""',
             "    args: dict[str, Any] = {}"]
    for field, py_name, is_required, _ in mappings:
        if is_required:
            lines.append(f'    args[{field!r}] = {py_name}')
        else:
            lines.append(f"    if {py_name} is not None:")
            lines.append(f'        args[{field!r}] = {py_name}')
    lines.append("    args.update(extra)")
    lines.append(f"    return invoke_runtime_tool({tool_name!r}, args, workspace=workspace, timeout_seconds=timeout_seconds)")
    return "\n".join(lines)


def generate_typed_wrappers(
    output_path: str | None = None,
    selected_tools: list[str] | None = None,
    category: str | None = None,
    overwrite: bool = True,
) -> dict[str, Any]:
    catalog = load_runtime_schema_catalog(category=category)
    records = catalog["tools"]
    if selected_tools:
        missing = sorted(set(selected_tools) - set(records))
        if missing:
            raise ValueError(f"unknown tools: {', '.join(missing)}")
        records = {name: records[name] for name in selected_tools}

    target = Path(output_path).expanduser().resolve() if output_path else PROJECT_ROOT / "generated" / "cst_toolbox_wrappers.py"
    if target.exists() and not overwrite:
        raise FileExistsError(str(target))
    target.parent.mkdir(parents=True, exist_ok=True)

    chunks = [
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "from cst_runtime_cli_bridge import invoke_runtime_tool",
        "",
        "",
    ]
    for name, record in records.items():
        chunks.append(_function_source(name, record))
        chunks.append("")
        chunks.append("")
    target.write_text("\n".join(chunks).rstrip() + "\n", encoding="utf-8")
    return {
        "ok": True,
        "output_path": str(target),
        "tool_count": len(records),
        "functions": [tool_name_to_function(name) for name in records],
    }
