"""Read S-parameters straight from a closed .cst via cst.results.

This is the independent evidence path: it does not go through the running Design
Environment at all, so it cross-checks the Touchstone that was exported from the
live session. The project must be closed first -- cst.results reads the on-disk
result database, and an open project can hold results the reader will not see.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
from pathlib import Path

os.environ.setdefault("CST_INSTALL_ROOT", r"C:\CST")
sys.path.insert(0, r"C:\CST\AMD64\python_cst_libraries")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--csv-out", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    from cst.results import ProjectFile

    project = ProjectFile(str(Path(args.project).resolve()), allow_interactive=False)
    tree = project.get_3d()

    names = list(tree.get_tree_items())
    wanted = {
        "s11": r"1D Results\S-Parameters\S1,1",
        "s21": r"1D Results\S-Parameters\S2,1",
    }
    curves: dict[str, dict[float, float]] = {}
    for key, path in wanted.items():
        if path not in names:
            raise SystemExit(f"missing result {path!r}; tree has {len(names)} items")
        result = tree.get_result_item(path)
        xs = result.get_xdata()
        ys = result.get_ydata()
        # get_ydata returns complex linear S; the only valid dB conversion is 20*log10(abs(S)).
        curves[key] = {float(x): 20.0 * math.log10(max(abs(complex(y)), 1e-30)) for x, y in zip(xs, ys)}

    frequencies = sorted(curves["s11"])
    out = Path(args.csv_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["frequency_ghz", "s11_db", "s21_db"])
        for f in frequencies:
            writer.writerow([f"{f:.9g}", f"{curves['s11'][f]:.9g}", f"{curves['s21'][f]:.9g}"])

    peak = max(frequencies, key=lambda f: curves["s21"][f])
    best = min(frequencies, key=lambda f: curves["s11"][f])
    report = {
        "project": str(Path(args.project).resolve()),
        "reader": "cst.results.ProjectFile(allow_interactive=False)",
        "representation": "20*log10(abs(S))",
        "result_tree_items": len(names),
        "sample_count": len(frequencies),
        "frequency_span_ghz": [frequencies[0], frequencies[-1]],
        "s21_peak_db": curves["s21"][peak],
        "s21_peak_frequency_ghz": peak,
        "s11_min_db": curves["s11"][best],
        "s11_min_frequency_ghz": best,
        "csv": str(out.resolve()),
    }
    text = json.dumps(report, ensure_ascii=False, indent=2)
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)
