# CST V1 Templates

Engineering guidance only: verify actual facade/adapter coverage before selecting a solver, monitor or output. Eigenmode, far-field and arbitrary existing-project editing are not implied capabilities of this release. Unsupported requests must stop or use a supported, explicitly stated alternative.


Use templates as starting points, not as final validated designs. Simulate and validate before making performance claims.

## Template Selection

| Template | Use when | Stability |
| --- | --- | --- |
| 2.4 GHz Wi-Fi/IoT microstrip patch | Need a stable first CST MCP demo or simple antenna workflow | V1 primary |
| 77 GHz 1x4 radar patch array | Need a modern ADAS/mmWave showcase | V1 demo after patch is stable |
| Existing `.cst` parameter rerun | User provides a project or wants to modify current model | V1 primary |
| Rectangular PEC cavity eigenmode | Need a fast verification/eigenmode smoke test | V1 validation case |
| NFC/Qi coil | Near-field coupling demo | Later |

## 2.4 GHz Wi-Fi/IoT Microstrip Patch

Default card:

| Field | Default |
| --- | --- |
| center frequency | 2.4 GHz |
| sweep range | 1.8-3.0 GHz |
| substrate | FR-4 if user does not care; Rogers material if loss accuracy matters |
| substrate thickness | 1.6 mm for FR-4 |
| metal | Copper |
| feed | Microstrip feed or discrete/lumped feed, depending on available MCP support |
| boundary | Open / add space |
| solver | Time Domain |
| monitors | S11 over sweep, far-field at 2.4 GHz |
| outputs | S11, VSWR if available, realized gain/gain/directivity, radiation pattern |

Initial dimension guidance:

- Use effective dielectric constant and patch resonance equations to estimate patch width and length.
- Use substrate and ground plane dimensions with margin around the patch.
- Treat feed inset/location as a tunable parameter.
- If first S11 is poor, suggest a short sweep over patch length and feed position.

## 77 GHz 1x4 Radar Patch Array

Default card:

| Field | Default |
| --- | --- |
| frequency band | 76-81 GHz |
| center frequency | 77 GHz |
| array | 1x4 linear patch array |
| substrate | Rogers RO3003 or similar low-loss mmWave substrate |
| substrate thickness | 0.127 mm if not specified |
| metal | Copper |
| element spacing | about 0.5 free-space wavelength, adjusted for layout |
| feed | corporate feed or individual ports depending on task |
| boundary | Open / add space |
| solver | Frequency Domain or Time Domain based on requested outputs and model detail |
| monitors | S-parameters, far-field at 77 GHz, optional 76/79/81 GHz monitors |
| outputs | S11, mutual coupling if multiport, realized gain/directivity, main beam direction |

Use this template after the basic single-patch workflow is stable. mmWave arrays are more sensitive to meshing, material loss, feed implementation, and port definitions.

## Rectangular PEC Cavity Eigenmode

Use for a quick end-to-end CST smoke test or eigenmode workflow:

| Field | Default |
| --- | --- |
| cavity size | 100 x 50 x 30 mm |
| material | vacuum/air inside |
| boundaries | electric wall on all six sides |
| solver | HF Eigenmode |
| modes | 3 |
| outputs | mode frequencies and result tree evidence |

Do not call `Solver.FrequencyRange` for this eigenmode smoke test unless the specific CST setup requires it; doing so can open an interactive dialog when the range is unset.

## Existing Project Parameter Rerun

Default behavior:

1. Copy source `.cst` and companion project folder into the run directory.
2. Inspect parameters, monitors, solver, ports, and result tree.
3. Apply only requested parameter changes.
4. Save and run copied project.
5. Export comparable results and report before/after values.

If the user does not identify which parameter to change, list candidate geometry/design parameters and ask once.

## Template Report Requirements

Every template run must report:

- template name and version-like date
- all assumed default values
- generated/working project path
- solver type and frequency range or modes
- ports/excitations
- monitors
- outputs and validation status
