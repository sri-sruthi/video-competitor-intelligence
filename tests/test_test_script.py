from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test import build_comparison_summary, classify_match, interpret_consistency


class TestScriptHelpers(unittest.TestCase):
    def test_interpret_consistency_labels(self) -> None:
        self.assertEqual(interpret_consistency(80.0), "high")
        self.assertEqual(interpret_consistency(60.0), "medium")
        self.assertEqual(interpret_consistency(20.0), "low")

    def test_build_comparison_summary_uses_analytics_reports_only(self) -> None:
        reports = [
            {
                "company_name": "A",
                "ok": True,
                "analytics": {
                    "engagement": {
                        "avg_engagement_rate": 2.0,
                        "views_per_video": 100.0,
                    },
                    "consistency": {"consistency_score": 70.0},
                    "funnel": {"bofu_pct": 20.0},
                },
            },
            {
                "company_name": "B",
                "ok": True,
                "analytics": {
                    "engagement": {
                        "avg_engagement_rate": 1.0,
                        "views_per_video": 300.0,
                    },
                    "consistency": {"consistency_score": 90.0},
                    "funnel": {"bofu_pct": 60.0},
                },
            },
            {"company_name": "C", "ok": False},
        ]

        summary = build_comparison_summary(reports)

        self.assertEqual(summary["engagement_leader"]["company_name"], "A")
        self.assertEqual(summary["views_per_video_leader"]["company_name"], "B")
        self.assertEqual(summary["consistency_leader"]["company_name"], "B")
        self.assertEqual(summary["most_bottom_funnel"]["company_name"], "B")

    def test_classify_match_parent_brand_still_works(self) -> None:
        self.assertEqual(
            classify_match("Mailchimp", "Intuit Mailchimp"),
            "parent-brand",
        )


if __name__ == "__main__":
    unittest.main()
