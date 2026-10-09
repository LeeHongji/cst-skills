"""Locate where two S-parameter curves disagree most, and characterise why."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_sparams import read_reference_csv, read_touchstone  # noqa: E402

generated = Path(sys.argv[1])
reference = Path(sys.argv[2])

gf, gs11, gs21 = read_touchstone(generated)
rf, rs11, rs21 = read_reference_csv(reference)
assert gf == rf or len(gf) == len(rf)

rows = []
for i in range(len(gf)):
    rows.append((abs(gs21[i] - rs21[i]), gf[i], gs21[i], rs21[i], gs11[i], rs11[i]))

rows.sort(reverse=True)
print(f"{'f_GHz':>9} {'S21_gen':>9} {'S21_ref':>9} {'dS21':>8} {'S11_gen':>9} {'S11_ref':>9}")
for delta, f, a, b, c, d in rows[:8]:
    print(f"{f:9.5f} {a:9.3f} {b:9.3f} {delta:8.3f} {c:9.3f} {d:9.3f}")

print("\ntransmission zeros (minimum S21 in each stopband skirt)")
for label, lo, hi in (("lower", 0.90, 1.01), ("upper", 1.11, 1.25)):
    gi = min((i for i, f in enumerate(gf) if lo <= f <= hi), key=lambda i: gs21[i])
    ri = min((i for i, f in enumerate(rf) if lo <= f <= hi), key=lambda i: rs21[i])
    print(
        f"  {label}: generated {gf[gi]:.5f} GHz @ {gs21[gi]:.2f} dB | "
        f"reference {rf[ri]:.5f} GHz @ {rs21[ri]:.2f} dB | df = {(gf[gi]-rf[ri])*1000:.1f} MHz"
    )

band = [i for i, f in enumerate(gf) if 1.02 <= f <= 1.105]
d21 = [abs(gs21[i] - rs21[i]) for i in band]
d11 = [abs(gs11[i] - rs11[i]) for i in band]
print(f"\nin passband (1.02-1.105 GHz, {len(band)} samples):")
print(f"  max |dS21| = {max(d21):.3f} dB   mean = {sum(d21)/len(d21):.3f} dB")
print(f"  max |dS11| = {max(d11):.3f} dB   mean = {sum(d11)/len(d11):.3f} dB")

deep = [i for i in range(len(gf)) if min(gs21[i], rs21[i]) < -30.0]
shallow = [i for i in range(len(gf)) if min(gs21[i], rs21[i]) >= -30.0]
print(f"\nsamples where either curve is below -30 dB: {len(deep)}")
if shallow:
    ds = [abs(gs21[i] - rs21[i]) for i in shallow]
    print(f"  excluding those, max |dS21| = {max(ds):.3f} dB, mean = {sum(ds)/len(ds):.3f} dB")
