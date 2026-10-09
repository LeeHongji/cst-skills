---
name: cst-trace-compile
description: Compile a completed CST run workspace and native MCP trace into an immutable case dossier, run manifest, searchable lessons, failures, and strategy candidates. Use after a solver, reconstruction, sweep, optimization, or diagnosis has produced saved artifacts and evidence under the configured runtime root.
license: MIT
---

# CST Trace Compile

Provider: use the separate `cst-brain` MCP configured in the current research workspace. Its tools read and curate that workspace Brain and do not control CST. If unavailable, use the runtime Python and root recorded in `system/deployment.json` to run `python -m cst_brain --brain-root <workspace>/brain`, or report the unavailable service. Do not invent a tool call.

Compile only after the working project is saved and the result evidence has been inspected.

## Preconditions

- The run is under the configured LabPaths.runs_root (`<workspace>/runtime` in this distribution).
- Source and working-copy identities are clear.
- Solver status is known from CST logs or result evidence.
- Important reports, parameter exports, comparisons, and traces are present.

## Function jobs

First inspect `cst_get(job).learning`. If it is `published`, read the returned case and trace instead of recompiling the same run. Failed/skipped/unverified publication is not successful knowledge capture. The maintenance command `<runtime>/scripts/repair-function-learning.py --workspace <workspace> --job <ref> --apply` republishes only the finalized job-bound fact; it never rewrites iteration history or promotes a claim. For historical non-Function runs, use the import workflow below and label their provenance.

## Workflow

1. Call `brain_compile_run_tool` with the run directory, stable case ID, and descriptive title.
2. Read the compiled case with `brain_get_case_tool`.
3. Read the immutable manifest with `brain_get_trace_tool`.
4. Verify artifact hashes, parameter count, CST version, solver status, result summary, and reproducibility label.
5. Create separate failure or strategy candidates for reusable observations. Cite `trace://<case-id>` and specific artifacts.
6. Run `$cst-brain-lint`.
7. Update the hot/index notes only when the case is actively useful.

Do not label a run validated solely because a tool returned success. Do not generalize single-run lessons.

See [trace-contract.md](references/trace-contract.md) for event and manifest expectations.
