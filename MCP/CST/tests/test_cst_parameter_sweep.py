from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cst_parameter_sweep import (
    CSTParameterSweepRunner,
    _case_vba,
    _copy_project_bundle,
    build_sweep_cases,
    parse_sweep_values,
    preview_sweep,
)


class CSTParameterSweepTests(unittest.TestCase):
    def test_parse_comma_values(self):
        self.assertEqual(parse_sweep_values("1, 2.5, width/2"), [1, 2.5, "width/2"])

    def test_parse_range_values(self):
        self.assertEqual(parse_sweep_values("1:2:0.5"), [1, 1.5, 2])

    def test_build_cartesian_cases(self):
        cases = build_sweep_cases({"w": "1,2", "h": [10, 20]})

        self.assertEqual(
            cases,
            [
                {"w": 1, "h": 10},
                {"w": 1, "h": 20},
                {"w": 2, "h": 10},
                {"w": 2, "h": 20},
            ],
        )

    def test_build_zip_cases(self):
        cases = build_sweep_cases({"w": [1, 2, 3], "h": [10, 20]}, mode="zip")

        self.assertEqual(cases, [{"w": 1, "h": 10}, {"w": 2, "h": 20}])

    def test_preview_enforces_max_cases(self):
        with self.assertRaises(ValueError):
            preview_sweep({"w": "1,2,3", "h": "1,2,3"}, max_cases=5)

    def test_copy_project_bundle_copies_companion_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "base.cst"
            source.write_text("project", encoding="utf-8")
            companion = root / "base"
            companion.mkdir()
            (companion / "Model").mkdir()
            (companion / "Model" / "Parameters.json").write_text("{}", encoding="utf-8")

            target = root / "out" / "case.cst"
            _copy_project_bundle(source, target, overwrite=False)

            self.assertEqual(target.read_text(encoding="utf-8"), "project")
            self.assertTrue((root / "out" / "case" / "Model" / "Parameters.json").is_file())

    def test_parameter_history_does_not_rebuild_inside_structure_macro(self):
        vba = _case_vba({"L1": 360.0})

        self.assertIn("StoreParameters names, values", vba)
        self.assertNotIn("Rebuild", vba)

    def test_offline_result_read_occurs_after_project_close(self):
        class FakeProject:
            def __init__(self, events):
                self.events = events

            def close(self):
                self.events.append("close")

        class FakeManager:
            def __init__(self):
                self.events = []
                self.project = None

            def open_project(self, _path):
                self.events.append("open")
                self.project = FakeProject(self.events)

            def add_to_history(self, _name, _vba):
                self.events.append("history")

            def execute_vba(self, _vba):
                self.events.append("clear-results")

            def save_project(self, _path):
                self.events.append("save")

            def read_1d_result(self, **_kwargs):
                self.events.append("read")
                return {"x": [1.0], "y": [{"real": 0.1, "imag": 0.0}]}

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "base.cst"
            source.write_bytes(b"CST")
            manager = FakeManager()
            runner = CSTParameterSweepRunner(manager)

            result = runner.run_sweep(
                str(source),
                {"L1": [360.0]},
                output_dir=str(root / "sweep"),
                result_tree_paths=["1D Results\\S-Parameters\\S1,1"],
            )

            self.assertTrue(result["ok"])
            self.assertLess(
                manager.events.index("clear-results"), manager.events.index("history")
            )
            self.assertLess(manager.events.index("close"), manager.events.index("read"))

    def test_copied_results_are_cleared_before_parameter_history(self):
        class FakeProject:
            def close(self):
                pass

        class FakeManager:
            def __init__(self):
                self.events = []
                self.project = None

            def open_project(self, _path):
                self.events.append("open")
                self.project = FakeProject()

            def execute_vba(self, _vba):
                self.events.append("clear-results")

            def add_to_history(self, _name, _vba):
                self.events.append("history")

            def save_project(self, _path):
                self.events.append("save")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "base.cst"
            source.write_bytes(b"CST")
            manager = FakeManager()

            result = CSTParameterSweepRunner(manager).run_sweep(
                str(source),
                {"L1": [360.0]},
                output_dir=str(root / "sweep"),
            )

            self.assertTrue(result["ok"])
            self.assertLess(
                manager.events.index("clear-results"), manager.events.index("history")
            )


if __name__ == "__main__":
    unittest.main()
