# Experiment contract

Use the canonical JSON schemas in `brain/schemas`. At minimum, an experiment must contain:

- `project_revision_id`: immutable model revision from CST-Lab.
- `hypothesis`: a falsifiable engineering expectation.
- `parameters`: named bounds, type, and unit; exclude uncontrolled variables.
- `objectives` and `constraints`: signal, domain, representation, unit, aggregation, direction or target, evaluation window, missing-data policy, and quality gates.
- `fidelity_plan`: ordered stages such as saved-result audit, coarse probe, local search, and independent confirmation.
- `evaluation_budget`: maximum trials and solver minutes.
- `approval_policy`: explicit gates for solver use and source changes.
- `stop_conditions`: quantitative success or exhaustion rules.

## State rules

Experiment path: `planned -> prepared -> queued -> running -> validating -> completed`.

Use `partial` when evidence is useful but a required fidelity stage is missing. Use `invalid` for unusable evidence or metric definitions, and `failed` for execution failure. Never fabricate a numeric objective for these states.

Trial path: `planned -> queued -> running -> validating -> completed`. Failed, invalid, pruned, partial, and cancelled trials remain in the registry with error evidence.

## Metric rules

- Complex S-parameter dB uses `20*log10(abs(S))`.
- Power quantities use `10*log10(P)` only when the source is a power quantity.
- Frequency coverage permits only the metric engine's documented floating-point tolerance; it must still reject material truncation.
- A constraint result should include both its value and feasibility.
- A target objective should be ranked by absolute target error unless the spec defines another loss.

## Artifact rules

Keep `.cst` working copies and large solver companions in the workspace `runtime/` directory managed by the facade. Keep portable manifests, audits, trial JSON, comparisons, and trace snapshots as text. Reference every important artifact by path and SHA-256. Never copy large binary results into the Obsidian vault.
