#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import GEMINI_API_KEY, GROQ_API_KEY, YOUTUBE_API_KEY
from backend.services.ai_service import AIService
from backend.services.analytics_service import AnalyticsService
from backend.services.pptx_service import PPTXService
from backend.services.seo_service import SEOService
from backend.services.youtube_service import YouTubeService


DEFAULT_COMPANIES = ["HubSpot", "Salesforce", "Mailchimp"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a real local Phase 3 PowerPoint report using the live services."
    )
    parser.add_argument(
        "companies",
        nargs="*",
        default=DEFAULT_COMPANIES,
        help="Company names to include in the report. Defaults to HubSpot Salesforce Mailchimp.",
    )
    parser.add_argument(
        "--videos",
        type=int,
        default=5,
        help="Number of recent videos to analyze per company. Defaults to 5.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore on-disk YouTube and trends caches for this run.",
    )
    parser.add_argument(
        "--target-company",
        help="Company to use for the recommendations/action-plan slides. Defaults to the top RPI company.",
    )
    parser.add_argument(
        "--output",
        help="Optional output .pptx path. Defaults to output/phase3_live_report_<timestamp>.pptx",
    )
    return parser


def fallback_executive_summary(companies: list[str], rpi_scores: dict) -> str:
    if not companies:
        return "Executive summary unavailable. No companies were processed successfully."

    ranked = sorted(companies, key=lambda c: rpi_scores.get(c, {}).get("rank", 999))
    top_company = ranked[0]
    top_rpi = rpi_scores.get(top_company, {}).get("rpi_score", 0.0)
    return (
        f"The AI narrative layer was unavailable for this run, so this summary is based on the computed report metrics. "
        f"{top_company} currently ranks highest in the peer set with an RPI of {top_rpi:.1f}. "
        "Use the next slides to compare channel size, upload cadence, engagement quality, topic coverage, "
        "length strategy, and SEO execution across the selected companies. "
        "Treat funnel classification as a heuristic based on title and description cues rather than a direct conversion measurement."
    )


def fallback_gap_analysis(gap_topics: list[str]) -> str:
    if not gap_topics:
        return "No obvious whitespace topics were identified in the current competitive set."
    top_topics = ", ".join(gap_topics[:3])
    return (
        "The AI-written gap narrative was unavailable for this run. "
        f"Initial whitespace signals were identified around: {top_topics}. "
        "Use the opportunity ranking, trend interest, and scarcity signals on this slide to decide which themes deserve testing first."
    )


def fallback_action_plan(target_company: str, cadence_days: float) -> str:
    return (
        f"Week 1–2: audit {target_company}'s current content mix and confirm the next 3 production priorities. "
        f"Month 1: publish at least one new mid-funnel or bottom-funnel asset while moving toward a steadier cadence than the current {cadence_days:.1f}-day average. "
        "Month 2–3: double down on the best-performing format, track engagement and views-per-day, and refine topic selection using the trend and topic-cluster slides."
    )


def recommendations_need_fallback(recommendations: list[dict]) -> bool:
    if not recommendations:
        return True
    first = recommendations[0]
    title = str(first.get("title", "")).strip().lower()
    action = str(first.get("action", "")).strip().lower()
    return title.startswith("recommendation ") or action == "see full report for details."


def sanitize_recommendations_for_slides(recommendations: list[dict]) -> list[dict]:
    """
    Make recommendation copy safer for a client-facing deck.
    The goal is to keep the strong LLM wording while removing unsupported
    promises, awkward ellipses, and over-technical phrasing.
    """
    cleaned: list[dict] = []
    for rec in recommendations:
        title = " ".join(str(rec.get("title", "")).split()).replace("...", ".").strip()
        action = " ".join(str(rec.get("action", "")).split()).replace("...", ".").strip()
        rationale = " ".join(str(rec.get("data_rationale", "")).split()).replace("...", ".").strip()
        impact = " ".join(str(rec.get("expected_impact", "")).split()).replace("...", ".").strip()

        lowered_impact = impact.lower()
        if (
            any(ch.isdigit() for ch in impact)
            or "significantly" in lowered_impact
            or "guarantee" in lowered_impact
            or "reverse" in lowered_impact
            or "increase lead conversion rates" in lowered_impact
            or "click-through rates" in lowered_impact
        ):
            title_key = title.lower()
            if "seo" in title_key or "search" in title_key:
                impact = "Likely to improve discoverability and make the videos easier to navigate."
            elif "cadence" in title_key or "publish" in title_key:
                impact = "Likely to create more predictable audience expectations and steadier tracking."
            elif "conversion" in title_key or "bofu" in title_key:
                impact = "Likely to strengthen coverage for higher-intent viewers closer to a decision."
            elif "theme" in title_key or "trend" in title_key or "whitespace" in title_key:
                impact = "Likely to improve learning speed on whether the theme deserves a repeatable series."
            else:
                impact = "Likely to improve content-market fit if execution stays consistent."

        cleaned.append(
            {
                **rec,
                "title": title.rstrip("."),
                "action": action.rstrip(".") + ".",
                "data_rationale": rationale.rstrip(".") + ".",
                "expected_impact": impact.rstrip(".") + ".",
            }
        )

    return cleaned


