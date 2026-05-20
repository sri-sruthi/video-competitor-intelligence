#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.config import GEMINI_API_KEY, GROQ_API_KEY, YOUTUBE_API_KEY
from backend.services.ai_service import AIService
from backend.services.analytics_service import AnalyticsService
from backend.services.seo_service import SEOService
from backend.services.youtube_service import YouTubeService


DEFAULT_TOPICS = [
    "crm ai",
    "customer onboarding software",
    "video marketing automation",
]

COMPANY_TOPIC_PACKS = {
    "hubspot": [
        "crm ai",
        "customer onboarding software",
        "marketing automation",
        "sales pipeline management",
        "product demo videos",
    ],
    "salesforce": [
        "crm ai",
        "customer onboarding software",
        "sales automation",
        "enterprise ai platform",
        "product demo videos",
    ],
    "semrush": [
        "seo automation",
        "keyword research",
        "content marketing strategy",
        "website traffic analysis",
        "product demo videos",
    ],
    "mailchimp": [
        "email marketing automation",
        "customer onboarding software",
        "sms marketing",
        "product demo videos",
        "marketing automation",
    ],
    "monday.com": [
        "work management software",
        "project management automation",
        "customer onboarding software",
        "team collaboration software",
        "product demo videos",
    ],
    "loom": [
        "async video communication",
        "screen recording software",
        "customer onboarding videos",
        "product demo videos",
        "team collaboration software",
    ],
    "wistia": [
        "video marketing analytics",
        "webinar software",
        "product demo videos",
        "customer onboarding videos",
        "video hosting platform",
    ],
    "vidyard": [
        "sales video platform",
        "video prospecting",
        "product demo videos",
        "customer onboarding videos",
        "video messaging for sales",
    ],
    "mypromovideos": [
        "explainer video",
        "product demo video",
        "saas explainer video",
        "customer onboarding video",
        "motion graphics video",
    ],
}

VIDEO_SERVICES_TOPICS = [
    "explainer video",
    "product demo video",
    "customer onboarding video",
    "saas explainer video",
    "motion graphics video",
]

SAAS_TOPICS = [
    "crm ai",
    "customer onboarding software",
    "product demo videos",
    "video marketing automation",
    "sales enablement software",
]

GENERIC_B2B_TOPICS = [
    "product demo videos",
    "customer onboarding software",
    "video marketing strategy",
]


