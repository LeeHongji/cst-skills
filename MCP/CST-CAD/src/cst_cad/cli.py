from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any

from . import audit, drc, emit_vba, ir, verify
from .paths import CadPaths


def emit(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2))


def load_ir(path: str) -> dict[str, Any]:
    return ir.read(path)


def load_model_script(path: str) -> dict[str, Any]:
    """Import a ``design/model.py`` and call its ``build()`` entry point."""
    script = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f"cst_cad_model_{script.stem}", script)
    if spec is None or spec.loader is None:
        raise ValueError(f"cannot import model script {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if not hasattr(module, "build"):
        raise ValueError(f"model script {script} must define build() -> dict")
    return module.build()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="cst-cad")
    root.add_argument("--workspace-root")
    commands = root.add_subparsers(dest="command", required=True)

    build = commands.add_parser("build-ir", help="Run a design script and write its geometry IR")
    build.add_argument("model_script")
    build.add_argument("--output")

    validate = commands.add_parser("validate-ir", help="Schema and cross-reference validation")
    validate.add_argument("ir_path")

    intent = commands.add_parser("intent-id", help="Print the canonical identity of an IR document")
    intent.add_argument("ir_path")
    intent.add_argument("--show-canonical", action="store_true")

    run_drc = commands.add_parser("run-drc", help="Run design rule checks and write drc-report.json")
    run_drc.add_argument("ir_path")
    run_drc.add_argument("--output")

    review = commands.add_parser('audit', help='Write an offline self-contained geometry review')
    review.add_argument('ir_path')
    review.add_argument('--output', required=True)
    review.add_argument('--source-image')
    review.add_argument('--source-citation')
    review.add_argument('--registration', help='JSON with uniform scale/origin/calibration provenance')

    vba = commands.add_parser("emit-vba", help="Generate deterministic CST history blocks")
    vba.add_argument("ir_path")
    vba.add_argument("--output-dir", required=True)

    step = commands.add_parser("emit-step", help="Export STEP and/or DXF through CadQuery")
    step.add_argument("ir_path")
    step.add_argument("--step")
    step.add_argument("--dxf")
    step.add_argument("--dxf-layer")

    against = commands.add_parser("verify-against-cst", help="Compare IR expectations against a CST observation")
    against.add_argument("ir_path")
    against.add_argument("observation_path")
    against.add_argument("--tolerance", type=float, default=verify.DEFAULT_TOLERANCE)
    against.add_argument("--name-map")
    against.add_argument("--output")
    against.add_argument("--table", action="store_true")

    diff = commands.add_parser("diff-ir", help="Structural diff between two IR documents")
    diff.add_argument("left")
    diff.add_argument("right")
    diff.add_argument("--tolerance", type=float, default=1e-9)

    entities = commands.add_parser("expected-entities", help="List the CST entities the VBA backend will create")
    entities.add_argument("ir_path")
    return root


def main() -> None:
    args = parser().parse_args()
    paths = CadPaths.resolve(args.workspace_root)

    if args.command == 'audit':
        registration = json.loads(Path(args.registration).read_text(encoding='utf-8')) if args.registration else None
        emit(audit.write(load_ir(args.ir_path), args.output, source_image=args.source_image,
                         source_citation=args.source_citation, registration=registration))
        return

    if args.command == "build-ir":
        document = load_model_script(args.model_script)
        problems = ir.validate(document, paths)
        output = args.output or str(Path(args.model_script).resolve().parent.parent / "geometry-ir.json")
        if not problems:
            ir.write(document, output)
        emit(
            {
                "status": "ok" if not problems else "invalid",
                "model_id": document.get("model_id"),
                "model_intent_id": document.get("model_intent_id"),
                "short_intent_id": ir.short_intent_id(document),
                "output": output if not problems else None,
                "parameter_provenance": ir.provenance_summary(document),
                "problems": problems,
            }
        )
    elif args.command == "validate-ir":
        document = load_ir(args.ir_path)
        problems = ir.validate(document, paths)
        emit({"status": "valid" if not problems else "invalid", "problems": problems})
    elif args.command == "intent-id":
        document = load_ir(args.ir_path)
        payload = {
            "model_intent_id": ir.model_intent_id(document),
            "short_intent_id": ir.short_intent_id(document),
            "stored_model_intent_id": document.get("model_intent_id"),
        }
        if args.show_canonical:
            payload["canonical_text"] = ir.canonical_text(document)
        emit(payload)
    elif args.command == "run-drc":
        document = load_ir(args.ir_path)
        report = drc.run(document)
        output = args.output or str(Path(args.ir_path).resolve().parent / "drc-report.json")
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        emit({"status": report["status"], "summary": report["summary"], "output": output})
    elif args.command == "emit-vba":
        document = load_ir(args.ir_path)
        emit(emit_vba.write_blocks(document, args.output_dir))
    elif args.command == "emit-step":
        from . import emit_step

        document = load_ir(args.ir_path)
        written = {}
        if args.step:
            written["step"] = str(emit_step.export_step(document, args.step))
        if args.dxf:
            written["dxf"] = str(emit_step.export_dxf(document, args.dxf, layer=args.dxf_layer))
        emit({"status": "ok", "written": written})
        # OCP corrupts the heap while tearing down its kernel at interpreter exit,
        # which turns a successful export into a 0xC0000374 crash. The files are
        # already flushed, so leave immediately instead.
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0)
    elif args.command == "verify-against-cst":
        document = load_ir(args.ir_path)
        observation = verify.read_observation(args.observation_path)
        name_map = json.loads(Path(args.name_map).read_text(encoding="utf-8")) if args.name_map else None
        report = verify.compare(document, observation, tolerance=args.tolerance, name_map=name_map)
        if args.output:
            Path(args.output).parent.mkdir(parents=True, exist_ok=True)
            Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            report["output"] = args.output
        if args.table:
            print(verify.render_table(report))
            print()
        emit({key: value for key, value in report.items() if key not in {"entities", "parameters"}})
    elif args.command == "diff-ir":
        emit(ir.diff(load_ir(args.left), load_ir(args.right), tolerance=args.tolerance))
    elif args.command == "expected-entities":
        emit(emit_vba.expected_entities(load_ir(args.ir_path)))


if __name__ == "__main__":
    main()
