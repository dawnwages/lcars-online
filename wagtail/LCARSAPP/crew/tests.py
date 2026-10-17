import numpy as np
import pandas as pd
from django.test import SimpleTestCase

from crew import science

TRANSIT = [{"column": "disc_method", "op": "eq", "value": "tran"}]


class SnapshotTests(SimpleTestCase):
    def test_snapshot_hash_is_enforced(self):
        df, digest = science.load_snapshot()
        self.assertEqual(digest, science.SNAPSHOT_SHA256)
        self.assertEqual(len(df), 6375)
        with self.assertRaises(ValueError):
            science.load_snapshot(expected_sha256="0" * 64)

    def test_data_card_surfaces_known_hazards(self):
        df, _ = science.load_snapshot()
        card = science.data_card(df)
        # Almost half of masses are inferred from radius, not measured
        self.assertGreater(card["mass_from_mass_radius_relation_pct"], 40)
        # Discovery method drives which orbits are in the catalog
        periods = card["median_orbital_period_days_by_method"]
        self.assertGreater(periods["rv"], 10 * periods["tran"])

    def test_filters_reject_unknown_columns_and_ops(self):
        df, _ = science.load_snapshot()
        with self.assertRaises(ValueError):
            science.apply_filters(df, [{"column": "nope", "op": "eq", "value": 1}])
        with self.assertRaises(ValueError):
            science.apply_filters(df, [{"column": "pl_rade", "op": "drop", "value": 1}])


class RadiusValleyTests(SimpleTestCase):
    """Ground truth for the crew's evals."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        df, _ = science.load_snapshot()
        subset, _ = science.apply_filters(df, TRANSIT + [
            {"column": "rade_rel_err", "op": "lt", "value": 0.10}])
        cls.radii = subset["pl_rade"].dropna()

    def test_valley_found_with_moderate_precision_cut(self):
        a = science.analyze_radius_distribution(self.radii, n_boot=200, seed=1)
        self.assertLess(a.silverman["p_value"], 0.05)
        self.assertTrue(1.5 <= a.valley["radius_earth"] <= 2.1)

    def test_negative_control_finds_no_valley(self):
        r = np.asarray(self.radii)
        x = np.log10(r[(r >= 1) & (r <= 4)])
        null = 10 ** science.synthetic_null(x, seed=1)
        a = science.analyze_radius_distribution(null, n_boot=200, seed=1)
        self.assertGreater(a.silverman["p_value"], 0.05)

    def test_specification_curve_reports_every_cut(self):
        df, _ = science.load_snapshot()
        rows = science.specification_curve(df, TRANSIT, error_cuts=(None, 0.10, 0.05),
                                           n_boot=50, seed=1)
        self.assertEqual([r["radius_rel_err_lt"] for r in rows], [None, 0.10, 0.05])
        locations = [r["valley_radius_earth"] for r in rows if r["valley_radius_earth"]]
        self.assertTrue(all(1.5 <= v <= 2.1 for v in locations))


class SampleSizeGuardTests(SimpleTestCase):
    def test_empty_population_is_refused_not_significant(self):
        # Regression: n=0 once produced p=0.0
        with self.assertRaises(science.InsufficientSample):
            science.analyze_radius_distribution([], n_boot=10)
        with self.assertRaises(science.InsufficientSample):
            science.analyze_radius_distribution([1.5] * 50, n_boot=10)


class IngestTests(SimpleTestCase):
    """Validation and change detection for scheduled archive fetches (no network)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from crew import ingest
        cls.ingest = ingest
        cls.raw = science.SNAPSHOT.read_bytes()

    def test_valid_archive_is_accepted(self):
        df = self.ingest.validate.fn(self.raw)
        self.assertEqual(len(df), 6375)

    def test_error_page_and_truncated_download_are_refused(self):
        with self.assertRaises(ValueError):
            self.ingest.validate.fn(b"<?xml version='1.0'?><VOTABLE>ERROR</VOTABLE>")
        truncated = b"\n".join(self.raw.split(b"\n")[:100])
        with self.assertRaises(ValueError):
            self.ingest.validate.fn(truncated)

    def test_changes_are_detected(self):
        old = self.ingest.validate.fn(self.raw)
        new = old.copy()
        new.loc[new.pl_name == "Kepler-297 d", "pl_rade"] = 7.1
        new = new[new.pl_name != "11 Com b"]
        extra = old.iloc[[0]].assign(pl_name="TOI-9999 b", disc_method="tran")
        new = pd.concat([new, extra])
        changes = self.ingest.compare.fn(new, old)
        self.assertEqual((changes["added"], changes["removed"], changes["revised"]), (1, 1, 1))
        self.assertEqual(changes["revised_examples"][0]["fields"]["pl_rade"][1], 7.1)
        self.assertEqual(changes["added_by_method"], {"tran": 1})


class FilterValidationTests(SimpleTestCase):
    """Regression: a comparison with no value silently matched 0 planets, sending the
    Qwen Science Officer into a 34-minute debugging loop."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.df, _ = science.load_snapshot()

    def test_comparison_without_value_is_refused(self):
        with self.assertRaisesRegex(science.InvalidFilter, "needs a value"):
            science.apply_filters(self.df, [{"column": "pl_rade", "op": "gt", "value": None}])

    def test_numeric_text_is_converted(self):
        subset, steps = science.apply_filters(self.df, [{"column": "pl_rade", "op": "gt", "value": "1.0"}])
        self.assertGreater(len(subset), 4000)
        self.assertEqual(steps[0]["value"], 1.0)

    def test_order_ops_on_text_columns_are_refused(self):
        with self.assertRaisesRegex(science.InvalidFilter, "is text"):
            science.apply_filters(self.df, [{"column": "disc_method", "op": "lt", "value": "tran"}])
        with self.assertRaisesRegex(science.InvalidFilter, "not a number"):
            science.apply_filters(self.df, [{"column": "pl_rade", "op": "lt", "value": "big"}])
