"""Solver-specific evidence from the current invocation, never a cached success.

No CST imports: the guarded worker captures log/message checkpoints immediately
before run_solver and supplies only their fresh portions. A returned API call is
necessary but insufficient. Unknown evidence stays unknown; numerical gates are
evaluated separately from numerical solver convergence.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
import re
from typing import Any


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class LogCheckpoint:
    exists: bool
    size: int
    sha256: str

    @classmethod
    def capture(cls, path: Path) -> LogCheckpoint:
        path = Path(path)
        if not path.exists():
            return cls(False, 0, _sha(b""))
        if path.is_symlink() or not path.is_file():
            raise ValueError("solver log must be a regular file")
        data = path.read_bytes()
        return cls(True, len(data), _sha(data))

    def read_fresh(self, path: Path) -> dict[str, Any]:
        """Hash the old prefix, accepting append or an explicitly recorded reset.

        The worker owns the project and must capture this checkpoint just before
        its synchronous solver invocation. Unchanged files yield no evidence.
        A reset is preserved in the receipt rather than presented as an append.
        """
        path = Path(path)
        if not path.exists():
            return dict(mode="missing", text="", before_sha256=self.sha256,
                        after_sha256=None, offset=None, bytes=0)
        if path.is_symlink() or not path.is_file():
            raise ValueError("solver log must be a regular file")
        data = path.read_bytes()
        same_prefix = len(data) >= self.size and _sha(data[:self.size]) == self.sha256
        offset = self.size if self.exists and same_prefix else 0
        mode = "appended" if offset else ("replaced" if self.exists else "created")
        if self.exists and _sha(data) == self.sha256:
            mode, offset = "unchanged", len(data)
        fresh = data[offset:]
        return dict(mode=mode, text=fresh.decode("utf-8-sig", errors="replace"),
                    before_sha256=self.sha256, after_sha256=_sha(data),
                    offset=offset, bytes=len(fresh), fresh_sha256=_sha(fresh))


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_DATE = re.compile(r"^\s*\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\s+")
_FATAL = re.compile(
    r"\b(?:solver (?:aborted|failed)|calculation aborted|aborted by user|"
    r"fatal error|could not start (?:the )?solver|matrix calculation failed)\b", re.I)
_UNMET = re.compile(
    r"could not have been satisfied|steady state.*not (?:met|reached)|"
    r"maximum (?:number of )?(?:time steps|simulation time|pulse widths).*reached", re.I)
_TERMINAL = re.compile(r"solver finished successfully|post-processing finished\.", re.I)


def _messages(items: list[dict[str, Any] | str]) -> tuple[list[str], list[str]]:
    lines, errors = [], []
    for item in items:
        if isinstance(item, str):
            text, severity = item, ""
        else:
            text = str(item.get("text", item.get("message", "")))
            severity = str(item.get("type", item.get("severity", ""))).casefold()
        lines.extend(text.splitlines())
        if severity in ("error", "fatal"):
            errors.append(text)
    return lines, errors


def _rom_residuals(lines: list[str]) -> list[float]:
    values: list[float] = []
    in_table = False
    for line in lines:
        if re.search(r"\bStep\s+Residual\b", line, re.I):
            in_table = True
            values = []  # A later ROM solve supersedes an earlier table.
            continue
        if not in_table:
            continue
        if match := re.fullmatch(rf"\s*\d+\s+({_NUMBER})\s*", line):
            values.append(float(match[1]))
        elif line.strip() and not re.fullmatch(r"[-=\s]+", line):
            in_table = False
    return values


def evaluate_solver_evidence(
    setup: dict[str, Any],
    *,
    log_text: str,
    messages: list[dict[str, Any] | str],
    solver_returned: bool,
) -> dict[str, Any]:
    """Evaluate fresh native evidence for TD-S or FD tetrahedral fast ROM.

    ``log_text`` is the new Model.log portion, falling back to output.txt only
    when Model.log has no fresh content. Messages supplement terminal/error
    evidence; they do not replace FD numeric adaptation or ROM evidence.
    """
    if setup.get("solver") not in ("time_domain", "frequency_domain"):
        raise ValueError("unsupported solver evidence kind")
    lines = [_DATE.sub("", line).strip() for line in log_text.splitlines()]
    message_lines, errors = _messages(messages)
    combined = lines + message_lines
    errors += [line for line in combined if _FATAL.search(line)]
    unmet = [line for line in combined if _UNMET.search(line)]
    terminal = [line for line in combined if _TERMINAL.search(line)]
    result: dict[str, Any] = dict(
        schema_version=1, evaluator_version="cst-solver-evidence-1",
        solver=setup["solver"], solver_returned=bool(solver_returned),
        status="unknown", converged=None, errors=sorted(set(errors)),
        terminal_markers=list(dict.fromkeys(terminal)), unmet_markers=list(dict.fromkeys(unmet)),
        native_log_sha256=_sha(log_text.encode("utf-8")), reasons=[],
    )
    if errors or not solver_returned:
        result.update(status="failed", converged=False)
        result["reasons"].append("solver error or solver call did not return normally")
    elif unmet:
        result.update(status="not_converged", converged=False)
        result["reasons"].append("native solver reports an unmet stopping criterion")

    if setup["solver"] == "time_domain":
        energy = [line for line in combined if "steady state energy criterion met" in line.casefold()]
        # Count log excitations if available. Reciprocity can supply the reverse
        # port without a second pulse; never require energy_count == port_count.
        starts = [i for i, line in enumerate(lines)
                  if re.search(r"Stimulation at port \d+\s*\(mode \d+\)", line, re.I)]
        per_excitation = [any("steady state energy criterion met" in line.casefold()
                              for line in lines[start:(starts[index+1] if index+1 < len(starts) else len(lines))])
                          for index, start in enumerate(starts)]
        accuracies = [float(m[1]) for line in lines
                      if (m := re.search(rf"Steady state accuracy limit:\s*({_NUMBER})\s*dB", line, re.I))]
        accuracy_matches = bool(accuracies) and all(
            math.isclose(value, setup["settings"]["accuracy_db"], rel_tol=1e-9, abs_tol=1e-9)
            for value in accuracies)
        result["time_domain"] = dict(
            energy_criterion_observed=bool(energy),
            observed_excitation_count=len(starts) if starts else None,
            each_observed_excitation_converged=per_excitation,
            accuracy_db_readback=accuracies, accuracy_matches=accuracy_matches,
            reciprocity_observed=any("two-port reciprocity" in line.casefold() for line in combined),
        )
        ready = bool(energy) and bool(terminal) and (not starts or all(per_excitation)) and accuracy_matches
        if accuracies and not accuracy_matches:
            result.update(status="failed", converged=False)
            result["reasons"].append("TD steady-state limit differs from effective setup")
        if not ready:
            result["reasons"].append("missing TD energy, terminal, excitation or accuracy readback evidence")
    else:
        convergence = setup["convergence"]
        mesh_enabled = convergence["adaptive_mesh"]
        mesh_stop = [line for line in lines if "mesh adaptation terminated because" in line.casefold()]
        deltas = [float(m[1]) for line in lines
                  if (m := re.search(rf"All S-Parameters\s*:\s*({_NUMBER})", line, re.I))]
        passes = [int(m[1]) for line in lines
                  if (m := re.search(r"Adaptive mesh refinement pass\s+(\d+)", line, re.I))]
        samples = [int(m[1]) for line in lines
                   if (m := re.search(r"Mesh adaptation sample\s+\d+\s+of\s+(\d+)", line, re.I))]
        desired = bool(mesh_stop) and "desired accuracy limit is reached" in mesh_stop[-1].casefold()
        limit_hit = bool(mesh_stop) and "maximum number of passes is reached" in mesh_stop[-1].casefold()
        checks = convergence["checks"]
        numeric_mesh_ok = (len(deltas) >= checks and
                           all(0 <= v <= convergence["max_delta_s"] for v in deltas[-checks:]) and
                           bool(passes) and convergence["min_passes"] <= passes[-1] <= convergence["max_passes"])
        # The current emitter resolves exactly one adaptation frequency. Multiple
        # samples need per-sample records, not one global final delta-S.
        single_sample = not samples or max(samples) == 1
        mesh_ok = (desired and numeric_mesh_ok and single_sample) if mesh_enabled else not passes
        residuals = _rom_residuals(lines)
        rom_ok = bool(residuals) and 0 <= residuals[-1] <= setup["settings"]["accuracy_rom"]
        result["frequency_domain"] = dict(
            adaptive_mesh_requested=mesh_enabled, mesh_stop_markers=mesh_stop,
            mesh_passes=passes, delta_s=deltas, mesh_converged=mesh_ok if mesh_enabled else None,
            rom_residuals=residuals, rom_converged=rom_ok if residuals else None,
            single_adaptation_sample=single_sample,
        )
        ready = mesh_ok and rom_ok and bool(terminal)
        if result["status"] == "unknown" and (
            (mesh_enabled and limit_hit) or
            (residuals and not rom_ok) or (not mesh_enabled and passes)
        ):
            result.update(status="not_converged", converged=False)
            result["reasons"].append("mesh pass limit, unexpected adaptation or ROM tolerance not satisfied")
        if not ready:
            result["reasons"].append("missing or insufficient FD mesh, ROM or terminal evidence")
    if ready and result["status"] == "unknown":
        result.update(status="converged", converged=True)
    return result
