# Result Validation

Use this file before claiming a CST simulation succeeded.

## Evidence Requirements

A run is validated only when at least one concrete evidence source exists:

- saved working `.cst` project path
- CST result-tree/readback evidence exported by the Function worker and retrieved with `cst_get`
- exported Touchstone, JSON, CSV, TXT, image, or report file
- readable 1D result from `cst_read_1d_result_tool`
- solver log or model log showing completion

If the solver command returns success but no result evidence is available, report `needs_validation`.

## S-Parameters

For S11/S-parameters:

- Confirm the result item or Touchstone export exists.
- If data is complex, compute dB as `20*log10(abs(S11))`.
- Do not label raw complex magnitude as dB.
- Report the frequency unit and interpolation method if evaluating at a target frequency.
- For pass/fail, state the threshold, for example `S11 <= -10 dB at 2.4 GHz`.

Suggested summary:

```text
S11 validation:
- target:
- best frequency:
- S11 at target:
- minimum S11 in band:
- evidence file:
- status: pass/fail/needs_validation
```

## VSWR

If VSWR is not directly exported, derive it from reflection coefficient magnitude:

```text
VSWR = (1 + |Gamma|) / (1 - |Gamma|)
```

Do not compute VSWR from a dB value without converting back to magnitude.

## Far Field

For gain or radiation pattern claims:

- Use `Realized Gain`, `Gain`, or `Directivity`.
- Do not use `Abs(E)` as gain or dBi evidence.
- State frequency, port/excitation, quantity, unit, and coordinate convention.
- Record whether the plot/data is 3D, theta cut, phi cut, or polar/cartesian.

Suggested summary:

```text
Far-field validation:
- quantity:
- frequency:
- peak value:
- main direction:
- evidence file/result item:
- status:
```

## Near Field and Current

For E/H fields, SAR, current, or coupling:

- Confirm the monitor exists before solving or that the result tree contains the item afterward.
- State field quantity, frequency/time, plane/cut/volume, and unit.
- Do not infer far-field gain from near-field magnitude.

## Eigenmode

For eigenmode runs:

- Confirm mode frequency result entries exist.
- Report requested modes and solved modes.
- Include mode frequencies with units.
- Note whether boundaries were PEC/electric wall, magnetic wall, open, or symmetry.

## Parameter Sweep

For sweeps:

- Include previewed case count and actual completed/failed case counts.
- Include sweep mode: `single`, `zip`, or `cartesian`.
- Include parameter table and objective metric.
- Identify the best case only if the objective was computed from validated results.

## Report Status Values

Use these statuses consistently:

| Status | Meaning |
| --- | --- |
| `validated` | Solver and requested result evidence were found and parsed |
| `needs_validation` | Project or solver ran, but requested result evidence is missing/incomplete |
| `blocked` | CST/MCP/license/input/project issue prevented meaningful execution |
| `plan_only` | User requested planning or script generation without execution |
| `partial` | Some outputs validated but others failed or were not generated |

## Minimum Final Report

Every executed CST task should include:

- working project path
- source project path when applicable
- run directory
- assumptions/defaults
- MCP tools used
- solver and result setup
- evidence files/result tree entries
- validation status
- issues, warnings, and recommended next action
