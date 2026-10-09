---
name: cst-vba-modeling
description: Prepare deterministic CST model adapters and CAD IR for the Function facade; extend backend History/VBA emission and readback when needed. Use for geometry, materials, ports and solver setup, not direct legacy MCP writes or pure result analysis.
license: MIT
---

# CST Modeling Adapter

Produce deterministic model source and reviewable CAD IR. This skill does not
own a live CST session. Production model writes are performed by the
`cst_run` Guardian worker, never by legacy `cst_add_to_history_tool` calls.

## Workflow

1. Retrieve related modeling evidence, identify the topic/design and establish
   units, parameters, coordinate system, conductor nets, materials and ports.
2. Implement the design's `build(overrides=None)` source returning valid CAD IR.
   Keep numeric geometry and parameter expressions consistent; the facade
   validates both. Preserve deterministic solid names and source dependencies.
3. Build in order: parameters/materials, geometry/Boolean topology, ports,
   boundaries, mesh, solver and monitors. Use the actual supported IR schema
   and emitter; do not invent fields for missing native CST capabilities.
4. Submit an offline audit through `cst_run`. Inspect DRC and the 3D artifact,
   including feed intrusion, conductor connectivity, gaps and line miters.
5. Return to `$cst-simulation-workflow` for approval, solve and evidence checks.

For backend development, `references/vba-patterns.md` describes small named
History blocks. Extend the emitter and readback together with a targeted
regression when a needed operation is missing. Raw VBA blocks are not a public
request payload and must not bypass the reviewed adapter or task ownership.
Never call `Rebuild` inside an `AddToHistory` structure macro. A saved project,
readback and solver evidence must substantiate modeling success.
