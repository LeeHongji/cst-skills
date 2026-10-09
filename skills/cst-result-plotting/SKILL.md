---
name: cst-result-plotting
description: Plot and validate retained CST Touchstone or CSV evidence, export reviewable figures and metrics, and evaluate pointwise passband gates. Use after simulation or for offline comparisons; this skill does not own a live solver session.
license: MIT
---

# CST Result Plotting

Use exported Touchstone/CSV evidence returned by `cst_get`, together with the
matching model/settings manifest. Plotting is offline and must not launch CST.

1. Retrieve the completed job and artifact references. Distinguish solver,
   cache and offline-analysis provenance.
2. Read the archived curves; complex S parameters use `20*log10(abs(S))`.
   Require coverage at both band edges, retain all in-band samples, and do not
   extrapolate acceptance. Use the existing `cst_lab.contracts.touchstone`
   and Function metric implementation rather than duplicating gate logic.
3. Use `cst_run` with `operation=analyze` or `compare`, `fidelity=offline`,
   source paths within the selected topic workspace and its acceptance contract.
4. Plot retained arrays with standard plotting tools; keep CSV, PNG and JSON
   metrics together. Visually inspect the figure and label units, frequency
   band, ports, phase reference and screening/confirmation status.
5. Report worst S11, minimum S21, phase/imbalance when applicable, gates and
   missing evidence. A visually good plot is not a passed gate.

Use `<runtime>/scripts/plot-review.py --source <export.s2p> --output <new-review-dir>` for derived plots. This reads exported data only. Do not alter finalized Function evidence; evaluate gates through the facade.
