"""
seo_service.py
Google Trends and SEO signal analysis for the Video Competitor Intelligence tool.

Compatible with youtube_service.py and analytics_service.py from Phase 1.
"""

from __future__ import annotations

import csv
import json
import re
import ssl
import time
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen
from datetime import datetime
from pathlib import Path

import certifi
from pytrends.request import TrendReq
from backend.config import SERPAPI_API_KEY


class SEOService:
    """
    Provides Google Trends data and SEO signal scoring for YouTube video lists.

    pytrends is an unofficial Google Trends scraper, so this service uses:
      - lightweight throttling between topic lookups
      - retry with exponential backoff on transient failures
      - in-memory + disk cache to avoid repeated lookups
      - explicit fallback metadata so callers can tell when trend data is real
    """

    _TRENDS_SLEEP_SECONDS: float = 2.0
    _MAX_RETRIES: int = 3
    _BASE_BACKOFF_SECONDS: float = 2.0
    _CACHE_TTL_SECONDS: int = 24 * 60 * 60
    _FALLBACK_CACHE_TTL_SECONDS: int = 60 * 60
    _CACHE_VERSION: int = 1

    _MONTH_NAMES = {
        1: "Jan",
        2: "Feb",
        3: "Mar",
        4: "Apr",
        5: "May",
        6: "Jun",
        7: "Jul",
        8: "Aug",
        9: "Sep",
        10: "Oct",
        11: "Nov",
        12: "Dec",
    }

    def __init__(
        self,
        *,
        use_disk_cache: bool = True,
        serpapi_api_key: str | None = None,
        cache_ttl_seconds: int | None = None,
        fallback_cache_ttl_seconds: int | None = None,
        max_retries: int | None = None,
        base_backoff_seconds: float | None = None,
    ):
        """Initialise a shared pytrends session and optional cache."""
        self._pytrends = None
        self._pytrends_init_error = ""
        self._use_disk_cache = use_disk_cache
        self._serpapi_api_key = (
            serpapi_api_key.strip()
            if isinstance(serpapi_api_key, str) and serpapi_api_key.strip()
            else SERPAPI_API_KEY
        )
        self._cache_ttl_seconds = (
            self._CACHE_TTL_SECONDS
            if cache_ttl_seconds is None
            else max(int(cache_ttl_seconds), 0)
        )
        self._fallback_cache_ttl_seconds = (
            self._FALLBACK_CACHE_TTL_SECONDS
            if fallback_cache_ttl_seconds is None
            else max(int(fallback_cache_ttl_seconds), 0)
        )
        self._max_retries = self._MAX_RETRIES if max_retries is None else max(int(max_retries), 1)
        self._base_backoff_seconds = (
            self._BASE_BACKOFF_SECONDS
            if base_backoff_seconds is None
            else max(float(base_backoff_seconds), 0.0)
        )
        self._cache_path = (
            Path(__file__).resolve().parent.parent.parent
            / ".cache"
            / "seo_trends_cache.json"
        )
        self._trend_cache: dict[str, dict] = self._load_cache()

    # ------------------------------------------------------------------
    # 1. Google Trends topic lookup
    # ------------------------------------------------------------------

    def get_topic_trends(self, topics: list[str]) -> dict[str, dict]:
        """
        Retrieve Google Trends interest_over_time for each topic (last 12 months).

        Returns:
            {
              topic: {
                avg_interest: float,
                trend_direction: str,
                peak_month: str,
                fallback_used: bool,
                source: str,          # "pytrends" | "cache" | "fallback"
                retries_used: int,
                error_reason: str,
              }
            }
        """
        results: dict[str, dict] = {}
        fetched_live = 0

        for topic in topics:
            cached = self._get_cached_topic(topic)
            if cached is not None:
                results[topic] = cached
                continue

            if fetched_live > 0:
                time.sleep(self._TRENDS_SLEEP_SECONDS)

            fetched = self._fetch_single_topic_trends(topic)
            results[topic] = fetched
            self._set_cached_topic(topic, fetched)
            fetched_live += 1

        return results

    def parse_trends_csv_export(self, csv_path: str | Path) -> dict:
        """
        Parse a Google Trends CSV export file into the same shape used elsewhere.

        This is a manual fallback when pytrends and SerpApi are unavailable.
        The CSV is expected to look like:
          "Time","crm ai"
          "2025-05-18",8
          ...

        Returns:
            {
              topic: {
                avg_interest, trend_direction, peak_month,
                fallback_used, source, retries_used, error_reason
              }
            }
        """
        path = Path(csv_path)
        default = {
            "unknown": self._default_trend_payload(
                fallback_used=True,
                source="fallback",
                retries_used=0,
                error_reason=f"Unable to parse CSV export: {path}",
            )
        }

        try:
            with path.open(newline="") as handle:
                rows = list(csv.reader(handle))
        except OSError:
            return default

        if len(rows) < 2 or len(rows[0]) < 2:
            return default

        topic = rows[0][1].strip().strip('"') or "unknown"
        dates: list[datetime] = []
        values: list[int] = []

        for row in rows[1:]:
            if len(row) < 2:
                continue
            raw_date = row[0].strip().strip('"')
            raw_value = row[1].strip()
            if not raw_date or not raw_value:
                continue

            try:
                point_date = datetime.fromisoformat(raw_date)
                point_value = int(raw_value)
            except ValueError:
                continue

            dates.append(point_date)
            values.append(point_value)

        if not values:
            return default

        avg_interest = sum(values) / len(values)
        if len(values) >= 4:
            slope = self._simple_slope(list(range(len(values))), values)
            if slope > 1.0:
                trend_direction = "rising"
            elif slope < -1.0:
                trend_direction = "declining"
            else:
                trend_direction = "flat"
        else:
            trend_direction = "unknown"

        peak_index = values.index(max(values))
        peak_month = self._MONTH_NAMES.get(dates[peak_index].month, "unknown")

        return {
            topic: {
                "avg_interest": round(avg_interest, 2),
                "trend_direction": trend_direction,
                "peak_month": peak_month,
                "fallback_used": False,
                "source": "csv_export",
                "retries_used": 0,
                "error_reason": "",
            }
        }

    # ------------------------------------------------------------------
    # 2. Video SEO scoring
    # ------------------------------------------------------------------

    def score_video_seo(self, videos: list[dict]) -> dict:
        """
        Compute a composite SEO score for a company's video list.

        Signal weights:
          title_length_score     0.25
          description_depth      0.25
          has_timestamps_pct     0.20
          tags_count_avg         0.15
          keyword_in_title_score 0.15
        """
        if not videos:
            return {
                "seo_score": 0.0,
                "seo_label": "Low visibility foundation",
                "breakdown": {
                    "title_length_score": 0.0,
                    "description_depth": 0.0,
                    "has_timestamps_pct": 0.0,
                    "tags_count_avg": 0.0,
                    "keyword_in_title_score": 0.0,
                },
            }

        n = len(videos)
        timestamp_re = re.compile(r"\b\d{1,2}:\d{2}\b")
        intent_re = re.compile(
            r"\b(how|why|what|guide|tutorial|demo|comparison|vs|pricing|setup|review|case study)\b",
            re.IGNORECASE,
        )

        title_lengths: list[float] = []
        desc_scores: list[float] = []
        timestamp_flags: list[float] = []
        tags_counts: list[float] = []
        keyword_title_flags: list[float] = []

        for v in videos:
            title = v.get("title", "")
            description = v.get("description", "")
            tags = v.get("tags", [])

            title_len = len(title)
            if 45 <= title_len <= 75:
                tl_score = 100.0
            elif title_len < 45:
                tl_score = (title_len / 45) * 100.0
            else:
                overshoot = title_len - 75
                tl_score = max(0.0, 100.0 - (overshoot / 35) * 100.0)
            title_lengths.append(tl_score)

            desc_len = len(description.strip())
            desc_word_count = len(description.split())
            if desc_len < 80:
                dd_score = 20.0
            elif desc_len < 180:
                dd_score = 55.0
            elif desc_len < 320:
                dd_score = 80.0
            else:
                dd_score = 100.0
            desc_scores.append(dd_score)

            timestamp_flags.append(1.0 if timestamp_re.search(description) else 0.0)
            tags_counts.append(float(len(tags) if isinstance(tags, list) else 0))
            keyword_title_flags.append(
                1.0 if intent_re.search(title) or len(title.split()) >= 6 else 0.0
            )

        avg_tl = sum(title_lengths) / n
        avg_dd = sum(desc_scores) / n
        avg_ts_pct = (sum(timestamp_flags) / n) * 100.0

        raw_avg_tags = sum(tags_counts) / n
        norm_tags = min(raw_avg_tags / 12.0 * 100.0, 100.0)
        keyword_score = (sum(keyword_title_flags) / n) * 100.0

        seo_score = (
            0.25 * avg_tl
            + 0.25 * avg_dd
            + 0.20 * avg_ts_pct
            + 0.15 * norm_tags
            + 0.15 * keyword_score
        )

        rounded_score = round(seo_score, 2)
        if rounded_score >= 80:
            seo_label = "Strong discovery foundation"
        elif rounded_score >= 60:
            seo_label = "Solid but uneven discovery setup"
        elif rounded_score >= 40:
            seo_label = "Discovery basics need work"
        else:
            seo_label = "Low visibility foundation"

        return {
            "seo_score": rounded_score,
            "seo_label": seo_label,
            "breakdown": {
                "title_length_score": round(avg_tl, 2),
                "description_depth": round(avg_dd, 2),
                "has_timestamps_pct": round(avg_ts_pct, 2),
                "tags_count_avg": round(raw_avg_tags, 2),
                "keyword_in_title_score": round(keyword_score, 2),
            },
        }

    # ------------------------------------------------------------------
    # 3. Content opportunity scoring
    # ------------------------------------------------------------------

    def compute_opportunity_scores(
        self,
        gap_topics: list[str],
        trends_data: dict,
        competitor_coverage: dict,
    ) -> list[dict]:
        """
        Rank gap topics by their content opportunity score.

        opportunity_score = (trend_interest * 0.45) + (scarcity_score * 0.35) + (momentum_score * 0.20)
        """
        topic_company_counts: dict[str, dict[str, int]] = {}

        for topic in gap_topics:
            counts: dict[str, int] = {}
            if topic in competitor_coverage and isinstance(competitor_coverage.get(topic), dict):
                counts = {
                    str(company): int(value)
                    for company, value in competitor_coverage.get(topic, {}).items()
                }
            else:
                for company, cluster_ids in competitor_coverage.items():
                    normalized_ids = [str(cluster_id) for cluster_id in cluster_ids]
                    counts[str(company)] = 1 if topic in normalized_ids else 0
            topic_company_counts[topic] = counts

        scored: list[dict] = []

        for topic in gap_topics:
            trend_info = trends_data.get(topic, {})
            trend_interest = float(trend_info.get("avg_interest", 50))
            trend_direction = trend_info.get("trend_direction", "unknown")

            company_counts = topic_company_counts.get(topic, {})
            count_values = list(company_counts.values()) if company_counts else [0]
            max_count = max(count_values)
            total_count = sum(count_values)
            company_presence = sum(1 for value in count_values if value > 0)

            if max_count == 0:
                scarcity_score = 100.0
            else:
                saturation_ratio = total_count / max(max_count * len(count_values), 1)
                presence_ratio = company_presence / max(len(count_values), 1)
                scarcity_score = max(
                    0.0,
                    100.0 - ((0.55 * saturation_ratio) + (0.45 * presence_ratio)) * 100.0,
                )

            if trend_direction == "rising":
                momentum_score = 100.0
            elif trend_direction == "flat":
                momentum_score = 60.0
            elif trend_direction == "declining":
                momentum_score = 30.0
            else:
                momentum_score = 45.0

            opportunity_score = round(
                (trend_interest * 0.45) + (scarcity_score * 0.35) + (momentum_score * 0.20),
                2,
            )

            recommendation_type = self._classify_recommendation_type(
                trend_direction, scarcity_score
            )
            if scarcity_score >= 75 and trend_direction == "rising":
                brief = "High-upside whitespace with visible demand momentum."
            elif scarcity_score >= 75:
                brief = "Underused theme with room for a differentiated test."
            elif trend_direction == "rising":
                brief = "Growing demand, but peers are already active here."
            else:
                brief = "Useful as a selective experiment rather than a core pillar."

            topic_label = self._client_ready_topic_label(topic)
            evidence = (
                f"Trend interest is {trend_interest:.0f}/100, scarcity is {scarcity_score:.0f}/100, "
                f"and {company_presence} of {max(len(count_values), 1)} peers actively cover this theme."
            )
            if trend_direction == "rising":
                suggested_experiment = (
                    f"Test one search-led explainer or proof asset on {topic_label} in the next publishing cycle."
                )
                signal_to_watch = "Track first-14-day views-per-day, packaging click appeal, and engagement rate."
            elif scarcity_score >= 75:
                suggested_experiment = (
                    f"Pilot a focused {topic_label} series and compare response against current core themes."
                )
                signal_to_watch = "Watch repeat-viewer response and whether the topic earns above-baseline comments or saves."
            else:
                suggested_experiment = (
                    f"Use {topic_label} as a selective supporting topic rather than a primary content pillar."
                )
                signal_to_watch = "Monitor whether discovery improves enough to justify repeating the topic."

            scored.append(
                {
                    "topic": topic,
                    "opportunity_score": opportunity_score,
                    "trend_interest": round(trend_interest, 2),
                    "momentum_score": round(momentum_score, 2),
                    "scarcity_score": round(scarcity_score, 2),
                    "recommendation_type": recommendation_type,
                    "opportunity_brief": brief,
                    "supporting_evidence": evidence,
                    "suggested_experiment": suggested_experiment,
                    "signal_to_watch": signal_to_watch,
                    "fallback_used": bool(trend_info.get("fallback_used", False)),
                    "trend_source": trend_info.get("source", "unknown"),
                }
            )

        return sorted(scored, key=lambda x: x["opportunity_score"], reverse=True)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _default_trend_payload(
        self,
        *,
        fallback_used: bool,
        source: str,
        retries_used: int,
        error_reason: str = "",
    ) -> dict:
        return {
            "avg_interest": 50.0,
            "trend_direction": "unknown",
            "peak_month": "unknown",
            "fallback_used": fallback_used,
            "source": source,
            "retries_used": retries_used,
            "error_reason": error_reason,
        }

    def _fetch_single_topic_trends(self, topic: str) -> dict:
        """
        Fetch 12-month Google Trends data for a single topic.

        Retries transient failures with exponential backoff and returns
        fallback metadata when pytrends still fails.
        """
        last_error = ""

        for attempt in range(self._max_retries):
            try:
                pytrends = self._get_pytrends_client()
                pytrends.build_payload(
                    kw_list=[topic],
                    timeframe="today 12-m",
                    geo="",
                )
                df = pytrends.interest_over_time()

                if df is None or df.empty or topic not in df.columns:
                    return self._default_trend_payload(
                        fallback_used=True,
                        source="fallback",
                        retries_used=attempt,
                        error_reason="empty_response",
                    )

                series = df[topic].dropna()
                if series.empty:
                    return self._default_trend_payload(
                        fallback_used=True,
                        source="fallback",
                        retries_used=attempt,
                        error_reason="empty_series",
                    )

                avg_interest = float(series.mean())
                y = series.values
                if len(y) >= 4:
                    slope = self._simple_slope(list(range(len(series))), list(y))
                    if slope > 1.0:
                        trend_direction = "rising"
                    elif slope < -1.0:
                        trend_direction = "declining"
                    else:
                        trend_direction = "flat"
                else:
                    trend_direction = "unknown"

                peak_idx = series.idxmax()
                if isinstance(peak_idx, datetime):
                    peak_month = self._MONTH_NAMES.get(peak_idx.month, "unknown")
                else:
                    peak_month = "unknown"

                return {
                    "avg_interest": round(avg_interest, 2),
                    "trend_direction": trend_direction,
                    "peak_month": peak_month,
                    "fallback_used": False,
                    "source": "pytrends",
                    "retries_used": attempt,
                    "error_reason": "",
                }

            except Exception as exc:
                last_error = str(exc)
                if attempt < self._max_retries - 1:
                    delay = self._base_backoff_seconds * (2 ** attempt)
                    if delay > 0:
                        time.sleep(delay)
                    continue

        serpapi_result = self._fetch_serpapi_topic_trends(topic, error_reason=last_error)
        if serpapi_result is not None:
            return serpapi_result

        print(f"[SEOService] pytrends error for '{topic}': {last_error}")
        return self._default_trend_payload(
            fallback_used=True,
            source="fallback",
            retries_used=self._max_retries - 1,
            error_reason=last_error,
        )

    def _fetch_serpapi_topic_trends(
        self,
        topic: str,
        *,
        error_reason: str,
    ) -> dict | None:
        """
        Try SerpApi's Google Trends endpoint as a backup provider.

        Returns None when SerpApi is unavailable, unconfigured, or fails.
        """
        if not self._serpapi_api_key:
            return None

        params = {
            "engine": "google_trends",
            "q": topic,
            "data_type": "TIMESERIES",
            "date": "today 12-m",
            "tz": "0",
            "api_key": self._serpapi_api_key,
        }
        url = f"https://serpapi.com/search.json?{urlencode(params)}"
        ssl_context = ssl.create_default_context(cafile=certifi.where())

        try:
            with urlopen(url, timeout=20, context=ssl_context) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, URLError, TimeoutError, ValueError, json.JSONDecodeError) as exc:
            print(f"[SEOService] SerpApi fallback error for '{topic}': {exc}")
            return None

        timeline = payload.get("interest_over_time", {}).get("timeline_data", [])
        values: list[int] = []
        peak_month = "unknown"
        peak_value = -1

        for point in timeline:
            bucket_values = point.get("values", [])
            if not bucket_values:
                continue

            first = bucket_values[0]
            extracted = first.get("extracted_value")
            if extracted is None:
                continue

            try:
                numeric = int(extracted)
            except (TypeError, ValueError):
                continue

            values.append(numeric)

            timestamp = point.get("timestamp")
            if numeric > peak_value and timestamp:
                try:
                    peak_dt = datetime.fromtimestamp(int(timestamp))
                    peak_month = self._MONTH_NAMES.get(peak_dt.month, "unknown")
                    peak_value = numeric
                except (TypeError, ValueError, OSError):
                    pass

        if not values:
            return None

        avg_interest = sum(values) / len(values)
        if len(values) >= 4:
            slope = self._simple_slope(list(range(len(values))), values)
            if slope > 1.0:
                trend_direction = "rising"
            elif slope < -1.0:
                trend_direction = "declining"
            else:
                trend_direction = "flat"
        else:
            trend_direction = "unknown"

        return {
            "avg_interest": round(avg_interest, 2),
            "trend_direction": trend_direction,
            "peak_month": peak_month,
            "fallback_used": False,
            "source": "serpapi",
            "retries_used": self._max_retries,
            "error_reason": error_reason,
        }

    def _get_pytrends_client(self):
        if self._pytrends is not None:
            return self._pytrends

        try:
            self._pytrends = TrendReq(hl="en-US", tz=0)
            self._pytrends_init_error = ""
            return self._pytrends
        except Exception as exc:
            self._pytrends_init_error = str(exc)
            raise

    def _normalize_topic_key(self, topic: str) -> str:
        return " ".join(topic.lower().split())

    def _get_cache_ttl_seconds(self, payload: dict) -> int:
        if payload.get("fallback_used"):
            return self._fallback_cache_ttl_seconds
        return self._cache_ttl_seconds

    def _get_cached_topic(self, topic: str) -> dict | None:
        key = self._normalize_topic_key(topic)
        entry = self._trend_cache.get(key)
        if not entry:
            return None

        fetched_at = float(entry.get("fetched_at", 0.0))
        ttl = self._get_cache_ttl_seconds(entry.get("data", {}))
        if ttl <= 0 or fetched_at <= 0:
            return None
        if time.time() - fetched_at > ttl:
            return None

        return {
            **entry["data"],
            "source": "cache",
        }

    def _set_cached_topic(self, topic: str, payload: dict) -> None:
        key = self._normalize_topic_key(topic)
        self._trend_cache[key] = {
            "fetched_at": time.time(),
            "data": payload,
        }
        self._save_cache()

    def _load_cache(self) -> dict[str, dict]:
        if not self._use_disk_cache or not self._cache_path.exists():
            return {}

        try:
            raw = json.loads(self._cache_path.read_text())
        except (OSError, json.JSONDecodeError, ValueError):
            return {}

        if raw.get("version") != self._CACHE_VERSION:
            return {}

        topics = raw.get("topics", {})
        return topics if isinstance(topics, dict) else {}

    def _save_cache(self) -> None:
        if not self._use_disk_cache:
            return

        self._cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": self._CACHE_VERSION,
            "topics": self._trend_cache,
        }
        try:
            self._cache_path.write_text(json.dumps(payload, indent=2, sort_keys=True))
        except OSError:
            pass

    @staticmethod
    def _simple_slope(x: list[float], y: list[float]) -> float:
        """Compute the OLS slope of y on x without scipy dependency."""
        n = len(x)
        if n < 2:
            return 0.0
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_x2 = sum(xi**2 for xi in x)
        denom = n * sum_x2 - sum_x**2
        if denom == 0:
            return 0.0
        return (n * sum_xy - sum_x * sum_y) / denom

    @staticmethod
    def _classify_recommendation_type(
        trend_direction: str, scarcity_score: float
    ) -> str:
        """Assign a recommendation type label based on trend and scarcity signals."""
        rising = trend_direction == "rising"
        flat = trend_direction in ("flat", "unknown")
        high_scarcity = scarcity_score >= 70.0

        if rising and high_scarcity:
            return "Rising demand, low coverage"
        if flat and high_scarcity:
            return "Steady demand, low coverage"
        if rising and not high_scarcity:
            return "Growing theme to match"
        if trend_direction == "declining" and high_scarcity:
            return "Niche test opportunity"
        return "Monitor for fit"

    @staticmethod
    def _client_ready_topic_label(topic: str) -> str:
        words = re.findall(r"[A-Za-z0-9\+\-]+", str(topic or ""))
        cleaned = [word for word in words if word and not word.isdigit()]
        if not cleaned:
            return "this theme"
        return " ".join(cleaned[:4]).title()
