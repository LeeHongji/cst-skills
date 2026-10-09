"""Print a DRC or verify report as a compact review table."""

from __future__ import annotations

import json
import sys
from pathlib import Path


def show_drc(report: dict) -> None:
    print(f"status={report['status']}  summary={json.dumps(report['summary'], ensure_ascii=False)}")
    print()
    header = f"{'rule id':<20} {'rule':<20} {'sev':<8} {'status':<7} {'measured':>14} {'threshold':>12} {'viol':>5}"
    print(header)
    print("-" * len(header))
    for check in report["checks"]:
        measured = check.get("measured")
        measured_text = "-" if measured is None else (f"{measured:.9g}" if isinstance(measured, (int, float)) else str(measured))
        threshold = check.get("threshold")
        threshold_text = "-" if threshold is None else (f"{threshold:.9g}" if isinstance(threshold, (int, float)) else str(threshold))
        print(
            f"{check['id']:<20} {check['rule']:<20} {check['severity']:<8} {check['status']:<7} "
            f"{measured_text:>14} {threshold_text:>12} {len(check.get('violations', [])):>5}"
        )
    print()
    for check in report["checks"]:
        for extra in ("closest_pair", "narrowest", "message"):
            if check.get(extra):
                print(f"  {check['id']}.{extra}: {json.dumps(check[extra], ensure_ascii=False)}")
        if check.get("per_net"):
            print(f"  {check['id']}.per_net: " + ", ".join(f"{item['net']}={item['components']}" for item in check["per_net"]))
        if check.get("per_port"):
            print(f"  {check['id']}.per_port: " + json.dumps(check["per_port"], ensure_ascii=False))
        for violation in check.get("violations", []):
            print(f"  !! {check['id']}: {json.dumps(violation, ensure_ascii=False)}")


def show_verify(report: dict) -> None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from cst_cad.verify import render_table

    print(f"status={report['status']}  summary={json.dumps(report['summary'], ensure_ascii=False)}")
    print()
    print(render_table(report))
    mismatched = [row for row in report.get("parameters", []) if row["status"] != "match"]
    if mismatched:
        print()
        print("parameter mismatches:")
        for row in mismatched:
            print(f"  {row['name']}: expected={row['expected']} actual={row['actual']} status={row['status']}")


def main() -> None:
    report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8-sig"))
    if "checks" in report:
        show_drc(report)
    else:
        show_verify(report)


if __name__ == "__main__":
    main()
