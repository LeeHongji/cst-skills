---
name: cst-experiment-orchestration
description: Plan bounded CST parameter studies, optimization and confirmation through the production Function facade and CST Brain. Use when experiments need explicit objectives, budgets, stop conditions, reproducible evidence and reusable lessons; lifecycle and locks are managed internally.
license: MIT
---

# CST Experiment Orchestration

Plan bounded experiments; delegate locks, task state, execution and publication
to the three-tool facade. Do not maintain a second manual Lab trial lifecycle.

1. Use `$cst-brain-query`; record the relevant cases and applicability limits.
2. Select the topic/design/attempt contracts. Define objective, allowed parameter
   ranges, acceptance gates, fidelity, iteration budget and stopping condition.
   Use the deployed Function contract; the historical Lab experiment schema in
   `references/experiment-contract.md` is background, not another submission API.
3. Obtain the audit/approval through `$cst-simulation-workflow`.
4. Preview the candidate count offline. Execute candidates sequentially through
   `cst_run`; use stable request IDs for retries and distinct IDs for new points.
5. Use `cst_get` to inspect results and append-only iteration facts. Failed,
   blocked or nonconverged candidates remain evidence, not numeric successes.
6. Compare exported evidence with `operation=compare`; do not infer sensitivity
   when mesh/solver setup also changed. A screen cache hit claims no new solve.
7. Confirm the selected candidate with `fidelity=confirm`. Check the actual
   physics gates as well as successful execution and independent reopen.
8. Inspect job-bound learning publication. Use `$cst-trace-compile` only for
   evidence repair/import when needed, then `$cst-strategy-learning` for lessons.

Stop when goals, budgets or no-improvement limits are reached. Request user
steering when a material design tradeoff is unresolved. Report job/artifact
references, parameter and setup deltas, metrics, acceptance and remaining limits.
