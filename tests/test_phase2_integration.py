from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.analytics_service import AnalyticsService
from tests.phase2_test_support import load_ai_module, load_seo_module


AI_MODULE, FakeClient = load_ai_module()
SEO_MODULE, FakeTrendReq = load_seo_module()
AIService = AI_MODULE.AIService
SEOService = SEO_MODULE.SEOService


def make_videos(prefix: str) -> list[dict]:
    return [
        {
            "title": f"Introducing {prefix} AI workflows for revenue teams",
            "description": "00:00 Intro\n" + ("x" * 320),
            "tags": ["ai", "crm", "workflows", "revops", "sales", "marketing"],
            "published_at": "2026-05-01T00:00:00Z",
            "view_count": 1200,
            "like_count": 30,
            "comment_count": 4,
            "duration_seconds": 210,
        },
        {
            "title": f"How to launch {prefix} onboarding faster",
            "description": "00:00 Setup\n" + ("x" * 280),
            "tags": ["onboarding", "tutorial", "saas"],
            "published_at": "2026-05-05T00:00:00Z",
            "view_count": 850,
            "like_count": 22,
            "comment_count": 6,
            "duration_seconds": 430,
        },
        {
            "title": f"The future of {prefix} customer education",
            "description": "Perspective video " + ("y" * 210),
            "tags": ["thought leadership", "education"],
            "published_at": "2026-05-10T00:00:00Z",
            "view_count": 660,
            "like_count": 11,
            "comment_count": 2,
            "duration_seconds": 620,
        },
        {
            "title": f"5 ways {prefix} demos convert better",
            "description": "00:00 Tips\n" + ("z" * 305),
            "tags": ["demos", "conversion", "listicle", "video"],
            "published_at": "2026-05-17T00:00:00Z",
            "view_count": 980,
            "like_count": 25,
            "comment_count": 5,
            "duration_seconds": 260,
        },
        {
            "title": f"{prefix} integration walkthrough for ops teams",
            "description": "00:00 Walkthrough\n" + ("w" * 330),
            "tags": ["integration", "ops", "tutorial", "implementation"],
            "published_at": "2026-05-24T00:00:00Z",
            "view_count": 720,
            "like_count": 19,
            "comment_count": 3,
            "duration_seconds": 540,
        },
    ]


class Phase2IntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClient.reset()
        FakeTrendReq.reset()
        self.analytics = AnalyticsService()
        self.seo = SEOService()
        self.ai = AIService("test-key")

    def _build_company_profile(self, company_name: str, videos: list[dict]) -> dict:
        engagement = self.analytics.compute_engagement_metrics(videos)
        consistency = self.analytics.compute_upload_consistency(videos)
        funnel = self.analytics.classify_content_funnel(videos)
        length = self.analytics.analyse_video_length_strategy(videos)
        titles = self.analytics.analyse_title_patterns(videos)
        seo_score = self.seo.score_video_seo(videos)

        return {
            **engagement,
            **consistency,
            **funnel,
            **length,
            "rpi_score": 72.4 if company_name == "HubSpot" else 68.2,
            "rank": 1 if company_name == "HubSpot" else 2,
            "dominant_strategy_label": titles["dominant_strategy"]["label"],
            "dominant_strategy_description": titles["dominant_strategy"]["description"],
            "tutorial_count": titles["tutorial_count"],
            "listicle_count": titles["listicle_count"],
            "thought_leadership_count": titles["thought_leadership_count"],
            "product_led_count": titles["product_led_count"],
            "seo_score": seo_score["seo_score"],
        }

    def test_pipeline_generates_recommendations_from_phase1_and_seo_metrics(self) -> None:
        profile = self._build_company_profile("HubSpot", make_videos("HubSpot"))

        FakeClient.queued_results = [
            json.dumps(
                [
                    {
                        "title": f"Recommendation {i}",
                        "action": "Ship deeper implementation videos",
                        "data_rationale": "Tutorials outperform thought leadership.",
                        "expected_impact": "Higher conversion intent.",
                        "priority": "high" if i == 1 else "medium",
                    }
                    for i in range(1, 6)
                ]
            )
        ]

        with patch.object(AI_MODULE.asyncio, "sleep", new=AsyncMock()):
            recommendations = self.ai.generate_recommendations(
                "HubSpot",
                profile,
                ["agent onboarding", "crm implementation proof"],
            )

        self.assertEqual(len(recommendations), 5)
        self.assertEqual(recommendations[0]["title"], "Recommendation 1")
        self.assertEqual(recommendations[0]["priority"], "high")

        prompt = self.ai._client.calls[-1]["contents"]
        self.assertIn("Company: HubSpot", prompt)
        self.assertIn("SEO score:", prompt)
        self.assertIn('"agent onboarding"', prompt)

    def test_pipeline_supports_summary_profiles_gap_analysis_and_action_plan(self) -> None:
        hubspot = self._build_company_profile("HubSpot", make_videos("HubSpot"))
        salesforce = self._build_company_profile("Salesforce", make_videos("Salesforce"))
        gaps = ["agent onboarding", "video roi calculator"]
        trends = {
            "agent onboarding": {
                "avg_interest": 82.0,
                "trend_direction": "rising",
                "peak_month": "Apr",
            },
            "video roi calculator": {
                "avg_interest": 61.0,
                "trend_direction": "flat",
                "peak_month": "Mar",
            },
        }
        opportunities = self.seo.compute_opportunity_scores(
            gaps,
            trends,
            {
                "HubSpot": [],
                "Salesforce": ["video roi calculator"],
            },
        )

        FakeClient.queued_results = [
            "Executive summary",
            "HubSpot profile",
            "Salesforce profile",
            "Gap analysis",
            "90-day plan",
        ]

        with patch.object(AI_MODULE.asyncio, "sleep", new=AsyncMock()):
            summary = self.ai.generate_executive_summary(
                {
                    "HubSpot": hubspot,
                    "Salesforce": salesforce,
                }
            )
            profiles = self.ai.generate_strategy_profiles(
                {
                    "HubSpot": hubspot,
                    "Salesforce": salesforce,
                }
            )
            gap_analysis = self.ai.generate_gap_analysis(gaps, trends)
            plan = self.ai.generate_action_plan(
                [
                    {
                        "title": opportunities[0]["topic"],
                        "action": "Publish one video per week around this gap.",
                        "data_rationale": "Search demand is rising and no peer owns it.",
                        "priority": "high",
                    }
                ],
                current_cadence=6.8,
            )

        self.assertEqual(summary, "Executive summary")
        self.assertEqual(profiles["HubSpot"], "HubSpot profile")
        self.assertEqual(profiles["Salesforce"], "Salesforce profile")
        self.assertEqual(gap_analysis, "Gap analysis")
        self.assertEqual(plan, "90-day plan")
        self.assertEqual(opportunities[0]["topic"], "agent onboarding")
        total_calls = sum(len(client.calls) for client in FakeClient.created_clients)
        self.assertEqual(total_calls, 5)
        self.assertIn(
            "Current upload cadence: one video every 6.8 days",
            FakeClient.created_clients[-1].calls[-1]["contents"],
        )


if __name__ == "__main__":
    unittest.main()
