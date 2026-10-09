"""The active guardian preflight check must stay independent of legacy Fig. 15."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
PROJECT_ROOT = ROOT / "MCP" / "CST"


def test_guardian_l0_uses_neutral_no_solve_fixture(tmp_path: Path) -> None:
    output = tmp_path / "guardian-l0"
    result = subprocess.run(
        [
            sys.executable,
            str(PROJECT_ROOT / "tools" / "verify_guardian_live.py"),
            "--output",
            str(output),
            "--skip-live",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads((output / "verification-report.json").read_text(encoding="utf-8"))
    scenario = report["scenarios"][0]
    assert report["all_passed"] is True
    assert report["live_suite_skipped"] is True
    assert scenario["cst_launched"] is False
    assert scenario["clean_status"] == "pass"
    assert scenario["overlapping_status"] == "fail"
    assert scenario["rules_that_caught_it"] == ["no_cross_net_short"]
