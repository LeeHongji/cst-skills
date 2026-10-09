from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

import cst_runtime_cli_bridge as bridge


class CSTRuntimeCLIBridgeTests(unittest.TestCase):
    def test_detect_runtime_reports_vendor_path(self):
        result = bridge.detect_runtime()

        self.assertIn("runtime_script_root", result)
        self.assertIn("python_executable", result)

    def test_runtime_env_includes_vendor_pythonpath(self):
        env = bridge.runtime_env()

        self.assertIn(str(bridge.RUNTIME_SCRIPT_ROOT), env["PYTHONPATH"])

    def test_invoke_runtime_tool_uses_json_payload(self):
        completed = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=json.dumps({"status": "success", "value": 1}),
            stderr="",
        )
        with patch("cst_runtime_cli_bridge.subprocess.run", return_value=completed) as run:
            result = bridge.invoke_runtime_tool("list-parameters", {"project_path": r"C:\tmp\a.cst"})

        command = run.call_args.args[0]
        self.assertEqual(command[:3], [bridge.sys.executable, "-m", "cst_runtime"])
        self.assertEqual(command[3:6], ["invoke", "--tool", "list-parameters"])
        self.assertEqual(run.call_args.kwargs["stdin"], subprocess.DEVNULL)
        self.assertIn("--args-json", command)
        self.assertEqual(result["json"], {"status": "success", "value": 1})
        self.assertTrue(result["ok"])

    def test_describe_runtime_tool_rejects_empty_tool_name(self):
        with self.assertRaises(ValueError):
            bridge.describe_runtime_tool(" ")


if __name__ == "__main__":
    unittest.main()
