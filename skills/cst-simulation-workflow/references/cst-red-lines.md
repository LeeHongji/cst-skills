# CST Red Lines

These rules protect correctness, source projects, and CST session stability.

## Project Safety

- Do not overwrite the user's source `.cst` file. Work on a copied project unless explicitly told otherwise.
- Preserve companion project folders when copying `.cst` files; CST results and metadata may live beside the file.
- Inspect existing/open projects before writing.
- If multiple projects are open and the target is ambiguous, stop and ask for the target project.
- Save before long solves.
- Report `.lok` locks or cleanup failures; do not hide them.

## Session and Process Safety

- Treat "MCP server alive" and "CST project usable" as separate states.
- Do not assume the Design Environment has a project loaded just because CST is running.
- Keep modeler operations and result-reading operations separate when the API/tooling separates them.
- Close or cleanup the working project at the end of an execution task, unless the user explicitly wants CST left open.
- Record access-denied cleanup residuals as nonblocking only when result evidence is already saved.

## Numerical Correctness

- S-parameters may be complex. Convert to dB with `20*log10(abs(S))`.
- VSWR uses reflection coefficient magnitude, not dB directly.
- `Abs(E)` is electric-field magnitude, not gain.
- Far-field gain claims require `Realized Gain`, `Gain`, or `Directivity`.
- State frequency units explicitly.
- Do not claim convergence, pass/fail, or optimality without evidence.

## Solver Setup

- Do not set frequency range blindly for every solver. Eigenmode workflows may not need `Solver.FrequencyRange`.
- Use solver choice appropriate to task:
  - Time Domain for many broadband antenna S-parameter sweeps.
  - Frequency Domain for narrowband/high-Q accuracy or when requested.
  - HF Eigenmode for cavity/mode frequency tasks.
- Add monitors before solving when monitor outputs are required.
- Rebuild/save after geometry or parameter changes before solving.

## Reporting

- Do not fabricate solver status, mesh counts, convergence, S11, gain, or mode frequencies.
- Include exact result paths and result tree items.
- Mark incomplete result extraction as `needs_validation` or `partial`, not success.
- Record defaults and assumptions that influenced geometry, solver, or result interpretation.

## Automation Scope

- Submit production writes through the three-tool Function facade. Native/runtime
  code and named History blocks belong inside tested backend adapters.
- Use small VBA/history blocks with clear titles.
- Avoid destructive cleanup of unrelated CST processes or unrelated project folders.
- Do not make broad parameter sweeps without previewing case count.
- Do not continue optimization after target is reached unless user asks for more exploration.
