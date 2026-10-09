from __future__ import annotations

import unittest
from pathlib import Path

from cst_automation import CSTSessionManager, _jsonable


class FakeModel3D:
    def __init__(self):
        self.history = []
        self.vba = []
        self.solver_runs = 0

    def add_to_history(self, title, code):
        self.history.append((title, code))

    def _execute_vba_code(self, code):
        self.vba.append(code)

    def run_solver(self):
        self.solver_runs += 1


class FakeSimulationTask:
    def __init__(self):
        self.names = []
        self.updates = 0

    def Reset(self):
        pass

    def Name(self, name):
        self.names.append(name)

    def Update(self):
        self.updates += 1


class FakeSchematic:
    def __init__(self):
        self.vba = []
        self.update_results = 0
        self.exports = []
        self.SimulationTask = FakeSimulationTask()

    def execute_vba_code(self, code):
        self.vba.append(code)

    def UpdateResults(self):
        self.update_results += 1

    def TouchstoneExport(self, tree_item, filename, impedance):
        self.exports.append((tree_item, filename, impedance))
        return True


class FakeProject:
    def __init__(self):
        self.model3d = FakeModel3D()
        self.schematic = FakeSchematic()
        self.saved = []

    def filename(self):
        return r"C:\tmp\case.cst"

    def folder(self):
        return r"C:\tmp"

    def project_type(self):
        return "MWS"

    def get_messages(self):
        return ["ready"]

    def save(self, path=None):
        self.saved.append(path)


class CSTAutomationTests(unittest.TestCase):
    def manager_with_project(self):
        manager = CSTSessionManager()
        manager.project = FakeProject()
        return manager

    def test_jsonable_converts_paths_and_nested_values(self):
        self.assertEqual(
            _jsonable({"path": Path("a/b"), "items": (1, Path("c"))}),
            {
                "path": "a\\b" if "\\" in str(Path("a/b")) else "a/b",
                "items": [1, "c"],
            },
        )

    def test_add_to_history_calls_model3d(self):
        manager = self.manager_with_project()

        result = manager.add_to_history("material", 'Material.Name "Copper"')

        self.assertEqual(result, {"ok": True, "title": "material"})
        self.assertEqual(manager.project.model3d.history, [("material", 'Material.Name "Copper"')])

    def test_execute_vba_wraps_code_in_sub_main(self):
        manager = self.manager_with_project()

        manager.execute_vba('Solver.FrequencyRange "1", "2"')

        self.assertEqual(manager.project.model3d.vba, ['Sub Main\nSolver.FrequencyRange "1", "2"\nEnd Sub'])

    def test_schematic_execute_vba_wraps_code_in_sub_main(self):
        manager = self.manager_with_project()

        manager.schematic_execute_vba('ReportInformationToWindow "x"')

        self.assertEqual(manager.project.schematic.vba, ['Sub Main\nReportInformationToWindow "x"\nEnd Sub'])

    def test_schematic_run_simulation_updates_named_task(self):
        manager = self.manager_with_project()

        result = manager.schematic_run_simulation(task_name="SPara1")

        self.assertTrue(result["ok"])
        self.assertEqual(manager.project.schematic.SimulationTask.names, ["SPara1"])
        self.assertEqual(manager.project.schematic.SimulationTask.updates, 1)

    def test_schematic_export_touchstone_calls_ds_export(self):
        manager = self.manager_with_project()

        result = manager.schematic_export_touchstone("Tasks\\SPara1\\S-Parameters", r"C:\tmp\out", 50)

        self.assertTrue(result["ok"])
        self.assertEqual(manager.project.schematic.exports, [("Tasks\\SPara1\\S-Parameters", r"C:\tmp\out", "50")])

    def test_run_solver_calls_model3d(self):
        manager = self.manager_with_project()

        result = manager.run_solver()

        self.assertTrue(result["ok"])
        self.assertEqual(manager.project.model3d.solver_runs, 1)

    def test_run_python_returns_result_and_updates_project(self):
        manager = self.manager_with_project()

        result = manager.run_python("result = {'filename': prj.filename()}")

        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], {"filename": r"C:\tmp\case.cst"})

    def test_empty_history_code_rejected(self):
        manager = self.manager_with_project()

        with self.assertRaises(ValueError):
            manager.add_to_history("x", " ")


if __name__ == "__main__":
    unittest.main()
