from __future__ import annotations

import pytest

import mcp_server


LEGACY_IN_PROCESS_CST_WRITES = (
    "cst_launch_tool",
    "cst_open_project_tool",
    "cst_new_project_tool",
    "cst_save_project_tool",
    "cst_add_to_history_tool",
    "cst_execute_vba_tool",
    "cst_run_solver_tool",
    "cst_run_python_tool",
    "cst_export_touchstone_tool",
    "cst_create_schematic_project_tool",
    "cst_open_schematic_project_tool",
    "cst_schematic_execute_vba_tool",
    "cst_schematic_add_to_history_tool",
    "cst_insert_em_3d_block_or_nport_tool",
    "cst_add_resistor_tool",
    "cst_add_inductor_tool",
    "cst_add_capacitor_tool",
    "cst_add_diode_spice_model_tool",
    "cst_add_ground_tool",
    "cst_add_external_port_tool",
    "cst_connect_schematic_nodes_tool",
    "cst_configure_frequency_sweep_tool",
    "cst_configure_power_sweep_tool",
    "cst_run_circuit_cosimulation_tool",
    "cst_export_schematic_sparameters_tool",
    "cst_sweep_run_tool",
    "cst_runtime_invoke_tool",
    "cst_toolbox_invoke_tool",
)


def test_every_known_in_process_write_is_fail_closed() -> None:
    for name in LEGACY_IN_PROCESS_CST_WRITES:
        function = getattr(mcp_server, name)
        assert function.cst_guardian_required is True, name
        with pytest.raises(
            mcp_server.UnguardedCSTWriteBlocked,
            match="legacy in-process CST write",
        ):
            function()


def test_block_happens_before_the_legacy_session_is_touched(monkeypatch) -> None:
    touched = False

    def unsafe_solver():
        nonlocal touched
        touched = True

    monkeypatch.setattr(mcp_server.session, "run_solver", unsafe_solver)
    with pytest.raises(mcp_server.UnguardedCSTWriteBlocked):
        mcp_server.cst_run_solver_tool()
    assert touched is False


def test_offline_and_environment_detection_remain_available(monkeypatch) -> None:
    expected = {"cst_interface_importable": True}
    monkeypatch.setattr(mcp_server.session, "detect_environment", lambda: expected)
    assert mcp_server.cst_detect_tool() == expected
    assert mcp_server.cst_sweep_preview_tool({"x": [1, 2]})["case_count"] == 2
