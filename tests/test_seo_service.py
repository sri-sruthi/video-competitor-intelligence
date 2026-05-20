from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.phase2_test_support import load_seo_module


SEO_MODULE, FakeTrendReq = load_seo_module()
SEOService = SEO_MODULE.SEOService


class SEOServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeTrendReq.reset()
        self.service = SEOService(
            use_disk_cache=False,
            base_backoff_seconds=0.0,
        )
        self.service._serpapi_api_key = None

    def test_init_uses_expected_pytrends_locale(self) -> None:
        instance = self.service._get_pytrends_client()

        self.assertEqual(instance.kwargs["hl"], "en-US")
        self.assertEqual(instance.kwargs["tz"], 0)

    def test_get_topic_trends_sleeps_between_topics(self) -> None:
        with (
            patch.object(
                self.service,
                "_fetch_single_topic_trends",
                side_effect=[
                    {"avg_interest": 60.0, "fallback_used": False, "source": "pytrends"},
                    {"avg_interest": 70.0, "fallback_used": False, "source": "pytrends"},
                    {"avg_interest": 80.0, "fallback_used": False, "source": "pytrends"},
                ],
            ) as fetch_mock,
            patch.object(SEO_MODULE.time, "sleep") as sleep_mock,
        ):
            result = self.service.get_topic_trends(["crm ai", "demo videos", "use cases"])

        self.assertEqual(fetch_mock.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)
        self.assertEqual(result["crm ai"]["avg_interest"], 60.0)
        self.assertEqual(result["use cases"]["avg_interest"], 80.0)

    def test_get_topic_trends_uses_memory_cache_without_sleeping(self) -> None:
        self.service._set_cached_topic(
            "crm ai",
            {
                "avg_interest": 66.0,
                "trend_direction": "flat",
                "peak_month": "Apr",
                "fallback_used": False,
                "source": "pytrends",
                "retries_used": 0,
                "error_reason": "",
            },
        )

        with (
            patch.object(self.service, "_fetch_single_topic_trends") as fetch_mock,
            patch.object(SEO_MODULE.time, "sleep") as sleep_mock,
        ):
            result = self.service.get_topic_trends(["crm ai"])

        fetch_mock.assert_not_called()
        sleep_mock.assert_not_called()
        self.assertEqual(result["crm ai"]["avg_interest"], 66.0)
        self.assertEqual(result["crm ai"]["source"], "cache")

    def test_parse_trends_csv_export_reads_manual_google_trends_file(self) -> None:
        csv_path = Path(__file__).resolve().parents[1] / "data" / "google_trends_exports" / "crm_ai_worldwide_past_12_months.csv"

        result = self.service.parse_trends_csv_export(csv_path)

        self.assertIn("crm ai", result)
        self.assertEqual(result["crm ai"]["source"], "csv_export")
        self.assertFalse(result["crm ai"]["fallback_used"])
        self.assertEqual(result["crm ai"]["peak_month"], "Mar")
        self.assertEqual(result["crm ai"]["avg_interest"], 44.98)

    def test_score_video_seo_returns_full_score_for_optimized_video(self) -> None:
        videos = [
            {
                "title": "Alpha bravo charlie delta echo foxtrot golf hotel india",
                "description": "00:00 Intro\n" + ("x" * 320),
                "tags": [f"tag-{i}" for i in range(10)],
            }
        ]

        result = self.service.score_video_seo(videos)

        self.assertGreaterEqual(result["seo_score"], 95.0)
        self.assertGreaterEqual(result["breakdown"]["title_length_score"], 90.0)
        self.assertEqual(result["breakdown"]["description_depth"], 100.0)
        self.assertEqual(result["breakdown"]["has_timestamps_pct"], 100.0)
        self.assertEqual(result["breakdown"]["tags_count_avg"], 10.0)
        self.assertEqual(result["breakdown"]["keyword_in_title_score"], 100.0)

    def test_score_video_seo_returns_zero_for_empty_list(self) -> None:
        result = self.service.score_video_seo([])

        self.assertEqual(result["seo_score"], 0.0)
        self.assertEqual(result["breakdown"]["description_depth"], 0.0)

    def test_fetch_single_topic_trends_classifies_rising_and_peak_month(self) -> None:
        topic = "ai crm"
        index = pd.to_datetime(
            ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
        )
        self.service._get_pytrends_client().df = pd.DataFrame({topic: [10, 20, 35, 60]}, index=index)

        result = self.service._fetch_single_topic_trends(topic)

        self.assertEqual(result["avg_interest"], 31.25)
        self.assertEqual(result["trend_direction"], "rising")
        self.assertEqual(result["peak_month"], "Apr")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["source"], "pytrends")
        self.assertEqual(
            self.service._pytrends.last_payload,
            {"kw_list": [topic], "timeframe": "today 12-m", "geo": ""},
        )

    def test_fetch_single_topic_trends_retries_then_succeeds(self) -> None:
        retrying_service = SEOService(
            use_disk_cache=False,
            base_backoff_seconds=1.0,
        )
        topic = "crm ai"
        index = pd.to_datetime(
            ["2026-01-01", "2026-02-01", "2026-03-01", "2026-04-01"]
        )
        retrying_service._get_pytrends_client().df = pd.DataFrame({topic: [10, 20, 35, 60]}, index=index)
        attempts = {"count": 0}

        def flaky_build_payload(**kwargs):
            attempts["count"] += 1
            retrying_service._get_pytrends_client().last_payload = kwargs
            if attempts["count"] < 3:
                raise RuntimeError("429")

        retrying_service._get_pytrends_client().build_payload = flaky_build_payload

        with patch.object(SEO_MODULE.time, "sleep") as sleep_mock:
            result = retrying_service._fetch_single_topic_trends(topic)

        self.assertEqual(attempts["count"], 3)
        self.assertEqual(result["retries_used"], 2)
        self.assertFalse(result["fallback_used"])
        self.assertEqual(sleep_mock.call_count, 2)

    def test_fetch_single_topic_trends_falls_back_on_errors(self) -> None:
        self.service._get_pytrends_client().raise_on_build = RuntimeError("rate limited")

        result = self.service._fetch_single_topic_trends("b2b webinars")

        self.assertEqual(result["avg_interest"], 50.0)
        self.assertEqual(result["trend_direction"], "unknown")
        self.assertEqual(result["peak_month"], "unknown")
        self.assertTrue(result["fallback_used"])
        self.assertEqual(result["source"], "fallback")
        self.assertIn("rate limited", result["error_reason"])

    def test_fetch_single_topic_trends_uses_serpapi_backup_when_configured(self) -> None:
        service = SEOService(
            use_disk_cache=False,
            base_backoff_seconds=0.0,
            serpapi_api_key="serp-key",
        )
        service._get_pytrends_client().raise_on_build = RuntimeError("rate limited")

        payload = {
            "interest_over_time": {
                "timeline_data": [
                    {"timestamp": "1735689600", "values": [{"extracted_value": 20}]},
                    {"timestamp": "1738368000", "values": [{"extracted_value": 35}]},
                    {"timestamp": "1740787200", "values": [{"extracted_value": 50}]},
                    {"timestamp": "1743465600", "values": [{"extracted_value": 80}]},
                ]
            }
        }

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return json.dumps(payload).encode("utf-8")

        with patch.object(SEO_MODULE, "urlopen", return_value=FakeResponse()):
            result = service._fetch_single_topic_trends("crm ai")

        self.assertEqual(result["source"], "serpapi")
        self.assertFalse(result["fallback_used"])
        self.assertEqual(result["avg_interest"], 46.25)
        self.assertEqual(result["trend_direction"], "rising")

    def test_compute_opportunity_scores_prioritises_rising_scarce_topics(self) -> None:
        scored = self.service.compute_opportunity_scores(
            gap_topics=["ai onboarding", "feature roundup"],
            trends_data={
                "ai onboarding": {
                    "avg_interest": 90.0,
                    "trend_direction": "rising",
                    "fallback_used": False,
                    "source": "pytrends",
                },
                "feature roundup": {
                    "avg_interest": 55.0,
                    "trend_direction": "flat",
                    "fallback_used": True,
                    "source": "fallback",
                },
            },
            competitor_coverage={
                "ai onboarding": {"HubSpot": 0, "Salesforce": 0, "Semrush": 0},
                "feature roundup": {"HubSpot": 1, "Salesforce": 0, "Semrush": 0},
            },
        )

        self.assertEqual(scored[0]["topic"], "ai onboarding")
        self.assertEqual(scored[0]["recommendation_type"], "Rising demand, low coverage")
        self.assertFalse(scored[0]["fallback_used"])
        self.assertIn("supporting_evidence", scored[0])
        self.assertIn("suggested_experiment", scored[0])
        self.assertIn("signal_to_watch", scored[0])
        self.assertGreater(
            scored[0]["opportunity_score"],
            scored[1]["opportunity_score"],
        )

    def test_recommendation_type_helper_covers_declining_sparse_topic(self) -> None:
        label = self.service._classify_recommendation_type("declining", 88.0)

        self.assertEqual(label, "Niche test opportunity")


if __name__ == "__main__":
    unittest.main()
