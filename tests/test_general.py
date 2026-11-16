"""Generic multi-winding scenarios and human-readable advice checks."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from advisor import inspect_design, inspect_settings, inspect_candidate
from engine import Output, Settings, optimize
from winding_layout import (
    Bobbin, Packing, Winding, calculate_layout, from_candidate
)


class GeneralPurposeTests(unittest.TestCase):
    def test_generic_default(self):
        s = Settings()
        self.assertEqual(len(s.outputs), 3)
        self.assertNotIn("Upper", " ".join(o.name for o in s.outputs))
        self.assertTrue(optimize(s))

    def test_many_outputs(self):
        outputs = [Output(f"Out {i}", f"Group {i//4}", 12 if i % 2 else 5, .015)
                   for i in range(24)]
        c = optimize(Settings(outputs=outputs))[0]
        self.assertEqual(len(c.windings), 24)

    def test_invalid_settings_explained(self):
        notes = inspect_settings(Settings(vin_min_v=40, vin_max_v=10))
        self.assertTrue(any(n.level == "ERROR" for n in notes))
        self.assertTrue(all(n.action for n in notes))

    def test_multiple_winding_advice(self):
        s = Settings(outputs=[
            Output(f"Out {i}", "G", 5, .015) for i in range(18)
        ])
        notes = inspect_settings(s)
        self.assertIn("MANY_WINDINGS", [n.code for n in notes])

    def test_output_voltage_error_advice(self):
        s = Settings(outputs=[
            Output("first", "G", 12, .2), Output("tiny", "G", 0.9, .05)])
        candidates = optimize(s)
        self.assertTrue(candidates)
        codes = {note.code for note in inspect_candidate(s, candidates[0])}
        self.assertIn("MOSFET_VDS", codes)

    def test_nominal_winding_geometry(self):
        s = Settings()
        c = optimize(s)[0]
        layout = calculate_layout(from_candidate(c), Bobbin(
            name="Custom", winding_width_mm=25,
            mean_turn_length_mm=65))
        self.assertEqual(layout.fits, None)
        self.assertGreaterEqual(len(layout.layers), len(s.outputs) + 1)
        self.assertGreater(layout.wire_length_m, 0)

    def test_radial_overflow_recommendation(self):
        w = [Winding("primary", "P", 20, .5, 2),
             Winding("secondary", "S", 50, .4, 1)]
        layout = calculate_layout(w, Bobbin("Small", 10, 40, 0.4))
        self.assertFalse(layout.fits)
        self.assertIn("НЕ ПОМЕЩАЕТСЯ", " ".join(layout.warnings))

    def test_large_bobbin_fit(self):
        w = [Winding("primary", "P", 8, .2),
             Winding("secondary", "S", 15, .2)]
        layout = calculate_layout(w, Bobbin("Large", 30, 40, 10))
        self.assertTrue(layout.fits)

    def test_reject_invalid_width(self):
        with self.assertRaises(ValueError):
            calculate_layout([Winding("P", "P", 5, .2)],
                             Bobbin("Custom", 2, 40),
                             Packing(end_margin_mm=1.5))


if __name__ == "__main__":
    unittest.main()
