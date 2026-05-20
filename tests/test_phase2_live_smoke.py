from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.run_phase2_live_smoke import (
    dedupe_topics,
    generate_single_company_summary,
    infer_trend_topics,
)


class Phase2LiveSmokeTopicTests(unittest.TestCase):
    def test_known_hubspot_pack_is_company_specific(self) -> None:
        topics = infer_trend_topics(
            "HubSpot",
            "HubSpot",
            [],
        )

        self.assertEqual(
            topics,
            [
                "crm ai",
                "customer onboarding software",
                "marketing automation",
                "sales pipeline management",
                "product demo videos",
            ],
        )

    def test_video_agency_topics_are_more_relevant_than_generic_saas_topics(self) -> None:
        topics = infer_trend_topics(
            "mypromovideos",
            "Mypromovideos - Animation Video Production Agency",
            [
                {
                    "title": "Best SaaS Explainer Video",
                    "description": "Animation walkthrough for product onboarding",
                }
            ],
        )

        self.assertIn("explainer video", topics)
        self.assertIn("motion graphics video", topics)
        self.assertNotIn("crm ai", topics)

    def test_unknown_saas_channel_uses_saas_topic_pack(self) -> None:
        topics = infer_trend_topics(
            "AcmeFlow",
            "AcmeFlow",
            [
                {
                    "title": "How to automate customer onboarding",
                    "description": "CRM workflow automation for sales teams",
                }
            ],
        )

        self.assertIn("crm ai", topics)
        self.assertIn("sales enablement software", topics)

    def test_dedupe_topics_preserves_order_and_limit(self) -> None:
        topics = dedupe_topics(
            [
                "crm ai",
                "CRM AI",
                "customer onboarding software",
                "crm ai",
                "product demo videos",
                "sales enablement software",
                "marketing automation",
            ],
            limit=4,
        )

        self.assertEqual(
            topics,
            [
                "crm ai",
                "customer onboarding software",
                "product demo videos",
                "sales enablement software",
            ],
        )

    def test_single_company_summary_prompt_uses_cautious_balanced_guidance(self) -> None:
        captured = {}

        class FakeAI:
            async def _call_gemini(self, prompt: str) -> str:
                captured["prompt"] = prompt
                return "Summary"

        result = generate_single_company_summary(
            FakeAI(),
            "HubSpot",
            {
                "avg_engagement_rate": 1.3,
                "views_per_video": 1400.0,
                "avg_views_per_day": 210.5,
                "consistency_score": 37.08,
                "funnel_label": "Top-Heavy",
                "tofu_pct": 80.0,
                "mofu_pct": 20.0,
                "bofu_pct": 0.0,
                "unclassified_count": 3,
                "best_performing_length": "short",
                "dominant_format": "product_update",
                "dominant_format_pct": 40.0,
                "format_diversity_score": 57.1,
                "dominant_strategy_label": "product_led",
                "dominant_strategy_description": "Feature-focused",
                "seo_score": 78.9,
            },
            {
                "crm ai": {
                    "avg_interest": 43.94,
                    "trend_direction": "flat",
                    "peak_month": "Mar",
                    "source": "serpapi",
                }
            },
        )

        self.assertEqual(result, "Summary")
        self.assertIn("Treat funnel distribution as a heuristic", captured["prompt"])
        self.assertIn("Do not over-focus on TOFU/MOFU/BOFU alone", captured["prompt"])
        self.assertIn("Average views per day: 210.5", captured["prompt"])
        self.assertIn("Dominant format: product_update", captured["prompt"])
        self.assertIn("default-classified videos=3", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