def build_fallback_recommendations(
    target_company: str,
    company_row: dict,
    gap_topics: list[str],
    seo_score: float,
) -> list[dict]:
    dominant_format = company_row.get("dominant_format", "mixed")
    dominant_strategy = company_row.get("dominant_strategy_label", "mixed")
    funnel_label = company_row.get("funnel_label", "Mixed")
    recommendations: list[dict] = []

    if company_row.get("bofu_pct", 0.0) <= 5:
        recommendations.append(
            {
                "title": "Build a clear conversion layer",
                "action": (
                    f"Add at least one BOFU asset each month for {target_company}, such as a demo, case study, "
                    "comparison, or implementation proof video."
                ),
                "data_rationale": (
                    f"The current funnel mix is {company_row.get('tofu_pct', 0):.1f}% TOFU / "
                    f"{company_row.get('mofu_pct', 0):.1f}% MOFU / {company_row.get('bofu_pct', 0):.1f}% BOFU."
                ),
                "expected_impact": "Stronger conversion intent capture and a more balanced content path.",
                "priority": "high",
            }
        )

    if company_row.get("consistency_score", 0.0) < 55:
        recommendations.append(
            {
                "title": "Stabilize the publishing rhythm",
                "action": (
                    f"Move toward a predictable publishing cadence instead of the current average gap of "
                    f"{company_row.get('mean_gap_days', 0.0):.1f} days."
                ),
                "data_rationale": (
                    f"Consistency is currently {company_row.get('consistency_score', 0.0):.1f}/100, which limits repeat audience habits."
                ),
                "expected_impact": "More reliable audience retention and stronger performance compounding over time.",
                "priority": "high",
            }
        )

    if company_row.get("format_diversity_score", 0.0) < 40:
        recommendations.append(
            {
                "title": "Broaden the format mix",
                "action": (
                    f"Reduce over-reliance on {dominant_format.replace('_', ' ')} content by testing tutorials, case studies, "
                    "customer proof, or webinar cut-downs."
                ),
                "data_rationale": (
                    f"Format diversity is only {company_row.get('format_diversity_score', 0.0):.1f}/100 and "
                    f"{company_row.get('dominant_format_pct', 0.0):.1f}% of the recent sample falls into one format."
                ),
                "expected_impact": "Lower fatigue risk and better coverage of different audience intents.",
                "priority": "medium",
            }
        )

    recommendations.append(
        {
            "title": "Turn trend demand into publishable themes",
            "action": (
                "Translate the whitespace and search-interest signals into a 6-week editorial calendar with explicit titles, "
                "formats, and CTAs."
            ),
            "data_rationale": (
                f"The current strategy is {dominant_strategy.replace('_', ' ')} and the funnel is {funnel_label}, "
                f"so trend-aligned themes can expand coverage without abandoning what already works."
            ),
            "expected_impact": "Better topic-market fit and more defensible content planning.",
            "priority": "medium",
        }
    )

    if seo_score < 75:
        recommendations.append(
            {
                "title": "Improve packaging for search and click-through",
                "action": (
                    "Tighten title structure, strengthen description depth, and add timestamps where they genuinely improve navigation."
                ),
                "data_rationale": f"The current SEO score is {seo_score:.1f}/100, leaving room to improve discoverability.",
                "expected_impact": "Higher qualified discovery and easier content navigation for viewers.",
                "priority": "medium",
            }
        )
    else:
        recommendations.append(
            {
                "title": "Preserve strong packaging while deepening substance",
                "action": (
                    "Keep the current packaging discipline, but shift more videos toward mid-funnel and proof-oriented stories."
                ),
                "data_rationale": f"SEO is already strong at {seo_score:.1f}/100, so the bigger upside is strategic mix rather than packaging basics.",
                "expected_impact": "Maintains discoverability while improving depth and conversion relevance.",
                "priority": "medium",
            }
        )

    if gap_topics:
        recommendations.append(
            {
                "title": "Test one whitespace theme immediately",
                "action": f"Pilot a content theme around {gap_topics[0]} and measure views-per-day plus engagement within the first two weeks.",
                "data_rationale": "The topic-cluster analysis found at least one under-covered theme across the peer set.",
                "expected_impact": "Faster learning on whether the identified whitespace can become a repeatable content pillar.",
                "priority": "medium",
            }
        )

    return recommendations[:5]


