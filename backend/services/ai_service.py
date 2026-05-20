"""
ai_service.py
AI-powered narrative generation for the Video Competitor Intelligence tool.

Primary provider: Google Gemini
Fallback provider: Groq chat completions
"""

import asyncio
import json
import re
import time
from typing import Any

import certifi
from google import genai
from google.genai import types
import httpx


class AIService:
    """
    Generates strategic video marketing narratives using Google Gemini 2.5 Flash.

    All public methods are synchronous wrappers; async helpers handle
    the 15 RPM free-tier rate limit via asyncio.sleep(4) between calls.
    """

    SYSTEM_PROMPT: str = (
        "You are a senior B2B video growth strategist creating client-facing intelligence for SaaS, fintech, and enterprise brands. "
        "Your job is not to praise competitors. Your job is to help the client company grow. "
        "Translate competitive observations into specific actions the client can take next. "
        "Write for CMOs, founders, and marketing leads who are smart but non-technical. "
        "Be specific, cite the exact data provided, and explain why each point matters in plain English. "
        "Use careful language such as 'suggests', 'appears', or 'may indicate' when the evidence is directional. "
        "Never invent data, never promise exact revenue or uplift, and never give empty advice like 'post more consistently' without saying how, why, and what to measure. "
        "Every output should answer two questions: why should the client care, and what should they do next."
    )
    _MODEL_RETRY_ATTEMPTS: int = 3
    _MODEL_RETRY_BASE_SLEEP_SECONDS: float = 2.0
    _RETRYABLE_ERROR_MARKERS = ("503", "UNAVAILABLE", "RESOURCE_EXHAUSTED")
    _GROQ_MODEL: str = "llama-3.3-70b-versatile"
    _GROQ_ENDPOINT: str = "https://api.groq.com/openai/v1/chat/completions"

    def __init__(self, api_key: str, groq_api_key: str | None = None):
        """
        Initialise the Gemini client.

        Args:
            api_key: A valid Google Gemini API key.
        """
        normalized_api_key = (api_key or "").strip()
        self._groq_api_key = (groq_api_key or "").strip() or None
        if not normalized_api_key and not self._groq_api_key:
            raise ValueError(
                "Missing AI API key. Provide GEMINI_API_KEY, GROQ_API_KEY, or both before creating AIService."
            )
        self._api_key = normalized_api_key
        self._client = genai.Client(api_key=self._api_key) if self._api_key else None
        self._config = types.GenerateContentConfig(
            system_instruction=self.SYSTEM_PROMPT,
        )
        self._call_count = 0  # tracks calls within a session for rate-limit sleep
        self._gemini_blocked_until: float = 0.0
        self._gemini_block_reason: str = ""
        self._groq_disabled_reason: str = ""

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def generate_executive_summary(self, all_companies_data: dict) -> str:
        """
        Generate a 200-word executive summary comparing all companies.

        Consumes:
          all_companies_data: {
            company_name: {
              rpi_score, rank,                        # from compute_rpi()
              avg_engagement_rate,                    # from compute_engagement_metrics()
              consistency_score,                      # from compute_upload_consistency()
              tofu_pct, mofu_pct, bofu_pct,           # from classify_content_funnel()
              funnel_label,
            }
          }

        Returns:
            Clean text string (~200 words).
        """
        lines = []
        for company, data in all_companies_data.items():
            lines.append(
                f"- {company}: RPI={data.get('rpi_score', 'N/A')}, "
                f"rank={data.get('rank', 'N/A')}, "
                f"avg_engagement_rate={data.get('avg_engagement_rate', 'N/A')}%, "
                f"upload_consistency={data.get('consistency_score', 'N/A')}/100, "
                f"funnel={data.get('funnel_label', 'N/A')} "
                f"(TOFU {data.get('tofu_pct', 'N/A')}% / "
                f"MOFU {data.get('mofu_pct', 'N/A')}% / "
                f"BOFU {data.get('bofu_pct', 'N/A')}%)"
            )

        prompt = (
            "Here is comparative video marketing data for multiple companies:\n\n"
            + "\n".join(lines)
            + "\n\nWrite a 200-word executive summary for a video marketing team. "
            "Use cautious language such as 'suggests', 'appears', or 'may indicate'. "
            "Do not claim that the data proves strategy success. "
            "Who is leading and why, based on the sampled metrics (cite specific numbers). "
            "What are the top 3 strategic takeaways? "
            "What does this mean for content planning? "
            "Format the response exactly like this: one short intro paragraph, then 3 to 5 lines starting with '- ', then one final line starting with 'What this means:'. "
            "Avoid markdown headings."
        )
        return asyncio.run(self._call_gemini(prompt))

    def generate_strategy_profiles(self, all_companies_data: dict) -> dict[str, str]:
        """
        Generate a 100-word strategy profile for each company.

        Consumes per company:
          title_patterns    — from analyse_title_patterns()
          funnel_distribution — from classify_content_funnel()
          length_strategy   — from analyse_video_length_strategy()
          consistency_score — from compute_upload_consistency()

        Args:
            all_companies_data: {
              company_name: {
                dominant_strategy_label, dominant_strategy_description,
                funnel_label, tofu_pct, mofu_pct, bofu_pct,
                best_performing_length, consistency_score,
                tutorial_count, listicle_count,
                thought_leadership_count, product_led_count,
              }
            }

        Returns:
            {company_name: profile_text}
        """
        profiles: dict[str, str] = {}

        for company, data in all_companies_data.items():
            prompt = (
                f"Company: {company}\n"
                f"Dominant title strategy: {data.get('dominant_strategy_label', 'N/A')} "
                f"— {data.get('dominant_strategy_description', '')}\n"
                f"Title breakdown: tutorial={data.get('tutorial_count', 0)}, "
                f"listicle={data.get('listicle_count', 0)}, "
                f"thought_leadership={data.get('thought_leadership_count', 0)}, "
                f"product_led={data.get('product_led_count', 0)}\n"
                f"Funnel distribution: {data.get('funnel_label', 'N/A')} "
                f"(TOFU {data.get('tofu_pct', 0)}% / "
                f"MOFU {data.get('mofu_pct', 0)}% / "
                f"BOFU {data.get('bofu_pct', 0)}%)\n"
                f"Best-performing video length: {data.get('best_performing_length', 'N/A')}\n"
                f"Upload consistency score: {data.get('consistency_score', 0)}/100\n\n"
                "Describe this company's apparent video content strategy in 100 words. "
                "What are they optimising for? What audience are they targeting? "
                "What is their production philosophy? Be specific."
            )
            profiles[company] = asyncio.run(self._call_gemini(prompt))

        return profiles

    def generate_gap_analysis(
        self, gap_topics: list[str], pytrends_data: dict
    ) -> str:
        """
        Generate a 150-word gap analysis for uncovered content topics.

        Args:
            gap_topics: List of cluster label strings from
                        cluster_content_topics()["gap_topics"].
            pytrends_data: {topic: {avg_interest, trend_direction, peak_month}}
                           from seo_service.get_topic_trends().

        Returns:
            Clean text string (~150 words).
        """
        if not gap_topics:
            return (
                "The sampled peer set does not show a single obvious uncovered theme, "
                "so the best opportunity is likely to come from strategic whitespace: topics or formats that competitors cover weakly, inconsistently, or without clear buyer-stage intent."
            )

        topic_lines = []
        for topic in gap_topics:
            trends = pytrends_data.get(topic, {})
            topic_lines.append(
                f"- \"{topic}\": avg_search_interest={trends.get('avg_interest', 'N/A')}/100, "
                f"trend={trends.get('trend_direction', 'unknown')}, "
                f"peak_month={trends.get('peak_month', 'N/A')}"
            )

        prompt = (
            "These are content themes with low peer coverage, "
            "along with their Google Trends interest scores:\n\n"
            + "\n".join(topic_lines)
            + "\n\nWrite a 150-word strategic whitespace analysis identifying the top 3 opportunities. "
            "For each opportunity: explain why the client should care, what kind of video to test, and why the demand signal looks promising or cautious. "
            "If a theme label looks noisy or weak, say the signal is low-confidence instead of over-interpreting it. "
            "Do not say 'no content gaps were identified.'"
        )
        return asyncio.run(self._call_gemini(prompt))

    def generate_recommendations(
        self, target_company: str, all_data: dict, gaps: list[str]
    ) -> list[dict]:
        """
        Generate 5 specific, data-driven video marketing recommendations.

        Args:
            target_company: Name of the company to recommend for.
            all_data: Full analytics dict for target_company, containing keys
                      from all Phase 1 analytics methods (engagement, consistency,
                      funnel, length_strategy, title_patterns, rpi).
            gaps: List of gap topic label strings from cluster_content_topics().

        Returns:
            List of 5 dicts.
        """
        company_summary = self._format_company_summary(target_company, all_data)
        gaps_str = ", ".join(f'"{g}"' for g in gaps) if gaps else "none identified"

        prompt = (
            f"{company_summary}\n\n"
            f"Content gap topics not covered by any competitor: {gaps_str}\n\n"
            f"Generate 5 specific video marketing recommendations for {target_company}. "
            "Each recommendation must reference specific numbers from the data above and be written from the client's perspective. "
            "Include the exact action to take, why it matters, the likely business impact, the success KPI to watch, and the supporting evidence. "
            "Expected impact must be directional and qualitative, not a guaranteed or precisely forecasted result. "
            "Do not use ellipses. Do not assume the peer set is perfectly comparable in size or business model. "
            "Avoid generic advice and avoid repeating the same recommendation five different ways.\n\n"
            "Return ONLY a valid JSON array with exactly 5 objects. Each object must have "
            "these exact keys: title, action, data_rationale, why_this_matters, business_impact, success_kpi, supporting_evidence, expected_impact, priority. "
            "priority must be either 'high' or 'medium'. "
            "Do not include any text outside the JSON array."
        )

        raw = asyncio.run(self._call_gemini(prompt))
        return self._parse_json_array(raw, fallback_count=5)

    def generate_action_plan(
        self,
        recommendations: list[dict],
        current_cadence: float,
        planning_context: dict | None = None,
    ) -> str:
        """
        Generate a 90-day video marketing action plan.

        Args:
            recommendations: List of recommendation dicts from
                             generate_recommendations().
            current_cadence: Current mean_gap_days from
                             compute_upload_consistency().

        Returns:
            Clean text string with a structured 90-day plan.
        """
        recs_text = "\n".join(
            f"{i+1}. [{r.get('priority', 'medium').upper()}] {r.get('title', '')}: "
            f"{r.get('action', '')} — {r.get('data_rationale', '')}"
            for i, r in enumerate(recommendations)
        )
        planning_context = planning_context or {}
        whitespace_themes = ", ".join(planning_context.get("whitespace_topics", [])[:3]) or "none highlighted"

        prompt = (
            f"Current upload cadence: one video every {current_cadence:.1f} days.\n\n"
            f"Target company funnel label: {planning_context.get('funnel_label', 'N/A')}\n"
            f"Target company funnel mix: awareness {planning_context.get('tofu_pct', 'N/A')}% / "
            f"consideration {planning_context.get('mofu_pct', 'N/A')}% / proof {planning_context.get('bofu_pct', 'N/A')}%\n"
            f"Top-performing content length: {planning_context.get('best_performing_length', 'N/A')} "
            f"(confidence: {planning_context.get('length_confidence', 'N/A')})\n"
            f"SEO score: {planning_context.get('seo_score', 'N/A')}/100\n"
            f"Whitespace themes: {whitespace_themes}\n\n"
            f"Recommendations to action:\n{recs_text}\n\n"
            "Create a 90-day video marketing action plan based on these recommendations. "
            "Organise into three sections:\n"
            "  • Week 1–2 (quick wins)\n"
            "  • Month 1 (foundation)\n"
            "  • Month 2–3 (growth)\n"
            "For each section: state exactly what to produce, when to publish it, what business goal it supports, "
            "and what metric to track. Use the funnel mix, cadence, format signal, SEO score, and whitespace themes above rather than generic planning advice. "
            "Be specific, reference the actual recommendations above, and keep the language client-ready. "
            "Avoid markdown headers, placeholder company names, and generic boilerplate."
        )
        return asyncio.run(self._call_gemini(prompt))

    def generate_slide_interpretations(self, deck_context: dict) -> dict[str, str]:
        """
        Generate short, client-readable interpretations for the metric slides.

        Returns:
            Dict keyed by slide id, e.g. {"slide_03": "...", "slide_04": "..."}.
        """
        prompt = (
            "You are writing short interpretation notes for a client-facing PowerPoint. "
            "The audience is non-technical. Use plain business language. "
            "Every slide note must cite at least one exact numerical value from that slide's context. "
            "Do not use ellipses. Do not invent metrics. Do not refer to information from other slides unless it is explicitly in that slide's context. "
            "Each value must be 1-2 concise sentences, no markdown bullets. "
            "Frame the point around why the client should care or what the number suggests they should do next. "
            "Avoid jargon like 'evergreen', 'TOFU', 'whitespace', or 'top-of-funnel' unless you immediately explain it in plain English.\n\n"
            "The context object below is already keyed by slide id. Use only the matching slide key when writing each note. "
            "Slide map: slide_02 Executive brief, slide_03 Channel overview, slide_04 Video marketing health score, "
            "slide_05 Upload cadence and consistency, slide_06 Audience journey coverage, slide_07 Engagement trend, "
            "slide_08 Top performing videos, slide_09 Content topics and themes, slide_10 Content format performance, "
            "slide_11 Discovery and search visibility, slide_12 Strategic whitespace opportunities, "
            "slide_13 Priority moves - high, slide_14 Priority moves - medium, slide_15 Company growth scorecard, slide_16 90-day action plan.\n\n"
            "Return ONLY a valid JSON object with these exact keys: "
            "slide_02, slide_03, slide_04, slide_05, slide_06, slide_07, slide_08, slide_09, "
            "slide_10, slide_11, slide_12, slide_13, slide_14, slide_15, slide_16.\n\n"
            f"Slide-specific context:\n{json.dumps(deck_context, ensure_ascii=True)}"
        )
        raw = asyncio.run(self._call_gemini(prompt))
        return self._parse_json_object(raw)

    # ------------------------------------------------------------------
    # Private async core
    # ------------------------------------------------------------------

    async def _call_gemini(self, prompt: str) -> str:
        """
        Send a prompt to the primary provider and optionally fail over to Groq.

        Inserts asyncio.sleep(4) before every call after the first to
        stay within the 15 RPM free-tier quota.

        Args:
            prompt: The user-turn prompt text.

        Returns:
            Stripped response text string.
        """
        if self._call_count > 0:
            await asyncio.sleep(4)

        self._call_count += 1
        gemini_error = self._gemini_block_reason if self._gemini_blocked_until > time.monotonic() else ""
        if self._api_key and self._gemini_blocked_until <= time.monotonic():
            gemini_text, gemini_error = await self._call_gemini_provider(prompt)
            if gemini_text:
                return gemini_text

        if self._groq_api_key and not self._groq_disabled_reason:
            groq_text = await self._call_groq(prompt, prior_error=gemini_error)
            if groq_text:
                return groq_text

        return ""

    async def _call_gemini_provider(self, prompt: str) -> tuple[str, str]:
        """
        Call Gemini and return (text, error_message).
        """
        self._client = genai.Client(api_key=self._api_key)
        last_error = ""
        for attempt in range(self._MODEL_RETRY_ATTEMPTS):
            try:
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=self._config,
                )
                return response.text.strip(), ""
            except Exception as exc:
                message = str(exc)
                last_error = message
                if "RESOURCE_EXHAUSTED" in message or "Quota exceeded" in message:
                    delay_seconds = self._extract_retry_delay_seconds(message)
                    self._gemini_blocked_until = time.monotonic() + delay_seconds
                    self._gemini_block_reason = message
                retryable = any(marker in message for marker in self._RETRYABLE_ERROR_MARKERS)
                if retryable and attempt < self._MODEL_RETRY_ATTEMPTS - 1:
                    delay = self._MODEL_RETRY_BASE_SLEEP_SECONDS * (2 ** attempt)
                    await asyncio.sleep(delay)
                    continue

                print(f"[AIService] Gemini API error (call #{self._call_count}): {exc}")
                break

        return "", last_error

    async def _call_groq(self, prompt: str, prior_error: str = "") -> str:
        """
        Call Groq as a fallback provider using its OpenAI-compatible endpoint.
        """
        if self._groq_disabled_reason:
            return ""
        try:
            return await asyncio.to_thread(self._call_groq_sync, prompt)
        except Exception as exc:
            suffix = f" after Gemini failure: {prior_error}" if prior_error else ""
            print(f"[AIService] Groq fallback error (call #{self._call_count}): {exc}{suffix}")
            return ""

    def _call_groq_sync(self, prompt: str) -> str:
        if not self._groq_api_key:
            return ""

        payload = {
            "model": self._GROQ_MODEL,
            "messages": [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
        }
        headers = {
            "Authorization": f"Bearer {self._groq_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "video-competitor-intel/1.0",
        }

        try:
            with httpx.Client(timeout=45.0, verify=certifi.where(), headers=headers) as client:
                response = client.post(self._GROQ_ENDPOINT, json=payload)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Groq transport error: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500]
            if response.status_code in (401, 403, 404):
                self._groq_disabled_reason = (
                    f"Groq disabled for this run due to HTTP {response.status_code}. "
                    "Check GROQ_API_KEY, project permissions, allowed models, or account access."
                )
            raise RuntimeError(f"Groq HTTP {response.status_code}: {detail}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError(f"Groq returned non-JSON response: {response.text[:300]}") from exc

        choices = payload.get("choices", [])
        if not choices:
            return ""

        message = choices[0].get("message", {})
        return str(message.get("content", "")).strip()

    @staticmethod
    def _extract_retry_delay_seconds(message: str) -> float:
        match = re.search(r"retry in ([0-9]+(?:\.[0-9]+)?)s", message, flags=re.IGNORECASE)
        if match:
            return max(float(match.group(1)), 1.0)
        match = re.search(r"retryDelay': '([0-9]+)s'", message)
        if match:
            return max(float(match.group(1)), 1.0)
        match = re.search(r"retryDelay': '([0-9]+(?:\.[0-9]+)?)ms'", message)
        if match:
            return max(float(match.group(1)) / 1000.0, 1.0)
        return 60.0

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _format_company_summary(company: str, data: dict) -> str:
        """Format a concise analytics summary string for Gemini prompts."""
        return (
            f"Company: {company}\n"
            f"RPI score: {data.get('rpi_score', 'N/A')} (rank {data.get('rank', 'N/A')})\n"
            f"Avg engagement rate: {data.get('avg_engagement_rate', 'N/A')}%\n"
            f"Engagement trend slope: {data.get('engagement_trend_slope', 'N/A')}\n"
            f"Views per video: {data.get('views_per_video', 'N/A')}\n"
            f"Upload consistency score: {data.get('consistency_score', 'N/A')}/100\n"
            f"Mean upload gap: {data.get('mean_gap_days', 'N/A')} days\n"
            f"Cadence confidence: {data.get('cadence_confidence', 'N/A')}\n"
            f"Weekly cadence detected: {data.get('detect_weekly_cadence', 'N/A')}\n"
            f"Funnel distribution: {data.get('funnel_label', 'N/A')} "
            f"(TOFU {data.get('tofu_pct', 'N/A')}% / "
            f"MOFU {data.get('mofu_pct', 'N/A')}% / "
            f"BOFU {data.get('bofu_pct', 'N/A')}%)\n"
            f"Funnel confidence: {data.get('funnel_confidence', 'N/A')}\n"
            f"Best-performing video length: {data.get('best_performing_length', 'N/A')}\n"
            f"Length confidence: {data.get('length_confidence', 'N/A')}\n"
            f"Dominant title strategy: {data.get('dominant_strategy_label', 'N/A')}\n"
            f"Dominant format: {data.get('dominant_format', 'N/A')}\n"
            f"Format diversity score: {data.get('format_diversity_score', 'N/A')}/100\n"
            f"SEO score: {data.get('seo_score', 'N/A')}/100"
        )

    @staticmethod
    def _parse_json_array(raw: str, fallback_count: int = 5) -> list[dict]:
        """
        Parse a JSON array from a Gemini response, stripping markdown fences.

        Args:
            raw: Raw response string from Gemini.
            fallback_count: Number of empty placeholder dicts to return on failure.

        Returns:
            Parsed list of dicts, or a list of empty dicts on failure.
        """
        # Strip markdown code fences if present
        cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()

        # Extract the first [...] block
        match = re.search(r"\[.*\]", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, list):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass

        print(f"[AIService] Failed to parse JSON array. Raw response:\n{raw[:500]}")
        return [
            {
                "title": f"Recommendation {i + 1}",
                "action": "See full report for details.",
                "data_rationale": "",
                "why_this_matters": "",
                "business_impact": "",
                "success_kpi": "",
                "supporting_evidence": "",
                "expected_impact": "",
                "priority": "medium",
            }
            for i in range(fallback_count)
        ]

    @staticmethod
    def _parse_json_object(raw: str) -> dict[str, str]:
        """
        Parse a JSON object from a model response, stripping markdown fences.
        """
        cleaned = re.sub(r"```(?:json)?", "", raw).replace("```", "").strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(0)

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except (json.JSONDecodeError, ValueError):
            pass

        return {}
