---
name: cst-strategy-learning
description: Turn CST modeling, simulation, sweep, optimization, and failure traces into reusable strategy candidates and evidence-backed engineering playbooks. Use when comparing runs, extracting optimization tactics, recording recovery patterns, or deciding whether a lesson can be promoted beyond one case.
license: MIT
---

# CST Strategy Learning

Provider: use the separate `cst-brain` MCP configured in the current research workspace. Its tools read and curate that workspace Brain and do not control CST. If unavailable, use the runtime Python and root recorded in `system/deployment.json` to run `python -m cst_brain --brain-root <workspace>/brain`, or report the unavailable service. Do not invent a tool call.

Store observable strategy traces, not hidden chain-of-thought. Record decision, concise rationale, action, observation, evidence, and outcome.

## Workflow

1. Query related cases and strategies with `$cst-brain-query`.
2. Compare at least:
   - objective and constraints,
   - parameterization and search space,
   - solver/mesh fidelity,
   - evaluation budget,
   - failures and recoveries,
   - final metrics and reproducibility.
3. Create a `strategy` candidate with `brain_create_candidate_tool`.
4. State the applicability boundary and known failure modes.
5. Add independent evidence references as they accumulate.
6. Promote only with two independent evidence references or explicit human approval through `brain_promote_claim_tool`.
7. Keep contradicted strategies; change status and connect the counter-evidence instead of erasing history.

For expensive searches, separate exploration, confirmation, and final high-fidelity validation. Preserve rejected attempts when they teach a reusable boundary.

See [strategy-template.md](references/strategy-template.md) for the minimum candidate structure.