def topic_diversity_score(topic_clusters: dict, company_name: str) -> float:
    clusters = topic_clusters.get("clusters", [])
    coverage = topic_clusters.get("company_coverage", {}).get(company_name, [])
    if not clusters:
        return 0.0
    return round(len(coverage) / len(clusters) * 100, 2)


def simplify_gap_topic_query(label: str) -> str:
    parts = [part.strip() for part in label.split("/") if part.strip()]
    return parts[0] if parts else label


def validate_slide_interpretations(
    generated: dict[str, str],
    fallback: dict[str, str],
) -> dict[str, str]:
    """
    Keep LLM interpretations only when they remain numerical, slide-specific,
    and client-readable. Otherwise fall back to deterministic text.
    """
    final: dict[str, str] = {}
    expected_keywords = {
        "slide_02": ("rpi", "engagement", "consistency"),
        "slide_03": ("subscriber", "video", "channel"),
        "slide_04": ("rpi", "rank", "score"),
        "slide_05": ("consistency", "cadence", "gap"),
        "slide_06": ("tofu", "mofu", "bofu", "unclassified", "awareness"),
        "slide_07": ("engagement", "trend", "rate"),
        "slide_08": ("views", "video", "engagement", "per day"),
        "slide_09": ("topic", "theme", "cluster", "gap"),
        "slide_10": ("short", "medium", "long", "length"),
        "slide_11": ("seo", "timestamp", "description", "title"),
        "slide_12": ("opportunity", "score", "trend", "scarcity"),
        "slide_13": ("recommendation", "priority", "impact", "action"),
        "slide_14": ("rank", "score", "engagement", "consistency"),
    }

    for slide_key, fallback_text in fallback.items():
        candidate = str(generated.get(slide_key, "") or "").strip()
        lowered = candidate.lower()
        keyword_match = any(keyword in lowered for keyword in expected_keywords.get(slide_key, ()))
        has_number = any(ch.isdigit() for ch in candidate)
        too_vague = candidate.endswith(":") or candidate.lower().startswith("interpretation:")
        final[slide_key] = candidate if candidate and has_number and keyword_match and not too_vague else fallback_text

    return final


