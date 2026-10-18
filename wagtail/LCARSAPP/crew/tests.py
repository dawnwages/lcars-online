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

    def test_text_value_that_never_occurs_is_refused(self):
        # Regression: Tactical filtered disc_method = 'transit' (the code is 'tran'),
        # got 0 planets, and spent its whole budget guessing names
        with self.assertRaisesRegex(science.InvalidFilter, "has no value 'transit'.*'tran'"):
            science.apply_filters(self.df, [{"column": "disc_method", "op": "eq", "value": "transit"}])
        subset, _ = science.apply_filters(self.df, [{"column": "disc_method", "op": "eq", "value": "tran"}])
        self.assertGreater(len(subset), 4000)


class ReviewNumberTests(SimpleTestCase):
    """Regression: mission 7's Tactical cited p=0.07 and '97%', numbers nothing computed."""

    EVIDENCE = ["{'n': 3639, 'silverman': {'p_value': 0.018}, 'valley': {'radius_earth': 1.719}}",
                "{'final_n': 113}", "{'n_planets': 6451}"]

    def test_invented_numbers_are_caught(self):
        from crew.agents import unsupported_numbers
        claim = ("97% transit-dominated (4785/6451). Non-significant (p=0.07) for n=113. "
                 "Full sample n=3639, p=0.018, valley at 1.72.")
        self.assertEqual(unsupported_numbers(claim, self.EVIDENCE), ["0.07", "4785", "97%"])

    def test_cited_numbers_and_small_counts_pass(self):
        from crew.agents import unsupported_numbers
        self.assertEqual(unsupported_numbers(
            "n=3639 with p=0.018; valley 1.72; 113 long-period planets; 2 issues; 1.8% of n", 
            self.EVIDENCE + ["0.018"]), [])


    def test_percent_written_without_sign_matches_a_fraction(self):
        # Regression: mission 13's reviewer cited the 20% precision cut as "20"; results store 0.2
        from crew.agents import unsupported_numbers
        self.assertEqual(unsupported_numbers("Significant at cuts down to 20 percent error",
                                             ["{'radius_rel_err_lt': 0.2}"]), [])



class NumberCheckFormatTests(SimpleTestCase):
    """How people write numbers in reports, decided up front rather than one mission at a time.

    Regressions: mission 14's Log wrote "1,938" (split into "1" and "938"), and a percent
    leniency made the check accept invented numbers like p = 0.07 and "97%".
    """

    EVIDENCE = ["{'n': 1938, 'p_value': 0.004, 'radius_earth': 1.75, 'ci95': [1.659, 1.818], "
                "'depth_ratio': 0.719, 'final_n': 1918, 'n_planets': 6451, 'cut': 0.15, 'p8': 0.06}"]

    SUPPORTED = {
        "thousands separator": "We analyzed 1,938 planets (1,918 by transit) of 6,451.",
        "range with hyphen": "The 95% interval is 1.66-1.82 Earth radii.",
        "range with en dash": "The 95% interval is 1.66\u20131.82 Earth radii.",
        "range with to": "from 1.659 to 1.818",
        "approximately": "a valley at ~1.75 and p\u22480.004",
        "inequality": "p<0.05 is the threshold and p = 0.004",
        "percent of a fraction": "radius error under 15% (15 percent)",
        "rounded": "valley at 1.8 Earth radii, depth 0.72",
        "small counts": "significant at four of six cuts, 2 issues",
    }
    INVENTED = {
        "a p-value nothing computed": ("p = 0.07", ["0.07"]),
        "a count nothing produced": ("113 long-period planets", ["113"]),
        "a percentage of nothing": ("97% transit-dominated", ["97%"]),
        "a wrong count with separator": ("4,785 transit planets", ["4,785"]),
    }

    def test_supported_formats_pass(self):
        from crew.agents import unsupported_numbers
        for name, text in self.SUPPORTED.items():
            with self.subTest(name):
                self.assertEqual(unsupported_numbers(text, self.EVIDENCE + ["0.05"]), [])

    def test_invented_numbers_are_caught(self):
        from crew.agents import unsupported_numbers
        for name, (text, expected) in self.INVENTED.items():
            with self.subTest(name):
                self.assertEqual(unsupported_numbers(text, self.EVIDENCE), expected)
