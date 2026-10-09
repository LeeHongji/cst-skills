"""Native historical logs and adversarial stopping cases; never launches CST."""
from copy import deepcopy
from pathlib import Path

import pytest

from cst_guardian.solver_evidence import LogCheckpoint, evaluate_solver_evidence

FIXTURES = Path(__file__).parent / "fixtures" / "solver-evidence"
FD = dict(solver="frequency_domain", convergence=dict(adaptive_mesh=True,
    min_passes=6, max_passes=12, checks=2, max_delta_s=.01), settings=dict(accuracy_rom=5e-5))
TD = dict(solver="time_domain", settings=dict(accuracy_db=-50))


def evaluate(setup, text, messages=None, returned=True):
    return evaluate_solver_evidence(setup, log_text=text, messages=messages or [], solver_returned=returned)


@pytest.fixture
def fd_text():
    return (FIXTURES / "fd-trial0003.log").read_text(encoding="utf-8")


@pytest.fixture
def td_text():
    return (FIXTURES / "td-wr90.log").read_text(encoding="utf-8")


def test_actual_final_four_port_native_log(fd_text):
    result = evaluate(FD, fd_text)
    assert result["converged"] is True
    fd = result["frequency_domain"]
    assert fd["mesh_passes"][-1] == 11
    assert fd["delta_s"][-2:] == [.00855387, .00579435]
    assert fd["rom_residuals"][-1] == 4.324690e-6


def test_actual_wr90_reciprocity_is_one_excitation(td_text):
    result = evaluate(TD, td_text)
    assert result["converged"] is True
    assert result["time_domain"]["observed_excitation_count"] == 1
    assert result["time_domain"]["reciprocity_observed"] is True
    assert result["time_domain"]["accuracy_db_readback"] == [-50.]


def test_td_wrong_applied_accuracy_is_failed(td_text):
    setup = deepcopy(TD); setup["settings"]["accuracy_db"] = -60
    assert evaluate(setup, td_text)["status"] == "failed"


def test_td_second_excitation_without_energy_is_unknown(td_text):
    result = evaluate(TD, td_text + "\nStimulation at port 2 (mode 1)\n")
    assert result["converged"] is None
    assert result["time_domain"]["each_observed_excitation_converged"] == [True, False]


def test_success_marker_without_numeric_evidence_cannot_pass():
    for setup in (TD, FD):
        assert evaluate(setup, "Solver finished successfully.")["converged"] is None


@pytest.mark.parametrize("error", ["Solver aborted", "Solver failed", "Fatal error in mesh"])
def test_error_overrides_earlier_success(td_text, error):
    assert evaluate(TD, td_text, [dict(text=error)])["status"] == "failed"


def test_structured_native_error_and_failed_call_override_success(fd_text):
    assert evaluate(FD, fd_text, [dict(text="License unavailable", type="Error")])["status"] == "failed"
    assert evaluate(FD, fd_text, returned=False)["status"] == "failed"


def test_td_unmet_threshold_overrides_energy_marker(td_text):
    assert evaluate(TD, td_text, ["Steady state could not have been satisfied"])["status"] == "not_converged"


def test_mesh_pass_limit_is_not_mesh_convergence(fd_text):
    text = fd_text.replace("desired accuracy limit is reached", "maximum number of passes is reached")
    assert evaluate(FD, text)["status"] == "not_converged"


def test_one_good_delta_is_not_two_consecutive_checks(fd_text):
    text = fd_text.replace("0.00855387", "0.01855387")
    assert evaluate(FD, text)["converged"] is None


def test_mesh_marker_without_delta_values_is_unknown(fd_text):
    assert evaluate(FD, fd_text.replace("All S-Parameters", "Other quantity"))["converged"] is None


def test_rom_failure_is_independent_of_mesh_success(fd_text):
    text = fd_text.replace("4.324690e-06", "4.324690e-02")
    result = evaluate(FD, text)
    assert result["status"] == "not_converged"
    assert result["frequency_domain"]["mesh_converged"] is True


def test_rom_success_without_completion_is_unknown(fd_text):
    assert evaluate(FD, fd_text.replace("Post-processing finished.", "Still working"))["converged"] is None


def test_multiple_mesh_samples_need_per_sample_evidence(fd_text):
    assert evaluate(FD, fd_text + "\nMesh adaptation sample 2 of 2 (4 GHz)\n")["converged"] is None


def test_no_mesh_request_cannot_silently_run_adaptation(fd_text):
    setup = deepcopy(FD); setup["convergence"]["adaptive_mesh"] = False
    assert evaluate(setup, fd_text)["status"] == "not_converged"
    text = "Step\tResidual\n0\t1.0\n4\t2e-6\nPost-processing finished."
    result = evaluate(setup, text)
    assert result["converged"] is True
    assert result["frequency_domain"]["mesh_converged"] is None


def test_unchanged_previous_log_supplies_no_success(tmp_path, td_text):
    path = tmp_path / "Model.log"; path.write_text(td_text, encoding="utf-8")
    before = LogCheckpoint.capture(path)
    fresh = before.read_fresh(path)
    assert fresh["mode"] == "unchanged"
    assert fresh["text"] == ""
    assert evaluate(TD, fresh["text"])["converged"] is None
    with path.open("a", encoding="utf-8") as f:
        f.write("\nSolver aborted")
    fresh = before.read_fresh(path)
    assert fresh["mode"] == "appended"
    assert "criterion met" not in fresh["text"]
    assert evaluate(TD, fresh["text"])["status"] == "failed"


def test_log_replacement_is_recorded_and_not_mixed_with_old_success(tmp_path, td_text):
    path = tmp_path / "Model.log"; path.write_text(td_text, encoding="utf-8")
    before = LogCheckpoint.capture(path)
    path.write_text("Solver aborted", encoding="utf-8")
    fresh = before.read_fresh(path)
    assert fresh["mode"] == "replaced" and fresh["offset"] == 0
    assert fresh["text"] == "Solver aborted"
    assert evaluate(TD, fresh["text"])["status"] == "failed"


def test_missing_then_created_log(tmp_path):
    path = tmp_path / "Model.log"
    before = LogCheckpoint.capture(path)
    assert before.read_fresh(path)["mode"] == "missing"
    path.write_text("new run", encoding="utf-8")
    assert before.read_fresh(path)["mode"] == "created"
