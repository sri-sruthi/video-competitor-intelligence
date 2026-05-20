from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.phase2_test_support import load_ai_module


AI_MODULE, FakeClient = load_ai_module()
AIService = AI_MODULE.AIService


class AIServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        FakeClient.reset()

    def test_init_requires_non_empty_api_key(self) -> None:
        with self.assertRaises(ValueError):
            AIService("")

    def test_init_configures_gemini_model_once(self) -> None:
        service = AIService("test-key")

        self.assertEqual(len(FakeClient.created_clients), 1)
        client = FakeClient.created_clients[0]
        self.assertEqual(client.api_key, "test-key")
        self.assertEqual(service._config.system_instruction, service.SYSTEM_PROMPT)

    def test_call_gemini_sleeps_after_first_call_and_recovers_from_errors(self) -> None:
        service = AIService("test-key")
        FakeClient.queued_results = [" first response ", RuntimeError("boom")]

        with patch.object(AI_MODULE.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            first = asyncio.run(service._call_gemini("Prompt one"))
            second = asyncio.run(service._call_gemini("Prompt two"))

        self.assertEqual(first, "first response")
        self.assertEqual(second, "")
        self.assertEqual(service._call_count, 2)
        sleep_mock.assert_awaited_once_with(4)
        self.assertEqual(service._client.calls[0]["model"], "gemini-2.5-flash")
        self.assertEqual(service._client.calls[0]["config"], service._config)

    def test_call_gemini_retries_retryable_503_errors(self) -> None:
        service = AIService("test-key")
        FakeClient.queued_results = [
            RuntimeError("503 UNAVAILABLE"),
            " recovered ",
        ]

        with patch.object(AI_MODULE.asyncio, "sleep", new=AsyncMock()) as sleep_mock:
            result = asyncio.run(service._call_gemini("Retry please"))

        self.assertEqual(result, "recovered")
        self.assertEqual(len(service._client.calls), 2)
        sleep_mock.assert_any_await(2.0)

    def test_call_gemini_falls_back_to_groq_when_gemini_fails(self) -> None:
        service = AIService("test-key", groq_api_key="groq-key")
        FakeClient.queued_results = [
            RuntimeError("503 UNAVAILABLE"),
            RuntimeError("503 UNAVAILABLE"),
            RuntimeError("503 UNAVAILABLE"),
        ]

        with (
            patch.object(AI_MODULE.asyncio, "sleep", new=AsyncMock()) as sleep_mock,
            patch.object(service, "_call_groq", new=AsyncMock(return_value="groq recovered")) as groq_mock,
        ):
            result = asyncio.run(service._call_gemini("Fallback please"))

        self.assertEqual(result, "groq recovered")
        groq_mock.assert_awaited_once()
        sleep_mock.assert_any_await(2.0)

    def test_call_gemini_skips_provider_until_retry_window_after_quota_error(self) -> None:
        service = AIService("test-key", groq_api_key="groq-key")
        service._gemini_blocked_until = 10_000_000.0

        with (
            patch.object(AI_MODULE.time, "monotonic", return_value=1.0),
            patch.object(service, "_call_gemini_provider", new=AsyncMock()) as gemini_mock,
            patch.object(service, "_call_groq", new=AsyncMock(return_value="groq recovered")) as groq_mock,
        ):
            result = asyncio.run(service._call_gemini("Fallback now"))

        self.assertEqual(result, "groq recovered")
        gemini_mock.assert_not_awaited()
        groq_mock.assert_awaited_once()

    def test_call_groq_disables_future_fallbacks_after_hard_403(self) -> None:
        service = AIService("test-key", groq_api_key="groq-key")

        class FakeClient:
            def __init__(self, *args, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def post(self, *args, **kwargs):
                return SimpleNamespace(status_code=403, text="error code: 1010")

        with patch.object(AI_MODULE.httpx, "Client", FakeClient):
            result = asyncio.run(service._call_groq("Try Groq", prior_error="quota"))

        self.assertEqual(result, "")
        self.assertIn("HTTP 403", service._groq_disabled_reason)

        with patch.object(service, "_call_groq_sync") as sync_mock:
            second = asyncio.run(service._call_groq("Try again", prior_error="quota"))

        self.assertEqual(second, "")
        sync_mock.assert_not_called()

    def test_generate_slide_interpretations_parses_json_object_response(self) -> None:
        service = AIService("test-key")

        async def fake_call(prompt: str) -> str:
            self.assertIn("slide_03", prompt)
            self.assertIn("slide_16", prompt)
            return json.dumps(
                {
                    "slide_03": "Channel overview insight.",
                    "slide_04": "RPI insight.",
                    "slide_16": "Action plan insight.",
                }
            )

        service._call_gemini = fake_call
        result = service.generate_slide_interpretations({"companies": ["HubSpot"]})

        self.assertEqual(result["slide_03"], "Channel overview insight.")
        self.assertEqual(result["slide_04"], "RPI insight.")
        self.assertEqual(result["slide_16"], "Action plan insight.")

    def test_parse_json_array_strips_fences_and_extracts_list(self) -> None:
        raw = """```json
        [{"title": "Ship benchmark explainers", "priority": "high"}]
        ```"""

        parsed = AIService._parse_json_array(raw)

        self.assertEqual(parsed[0]["title"], "Ship benchmark explainers")
        self.assertEqual(parsed[0]["priority"], "high")

    def test_parse_json_array_returns_fallback_shape_on_invalid_json(self) -> None:
        parsed = AIService._parse_json_array("not valid json", fallback_count=3)

        self.assertEqual(len(parsed), 3)
        self.assertEqual(parsed[0]["title"], "Recommendation 1")
        self.assertEqual(parsed[0]["priority"], "medium")

    def test_generate_executive_summary_passes_company_metrics_to_prompt(self) -> None:
        service = AIService("test-key")
        captured: dict[str, str] = {}

        async def fake_call(prompt: str) -> str:
            captured["prompt"] = prompt
            return "Executive summary"

        service._call_gemini = fake_call

        result = service.generate_executive_summary(
            {
                "HubSpot": {
                    "rpi_score": 81.4,
                    "rank": 1,
                    "avg_engagement_rate": 2.3,
                    "consistency_score": 62.5,
                    "funnel_label": "Top-Heavy",
                    "tofu_pct": 60.0,
                    "mofu_pct": 25.0,
                    "bofu_pct": 15.0,
                }
            }
        )

        self.assertEqual(result, "Executive summary")
        self.assertIn("HubSpot", captured["prompt"])
        self.assertIn("RPI=81.4", captured["prompt"])
        self.assertIn("TOFU 60.0%", captured["prompt"])

    def test_generate_recommendations_parses_json_response(self) -> None:
        service = AIService("test-key")
        recommendations = [
            {
                "title": f"Recommendation {i}",
                "action": "Do the thing",
                "data_rationale": "Because the numbers say so",
                "expected_impact": "Higher pipeline",
                "priority": "high" if i == 1 else "medium",
            }
            for i in range(1, 6)
        ]

        async def fake_call(prompt: str) -> str:
            self.assertIn("Content gap topics not covered by any competitor", prompt)
            self.assertIn("SEO score: 74.5/100", prompt)
            return json.dumps(recommendations)

        service._call_gemini = fake_call

        result = service.generate_recommendations(
            "Mailchimp",
            {
                "rpi_score": 65.3,
                "rank": 2,
                "avg_engagement_rate": 1.9,
                "engagement_trend_slope": 0.03,
                "views_per_video": 1240.0,
                "consistency_score": 58.0,
                "mean_gap_days": 6.5,
                "detect_weekly_cadence": True,
                "funnel_label": "Balanced",
                "tofu_pct": 40.0,
                "mofu_pct": 30.0,
                "bofu_pct": 30.0,
                "best_performing_length": "medium",
                "dominant_strategy_label": "tutorial",
                "seo_score": 74.5,
            },
            ["ai onboarding", "crm migration"],
        )

        self.assertEqual(len(result), 5)
        self.assertEqual(result[0]["title"], "Recommendation 1")
        self.assertEqual(result[0]["action"], "Do the thing")

    def test_extract_retry_delay_seconds_parses_seconds_and_milliseconds(self) -> None:
        self.assertEqual(
            AIService._extract_retry_delay_seconds("Please retry in 13.501443241s."),
            13.501443241,
        )
        self.assertEqual(
            AIService._extract_retry_delay_seconds("retryDelay': '66.979954ms'"),
            1.0,
        )

    def test_generate_action_plan_embeds_cadence_and_priorities(self) -> None:
        service = AIService("test-key")
        captured: dict[str, str] = {}

        async def fake_call(prompt: str) -> str:
            captured["prompt"] = prompt
            return "90-day action plan"

        service._call_gemini = fake_call

        result = service.generate_action_plan(
            [
                {
                    "title": "Ship customer proof shorts",
                    "action": "Publish 2 testimonial edits per month",
                    "data_rationale": "BOFU share is underweight",
                    "priority": "high",
                },
                {
                    "title": "Refresh onboarding tutorials",
                    "action": "Replace stale setup guides",
                    "data_rationale": "Tutorials drive repeat viewing",
                    "priority": "medium",
                },
            ],
            current_cadence=9.5,
        )

        self.assertEqual(result, "90-day action plan")
        self.assertIn("one video every 9.5 days", captured["prompt"])
        self.assertIn("[HIGH] Ship customer proof shorts", captured["prompt"])
        self.assertIn("[MEDIUM] Refresh onboarding tutorials", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
