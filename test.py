"""
test.py
Quick smoke-test runner for the Video Competitor Intelligence backend.

Examples:
  python3 test.py
  python3 test.py HubSpot Salesforce Semrush Mailchimp monday.com
  python3 test.py --videos 10 HubSpot
  python3 test.py --videos 5 --comments 3 HubSpot
  python3 test.py --json --videos 5 HubSpot Salesforce
  python3 test.py --fresh Mailchimp
"""

from __future__ import annotations

import argparse
import json
import sys

from backend.config import YOUTUBE_API_KEY
from backend.services.analytics_service import AnalyticsService
from backend.services.youtube_service import YouTubeService


# Default comparison set chosen to surface different YouTube strategies.
DEFAULT_COMPANIES = [
    "HubSpot",
    "Salesforce",
    "Semrush",
    "Mailchimp",
    "monday.com",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test YouTube channel matching and optional video analytics."
    )
    parser.add_argument(
        "companies",
        nargs="*",
        default=DEFAULT_COMPANIES,
        help="Company names to look up. Defaults to a small multi-brand smoke test.",
    )
    parser.add_argument(
        "--videos",
        type=int,
        default=0,
        help="Fetch this many recent videos per matched channel and run analytics.",
    )
    parser.add_argument(
        "--comments",
        type=int,
        default=0,
        help=(
            "Fetch up to this many top comments for each of the first few recent "
            "videos. If --videos is omitted, a small recent-video sample is fetched."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the smoke-test report as JSON instead of formatted text.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore the persisted channel cache for this run.",
    )
    return parser


def normalize_text(value: str) -> str:
    return " ".join(value.lower().split())


def classify_match(company_name: str, channel_title: str) -> str:
    company = normalize_text(company_name)
    title = normalize_text(channel_title)
    company_tokens = company.split()
    title_tokens = title.split()

    if title == company:
        return "exact"

    if (
        company_tokens
        and title_tokens
        and title_tokens[-len(company_tokens):] == company_tokens
        and title_tokens[: -len(company_tokens)]
    ):
        return "parent-brand"

    if title.startswith(company):
        return "brand-prefix"
    if company in title:
        return "contains-brand"
    return "weak"


def format_int(value: int) -> str:
    return f"{value:,}"


def interpret_consistency(score: float) -> str:
    if score >= 75:
        return "high"
    if score >= 45:
        return "medium"
    return "low"


def sanitize_channel(channel: dict) -> dict:
    return {
        **channel,
        "title": channel.get("title", "").strip(),
        "description": channel.get("description", "").strip(),
    }


def summarize_analytics(videos: list[dict], analytics: AnalyticsService) -> dict:
    engagement = analytics.compute_engagement_metrics(videos)
    consistency = analytics.compute_upload_consistency(videos)
    funnel = analytics.classify_content_funnel(videos)
    length = analytics.analyse_video_length_strategy(videos)
    title_patterns = analytics.analyse_title_patterns(videos)

    return {
        "engagement": engagement,
        "consistency": consistency,
        "funnel": funnel,
        "length_strategy": length,
        "title_patterns": title_patterns,
    }


def collect_comments(
    youtube: YouTubeService,
    videos: list[dict],
    per_video_limit: int,
    max_videos: int = 3,
) -> list[dict]:
    comment_reports: list[dict] = []
    for video in videos[:max_videos]:
        comments = youtube.get_top_comments(
            video["video_id"],
            max_results=per_video_limit,
        )
        comment_reports.append(
            {
                "video_id": video.get("video_id", ""),
                "title": video.get("title", "").strip(),
                "published_at": video.get("published_at", ""),
                "comments": comments,
            }
        )

    return comment_reports


def build_comparison_summary(reports: list[dict]) -> dict:
    analytics_reports = [
        report for report in reports
        if report.get("ok") and report.get("analytics")
    ]
    if not analytics_reports:
        return {}

    def winner(metric_getter, reverse: bool = True) -> dict:
        best = max(analytics_reports, key=metric_getter) if reverse else min(
            analytics_reports,
            key=metric_getter,
        )
        return {
            "company_name": best["company_name"],
            "value": metric_getter(best),
        }

    return {
        "engagement_leader": winner(
            lambda report: report["analytics"]["engagement"]["avg_engagement_rate"]
        ),
        "views_per_video_leader": winner(
            lambda report: report["analytics"]["engagement"]["views_per_video"]
        ),
        "consistency_leader": winner(
            lambda report: report["analytics"]["consistency"]["consistency_score"]
        ),
        "most_bottom_funnel": winner(
            lambda report: report["analytics"]["funnel"]["bofu_pct"]
        ),
    }


def build_company_report(
    company_name: str,
    youtube: YouTubeService,
    analytics: AnalyticsService,
    video_count: int,
    comment_count: int,
) -> dict:
    raw_channel = youtube.find_channel(company_name)
    if not raw_channel:
        return {
            "company_name": company_name,
            "ok": False,
            "error": "no channel found",
        }
    channel = sanitize_channel(raw_channel)

    report = {
        "company_name": company_name,
        "ok": True,
        "match_quality": classify_match(company_name, channel.get("title", "")),
        "channel": channel,
    }

    if video_count > 0:
        videos = youtube.get_recent_videos(
            channel["channel_id"],
            max_results=video_count,
        )
        report["recent_videos_count"] = len(videos)
        report["recent_videos"] = [
            {
                "video_id": video.get("video_id", ""),
                "title": video.get("title", "").strip(),
                "published_at": video.get("published_at", ""),
                "view_count": video.get("view_count", 0),
                "like_count": video.get("like_count", 0),
                "comment_count": video.get("comment_count", 0),
                "duration_seconds": video.get("duration_seconds", 0),
            }
            for video in videos
        ]

        if videos:
            report["analytics"] = summarize_analytics(videos, analytics)
            if comment_count > 0:
                report["top_comments"] = collect_comments(
                    youtube,
                    videos,
                    per_video_limit=comment_count,
                )

    return report


def print_channel_summary(report: dict) -> None:
    channel = report["channel"]

    print(f"Matched title      : {channel.get('title', '')}")
    print(f"Match quality      : {report['match_quality']}")
    print(f"Channel ID         : {channel.get('channel_id', '')}")
    print(f"Subscribers        : {format_int(channel.get('subscriber_count', 0))}")
    print(f"Video count        : {format_int(channel.get('video_count', 0))}")
    print(f"Total views        : {format_int(channel.get('total_views', 0))}")
    print(f"Published at       : {channel.get('published_at', '')}")
    print(f"Description        : {channel.get('description', '')[:140]}")


def print_video_analytics(report: dict) -> None:
    analytics = report.get("analytics")
    if not analytics:
        print("Recent videos      : none returned")
        return

    engagement = analytics["engagement"]
    consistency = analytics["consistency"]
    funnel = analytics["funnel"]
    length = analytics["length_strategy"]
    title_patterns = analytics["title_patterns"]

    print(f"Recent videos      : {report.get('recent_videos_count', 0)}")
    print(f"Avg engagement %   : {engagement['avg_engagement_rate']}")
    print(f"Median engagement %: {engagement['median_engagement_rate']}")
    print(f"Views per video    : {engagement['views_per_video']}")
    print(f"Consistency score  : {consistency['consistency_score']}")
    print(
        "Consistency label  : "
        f"{interpret_consistency(consistency['consistency_score'])}"
    )
    print(f"Weekly cadence     : {consistency['detect_weekly_cadence']}")
    print(f"Funnel label       : {funnel['funnel_label']}")
    print(f"Best length bucket : {length['best_performing_length']}")
    print(
        "Dominant title type: "
        f"{title_patterns['dominant_strategy']['label']}"
    )

    if report.get("top_comments"):
        for video_report in report["top_comments"]:
            print(f"Comments for       : {video_report['title'][:80]}")
            if video_report["comments"]:
                for idx, comment in enumerate(video_report["comments"], start=1):
                    print(f"  {idx}. {comment[:140]}")
            else:
                print("  No comments returned")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    youtube = YouTubeService(YOUTUBE_API_KEY, use_disk_cache=not args.fresh)
    analytics = AnalyticsService()

    requested_video_count = max(args.videos, 3 if args.comments > 0 else 0)
    reports: list[dict] = []

    for company_name in args.companies:
        try:
            report = build_company_report(
                company_name,
                youtube,
                analytics,
                video_count=requested_video_count,
                comment_count=args.comments,
            )
        except Exception as exc:
            report = {
                "company_name": company_name,
                "ok": False,
                "error": str(exc),
            }
        reports.append(report)

    successes = sum(1 for report in reports if report.get("ok"))
    failures = [
        report["company_name"]
        for report in reports
        if not report.get("ok")
    ]

    summary = {
        "successful_lookups": successes,
        "requested_companies": len(args.companies),
        "failed_companies": failures,
    }
    comparison_summary = build_comparison_summary(reports)

    if args.json:
        print(
            json.dumps(
                {
                    "reports": reports,
                    "summary": summary,
                    "comparison_summary": comparison_summary,
                },
                indent=2,
            )
        )
        return 0 if not failures else 1

    for report in reports:
        print(f"\n=== {report['company_name']} ===")
        if not report.get("ok"):
            print(f"Lookup failed      : {report.get('error', 'unknown error')}")
            continue

        print_channel_summary(report)
        if requested_video_count > 0:
            print_video_analytics(report)

    print("\n=== Summary ===")
    print(f"Successful lookups : {successes}/{len(args.companies)}")
    if failures:
        print(f"Failed companies   : {', '.join(failures)}")
    if comparison_summary:
        print("Engagement leader  : "
              f"{comparison_summary['engagement_leader']['company_name']} "
              f"({comparison_summary['engagement_leader']['value']})")
        print("Views/video leader : "
              f"{comparison_summary['views_per_video_leader']['company_name']} "
              f"({comparison_summary['views_per_video_leader']['value']})")
        print("Consistency leader : "
              f"{comparison_summary['consistency_leader']['company_name']} "
              f"({comparison_summary['consistency_leader']['value']})")
        print("Bottom-funnel lead : "
              f"{comparison_summary['most_bottom_funnel']['company_name']} "
              f"({comparison_summary['most_bottom_funnel']['value']})")

    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
