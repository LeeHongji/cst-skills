from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from cst_typed_wrapper_generator import generate_typed_wrappers, tool_name_to_function


class CSTTypedWrapperGeneratorTests(unittest.TestCase):
    def test_tool_name_to_function(self):
        self.assertEqual(tool_name_to_function("define-brick"), "define_brick")
        self.assertEqual(tool_name_to_function("1d-result"), "tool_1d_result")

    def test_generate_selected_wrapper(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "wrappers.py"

            result = generate_typed_wrappers(str(output), selected_tools=["define-brick"])

            text = output.read_text(encoding="utf-8")
            self.assertTrue(result["ok"])
            self.assertEqual(result["tool_count"], 1)
            self.assertIn("def define_brick", text)
            self.assertIn("invoke_runtime_tool('define-brick'", text)


if __name__ == "__main__":
    unittest.main()
