from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import certifi
import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import GROQ_API_KEY


DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_URL = "https://api.groq.com/openai/v1/chat/completions"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Smoke-test Groq chat completions independently of the main report pipeline."
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Groq model to call. Default: {DEFAULT_MODEL}",
    )
    parser.add_argument(
        "--prompt",
        default="Reply with exactly: GROQ_OK",
        help="Prompt to send to Groq.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds. Default: 30",
    )
    parser.add_argument(
        "--url",
        default=DEFAULT_URL,
        help=f"Groq API URL. Default: {DEFAULT_URL}",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    api_key = (GROQ_API_KEY or "").strip()

    if not api_key:
        print("ERROR: GROQ_API_KEY is missing or blank.", file=sys.stderr)
        return 2

    payload = {
        "model": args.model,
        "messages": [
            {
                "role": "system",
                "content": "You are a connectivity smoke test. Keep answers brief.",
            },
            {
                "role": "user",
                "content": args.prompt,
            },
        ],
        "temperature": 0,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "video-competitor-intel-groq-smoke/1.0",
    }

    print(f"Testing Groq endpoint: {args.url}")
    print(f"Model: {args.model}")

    try:
        with httpx.Client(timeout=args.timeout, verify=certifi.where(), headers=headers) as client:
            response = client.post(args.url, json=payload)
    except httpx.HTTPError as exc:
        print(f"ERROR: Network/transport failure: {exc}", file=sys.stderr)
        return 3

    print(f"HTTP status: {response.status_code}")

    if response.status_code >= 400:
        print("ERROR: Groq returned a non-success response.", file=sys.stderr)
        print(response.text[:1500], file=sys.stderr)
        return 4

    try:
        data = response.json()
    except ValueError:
        print("ERROR: Groq returned non-JSON output.", file=sys.stderr)
        print(response.text[:1500], file=sys.stderr)
        return 5

    message = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
        .strip()
    )

    usage = data.get("usage", {})
    print("SUCCESS: Groq responded.")
    print(f"Response: {message or '<empty>'}")
    if usage:
        print("Usage:")
        print(json.dumps(usage, indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
