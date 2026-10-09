#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from cst_cad import drc, emit_vba, ir, verify
from cst_cad.cli import load_model_script

INSTRUCTIONS = """Use CST-CAD as the design-first geometry plane. Geometry is authored as a
parametric model script, frozen into a geometry IR document whose SHA-256 is the
model_intent_id, checked by DRC, and only then turned into CST history blocks.
Never hand-edit generated VBA: change the model script and rebuild. Treat a
passing DRC report as necessary but not sufficient; verify against the saved
.cst with cad_verify_against_cst_tool before trusting the build."""

mcp = FastMCP("cst-cad-mcp", instructions=INSTRUCTIONS)


@mcp.tool()
def cad_build_ir_tool(model_script: str, output: str | None = None) -> dict[str, Any]:
    """Run a parametric design script and write its validated geometry IR document."""
    document = load_model_script(model_script)
    problems = ir.validate(document)
    target = output or str(Path(model_script).resolve().parent.parent / "geometry-ir.json")
    if not problems:
        ir.write(document, target)
    return {
        "status": "ok" if not problems else "invalid",
        "model_id": document.get("model_id"),
        "model_intent_id": document.get("model_intent_id"),
        "short_intent_id": ir.short_intent_id(document),
        "output": target if not problems else None,
        "parameter_provenance": ir.provenance_summary(document),
        "problems": problems,
    }


@mcp.tool()
def cad_run_drc_tool(ir_path: str, output: str | None = None) -> dict[str, Any]:
    """Run spacing, width, net connectivity, short, containment and port rules; write drc-report.json."""
    document = ir.read(ir_path)
    report = drc.run(document)
    target = output or str(Path(ir_path).resolve().parent / "drc-report.json")
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    Path(target).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {
        "status": report["status"],
        "summary": report["summary"],
        "output": target,
        "failed_checks": [check["id"] for check in report["checks"] if check["status"] != "pass"],
    }


@mcp.tool()
def cad_emit_vba_tool(ir_path: str, output_dir: str) -> dict[str, Any]:
    """Generate deterministic, individually named CST history blocks from a geometry IR."""
    return emit_vba.write_blocks(ir.read(ir_path), output_dir)


@mcp.tool()
def cad_emit_step_tool(ir_path: str, step_path: str | None = None, dxf_path: str | None = None) -> dict[str, Any]:
    """Export the IR to STEP and/or DXF through CadQuery for external CAD interchange."""
    from cst_cad import emit_step

    document = ir.read(ir_path)
    written: dict[str, str] = {}
    if step_path:
        written["step"] = str(emit_step.export_step(document, step_path))
    if dxf_path:
        written["dxf"] = str(emit_step.export_dxf(document, dxf_path))
    return {"status": "ok", "written": written}


@mcp.tool()
def cad_verify_against_cst_tool(
    ir_path: str,
    observation_path: str,
    tolerance: float = verify.DEFAULT_TOLERANCE,
    output: str | None = None,
) -> dict[str, Any]:
    """Compare IR expectations against entities and parameters observed in a saved CST project."""
    document = ir.read(ir_path)
    observation = verify.read_observation(observation_path)
    report = verify.compare(document, observation, tolerance=tolerance)
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report["output"] = output
    return report


@mcp.tool()
def cad_diff_ir_tool(left_path: str, right_path: str, tolerance: float = 1e-9) -> dict[str, Any]:
    """Structural diff between two geometry IR documents, tolerant of float noise."""
    return ir.diff(ir.read(left_path), ir.read(right_path), tolerance=tolerance)


if __name__ == "__main__":
    mcp.run()
