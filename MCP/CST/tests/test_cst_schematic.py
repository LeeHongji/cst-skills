from __future__ import annotations

import unittest

from cst_schematic import CSTSchematicVBA, SchematicEndpoint, vba_string, wrap_sub_main


class CSTSchematicVBATests(unittest.TestCase):
    def test_vba_string_escapes_quotes(self):
        self.assertEqual(vba_string('a"b'), '"a""b"')

    def test_wrap_sub_main_adds_wrapper(self):
        self.assertEqual(wrap_sub_main("ReportInformationToWindow(\"x\")"), 'Sub Main\nReportInformationToWindow("x")\nEnd Sub')

    def test_resistor_vba_sets_verified_property(self):
        code = CSTSchematicVBA.resistor("Rload", 100)

        self.assertIn('.Type("CircuitBasic\\Resistor")', code)
        self.assertIn('.SetLocalUnitForProperty("Resistance", "Ohm")', code)
        self.assertIn('.SetDoubleProperty("Resistance", "100")', code)

    def test_touchstone_block_sets_file(self):
        code = CSTSchematicVBA.block("NPORT1", "touchstone", file_path=r"C:\tmp\a.s2p")

        self.assertIn('.Type("Touchstone")', code)
        self.assertIn('.SetFile("C:\\tmp\\a.s2p")', code)

    def test_connect_generates_component_port_array(self):
        endpoints = [
            SchematicEndpoint("Externalport", "1", 0),
            SchematicEndpoint("BLOCK", "R1", 0),
        ]

        code = CSTSchematicVBA.connect(endpoints, net_name="net_in")

        self.assertIn("Dim ComponentPorts_net_in(1, 2) As Variant", code)
        self.assertIn('ComponentPorts_net_in(0, 0) = "EXTERNALPORT"', code)
        self.assertIn('ComponentPorts_net_in(1, 1) = "R1"', code)
        self.assertIn('GeneratedNetName_net_in = .AddComponentPorts("", ComponentPorts_net_in, False)', code)
        self.assertIn('If "net_in" <> "" Then .Rename GeneratedNetName_net_in, "net_in"', code)

    def test_frequency_sweep_creates_sparameter_task(self):
        code = CSTSchematicVBA.frequency_sweep(task_name="SPara1", fmin=1, fmax=10, samples=91)

        self.assertIn('.Type("S-Parameters")', code)
        self.assertIn('.SetLocalUnit("Frequency", "GHz")', code)
        self.assertIn('.SetSweepData(1, 10, 91)', code)


if __name__ == "__main__":
    unittest.main()