def build_slide_interpretation_context(
    companies: list[str],
    company_data: dict[str, dict],
    rpi_scores: dict[str, dict],
    seo_scores: dict[str, dict],
    topic_clusters: dict,
    opportunity_scores: list[dict],
    recommendations: list[dict],
    target_company: str,
) -> dict:
    ranked = sorted(companies, key=lambda c: rpi_scores.get(c, {}).get("rank", 999))
    leader = ranked[0] if ranked else ""
    runner_up = ranked[1] if len(ranked) > 1 else ""
    best_consistency = max(companies, key=lambda c: company_data.get(c, {}).get("consistency_score", 0))
    best_engagement = max(companies, key=lambda c: company_data.get(c, {}).get("avg_engagement_rate", 0))
    most_topics = max(companies, key=lambda c: len(topic_clusters.get("company_coverage", {}).get(c, [])))
    timestamp_zero = sum(
        1 for company in companies
        if seo_scores.get(company, {}).get("breakdown", {}).get("has_timestamps_pct", 0.0) == 0.0
    )
    return {
        "slide_02": {
            "leader": leader,
            "leader_rpi": rpi_scores.get(leader, {}).get("rpi_score", 0.0),
            "runner_up": runner_up,
            "runner_up_rpi": rpi_scores.get(runner_up, {}).get("rpi_score", 0.0) if runner_up else 0.0,
            "engagement_leader": best_engagement,
            "engagement_value": company_data.get(best_engagement, {}).get("avg_engagement_rate", 0.0),
            "consistency_leader": best_consistency,
            "consistency_value": company_data.get(best_consistency, {}).get("consistency_score", 0.0),
        },
        "slide_03": {
            "channels": {
                company: {
                    "subscriber_count": company_data.get(company, {}).get("subscriber_count", 0),
                    "video_count": company_data.get(company, {}).get("video_count", 0),
                }
                for company in companies
            }
        },
        "slide_04": {
            "rpi": {
                company: {
                    "rank": rpi_scores.get(company, {}).get("rank", 999),
                    "score": rpi_scores.get(company, {}).get("rpi_score", 0.0),
                }
                for company in companies
            }
        },
        "slide_05": {
            "cadence": {
                company: {
                    "mean_gap_days": company_data.get(company, {}).get("mean_gap_days", 0.0),
                    "consistency_score": company_data.get(company, {}).get("consistency_score", 0.0),
                }
                for company in companies
            }
        },
        "slide_06": {
            "funnel": {
                company: {
                    "label": company_data.get(company, {}).get("funnel_label", "—"),
                    "tofu_pct": company_data.get(company, {}).get("tofu_pct", 0.0),
                    "mofu_pct": company_data.get(company, {}).get("mofu_pct", 0.0),
                    "bofu_pct": company_data.get(company, {}).get("bofu_pct", 0.0),
                    "unclassified_count": company_data.get(company, {}).get("unclassified_count", 0),
                    "unclassified_pct": company_data.get(company, {}).get("unclassified_pct", 0.0),
                }
                for company in companies
            }
        },
        "slide_07": {
            "engagement": {
                company: {
                    "avg_engagement_rate": company_data.get(company, {}).get("avg_engagement_rate", 0.0),
                    "engagement_trend_slope": company_data.get(company, {}).get("engagement_trend_slope", 0.0),
                }
                for company in companies
            }
        },
        "slide_08": {
            "top_videos": {
                company: [
                    {
                        "title": video.get("title", ""),
                        "view_count": video.get("view_count", 0),
                        "like_count": video.get("like_count", 0),
                        "comment_count": video.get("comment_count", 0),
                        "duration_seconds": video.get("duration_seconds", 0),
                    }
                    for video in company_data.get(company, {}).get("top_videos", [])[:2]
                ]
                for company in companies
            }
        },
        "slide_09": {
            "topic_counts": {
                company: len(topic_clusters.get("company_coverage", {}).get(company, []))
                for company in companies
            },
            "representative_themes": {
                company: topic_clusters.get("company_theme_labels", {}).get(company, [])[:2]
                for company in companies
            },
            "leader": most_topics,
            "gap_topics": topic_clusters.get("gap_topics", [])[:4],
        },
        "slide_10": {
            "length": {
                company: {
                    "best_performing_length": company_data.get(company, {}).get("best_performing_length", "—"),
                    "short_er": company_data.get(company, {}).get("short", {}).get("avg_engagement_rate", 0.0),
                    "medium_er": company_data.get(company, {}).get("medium", {}).get("avg_engagement_rate", 0.0),
                    "long_er": company_data.get(company, {}).get("long", {}).get("avg_engagement_rate", 0.0),
                }
                for company in companies
            }
        },
        "slide_11": {
            "seo": {
                company: {
                    "seo_score": seo_scores.get(company, {}).get("seo_score", 0.0),
                    "timestamp_pct": seo_scores.get(company, {}).get("breakdown", {}).get("has_timestamps_pct", 0.0),
                    "description_depth": seo_scores.get(company, {}).get("breakdown", {}).get("description_depth", 0.0),
                }
                for company in companies
            },
            "timestamp_zero_count": timestamp_zero,
        },
        "slide_12": {
            "opportunities": opportunity_scores[:3],
        },
        "slide_13": {
            "target_company": target_company,
            "recommendations": recommendations[:5],
        },
        "slide_14": {
            "rankings": {
                company: {
                    "rank": rpi_scores.get(company, {}).get("rank", 999),
                    "engagement": company_data.get(company, {}).get("avg_engagement_rate", 0.0),
                    "consistency": company_data.get(company, {}).get("consistency_score", 0.0),
                    "seo_score": seo_scores.get(company, {}).get("seo_score", 0.0),
                }
                for company in companies
            }
        },
    }