def normalize_company_key(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def dedupe_topics(topics: list[str], limit: int = 5) -> list[str]:
    seen: set[str] = set()
    output: list[str] = []
    for topic in topics:
        key = normalize_company_key(topic)
        if not key or key in seen:
            continue
        seen.add(key)
        output.append(topic)
        if len(output) >= limit:
            break
    return output


def infer_trend_topics(
    company_name: str,
    channel_title: str,
    videos: list[dict],
) -> list[str]:
    normalized_company = normalize_company_key(company_name)
    if normalized_company in COMPANY_TOPIC_PACKS:
        return COMPANY_TOPIC_PACKS[normalized_company]

    text = " ".join(
        [
            company_name,
            channel_title,
            *[video.get("title", "") for video in videos[:10]],
            *[video.get("description", "")[:120] for video in videos[:5]],
        ]
    ).lower()

    if any(
        token in text
        for token in (
            "animation",
            "explainer",
            "motion graphics",
            "video production",
            "walkthrough",
            "visualization",
        )
    ):
        return VIDEO_SERVICES_TOPICS

    if any(
        token in text
        for token in (
            "crm",
            "sales",
            "marketing",
            "onboarding",
            "workspace",
            "software",
            "enterprise",
            "customer success",
            "demo",
            "ai",
        )
    ):
        return SAAS_TOPICS

    return GENERIC_B2B_TOPICS


def generate_single_company_summary(
    ai: AIService,
    company_name: str,
    company_data: dict,
    trends: dict,
) -> str:
    trend_lines = []
    for topic, info in trends.items():
        trend_lines.append(
            f"- {topic}: avg_interest={info.get('avg_interest', 'N/A')}, "
            f"trend={info.get('trend_direction', 'unknown')}, "
            f"peak_month={info.get('peak_month', 'unknown')}, "
            f"source={info.get('source', 'unknown')}"
        )

    prompt = (
        f"Company: {company_name}\n"
        f"Avg engagement rate: {company_data.get('avg_engagement_rate', 'N/A')}%\n"
        f"Views per video: {company_data.get('views_per_video', 'N/A')}\n"
        f"Average views per day: {company_data.get('avg_views_per_day', 'N/A')}\n"
        f"Upload consistency score: {company_data.get('consistency_score', 'N/A')}/100\n"
        f"Funnel distribution heuristic: {company_data.get('funnel_label', 'N/A')} "
        f"(TOFU {company_data.get('tofu_pct', 'N/A')}% / "
        f"MOFU {company_data.get('mofu_pct', 'N/A')}% / "
        f"BOFU {company_data.get('bofu_pct', 'N/A')}%), "
        f"default-classified videos={company_data.get('unclassified_count', 'N/A')}\n"
        f"Best-performing video length: {company_data.get('best_performing_length', 'N/A')}\n"
        f"Dominant format: {company_data.get('dominant_format', 'N/A')} "
        f"({company_data.get('dominant_format_pct', 'N/A')}% of sample)\n"
        f"Format diversity score: {company_data.get('format_diversity_score', 'N/A')}/100\n"
        f"Dominant title strategy: {company_data.get('dominant_strategy_label', 'N/A')} "
        f"— {company_data.get('dominant_strategy_description', '')}\n"
        f"SEO score: {company_data.get('seo_score', 'N/A')}/100\n\n"
        "Trend signals:\n"
        + "\n".join(trend_lines)
        + "\n\nWrite a 180-word executive summary for this single company's video strategy. "
        "Do not mention rank, leader, or comparative position unless comparative data was provided. "
        "Use cautious language such as 'suggests', 'may indicate', or 'appears to' for inferences. "
        "Treat funnel distribution as a heuristic based on titles/descriptions, not a hard truth. "
        "Do not over-focus on TOFU/MOFU/BOFU alone. Also weigh format mix, recent view velocity, "
        "SEO strength, title strategy, consistency, and trend alignment. Focus on: what the current "
        "strategy appears to be, the top 3 strategic takeaways, and what it implies for content planning. "
        "Cite the actual numbers above."
    )

    summary = asyncio.run(ai._call_gemini(prompt))
    return summary or (
        "Gemini summary unavailable right now. Trends, SEO, and analytics data were still collected successfully."
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a live Phase 2 smoke test across YouTube, analytics, trends, and Gemini."
    )
    parser.add_argument(
        "company",
        nargs="?",
        default="HubSpot",
        help="Company name to test. Defaults to HubSpot.",
    )
    parser.add_argument(
        "--videos",
        type=int,
        default=5,
        help="Number of recent videos to analyze. Defaults to 5.",
    )
    parser.add_argument(
        "--topics",
        nargs="*",
        default=None,
        help="Trend topics to fetch. If omitted, company-aware topics are selected automatically.",
    )
    parser.add_argument(
        "--trends-csv",
        help="Use a manual Google Trends CSV export instead of live trends providers.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore the on-disk trends cache for this run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full report as JSON.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not YOUTUBE_API_KEY:
        raise SystemExit("Missing YOUTUBE_API_KEY in .env")
    if not GEMINI_API_KEY and not GROQ_API_KEY:
        raise SystemExit("Missing GEMINI_API_KEY or GROQ_API_KEY in .env")

    youtube = YouTubeService(YOUTUBE_API_KEY)
    analytics = AnalyticsService()
    seo = SEOService(use_disk_cache=not args.fresh)
    ai = AIService(GEMINI_API_KEY or "", groq_api_key=GROQ_API_KEY)

    channel = youtube.find_channel(args.company)
    if not channel:
        raise SystemExit(f"No channel found for {args.company}")

    videos = youtube.get_recent_videos(channel["channel_id"], max_results=args.videos)
    if not videos:
        raise SystemExit(f"No recent videos returned for {args.company}")

    selected_topics = (
        args.topics
        if args.topics
        else infer_trend_topics(
            args.company,
            channel.get("title", ""),
            videos,
        )
    )

    engagement = analytics.compute_engagement_metrics(videos)
    consistency = analytics.compute_upload_consistency(videos)
    funnel = analytics.classify_content_funnel(videos)
    length = analytics.analyse_video_length_strategy(videos)
    format_mix = analytics.analyse_format_mix(videos)
    recency = analytics.compute_recent_view_velocity(videos)
    titles = analytics.analyse_title_patterns(videos)
    seo_score = seo.score_video_seo(videos)

    if args.trends_csv:
        trends = seo.parse_trends_csv_export(args.trends_csv)
    else:
        trends = seo.get_topic_trends(selected_topics)

    company_data = {
        **engagement,
        **consistency,
        **funnel,
        **length,
        **format_mix,
        **recency,
        "dominant_strategy_label": titles["dominant_strategy"]["label"],
        "dominant_strategy_description": titles["dominant_strategy"]["description"],
        "tutorial_count": titles["tutorial_count"],
        "listicle_count": titles["listicle_count"],
        "thought_leadership_count": titles["thought_leadership_count"],
        "product_led_count": titles["product_led_count"],
        "seo_score": seo_score["seo_score"],
    }

    summary = generate_single_company_summary(
        ai,
        args.company,
        company_data,
        trends,
    )

    payload = {
        "company": args.company,
        "channel": {
            "channel_id": channel.get("channel_id", ""),
            "title": channel.get("title", ""),
            "subscriber_count": channel.get("subscriber_count", 0),
            "video_count": channel.get("video_count", 0),
            "total_views": channel.get("total_views", 0),
            "published_at": channel.get("published_at", ""),
        },
        "recent_videos_count": len(videos),
        "selected_topics": selected_topics,
        "seo_score": seo_score,
        "trends": trends,
        "analytics": {
            "engagement": engagement,
            "consistency": consistency,
            "funnel": funnel,
            "length_strategy": length,
            "format_mix": format_mix,
            "recent_performance": recency,
            "title_patterns": titles,
        },
        "summary": summary,
    }

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"Company         : {payload['company']}")
    print(f"Channel         : {payload['channel']['title']}")
    print(f"Subscribers     : {payload['channel']['subscriber_count']:,}")
    print(f"Recent videos   : {payload['recent_videos_count']}")
    print(f"SEO score       : {payload['seo_score']['seo_score']}")
    print(f"Trend topics    : {', '.join(payload['selected_topics'])}")
    print("Trends")
    for topic, info in trends.items():
        print(
            f"  {topic}: avg={info.get('avg_interest')} "
            f"trend={info.get('trend_direction')} "
            f"peak={info.get('peak_month')} "
            f"source={info.get('source')}"
        )
    print("Summary")
    print(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
