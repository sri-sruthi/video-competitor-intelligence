from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.analytics_service import AnalyticsService


class AnalyticsServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = AnalyticsService()

    def test_upload_consistency_is_high_for_regular_weekly_schedule(self) -> None:
        videos = [
            {"published_at": "2026-05-01T00:00:00Z"},
            {"published_at": "2026-05-08T00:00:00Z"},
            {"published_at": "2026-05-15T00:00:00Z"},
            {"published_at": "2026-05-22T00:00:00Z"},
        ]

        result = self.service.compute_upload_consistency(videos)

        self.assertEqual(result["mean_gap_days"], 7.0)
        self.assertEqual(result["std_gap_days"], 0.0)
        self.assertEqual(result["consistency_score"], 100.0)
        self.assertTrue(result["detect_weekly_cadence"])

    def test_upload_consistency_stays_nonzero_for_irregular_schedule(self) -> None:
        videos = [
            {"published_at": "2026-05-01T00:00:00Z"},
            {"published_at": "2026-05-02T00:00:00Z"},
            {"published_at": "2026-05-10T00:00:00Z"},
            {"published_at": "2026-05-11T00:00:00Z"},
            {"published_at": "2026-05-25T00:00:00Z"},
        ]

        result = self.service.compute_upload_consistency(videos)

        self.assertGreater(result["std_gap_days"], 0.0)
        self.assertGreater(result["consistency_score"], 0.0)
        self.assertLess(result["consistency_score"], 100.0)

    def test_classify_content_funnel_tracks_default_classifications(self) -> None:
        videos = [
            {"title": "Brand campaign launch", "description": ""},
            {"title": "Feature comparison for buyers", "description": ""},
            {"title": "Customer onboarding walkthrough", "description": ""},
        ]

        result = self.service.classify_content_funnel(videos)

        self.assertEqual(result["tofu_count"], 0)
        self.assertEqual(result["mofu_count"], 1)
        self.assertEqual(result["bofu_count"], 1)
        self.assertEqual(result["unclassified_count"], 1)
        self.assertEqual(result["funnel_label"], "Low confidence")

    def test_analyse_format_mix_detects_multiple_editorial_formats(self) -> None:
        videos = [
            {"title": "How to onboard new customers", "description": "", "duration_seconds": 420},
            {"title": "Q2 Product Update", "description": "", "duration_seconds": 90},
            {"title": "Customer Story: Acme Corp", "description": "", "duration_seconds": 180},
            {"title": "2026 Marketing Webinar", "description": "", "duration_seconds": 1800},
        ]

        result = self.service.analyse_format_mix(videos)

        self.assertEqual(result["counts"]["tutorial"], 1)
        self.assertEqual(result["counts"]["product_update"], 1)
        self.assertEqual(result["counts"]["customer_story"], 1)
        self.assertEqual(result["counts"]["webinar"], 1)
        self.assertGreater(result["format_diversity_score"], 0.0)

    def test_compute_recent_view_velocity_uses_publish_age(self) -> None:
        videos = [
            {"published_at": "2026-05-18T00:00:00Z", "view_count": 500},
            {"published_at": "2026-05-14T00:00:00Z", "view_count": 1000},
        ]

        class FixedDateTime:
            @classmethod
            def now(cls, tz=None):
                from datetime import datetime, timezone
                return datetime(2026, 5, 19, tzinfo=timezone.utc)

            @classmethod
            def fromisoformat(cls, value):
                from datetime import datetime
                return datetime.fromisoformat(value)

        with patch("backend.services.analytics_service.datetime", FixedDateTime):
            result = self.service.compute_recent_view_velocity(videos)

        self.assertAlmostEqual(result["avg_views_per_day"], 350.0, places=2)
        self.assertAlmostEqual(result["median_views_per_day"], 350.0, places=2)
        self.assertAlmostEqual(result["top_views_per_day"], 500.0, places=2)


if __name__ == "__main__":
    unittest.main()
