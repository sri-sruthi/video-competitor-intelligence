from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_phase3_live_smoke import (
    build_fallback_slide_interpretations,
    build_fallback_recommendations,
    recommendations_need_fallback,
    sanitize_recommendations_for_slides,
    validate_slide_interpretations,
)


class Phase3LiveSmokeFallbackTests(unittest.TestCase):
    def test_detects_placeholder_recommendations(self) -> None:
        self.assertTrue(
            recommendations_need_fallback(
                [
                    {
                        "title": "Recommendation 1",
                        "action": "See full report for details.",
                    }
                ]
            )
        )
        self.assertFalse(
            recommendations_need_fallback(
                [
                    {
                        "title": "Build a clear conversion layer",
                        "action": "Add one BOFU asset each month.",
                    }
                ]
            )
        )

    def test_builds_specific_non_repetitive_fallback_recommendations(self) -> None:
        result = build_fallback_recommendations(
            "Salesforce",
            {
                "tofu_pct": 80.0,
                "mofu_pct": 20.0,
                "bofu_pct": 0.0,
                "consistency_score": 40.6,
                "mean_gap_days": 8.2,
                "dominant_format": "product_update",
                "dominant_format_pct": 80.0,
                "format_diversity_score": 25.0,
                "dominant_strategy_label": "product_led",
                "funnel_label": "Top-Heavy",
                "short": {"count": 5},
                "medium": {"count": 0},
                "long": {"count": 0},
                "best_performing_length": "short",
            },
            ["enterprise ai platform / proof / case study"],
            66.7,
        )

        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["priority"], "high")
        self.assertNotEqual(result[0]["title"], result[1]["title"])
        self.assertIn("BOFU", result[0]["data_rationale"])
        self.assertIn("SEO score is 66.7/100", result[4]["data_rationale"])

    def test_sanitizes_recommendations_for_slide_copy(self) -> None:
        cleaned = sanitize_recommendations_for_slides(
            [
                {
                    "title": "Revitalize Engagement & Boost Video Views",
                    "action": "Implement A/B testing...",
                    "data_rationale": "Slope is -0.44...",
                    "expected_impact": "Successfully reverse the -0.446 engagement trend into a positive slope.",
                    "priority": "high",
                }
            ]
        )

        self.assertTrue(cleaned[0]["action"].endswith("."))
        self.assertNotIn("...", cleaned[0]["action"])
        self.assertIn("Likely", cleaned[0]["expected_impact"])

    def test_builds_slide_interpretation_fallbacks(self) -> None:
        result = build_fallback_slide_interpretations(
            ["HubSpot", "Salesforce"],
            {
                "HubSpot": {
                    "subscriber_count": 175000,
                    "consistency_score": 37.1,
                    "avg_engagement_rate": 1.30,
                },
                "Salesforce": {
                    "subscriber_count": 863000,
                    "consistency_score": 40.6,
                    "avg_engagement_rate": 1.95,
                },
            },
            {
                "HubSpot": {"rank": 2, "rpi_score": 88.0},
                "Salesforce": {"rank": 1, "rpi_score": 100.0},
            },
            {
                "HubSpot": {"breakdown": {"has_timestamps_pct": 0.0}},
                "Salesforce": {"breakdown": {"has_timestamps_pct": 0.0}},
            },
            {
                "company_coverage": {"HubSpot": [0, 1], "Salesforce": [2]},
            },
            [{"topic": "enterprise ai platform", "opportunity_score": 82.0}],
            [{"title": "Build BOFU coverage"}],
            "Salesforce",
        )

        self.assertIn("slide_03", result)
        self.assertIn("slide_11", result)
        self.assertIn("0% timestamps", result["slide_11"])

    def test_validates_slide_interpretations_against_fallback(self) -> None:
        fallback = {
            "slide_08": "Fallback mentions 3216 views and 91.5 views per day.",
            "slide_11": "Fallback mentions 2 of 4 channels at 0% timestamps.",
        }
        result = validate_slide_interpretations(
            {
                "slide_08": "This matters for cadence overall.",
                "slide_11": "2 of 4 channels show 0% timestamps in the sample.",
            },
            fallback,
        )

        self.assertEqual(result["slide_08"], fallback["slide_08"])
        self.assertEqual(result["slide_11"], "2 of 4 channels show 0% timestamps in the sample.")


if __name__ == "__main__":
    unittest.main()
