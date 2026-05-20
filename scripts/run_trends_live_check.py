#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.seo_service import SEOService


DEFAULT_TOPICS = [
    "crm ai",
    "video marketing automation",
    "customer onboarding software",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a live Google Trends check using pytrends, SerpApi fallback, or a manual CSV export."
    )
    parser.add_argument(
        "topics",
        nargs="*",
        default=DEFAULT_TOPICS,
        help="Topics to fetch from trends providers. Ignored when --csv is used.",
    )
    parser.add_argument(
        "--csv",
        help="Path to a manual Google Trends CSV export to parse instead of calling live providers.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore the on-disk trends cache for this run.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    service = SEOService(use_disk_cache=not args.fresh)

    if args.csv:
        payload = service.parse_trends_csv_export(args.csv)
    else:
        payload = service.get_topic_trends(args.topics)

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
