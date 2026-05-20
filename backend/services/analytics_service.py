"""
analytics_service.py
Data science analysis layer for the Video Competitor Intelligence tool.
"""

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

import numpy as np
import pandas as pd
from scipy import stats as scipy_stats
from sklearn.cluster import AgglomerativeClustering
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.preprocessing import StandardScaler


class AnalyticsService:
    """Provides data-science analytics for YouTube channel and video data."""

    STRATEGIC_THEME_LIBRARY: dict[str, tuple[str, ...]] = {
        "Product Education": (
            "how to", "tutorial", "guide", "walkthrough", "explained",
            "playbook", "best practices", "step by step",
        ),
        "AI Automation": (
            "ai", "automation", "agent", "copilot", "workflow automation",
            "machine learning", "agentic",
        ),
        "Customer Proof & ROI": (
            "case study", "customer story", "testimonial", "roi", "results",
            "success story", "outcome", "proof",
        ),
        "Enterprise Security & Trust": (
            "security", "compliance", "governance", "privacy", "trust",
            "risk", "enterprise security",
        ),
        "Integrations & Workflows": (
            "integration", "connect", "workflow", "stack", "ecosystem",
            "sync", "api", "integration walkthrough",
        ),
        "Onboarding & Adoption": (
            "onboarding", "implementation", "setup", "migration", "rollout",
            "adoption", "getting started",
        ),
        "Product Launches & Updates": (
            "launch", "introducing", "new feature", "product update", "release",
            "spotlight", "roadmap",
        ),
        "Industry POV & Strategy": (
            "future of", "trends", "predictions", "strategy", "leadership",
            "industry outlook", "why ",
        ),
        "Comparison & Evaluation": (
            "comparison", "vs", "versus", "review", "pricing", "alternatives",
            "buyer's guide", "evaluation",
        ),
        "Use Cases by Role": (
            "sales", "marketing", "customer success", "revenue", "ops",
            "operations", "hr", "finance", "support",
        ),
    }

    STRATEGIC_THEME_PRIORITY: dict[str, int] = {
        "Customer Proof & ROI": 10,
        "Onboarding & Adoption": 9,
        "Integrations & Workflows": 9,
        "Use Cases by Role": 8,
        "Comparison & Evaluation": 8,
        "Enterprise Security & Trust": 8,
        "AI Automation": 7,
        "Product Education": 7,
        "Industry POV & Strategy": 6,
        "Product Launches & Updates": 5,
    }

    # ------------------------------------------------------------------
    # 1. Engagement metrics
    # ------------------------------------------------------------------

    def compute_engagement_metrics(self, videos: list[dict]) -> dict:
        """
        Compute engagement statistics for a list of videos.

        Engagement rate per video = (likes + comments) / max(views, 1) * 100.

        Args:
            videos: List of video dicts with keys view_count, like_count,
                    comment_count, published_at.

        Returns:
            Dict with keys:
              avg_engagement_rate, median_engagement_rate,
              engagement_trend_slope, views_per_video,
              rolling_avg_engagement (list of floats, length == len(videos)).
        """
        if not videos:
            return {
                "avg_engagement_rate": 0.0,
                "median_engagement_rate": 0.0,
                "engagement_trend_slope": 0.0,
                "views_per_video": 0.0,
                "rolling_avg_engagement": [],
                "engagement_sample_size": 0,
                "engagement_confidence": "LOW",
            }

        rates: list[float] = []
        total_views: int = 0

        for v in videos:
            views = max(int(v.get("view_count", 0)), 1)
            likes = int(v.get("like_count", 0))
            comments = int(v.get("comment_count", 0))
            er = (likes + comments) / views * 100
            rates.append(er)
            total_views += views

        arr = np.array(rates, dtype=float)
        avg_er = float(np.mean(arr))
        median_er = float(np.median(arr))

        # Trend slope on the most recent 20 videos
        trend_slice = rates[-20:]
        if len(trend_slice) >= 2:
            x = np.arange(len(trend_slice), dtype=float)
            slope, *_ = scipy_stats.linregress(x, trend_slice)
            trend_slope = float(slope)
        else:
            trend_slope = 0.0

        views_per_video = total_views / len(videos)

        # 5-video rolling mean
        s = pd.Series(rates)
        rolling = s.rolling(window=5, min_periods=1).mean().tolist()

        return {
            "avg_engagement_rate": round(avg_er, 4),
            "median_engagement_rate": round(median_er, 4),
            "engagement_trend_slope": round(trend_slope, 6),
            "views_per_video": round(views_per_video, 2),
            "rolling_avg_engagement": [round(r, 4) for r in rolling],
            "engagement_sample_size": len(videos),
            "engagement_confidence": self._sample_confidence_label(len(videos), medium_threshold=8, high_threshold=20),
        }

    # ------------------------------------------------------------------
    # 2. Upload consistency
    # ------------------------------------------------------------------

    def compute_upload_consistency(self, videos: list[dict]) -> dict:
        """
        Analyse how consistently a channel uploads videos.

        Args:
            videos: List of video dicts containing published_at (ISO 8601 str).

        Returns:
            Dict with keys:
              mean_gap_days, std_gap_days, consistency_score (0–100),
              detect_weekly_cadence (bool),
              seasonal_activity (dict month_number → upload_count for last 12 months).
        """
        if not videos:
            return {
                "mean_gap_days": 0.0,
                "std_gap_days": 0.0,
                "consistency_score": 0.0,
                "detect_weekly_cadence": False,
                "seasonal_activity": {},
                "recent_upload_count": 0,
                "cadence_confidence": "LOW",
                "cadence_confidence_reason": "No recent uploads available for cadence analysis.",
                "analysis_window": "full_sample",
            }

        # Parse and sort by date
        dated: list[tuple[datetime, dict]] = []
        for v in videos:
            raw = v.get("published_at", "")
            try:
                dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            dated.append((dt, v))

        dated.sort(key=lambda x: x[0])
        dates = [d for d, _ in dated]

        now = datetime.now(tz=timezone.utc)
        recent_cutoff = now - timedelta(days=180)
        recent_dates = [dt for dt in dates if dt >= recent_cutoff]
        analysis_dates = recent_dates if len(recent_dates) >= 3 else dates
        analysis_window = "recent_180d" if analysis_dates is recent_dates else "full_sample"

        if len(analysis_dates) < 2:
            mean_gap = 0.0
            std_gap = 0.0
            gaps = []
        else:
            gaps = [
                (analysis_dates[i] - analysis_dates[i - 1]).total_seconds() / 86_400
                for i in range(1, len(analysis_dates))
            ]
            mean_gap = float(np.mean(gaps))
            std_gap = float(np.std(gaps, ddof=0))

        # Use coefficient of variation with a smooth inverse scale so
        # irregular schedules score lower without collapsing to zero too
        # aggressively on small samples.
        if mean_gap <= 0:
            consistency_score = 0.0
        else:
            coeff_var = std_gap / mean_gap
            consistency_score = 100.0 / (1.0 + coeff_var)
        recent_upload_count = len(recent_dates)
        most_recent_upload_age_days = (
            (now - dates[-1]).total_seconds() / 86_400 if dates else 999.0
        )
        cadence_confidence = self._cadence_confidence_label(
            recent_upload_count=recent_upload_count,
            gap_count=len(gaps),
            most_recent_upload_age_days=most_recent_upload_age_days,
        )
        detect_weekly_cadence = 5 <= mean_gap <= 9 and len(analysis_dates) >= 3

        # Seasonal activity — last 12 months
        seasonal: dict[int, int] = defaultdict(int)
        for dt, _ in dated:
            delta_months = (now.year - dt.year) * 12 + (now.month - dt.month)
            if 0 <= delta_months < 12:
                seasonal[dt.month] += 1

        if cadence_confidence == "HIGH":
            cadence_reason = (
                f"Based on {recent_upload_count} uploads in the last 180 days, the recent cadence is well-supported."
            )
        elif cadence_confidence == "MEDIUM":
            cadence_reason = (
                f"Based on {recent_upload_count} recent uploads, the cadence read is directional rather than definitive."
            )
        else:
            cadence_reason = (
                "Recent upload volume is too thin for a strong cadence conclusion, so treat this as a low-confidence signal."
            )

        return {
            "mean_gap_days": round(mean_gap, 2),
            "std_gap_days": round(std_gap, 2),
            "consistency_score": round(consistency_score, 2),
            "detect_weekly_cadence": detect_weekly_cadence,
            "seasonal_activity": dict(seasonal),
            "recent_upload_count": recent_upload_count,
            "cadence_confidence": cadence_confidence,
            "cadence_confidence_reason": cadence_reason,
            "analysis_window": analysis_window,
        }

    # ------------------------------------------------------------------
    # 3. Content funnel classification
    # ------------------------------------------------------------------

    def classify_content_funnel(self, videos: list[dict]) -> dict:
        """
        Classify each video as TOFU, MOFU, or BOFU by title and description.

        Args:
            videos: List of video dicts with title and description fields.

        Returns:
            Dict with keys:
              tofu_count, mofu_count, bofu_count,
              unclassified_count,
              tofu_pct, mofu_pct, bofu_pct, unclassified_pct,
              funnel_label ("Awareness-focused" | "Balanced" | "Conversion-focused" | "Low confidence").
        """
        TOFU_SIGNALS = {
            "what is", "introduction", "beginners", "guide", "how to",
            "explained", "overview", "tips",
        }
        MOFU_SIGNALS = {
            "comparison", " vs ", "review", "demo", "case study",
            "features", "pricing", "best",
        }
        BOFU_SIGNALS = {
            "tutorial", "implementation", "onboarding", "getting started",
            "setup", "integration", "migration",
        }

        counts = {"TOFU": 0, "MOFU": 0, "BOFU": 0}
        unclassified_count = 0

        for v in videos:
            text = (
                v.get("title", "") + " " + v.get("description", "")
            ).lower()

            bofu_hit = any(s in text for s in BOFU_SIGNALS)
            mofu_hit = any(s in text for s in MOFU_SIGNALS)
            tofu_hit = any(s in text for s in TOFU_SIGNALS)

            # Priority: BOFU > MOFU > TOFU > unclassified
            if bofu_hit:
                counts["BOFU"] += 1
            elif mofu_hit:
                counts["MOFU"] += 1
            elif tofu_hit:
                counts["TOFU"] += 1
            else:
                unclassified_count += 1

        total = max(len(videos), 1)
        classified_total = max(sum(counts.values()), 1)
        tofu_pct = round(counts["TOFU"] / total * 100, 1)
        mofu_pct = round(counts["MOFU"] / total * 100, 1)
        bofu_pct = round(counts["BOFU"] / total * 100, 1)
        unclassified_pct = round(unclassified_count / total * 100, 1)

        if len(videos) < 4 or unclassified_count / total >= 0.45:
            funnel_label = "Low confidence"
            legacy_funnel_label = "Low Confidence"
            funnel_confidence = "LOW"
        else:
            classified_tofu_pct = round(counts["TOFU"] / classified_total * 100, 1)
            classified_bofu_pct = round(counts["BOFU"] / classified_total * 100, 1)
            if classified_tofu_pct >= 50:
                funnel_label = "Awareness-focused"
                legacy_funnel_label = "Top-Heavy"
            elif classified_bofu_pct >= 40:
                funnel_label = "Conversion-focused"
                legacy_funnel_label = "Bottom-Heavy"
            else:
                funnel_label = "Balanced"
                legacy_funnel_label = "Balanced"
            funnel_confidence = self._sample_confidence_label(
                len(videos) - unclassified_count,
                medium_threshold=4,
                high_threshold=10,
            )

        return {
            "tofu_count": counts["TOFU"],
            "mofu_count": counts["MOFU"],
            "bofu_count": counts["BOFU"],
            "unclassified_count": unclassified_count,
            "classified_count": sum(counts.values()),
            "tofu_pct": tofu_pct,
            "mofu_pct": mofu_pct,
            "bofu_pct": bofu_pct,
            "unclassified_pct": unclassified_pct,
            "funnel_label": funnel_label,
            "funnel_label_legacy": legacy_funnel_label,
            "funnel_confidence": funnel_confidence,
        }

    # ------------------------------------------------------------------
    # 4. Video length strategy
    # ------------------------------------------------------------------

    def analyse_video_length_strategy(self, videos: list[dict]) -> dict:
        """
        Bucket videos by duration and evaluate which length performs best.

        Buckets:
          short  < 300 s
          medium 300–900 s
          long   > 900 s

        Args:
            videos: List of video dicts with duration_seconds, view_count,
                    like_count, comment_count.

        Returns:
            Dict with keys:
              short, medium, long (each: count, avg_views, avg_engagement_rate),
              best_performing_length (bucket name or "insufficient_data").
        """
        buckets: dict[str, list[dict]] = {"short": [], "medium": [], "long": []}

        for v in videos:
            dur = int(v.get("duration_seconds", 0))
            if dur < 300:
                buckets["short"].append(v)
            elif dur <= 900:
                buckets["medium"].append(v)
            else:
                buckets["long"].append(v)

        result: dict[str, Any] = {}
        best_label = "insufficient_data"
        best_er = -1.0

        for label, vids in buckets.items():
            count = len(vids)
            if count == 0:
                result[label] = {"count": 0, "avg_views": 0.0, "avg_engagement_rate": 0.0}
                continue

            avg_views = float(np.mean([v.get("view_count", 0) for v in vids]))
            ers = [
                (int(v.get("like_count", 0)) + int(v.get("comment_count", 0)))
                / max(int(v.get("view_count", 0)), 1) * 100
                for v in vids
            ]
            avg_er = float(np.mean(ers))

            result[label] = {
                "count": count,
                "avg_views": round(avg_views, 2),
                "avg_engagement_rate": round(avg_er, 4),
            }

            if count >= 3 and avg_er > best_er:
                best_er = avg_er
                best_label = label

        result["best_performing_length"] = best_label
        represented_buckets = sum(1 for label in buckets if result.get(label, {}).get("count", 0) > 0)
        if len(videos) >= 18 and represented_buckets >= 2:
            confidence = "HIGH"
        elif len(videos) >= 8 and represented_buckets >= 2:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        result["length_confidence"] = confidence
        return result

    # ------------------------------------------------------------------
    # 5. Title pattern analysis
    # ------------------------------------------------------------------

    def analyse_title_patterns(self, videos: list[dict]) -> dict:
        """
        Identify structural patterns and dominant content strategy from titles.

        Args:
            videos: List of video dicts with a title field.

        Returns:
            Dict with keys:
              all_caps_words_ratio, listicle_count, tutorial_count,
              thought_leadership_count, product_led_count,
              dominant_strategy (dict with label and description).
        """
        if not videos:
            return {
                "all_caps_words_ratio": 0.0,
                "listicle_count": 0,
                "tutorial_count": 0,
                "thought_leadership_count": 0,
                "product_led_count": 0,
                "dominant_strategy": {"label": "none", "description": "No videos found."},
            }

        import re

        listicle_re = re.compile(r"\b\d+\s+(ways|tips|steps|things)\b", re.IGNORECASE)
        tutorial_re = re.compile(r"(^how to\b|tutorial\b|guide\b)", re.IGNORECASE)
        thought_re = re.compile(r"(^why\b|the future of\b|^what\b)", re.IGNORECASE)
        product_re = re.compile(r"\b(introducing|new feature|update)\b", re.IGNORECASE)

        total_words = 0
        caps_words = 0
        counts = {
            "listicle": 0,
            "tutorial": 0,
            "thought_leadership": 0,
            "product_led": 0,
        }

        for v in videos:
            title = v.get("title", "")
            words = title.split()
            total_words += len(words)
            caps_words += sum(1 for w in words if w.isupper() and len(w) > 1)

            if listicle_re.search(title):
                counts["listicle"] += 1
            if tutorial_re.search(title):
                counts["tutorial"] += 1
            if thought_re.search(title):
                counts["thought_leadership"] += 1
            if product_re.search(title):
                counts["product_led"] += 1

        caps_ratio = round(caps_words / max(total_words, 1), 4)

        strategy_descriptions = {
            "listicle": "Listicle-style content designed for SEO discovery and shareability.",
            "tutorial": "Tutorial/how-to content aimed at educating and converting prospects.",
            "thought_leadership": "Thought-leadership content positioning the brand as an authority.",
            "product_led": "Product-led content showcasing features and updates.",
        }

        dominant_key = max(counts, key=lambda k: counts[k])
        dominant_count = counts[dominant_key]

        return {
            "all_caps_words_ratio": caps_ratio,
            "listicle_count": counts["listicle"],
            "tutorial_count": counts["tutorial"],
            "thought_leadership_count": counts["thought_leadership"],
            "product_led_count": counts["product_led"],
            "dominant_strategy": {
                "label": dominant_key,
                "count": dominant_count,
                "description": strategy_descriptions[dominant_key]
                if dominant_count > 0
                else "No clear dominant strategy detected.",
            },
        }

    # ------------------------------------------------------------------
    # 6. Format mix
    # ------------------------------------------------------------------

    def analyse_format_mix(self, videos: list[dict]) -> dict:
        """
        Heuristically classify recent videos by editorial format.

        This is intentionally lightweight and should be treated as a directional
        signal rather than a strict source-of-truth taxonomy.
        """
        if not videos:
            return {
                "counts": {},
                "dominant_format": "none",
                "dominant_format_pct": 0.0,
                "format_diversity_score": 0.0,
            }

        format_patterns = {
            "webinar": ("webinar", "workshop", "masterclass", "live demo"),
            "customer_story": (
                "case study",
                "customer story",
                "testimonial",
                "success story",
            ),
            "tutorial": ("tutorial", "how to", "guide", "walkthrough", "onboarding"),
            "demo": ("demo", "product demo", "feature demo", "comparison"),
            "product_update": ("introducing", "launch", "new feature", "update", "spotlight"),
            "thought_leadership": (
                "why ",
                "future of",
                "trends",
                "predictions",
                "strategy",
            ),
            "event_clip": ("keynote", "conference", "summit", "panel", "fireside"),
            "short_clip": ("shorts",),
        }

        counts: dict[str, int] = defaultdict(int)

        for video in videos:
            title = video.get("title", "").lower()
            description = video.get("description", "").lower()
            duration_seconds = int(video.get("duration_seconds", 0))
            text = f"{title} {description}"

            matched_label = "other"
            for label, tokens in format_patterns.items():
                if any(token in text for token in tokens):
                    matched_label = label
                    break

            if matched_label == "other" and duration_seconds and duration_seconds <= 60:
                matched_label = "short_clip"

            counts[matched_label] += 1

        total = max(sum(counts.values()), 1)
        dominant_format = max(counts, key=counts.get)
        dominant_pct = round(counts[dominant_format] / total * 100, 1)
        non_zero_buckets = sum(1 for count in counts.values() if count > 0)
        diversity_score = round(non_zero_buckets / len(format_patterns) * 100, 1)

        return {
            "counts": dict(counts),
            "dominant_format": dominant_format,
            "dominant_format_pct": dominant_pct,
            "format_diversity_score": diversity_score,
        }

    # ------------------------------------------------------------------
    # 7. Recent performance / view velocity
    # ------------------------------------------------------------------

    def compute_recent_view_velocity(self, videos: list[dict]) -> dict:
        """
        Estimate recent performance using views-per-day on the available sample.

        This helps avoid over-indexing on raw cumulative views alone.
        """
        if not videos:
            return {
                "avg_views_per_day": 0.0,
                "median_views_per_day": 0.0,
                "top_views_per_day": 0.0,
            }

        now = datetime.now(tz=timezone.utc)
        velocities: list[float] = []

        for video in videos:
            raw = video.get("published_at", "")
            try:
                published_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue

            age_days = max((now - published_at).total_seconds() / 86_400, 1.0)
            views = max(int(video.get("view_count", 0)), 0)
            velocities.append(views / age_days)

        if not velocities:
            return {
                "avg_views_per_day": 0.0,
                "median_views_per_day": 0.0,
                "top_views_per_day": 0.0,
            }

        return {
            "avg_views_per_day": round(float(np.mean(velocities)), 2),
            "median_views_per_day": round(float(np.median(velocities)), 2),
            "top_views_per_day": round(float(np.max(velocities)), 2),
        }

    # ------------------------------------------------------------------
    # 8. Relative Performance Index (RPI)
    # ------------------------------------------------------------------

    def compute_rpi(self, all_companies_data: dict) -> dict:
        """
        Compute a normalised Relative Performance Index for each company.

        The five input metrics per company are converted to peer-relative
        percentile scores, then combined using fixed weights:
          engagement_rate    0.30
          views_per_sub      0.25
          consistency        0.20
          topic_diversity    0.15
          seo_score          0.10

        This is intentionally less sensitive to extreme outliers than a raw
        z-score approach, so mixed peer sets do not collapse the weakest
        company to 0 too aggressively.

        Args:
            all_companies_data: {company_name: {avg_engagement_rate,
              views_per_subscriber, consistency_score,
              topic_diversity_score, seo_score}}

        Returns:
            {company_name: {rpi_score, rank, metric_breakdown}}
            sorted by rank ascending (rank 1 = best).
        """
        if not all_companies_data:
            return {}

        WEIGHTS = {
            "avg_engagement_rate": 0.30,
            "views_per_subscriber": 0.25,
            "consistency_score": 0.20,
            "topic_diversity_score": 0.15,
            "seo_score": 0.10,
        }

        companies = list(all_companies_data.keys())
        metric_keys = list(WEIGHTS.keys())

        # Build matrix (companies × metrics)
        matrix = np.array(
            [
                [float(all_companies_data[c].get(m, 0)) for m in metric_keys]
                for c in companies
            ],
            dtype=float,
        )

        percentile_scores = np.zeros_like(matrix, dtype=float)
        for col_idx in range(matrix.shape[1]):
            col = matrix[:, col_idx]
            if np.allclose(col, col[0]):
                percentile_scores[:, col_idx] = 50.0
                continue

            order = np.argsort(col, kind="mergesort")
            ranks = np.empty_like(order, dtype=float)
            ranks[order] = np.arange(len(col), dtype=float)
            percentile_scores[:, col_idx] = (
                100.0 if len(col) == 1 else (ranks / (len(col) - 1)) * 100.0
            )

        weights_arr = np.array([WEIGHTS[m] for m in metric_keys])
        raw_scores = percentile_scores @ weights_arr  # shape (n_companies,)
        scaled = np.clip(raw_scores, 0.0, 100.0)

        # Rank (1 = highest score)
        order = np.argsort(-scaled)
        ranks = np.empty_like(order)
        ranks[order] = np.arange(1, len(companies) + 1)

        output = {}
        for idx, company in enumerate(companies):
            breakdown = {
                m: round(float(percentile_scores[idx, mi]), 2)
                for mi, m in enumerate(metric_keys)
            }
            output[company] = {
                "rpi_score": round(float(scaled[idx]), 2),
                "rank": int(ranks[idx]),
                "metric_breakdown": breakdown,
            }

        return dict(
            sorted(output.items(), key=lambda kv: kv[1]["rank"])
        )

    # ------------------------------------------------------------------
    # 7. Content topic clustering
    # ------------------------------------------------------------------

    def cluster_content_topics(self, all_videos_by_company: dict) -> dict:
        """
        Cluster video content topics across all companies using TF-IDF + Agglomerative Clustering.

        Args:
            all_videos_by_company: {company_name: [video_dicts]}
              Each video dict must have title and description fields.

        Returns:
            Dict with keys:
              clusters: [{id, label, top_terms, size}]
              company_coverage: {company_name: [cluster_ids]}
              company_theme_labels: {company_name: [theme_labels]}
              cluster_coverage: {cluster_label: {company_name: count}}
              gap_topics: [cluster_labels] — clusters with meaningful labels and sparse ownership
        """
        if not all_videos_by_company:
            return {
                "clusters": [],
                "company_coverage": {},
                "company_theme_labels": {},
                "cluster_coverage": {},
                "gap_topics": [],
            }

        # Build corpus: one document per video, track company membership
        corpus: list[str] = []
        doc_company: list[str] = []  # which company each document belongs to

        for company, videos in all_videos_by_company.items():
            for v in videos:
                text = self._topic_document_text(v)
                if text:
                    corpus.append(text)
                    doc_company.append(company)

        if len(corpus) < 2:
            return {
                "clusters": [],
                "company_coverage": {},
                "company_theme_labels": {},
                "cluster_coverage": {},
                "gap_topics": [],
            }

        n_clusters = min(8, len(corpus))

        # TF-IDF vectorisation
        vectorizer = TfidfVectorizer(
            max_features=500,
            stop_words="english",
            ngram_range=(1, 2),
        )
        tfidf_matrix = vectorizer.fit_transform(corpus)
        feature_names = vectorizer.get_feature_names_out()

        # Agglomerative clustering on dense matrix (cosine metric)
        dense = tfidf_matrix.toarray()
        # Remove zero vectors (cosine metric fails on them)
        non_zero_mask = dense.sum(axis=1) > 0
        dense = dense[non_zero_mask]

        if len(dense) < 2:
            return {
                "clusters": [],
                "company_coverage": {},
                "company_theme_labels": {},
                "cluster_coverage": {},
                "gap_topics": [],
            }

        doc_company = [
            company
            for i, company in enumerate(doc_company)
            if non_zero_mask[i]
        ]
        clusterer = AgglomerativeClustering(
            n_clusters=n_clusters,
            metric="cosine",
            linkage="average",
        )
        labels = clusterer.fit_predict(dense)

        # Build cluster summaries
        clusters: list[dict] = []
        for cid in range(n_clusters):
            mask = labels == cid
            cluster_docs = dense[mask]
            if cluster_docs.shape[0] == 0:
                continue

            # Top 3 TF-IDF terms for this cluster (mean score across docs)
            centroid = cluster_docs.mean(axis=0)
            top_indices = centroid.argsort()[::-1][:3]
            top_terms = [
                term for term in (feature_names[i] for i in top_indices)
                if self._is_meaningful_topic_term(term)
            ]
            if not top_terms:
                top_terms = [feature_names[i] for i in top_indices[:1]]
            label_str = " / ".join(top_terms)

            clusters.append(
                {
                    "id": cid,
                    "label": label_str,
                    "top_terms": top_terms,
                    "size": int(mask.sum()),
                }
            )

        # Company coverage — which cluster IDs does each company have videos in?
        company_coverage: dict[str, list[int]] = defaultdict(set)
        for doc_idx, cluster_id in enumerate(labels):
            company = doc_company[doc_idx]
            company_coverage[company].add(int(cluster_id))

        company_coverage_out = {c: sorted(s) for c, s in company_coverage.items()}

        # Gap topics — clusters where NO company has more than 1 video
        cluster_company_counts: dict[int, dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for doc_idx, cluster_id in enumerate(labels):
            company = doc_company[doc_idx]
            cluster_company_counts[cluster_id][company] += 1

        cluster_coverage_out: dict[str, dict[str, int]] = {}
        company_theme_labels: dict[str, list[str]] = {}
        cluster_label_by_id = {cluster["id"]: cluster["label"] for cluster in clusters}
        strategic_theme_counts = self._compute_strategic_theme_counts(all_videos_by_company)

        for cluster in clusters:
            cluster_coverage_out[cluster["label"]] = dict(cluster_company_counts[cluster["id"]])

        for company, cluster_ids in company_coverage_out.items():
            ranked_clusters = sorted(
                cluster_ids,
                key=lambda cid: cluster_company_counts[cid].get(company, 0),
                reverse=True,
            )
            strategic_labels = [
                label
                for label, _count in sorted(
                    strategic_theme_counts.get(company, {}).items(),
                    key=lambda item: (-item[1], item[0]),
                )
            ]
            unsupervised_labels = [
                self._canonicalize_topic_label(cluster_label_by_id.get(cid, ""))
                for cid in ranked_clusters
                if cluster_label_by_id.get(cid)
            ]
            merged_labels: list[str] = []
            for label in strategic_labels + unsupervised_labels:
                if label and label not in merged_labels:
                    merged_labels.append(label)
            company_theme_labels[company] = merged_labels[:4]

        gap_topics: list[str] = []
        for cluster in clusters:
            cid = cluster["id"]
            company_max = max(
                cluster_company_counts[cid].values(), default=0
            )
            label = cluster["label"]
            company_presence = sum(1 for count in cluster_company_counts[cid].values() if count > 0)
            if (
                company_max <= 1
                and company_presence <= 1
                and cluster["size"] >= 1
                and self._is_meaningful_topic_label(label)
            ):
                cleaned_label = self._canonicalize_topic_label(cluster["label"])
                if cleaned_label and cleaned_label not in gap_topics:
                    gap_topics.append(cleaned_label)

        strategic_gap_topics = self._derive_strategic_gap_topics(
            strategic_theme_counts=strategic_theme_counts,
            company_count=len(all_videos_by_company),
        )
        for label in strategic_gap_topics:
            if label not in gap_topics:
                gap_topics.append(label)

        return {
            "clusters": clusters,
            "company_coverage": company_coverage_out,
            "company_theme_labels": company_theme_labels,
            "cluster_coverage": cluster_coverage_out,
            "gap_topics": gap_topics[:6],
        }

    @staticmethod
    def _topic_document_text(video: dict) -> str:
        """
        Build a cleaner clustering document from the title and a trimmed,
        de-noised description snippet.
        """
        title = str(video.get("title", "") or "").strip()
        description = str(video.get("description", "") or "")
        description = re.sub(r"https?://\S+", " ", description)
        description = re.sub(r"www\.\S+", " ", description)
        description = re.sub(r"#\w+", " ", description)
        description = re.sub(r"[\r\n\t]+", " ", description)
        description = re.sub(
            r"\b(subscribe|follow us|learn more|click here|register now|watch now|free trial|book a demo)\b",
            " ",
            description,
            flags=re.IGNORECASE,
        )
        description = " ".join(description.split())
        if description:
            description = description[:180]
        return " ".join(part for part in [title, description] if part).strip()

    @staticmethod
    def _is_meaningful_topic_term(term: str) -> bool:
        cleaned = str(term or "").strip().lower()
        if not cleaned:
            return False
        banned = {
            "http", "https", "www", "com", "utm", "medium", "source",
            "youtube", "channel", "official", "hubspot", "salesforce",
            "mailchimp", "intuit", "mypromovideos", "clickhubspot",
            "today", "meet", "dive", "viral", "replay", "keynote",
            "conference", "summit", "watch", "episode", "live",
            "short", "shorts", "video", "videos", "tdx", "tableau",
            "2024", "2025", "2026",
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december",
            "monday", "tuesday", "wednesday", "thursday", "friday",
            "saturday", "sunday",
        }
        words = [word for word in re.findall(r"[a-z0-9]+", cleaned) if word]
        if not words:
            return False
        if any(word in banned for word in words):
            return False
        if all(len(word) <= 2 for word in words):
            return False
        return True

    def _is_meaningful_topic_label(self, label: str) -> bool:
        parts = [part.strip() for part in str(label or "").split("/") if part.strip()]
        if not parts:
            return False
        kept = [part for part in parts if self._is_meaningful_topic_term(part)]
        return len(kept) >= 1

    @staticmethod
    def _sample_confidence_label(
        sample_size: int,
        *,
        medium_threshold: int,
        high_threshold: int,
    ) -> str:
        if sample_size >= high_threshold:
            return "HIGH"
        if sample_size >= medium_threshold:
            return "MEDIUM"
        return "LOW"

    @staticmethod
    def _cadence_confidence_label(
        *,
        recent_upload_count: int,
        gap_count: int,
        most_recent_upload_age_days: float,
    ) -> str:
        if recent_upload_count >= 12 and gap_count >= 6 and most_recent_upload_age_days <= 45:
            return "HIGH"
        if recent_upload_count >= 6 and gap_count >= 3 and most_recent_upload_age_days <= 120:
            return "MEDIUM"
        return "LOW"

    def _compute_strategic_theme_counts(
        self,
        all_videos_by_company: dict[str, list[dict]],
    ) -> dict[str, dict[str, int]]:
        company_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for company, videos in all_videos_by_company.items():
            for video in videos:
                theme_hits = self._strategic_theme_hits(self._topic_document_text(video))
                for label in theme_hits:
                    company_counts[company][label] += 1
        return {company: dict(counts) for company, counts in company_counts.items()}

    def _strategic_theme_hits(self, text: str) -> list[str]:
        normalized = str(text or "").lower()
        hits: list[str] = []
        for label, patterns in self.STRATEGIC_THEME_LIBRARY.items():
            if any(pattern in normalized for pattern in patterns):
                hits.append(label)
        return hits

    def _derive_strategic_gap_topics(
        self,
        *,
        strategic_theme_counts: dict[str, dict[str, int]],
        company_count: int,
    ) -> list[str]:
        if company_count <= 0:
            return []

        candidates: list[tuple[float, str]] = []
        for label in self.STRATEGIC_THEME_LIBRARY:
            company_presence = sum(
                1 for company_counts in strategic_theme_counts.values()
                if company_counts.get(label, 0) > 0
            )
            total_mentions = sum(
                company_counts.get(label, 0)
                for company_counts in strategic_theme_counts.values()
            )
            scarcity = 1.0 - (company_presence / company_count)
            if company_presence <= max(1, math.floor(company_count / 2)):
                priority = self.STRATEGIC_THEME_PRIORITY.get(label, 5)
                score = (scarcity * 100) + (priority * 4) - (total_mentions * 3)
                candidates.append((score, label))
            elif total_mentions == 0 and self.STRATEGIC_THEME_PRIORITY.get(label, 0) >= 8:
                candidates.append((90 + self.STRATEGIC_THEME_PRIORITY[label], label))

        candidates.sort(key=lambda item: (-item[0], item[1]))
        return [label for _score, label in candidates[:6]]

    def _canonicalize_topic_label(self, label: str) -> str:
        theme_hits = self._strategic_theme_hits(label)
        if theme_hits:
            return theme_hits[0]

        cleaned_parts = [
            part.strip()
            for part in str(label or "").split("/")
            if self._is_meaningful_topic_term(part)
        ]
        if not cleaned_parts:
            return ""
        humanized = []
        for part in cleaned_parts[:3]:
            normalized = " ".join(word.capitalize() for word in part.split())
            if normalized not in humanized:
                humanized.append(normalized)
        return " / ".join(humanized)