def build_fallback_slide_interpretations(
    companies: list[str],
    company_data: dict[str, dict],
    rpi_scores: dict[str, dict],
    seo_scores: dict[str, dict],
    topic_clusters: dict,
    opportunity_scores: list[dict],
    recommendations: list[dict],
    target_company: str,
) -> dict[str, str]:
    if not companies:
        return {}

    ranked = sorted(companies, key=lambda c: rpi_scores.get(c, {}).get("rank", 999))
    leader = ranked[0]
    laggard = ranked[-1]
    biggest = max(companies, key=lambda c: company_data.get(c, {}).get("subscriber_count", 0))
    steadiest = max(companies, key=lambda c: company_data.get(c, {}).get("consistency_score", 0))
    engagement_leader = max(companies, key=lambda c: company_data.get(c, {}).get("avg_engagement_rate", 0))
    topic_leader = max(companies, key=lambda c: len(topic_clusters.get("company_coverage", {}).get(c, [])))
    timestamp_zero = sum(
        1 for company in companies
        if seo_scores.get(company, {}).get("breakdown", {}).get("has_timestamps_pct", 0.0) == 0.0
    )
    target_row = company_data.get(target_company, {})

    top_gap = opportunity_scores[0] if opportunity_scores else {}
    top_gap_name = simplify_gap_topic_query(top_gap.get("topic", "underserved theme"))
    top_gap_score = top_gap.get("opportunity_score", 0.0)
    top_video_company = max(
        companies,
        key=lambda c: max((video.get("view_count", 0) for video in company_data.get(c, {}).get("top_videos", [])), default=0),
    )
    top_video_views = max((video.get("view_count", 0) for video in company_data.get(top_video_company, {}).get("top_videos", [])), default=0)
    short_er_target = target_row.get("short", {}).get("avg_engagement_rate", 0.0)
    medium_er_target = target_row.get("medium", {}).get("avg_engagement_rate", 0.0)
    long_er_target = target_row.get("long", {}).get("avg_engagement_rate", 0.0)

    return {
        "slide_02": (
            f"{leader} leads the current peer set with an RPI of {rpi_scores.get(leader, {}).get('rpi_score', 0.0):.1f}. "
            f"{engagement_leader} also has the strongest recent engagement at {company_data.get(engagement_leader, {}).get('avg_engagement_rate', 0.0):.3f}%."
        ),
        "slide_03": (
            f"{biggest} has the largest existing audience in this peer set, with {company_data.get(biggest, {}).get('subscriber_count', 0):,} subscribers. "
            "Scale alone does not guarantee stronger execution, so the next slides compare whether that audience is being converted into stronger operating performance."
        ),
        "slide_04": (
            f"{leader} leads the overall peer score at {rpi_scores.get(leader, {}).get('rpi_score', 0.0):.1f}, while {laggard} is lowest at {rpi_scores.get(laggard, {}).get('rpi_score', 0.0):.1f}. "
            "RPI is best read as a roll-up of several metrics rather than a literal business KPI."
        ),
        "slide_05": (
            f"{steadiest} has the strongest consistency score at {company_data.get(steadiest, {}).get('consistency_score', 0.0):.1f}/100. "
            "More predictable cadence usually matters because it makes performance easier to compound and easier for viewers to anticipate."
        ),
        "slide_06": (
            "Treat the funnel split as a directional content signal, not a conversion truth. "
            "It helps reveal whether the recent sample leans more toward awareness, consideration, or proof-oriented content, while any unclassified share reflects titles and descriptions with unclear buyer-stage signals."
        ),
        "slide_07": (
            f"{engagement_leader} currently has the strongest recent average engagement at {company_data.get(engagement_leader, {}).get('avg_engagement_rate', 0.0):.3f}%. "
            "What matters here is both the level and whether the rolling line is strengthening or fading over the latest uploads."
        ),
        "slide_08": (
            f"{top_video_company} owns the strongest single recent top-video result in this sample at {top_video_views:,} views. "
            "Use the cards to compare not just raw views, but also engagement rate, publish date, and views per day."
        ),
        "slide_09": (
            f"{topic_leader} covers the broadest range of detected topics in the current sample, spanning {len(topic_clusters.get('company_coverage', {}).get(topic_leader, []))} detected clusters. "
            "Breadth can help discoverability, but focused ownership of a few high-intent themes can still outperform a wider spread."
        ),
        "slide_10": (
            f"For {target_company}, short videos currently lead at {short_er_target:.2f}% engagement versus {medium_er_target:.2f}% for medium and {long_er_target:.2f}% for long. "
            "Use this as a test-planning guide rather than a rule to ignore missing formats."
        ),
        "slide_11": (
            f"{timestamp_zero} of {len(companies)} channels show 0% timestamps in the fetched sample. "
            "That usually means chapter markers were absent in the recent descriptions we analyzed, which matters most for demos, tutorials, and webinar-style content."
        ),
        "slide_12": (
            f"The strongest current whitespace signal is {top_gap_name}, scoring {top_gap_score:.0f}/100 on the opportunity model. "
            "Use this as a prioritization tool for experiments, not as proof that a topic will automatically convert."
        ),
        "slide_13": (
            f"These recommendations are prioritized for {target_company}, which currently shows {target_row.get('consistency_score', 0.0):.1f}/100 consistency and {target_row.get('avg_engagement_rate', 0.0):.3f}% engagement. "
            "The highest-value actions focus on the largest gaps first rather than trying to change everything at once."
        ),
        "slide_14": (
            f"{leader} leads the current peer set overall with an RPI of {rpi_scores.get(leader, {}).get('rpi_score', 0.0):.1f}, while {laggard} is lowest at {rpi_scores.get(laggard, {}).get('rpi_score', 0.0):.1f}. "
            "Use this scorecard as a summary table and rely on the earlier slides for the underlying explanation."
        ),
    }


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not YOUTUBE_API_KEY:
        raise SystemExit("Missing YOUTUBE_API_KEY in .env")
    if not GEMINI_API_KEY and not GROQ_API_KEY:
        raise SystemExit("Missing GEMINI_API_KEY in .env")

    youtube = YouTubeService(YOUTUBE_API_KEY, use_disk_cache=not args.fresh)
    analytics = AnalyticsService()
    seo = SEOService(use_disk_cache=not args.fresh)
    ai = AIService(GEMINI_API_KEY or "", groq_api_key=GROQ_API_KEY)
    pptx = PPTXService()

    companies: list[str] = []
    company_data: dict[str, dict] = {}
    seo_scores: dict[str, dict] = {}
    videos_by_company: dict[str, list[dict]] = {}

    for company in args.companies:
        channel = youtube.find_channel(company)
        if not channel:
            print(f"[phase3] No channel found for {company}, skipping.")
            continue

        videos = youtube.get_recent_videos(channel["channel_id"], max_results=args.videos)
        if not videos:
            print(f"[phase3] No recent videos returned for {company}, skipping.")
            continue

        engagement = analytics.compute_engagement_metrics(videos)
        consistency = analytics.compute_upload_consistency(videos)
        funnel = analytics.classify_content_funnel(videos)
        length = analytics.analyse_video_length_strategy(videos)
        format_mix = analytics.analyse_format_mix(videos)
        recent = analytics.compute_recent_view_velocity(videos)
        titles = analytics.analyse_title_patterns(videos)
        seo_score = seo.score_video_seo(videos)

        top_videos = sorted(
            videos,
            key=lambda item: int(item.get("view_count", 0)),
            reverse=True,
        )[:2]

        companies.append(company)
        videos_by_company[company] = videos
        seo_scores[company] = seo_score
        company_data[company] = {
            "channel_id": channel.get("channel_id", ""),
            "title": channel.get("title", ""),
            "subscriber_count": channel.get("subscriber_count", 0),
            "video_count": channel.get("video_count", 0),
            "total_views": channel.get("total_views", 0),
            "published_at": channel.get("published_at", ""),
            **engagement,
            **consistency,
            **funnel,
            **length,
            **format_mix,
            **recent,
            "dominant_strategy_label": titles["dominant_strategy"]["label"],
            "dominant_strategy_description": titles["dominant_strategy"]["description"],
            "tutorial_count": titles["tutorial_count"],
            "listicle_count": titles["listicle_count"],
            "thought_leadership_count": titles["thought_leadership_count"],
            "product_led_count": titles["product_led_count"],
            "top_videos": top_videos,
        }

    if not companies:
        raise SystemExit("No companies were processed successfully.")

    topic_clusters = analytics.cluster_content_topics(videos_by_company)

    rpi_input = {}
    for company in companies:
        row = company_data[company]
        rpi_input[company] = {
            "avg_engagement_rate": row.get("avg_engagement_rate", 0.0),
            "views_per_subscriber": round(
                row.get("views_per_video", 0.0) / max(row.get("subscriber_count", 0), 1),
                6,
            ),
            "consistency_score": row.get("consistency_score", 0.0),
            "topic_diversity_score": topic_diversity_score(topic_clusters, company),
            "seo_score": seo_scores[company].get("seo_score", 0.0),
        }

    rpi_scores = analytics.compute_rpi(rpi_input)
    ranked_companies = sorted(companies, key=lambda c: rpi_scores.get(c, {}).get("rank", 999))
    target_company = args.target_company or ranked_companies[0]
    if target_company not in company_data:
        target_company = ranked_companies[0]

    gap_topics = topic_clusters.get("gap_topics", [])
    gap_queries = {topic: simplify_gap_topic_query(topic) for topic in gap_topics}
    unique_queries = []
    seen_queries = set()
    for query in gap_queries.values():
        if query not in seen_queries:
            unique_queries.append(query)
            seen_queries.add(query)

    fetched_gap_trends = seo.get_topic_trends(unique_queries) if unique_queries else {}
    trends_by_gap_topic = {
        topic: fetched_gap_trends.get(query, {})
        for topic, query in gap_queries.items()
    }

    opportunity_scores = seo.compute_opportunity_scores(
        gap_topics,
        trends_by_gap_topic,
        topic_clusters.get("cluster_coverage", {}),
    )

    ai_company_summary_data = {
        company: {
            **company_data[company],
            "rpi_score": rpi_scores.get(company, {}).get("rpi_score", 0.0),
            "rank": rpi_scores.get(company, {}).get("rank", 999),
            "seo_score": seo_scores.get(company, {}).get("seo_score", 0.0),
        }
        for company in companies
    }

    executive_summary = ai.generate_executive_summary(ai_company_summary_data)
    if not executive_summary:
        executive_summary = fallback_executive_summary(companies, rpi_scores)

    gap_analysis = ai.generate_gap_analysis(gap_topics, trends_by_gap_topic)
    if not gap_analysis:
        gap_analysis = fallback_gap_analysis(gap_topics)

    recommendations = ai.generate_recommendations(
        target_company,
        ai_company_summary_data[target_company],
        gap_topics,
    )
    if recommendations_need_fallback(recommendations):
        recommendations = build_fallback_recommendations(
            target_company,
            ai_company_summary_data[target_company],
            gap_topics,
            seo_scores[target_company].get("seo_score", 0.0),
        )
    recommendations = sanitize_recommendations_for_slides(recommendations)

    action_plan = ai.generate_action_plan(
        recommendations,
        current_cadence=company_data[target_company].get("mean_gap_days", 0.0),
    )
    if not action_plan:
        action_plan = fallback_action_plan(
            target_company,
            company_data[target_company].get("mean_gap_days", 0.0),
        )

    fallback_slide_interpretations = build_fallback_slide_interpretations(
        companies,
        company_data,
        rpi_scores,
        seo_scores,
        topic_clusters,
        opportunity_scores,
        recommendations,
        target_company,
    )
    slide_interpretations = ai.generate_slide_interpretations(
        build_slide_interpretation_context(
            companies,
            company_data,
            rpi_scores,
            seo_scores,
            topic_clusters,
            opportunity_scores,
            recommendations,
            target_company,
        )
    )
    if not slide_interpretations:
        slide_interpretations = fallback_slide_interpretations
    else:
        slide_interpretations = validate_slide_interpretations(
            slide_interpretations,
            fallback_slide_interpretations,
        )

    report_date = datetime.today().strftime("%B %d, %Y")
    output_path = Path(args.output) if args.output else (
        ROOT / "output" / f"phase3_live_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pptx"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "companies": companies,
        "report_date": report_date,
        "executive_summary": executive_summary,
        "company_data": company_data,
        "rpi_scores": rpi_scores,
        "topic_clusters": topic_clusters,
        "gap_analysis": gap_analysis,
        "opportunity_scores": opportunity_scores,
        "recommendations": recommendations,
        "action_plan": action_plan,
        "seo_scores": seo_scores,
        "slide_interpretations": slide_interpretations,
    }

    saved_path = pptx.generate_report(payload, str(output_path))

    print(f"Companies       : {', '.join(companies)}")
    print(f"Target company  : {target_company}")
    print(f"Recent videos   : {args.videos} per company")
    print(f"Output file     : {saved_path}")
    print("Open locally    : use PowerPoint or Keynote to inspect the generated deck.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
