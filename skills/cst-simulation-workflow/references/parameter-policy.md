# Parameter Policy

Engineering guidance only: verify actual facade/adapter coverage before selecting a solver, monitor or output. Eigenmode, far-field and arbitrary existing-project editing are not implied capabilities of this release. Unsupported requests must stop or use a supported, explicitly stated alternative.


Use this file when the user omits inputs or asks for defaults.

## Ask Once for Critical Inputs

Ask a compact question only when a missing value can change the simulation meaning.

Critical inputs:

| Input | Why it matters |
| --- | --- |
| case type | Patch antenna, array, NFC coil, filter, cavity, and waveguide require different setup |
| target frequency or band | Drives dimensions, solver range, mesh, and monitors |
| project source | Determines new-model vs inspect-and-edit workflow |
| execution intent | CST solves may be slow or license-bound |
| primary objective | S11, gain, directivity, field strength, mode frequency, coupling, or efficiency imply different outputs |

If several are missing, present a defaults card rather than asking a sequence of questions.

## Defaultable Inputs

Use these defaults when the user says to proceed with defaults:

| Input | Default |
| --- | --- |
| units | `mm`, `GHz`, `ns` |
| background | Vacuum or air |
| metal | Copper using CST material library/default conductivity |
| antenna boundary | Open / add space |
| antenna solver | Time Domain for broadband antenna cases; Frequency Domain when narrowband high-Q accuracy is requested |
| eigenmode solver | HF Eigenmode |
| frequency range | `0.7*f0` to `1.3*f0`; for 77 GHz radar use 76-81 GHz |
| mesh | Normal/adaptive mesh; refine near ports, feed gaps, edges, thin conductors |
| monitors | S-parameters plus far-field at `f0`; add near-field/current only when useful |
| outputs | S11, VSWR if available, realized gain/gain/directivity, radiation pattern, result tree, Markdown report |
| run directory | workspace `runtime/`, allocated by the facade |

State defaulted values in the report.

## Derived Inputs

For template-based new models, derive initial geometry from frequency and materials:

- Free-space wavelength: `lambda0_mm = 299.792458 / f_GHz`.
- Patch antenna initial dimensions: use common microstrip patch equations from `templates.md`; treat the result as a starting point, not an optimized design.
- Substrate outline: patch size plus margin, usually 3-6 substrate heights or a practical factor around 1.5-2.5 times patch dimensions.
- Feed location: template default first, then optimize if S11 is poor.
- Far-field monitor frequency: center frequency unless user gives multiple frequencies.
- Mesh refinement: ports, feed line/gap, patch edges, coil traces, thin dielectrics.

## Existing Project Inputs

When a `.cst` project exists, inspect before asking for values. Prefer reading:

- project path and active/open project identity
- parameters and values
- geometry/entity names
- materials
- ports/excitations
- boundaries
- solver type and frequency range
- monitors
- result tree
- recent messages/logs

Ask the user only for ambiguous choices, such as which parameter to sweep or which result item is the objective.

## Defaults Card Template

Use this shape before expensive solves:

```text
I will run this CST setup unless you change it:

Case:
Project:
Frequency:
Material/substrate:
Solver:
Boundary:
Ports/excitation:
Monitors:
Outputs:
Run mode:
Working directory:
```

If the user already said "directly run" or "use defaults", continue and include this card in the final report instead of pausing.
