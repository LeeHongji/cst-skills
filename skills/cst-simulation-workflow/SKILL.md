---
name: cst-simulation-workflow
description: Plan and execute supported CST experiments through cst_run, cst_get and cst_approve. Use for model audit, guarded simulation, exported-result analysis, comparison and confirmation. Check adapter coverage before promising additional CST solver or readback features.
license: MIT
---

# CST Simulation Workflow

Use `cst_run`, `cst_get`, and `cst_approve` as the production execution boundary.
They are MCP tools, backed internally by CAD, Lab and Guardian. The separate
`cst-brain` MCP serves knowledge retrieval and curation, not solver control.

## Workflow

1. Retrieve relevant evidence with `$cst-brain-query`. Identify the topic,
   design and attempt; the facade resolves the topic's registered data project.
2. Prepare the topic/design/attempt contracts and a deterministic `build(overrides=None)`
   geometry source with `$cst-vba-modeling`. Use existing schemas and examples;
   `cst_run` does not create research contracts from natural language.
3. Submit `operation=audit, fidelity=offline` and inspect its returned CAD/DRC
   artifacts with `cst_get`. Resolve geometry or setup errors before solving.
4. Bind the reviewed version and allowed ranges using `cst_approve`. Existing
   scoped user delegation is valid; never claim personal viewing for delegation.
5. Submit `operation=simulate` with `fidelity=screen` or `confirm`, a stable
   request_id, explicit parameters, and a reason. Retry an uncertain request
   with the SAME request_id. A deliberate new iteration gets a new ID.
6. Query `cst_get` until terminal. Completed execution and passing physics
   acceptance are separate. Confirm convergence, exported curves, immutable
   evidence and cache-free reopen; a cache hit is not a new solve.
7. Inspect the job-bound `learning` receipt. Report a publication error separately
   from a successful simulation; do not silently claim knowledge was captured.

`audit`, `analyze`, `compare` use `offline`; `simulate` uses `screen`/`confirm`.
Plan-only requests do not submit work. Offline analysis uses retained curve
files and acceptance contracts, not an unverified live CST result tree.

## Boundaries

- Do not use legacy native/runtime/toolbox write tools or topic solver scripts
  as fallback execution paths. Unsupported geometry/solver capabilities require
  a tested backend adapter before a production run.
- Sweep/optimization planners may choose candidate parameters; each execution
  must use this same lifecycle. See `references/workflow.md`.
- Preserve sources and historical evidence. Save/copy/lock/solve/export are
  worker responsibilities, not a second manually managed Agent lifecycle.
- Core verification is not complete CST feature coverage. In particular,
  arbitrary existing-project edits, eigenmode/far-field export, and detailed
  getters must be checked against current adapter capabilities.
- Complex S parameters use `20*log10(abs(S))`; `Abs(E)` is not gain.

Read `references/mcp-tool-map.md` for service boundaries,
`references/parameter-policy.md` for engineering inputs,
`references/result-validation.md` for result criteria, and
`references/cst-red-lines.md` for CST correctness constraints.
