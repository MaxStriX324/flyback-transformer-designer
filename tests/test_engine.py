"""Unit tests for the initial preliminary DCM model."""
import math
import sys
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine import Core, Output, Settings, load_project, optimize, save_project, validate, compare_cores


class TransformerTests(unittest.TestCase):
    def test_default_eight_windings(self):
        s = Settings()
        results = optimize(s)
        self.assertTrue(results)
        c = results[0]
        self.assertEqual(len(c.windings), 8)
        self.assertLessEqual(c.bpk_t, s.max_b_t)
        self.assertLessEqual(c.used_window_fraction, s.window_utilization)
        self.assertGreaterEqual(c.idle_fraction, s.min_demag_margin)

    def test_primary_energy(self):
        s = Settings()
        c = optimize(s)[0]
        pin = c.total_power_w / s.efficiency
        self.assertAlmostEqual(
            pin, 0.5 * c.lp_uh * 1e-6 * c.input_peak_a**2 *
            s.frequency_khz * 1e3, places=8)

    def test_primary_copper_loss(self):
        s = Settings()
        c = optimize(s)[0]
        area = c.primary_strands * math.pi / 4 * c.primary_wire_mm**2
        rho = 0.01724 * (1 + 0.00393 * (s.winding_temp_c - 20))
        predicted = (c.input_rms_a**2 * rho * s.core.mlt_mm / 1000 *
                     1.15 * c.primary_turns / area)
        self.assertAlmostEqual(c.primary_copper_loss_w, predicted, places=10)

    def test_polarity(self):
        c = optimize(Settings())[0]
        self.assertGreater(c.windings[0].predicted_v, 0)
        self.assertLess(c.windings[1].predicted_v, 0)

    def test_invalid_input(self):
        with self.assertRaises(ValueError):
            validate(Settings(vin_min_v=40, vin_max_v=10))

    def test_json_roundtrip(self):
        s = Settings()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "design.json"
            save_project(s, path)
            self.assertEqual(asdict(s), asdict(load_project(path)))

    def test_more_than_twenty_windings(self):
        s = Settings()
        s.outputs.extend(
            Output(f"AUX {n}", f"ISO-{n}", 5, 0.004, 0.6)
            for n in range(18))
        result = optimize(s)
        self.assertTrue(result)
        self.assertEqual(len(result[0].windings), 26)

    def test_tiny_core_rejected(self):
        tiny = Core("Impossible", 1e-6, 1e-6, 100, 1200, 30)
        self.assertEqual(optimize(Settings(core=tiny)), [])

    def test_core_comparison(self):
        summary = compare_cores(Settings())
        self.assertIn("ETD39", summary)


if __name__ == "__main__":
    unittest.main()
