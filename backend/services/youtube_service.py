"""
youtube_service.py
Fetches YouTube channel and video data for competitor intelligence analysis.
"""

from copy import deepcopy
import json
import math
from pathlib import Path
import re
from typing import Optional
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


CHANNEL_QUERY_ALIASES = {
    "loom": ["Atlassian Loom"],
    "mailchimp": ["MailChimp", "Intuit Mailchimp"],
    "monday.com": ["monday"],
    "semrush": ["SEMrush", "semrushHQ"],
}

CACHE_VERSION = 4
CHANNELS_LIST_BATCH_SIZE = 50
MAX_CHANNEL_SEARCH_QUERIES = 3


class YouTubeService:
    """Service for retrieving YouTube channel and video data via the Data API v3."""

    def __init__(self, api_key: str, use_disk_cache: bool = True):
        """
        Initialise the YouTube Data API client.

        Args:
            api_key: A valid YouTube Data API v3 key.
            use_disk_cache: Whether to reuse persisted channel matches.
        """
        if not api_key or not api_key.strip():
            raise ValueError(
                "Missing YOUTUBE_API_KEY. Add it to the project .env file "
                "or export it in your shell before creating YouTubeService."
            )

        self.api_key = api_key
        self.youtube = build("youtube", "v3", developerKey=api_key)
        self.use_disk_cache = use_disk_cache
        self._cache_path = (
            Path(__file__).resolve().parents[2] / ".cache" / "youtube_channel_cache.json"
        )
        self._channel_cache: dict[str, dict] = (
            self._load_channel_cache() if use_disk_cache else {}
        )
        self._recent_videos_cache: dict[tuple[str, int], list[dict]] = {}
        self._comments_cache: dict[tuple[str, int], list[str]] = {}

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def find_channel(self, company_name: str) -> dict:
        """
        Search YouTube for the official channel of a company.

        Strategy:
          1. Search with multiple brand-focused queries.
          2. Score candidates to prefer the main official brand channel.
          3. Penalise topic-specific sub-brand channels such as
             "Marketing", "Support", or regional variants unless those
             words are part of the company name.
          4. Fall back to the highest-scoring result.

        Args:
            company_name: The name of the company to look up.

        Returns:
            A dict with keys:
              channel_id, title, subscriber_count, video_count,
              total_views, published_at, description.
            Returns an empty dict if no channel is found.
        """
        if not company_name or not company_name.strip():
            return {}

        cache_key = self._normalize_text(company_name)
        if cache_key in self._channel_cache:
            return deepcopy(self._channel_cache[cache_key])

        items = self._search_channel_candidates(company_name)
        if not items:
            return {}

        # Collect candidate channel IDs
        channel_ids = [item["id"]["channelId"] for item in items]

        # Fetch richer details for all candidates in one request
        details_map = self._batch_channel_details(channel_ids)
        peer_context = self._build_peer_context(details_map)

        scored_candidates = []
        for search_item in items:
            item = self._merge_channel_item(
                search_item,
                details_map.get(search_item["id"]["channelId"], {}),
            )
            cid = item["id"]["channelId"]
            score = self._score_channel_candidate(
                company_name,
                item,
                peer_context=peer_context,
            )
            scored_candidates.append((score, cid, item))

        if not scored_candidates:
            return {}

        _, cid, best_item = max(scored_candidates, key=lambda row: row[0])
        snippet = best_item.get("snippet", {})
        stats = best_item.get("statistics", {})

        result = {
            "channel_id": cid,
            "title": snippet.get("title", "").strip(),
            "subscriber_count": int(stats.get("subscriberCount", 0)),
            "video_count": int(stats.get("videoCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "published_at": snippet.get("publishedAt", ""),
            "description": snippet.get("description", "").strip(),
        }
        self._channel_cache[cache_key] = deepcopy(result)
        if self.use_disk_cache:
            self._persist_channel_cache()
        return result

    def get_recent_videos(self, channel_id: str, max_results: int = 50) -> list[dict]:
        """
        Retrieve the most recent videos from a channel with full statistics.

        Args:
            channel_id: The YouTube channel ID.
            max_results: Maximum number of videos to retrieve (default 50).

        Returns:
            A list of dicts, each containing:
              video_id, title, description, published_at,
              view_count, like_count, comment_count, duration_seconds, tags.
        """
        if not channel_id:
            return []

        cache_key = (channel_id, max_results)
        if cache_key in self._recent_videos_cache:
            return deepcopy(self._recent_videos_cache[cache_key])

        # Step 1: get the uploads playlist ID
        uploads_playlist_id = self._get_uploads_playlist_id(channel_id)
        if not uploads_playlist_id:
            self._recent_videos_cache[cache_key] = []
            return []

        # Step 2: page through the playlist to collect video IDs
        video_ids = self._collect_playlist_video_ids(uploads_playlist_id, max_results)
        if not video_ids:
            self._recent_videos_cache[cache_key] = []
            return []

        # Step 3: fetch full video details in batches of 50
        result = self._fetch_video_details(video_ids)
        self._recent_videos_cache[cache_key] = deepcopy(result)
        return result

    def get_top_comments(self, video_id: str, max_results: int = 10) -> list[str]:
        """
        Return the top-level comment texts for a video, ordered by relevance.

        Comments may be disabled on many B2B videos; errors are silently caught.

        Args:
            video_id: The YouTube video ID.
            max_results: Maximum number of comments to return (default 10).

        Returns:
            A list of comment text strings (may be empty).
        """
        if not video_id:
            return []

        cache_key = (video_id, max_results)
        if cache_key in self._comments_cache:
            return list(self._comments_cache[cache_key])

        try:
            response = (
                self.youtube.commentThreads()
                .list(
                    videoId=video_id,
                    part="snippet",
                    maxResults=max_results,
                    order="relevance",
                    textFormat="plainText",
                )
                .execute()
            )
            comments = [
                item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
                for item in response.get("items", [])
            ]
            self._comments_cache[cache_key] = list(comments)
            return comments
        except HttpError:
            # Comments disabled or another API error — return empty list
            self._comments_cache[cache_key] = []
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_search_queries(self, company_name: str) -> list[str]:
        """Build brand, alias, and official-intent queries for channel search."""
        base_name = company_name.strip()
        normalized_name = self._normalize_text(base_name)
        aliases = CHANNEL_QUERY_ALIASES.get(normalized_name, [])

        brand_variants = [
            base_name,
            *self._build_generic_variants(base_name),
            *aliases,
        ]

        seen: set[str] = set()
        unique_variants: list[str] = []
        for variant in brand_variants:
            cleaned_variant = " ".join(variant.strip().split())
            if not cleaned_variant:
                continue
            variant_key = cleaned_variant.lower()
            if variant_key in seen:
                continue
            seen.add(variant_key)
            unique_variants.append(cleaned_variant)

        queries: list[str] = []
        if unique_variants:
            queries.append(unique_variants[0])
            queries.append(f"{unique_variants[0]} official")

        for variant in unique_variants[1:]:
            if len(queries) >= MAX_CHANNEL_SEARCH_QUERIES:
                break
            queries.append(variant)

        return queries[:MAX_CHANNEL_SEARCH_QUERIES]

    def _search_channel_candidates(self, company_name: str) -> list[dict]:
        """Search multiple queries and return de-duplicated channel results."""
        queries = self._build_search_queries(company_name)
        seen_channel_ids: set[str] = set()
        items: list[dict] = []

        for query in queries:
            try:
                response = (
                    self.youtube.search()
                    .list(
                        q=query,
                        type="channel",
                        part="snippet",
                        maxResults=10,
                    )
                    .execute()
                )
            except HttpError as exc:
                print(f"[YouTubeService] Search error for '{company_name}': {exc}")
                if self._is_quota_exceeded_error(exc):
                    break
                continue

            for item in response.get("items", []):
                channel_id = item.get("id", {}).get("channelId")
                if not channel_id or channel_id in seen_channel_ids:
                    continue
                seen_channel_ids.add(channel_id)
                items.append(item)

        return items

    def _score_channel_candidate(
        self,
        company_name: str,
        item: dict,
        stats: Optional[dict] = None,
        peer_context: Optional[dict] = None,
    ) -> float:
        """Score a channel candidate so the main official brand channel wins."""
        stats = stats or item.get("statistics", {})
        company_normalized = self._normalize_text(company_name)
        company_tokens = self._tokenize(company_name)
        title = item.get("snippet", {}).get("title", "")
        description = item.get("snippet", {}).get("description", "")
        title_normalized = self._normalize_text(title)
        title_tokens = self._tokenize(title)
        description_normalized = self._normalize_text(description)
        custom_url = self._normalize_text(item.get("snippet", {}).get("customUrl", ""))

        score = 0.0

        if title_normalized == company_normalized:
            score += 70

        if title_tokens[: len(company_tokens)] == company_tokens:
            score += 45

        if all(token in title_tokens for token in company_tokens):
            score += 25

        if custom_url == company_normalized:
            score += 30
        elif custom_url.endswith(company_normalized):
            score += 18

        duplicate_token_count = len(title_tokens) - len(set(title_tokens))
        if duplicate_token_count > 0 and title_normalized != company_normalized:
            score -= duplicate_token_count * 30

        extra_title_tokens = [
            token for token in title_tokens if token not in set(company_tokens)
        ]
        if not extra_title_tokens:
            score += 15
        else:
            # Keep a mild penalty for longer, less exact channel titles.
            score -= min(len(extra_title_tokens) * 4, 16)

        if "official" in title_normalized:
            score += 12

        if "official" in description_normalized:
            score += 8

        if company_normalized in description_normalized:
            score += 6

        company_context_terms = {
            "ai",
            "app",
            "apps",
            "business",
            "businesses",
            "crm",
            "customer",
            "customers",
            "enterprise",
            "marketing",
            "platform",
            "product",
            "products",
            "productivity",
            "sales",
            "screen recording",
            "service",
            "services",
            "software",
            "solution",
            "solutions",
            "team",
            "teams",
            "tool",
            "tools",
            "video messaging",
            "work",
            "workflow",
            "workflows",
            "workspace",
        }
        creator_or_irrelevant_terms = {
            "channel member",
            "decks",
            "discord",
            "donations",
            "duel links",
            "gameplay",
            "i make content",
            "just subscribe already",
            "master duel",
            "memes",
            "my twitter",
            "streamlabs",
            "streams",
            "twitch",
            "virtual cardboard",
        }
        tutorial_clone_terms = {
            "email marketing tutorial",
            "service tiers",
            "specially for",
            "tutorial 2023",
        }

        company_context_hits = self._count_phrase_hits(
            description_normalized,
            company_context_terms,
        )
        creator_or_irrelevant_hits = self._count_phrase_hits(
            description_normalized,
            creator_or_irrelevant_terms,
        )
        tutorial_clone_hits = self._count_phrase_hits(
            description_normalized,
            tutorial_clone_terms,
        )

        score += min(company_context_hits * 4, 24)
        score -= min(creator_or_irrelevant_hits * 18, 72)
        score -= min(tutorial_clone_hits * 14, 42)

        penalty_tokens = {
            "academy",
            "blog",
            "careers",
            "community",
            "courses",
            "developers",
            "events",
            "help",
            "india",
            "learning",
            "marketing",
            "partners",
            "podcast",
            "sales",
            "school",
            "studio",
            "support",
            "training",
            "uk",
        }
        for token in extra_title_tokens:
            if token in penalty_tokens:
                score -= 35

        subscriber_count = int(stats.get("subscriberCount", 0))
        video_count = int(stats.get("videoCount", 0))
        view_count = int(stats.get("viewCount", 0))

        if subscriber_count > 0:
            score += min(math.log10(subscriber_count), 6) * 5

        if video_count > 0:
            score += min(math.log10(video_count), 4) * 6

        title_is_brand_exact = title_normalized == company_normalized
        if title_is_brand_exact and creator_or_irrelevant_hits >= 2 and company_context_hits == 0:
            score -= 85

        if peer_context and title_is_brand_exact:
            max_subscribers = peer_context.get("max_subscribers", 0)
            max_videos = peer_context.get("max_videos", 0)
            max_views = peer_context.get("max_views", 0)

            # Exact-name channels can still be fake, abandoned, or tiny secondary
            # channels. Penalise them when a much more established peer exists.
            if (
                max_subscribers >= 5_000
                and subscriber_count < 100
                and video_count < 20
            ):
                score -= 140
            elif (
                max_subscribers >= 20_000
                and subscriber_count < 1_000
                and video_count < 50
            ):
                score -= 80

            if max_videos >= 100 and video_count < 10:
                score -= 35

            if max_views >= 100_000 and view_count < 1_000:
                score -= 25

        return score

    @staticmethod
    def _build_generic_variants(company_name: str) -> list[str]:
        """Generate a few low-risk generic brand variants for arbitrary names."""
        variants: list[str] = []

        if ".com" in company_name.lower():
            variants.append(re.sub(r"(?i)\.com", "", company_name))

        punctuation_stripped = re.sub(r"[^A-Za-z0-9 ]+", " ", company_name)
        if punctuation_stripped != company_name:
            variants.append(" ".join(punctuation_stripped.split()))

        return variants

    @staticmethod
    def _count_phrase_hits(text: str, phrases: set[str]) -> int:
        """Count how many provided phrases appear in normalized text."""
        return sum(1 for phrase in phrases if phrase in text)

    def _load_channel_cache(self) -> dict[str, dict]:
        """Load the persistent channel cache from disk."""
        try:
            if not self._cache_path.exists():
                return {}

            payload = json.loads(self._cache_path.read_text(encoding="utf-8"))
            if payload.get("version") != CACHE_VERSION:
                return {}

            channels = payload.get("channels", {})
            return channels if isinstance(channels, dict) else {}
        except (json.JSONDecodeError, OSError):
            return {}

    def _persist_channel_cache(self) -> None:
        """Persist successful channel lookups to a small JSON cache on disk."""
        try:
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "version": CACHE_VERSION,
                "channels": self._channel_cache,
            }
            self._cache_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        except OSError:
            # Cache persistence is a best-effort optimization.
            pass

    @staticmethod
    def _is_quota_exceeded_error(exc: HttpError) -> bool:
        """Return True when the YouTube API reports quota exhaustion."""
        return getattr(exc, "status_code", None) == 403 and "quotaExceeded" in str(exc)

    @staticmethod
    def _normalize_text(value: str) -> str:
        """Lowercase text and collapse punctuation for fuzzy comparisons."""
        return " ".join(re.findall(r"[a-z0-9]+", value.lower()))

    @classmethod
    def _tokenize(cls, value: str) -> list[str]:
        """Tokenize text using the same normalization as channel scoring."""
        normalized = cls._normalize_text(value)
        return normalized.split() if normalized else []

    @staticmethod
    def _merge_channel_item(search_item: dict, detail_item: dict) -> dict:
        """Merge search result fields with richer channel details."""
        merged_snippet = {
            **search_item.get("snippet", {}),
            **detail_item.get("snippet", {}),
        }
        return {
            "id": search_item.get("id", {}),
            "snippet": merged_snippet,
            "statistics": detail_item.get("statistics", {}),
        }

    @staticmethod
    def _build_peer_context(details_map: dict) -> dict:
        """Summarise the strongest candidate scale within the current result set."""
        subscriber_counts = []
        video_counts = []
        view_counts = []

        for item in details_map.values():
            stats = item.get("statistics", {})
            subscriber_counts.append(int(stats.get("subscriberCount", 0)))
            video_counts.append(int(stats.get("videoCount", 0)))
            view_counts.append(int(stats.get("viewCount", 0)))

        return {
            "max_subscribers": max(subscriber_counts, default=0),
            "max_videos": max(video_counts, default=0),
            "max_views": max(view_counts, default=0),
        }

    def _batch_channel_details(self, channel_ids: list[str]) -> dict:
        """
        Fetch details for a list of channel IDs in a single API call.

        Returns:
            {channel_id: channel_item_dict}
        """
        if not channel_ids:
            return {}

        details_map: dict[str, dict] = {}
        for i in range(0, len(channel_ids), CHANNELS_LIST_BATCH_SIZE):
            batch = channel_ids[i : i + CHANNELS_LIST_BATCH_SIZE]
            try:
                response = (
                    self.youtube.channels()
                    .list(
                        id=",".join(batch),
                        part="snippet,statistics",
                    )
                    .execute()
                )
                details_map.update(
                    {
                        item["id"]: item
                        for item in response.get("items", [])
                    }
                )
            except HttpError as exc:
                print(f"[YouTubeService] Channel details error: {exc}")
                if self._is_quota_exceeded_error(exc):
                    break

        return details_map

    def _get_uploads_playlist_id(self, channel_id: str) -> Optional[str]:
        """Return the uploads playlist ID for a channel."""
        try:
            response = (
                self.youtube.channels()
                .list(
                    id=channel_id,
                    part="contentDetails",
                )
                .execute()
            )
            items = response.get("items", [])
            if not items:
                return None
            return (
                items[0]
                .get("contentDetails", {})
                .get("relatedPlaylists", {})
                .get("uploads")
            )
        except HttpError as exc:
            print(f"[YouTubeService] Uploads playlist error for {channel_id}: {exc}")
            return None

    def _collect_playlist_video_ids(
        self, playlist_id: str, max_results: int
    ) -> list[str]:
        """Page through a playlist and return up to max_results video IDs."""
        video_ids: list[str] = []
        next_page_token = None
        page_size = min(50, max_results)

        while len(video_ids) < max_results:
            try:
                kwargs = dict(
                    playlistId=playlist_id,
                    part="contentDetails",
                    maxResults=page_size,
                )
                if next_page_token:
                    kwargs["pageToken"] = next_page_token

                response = self.youtube.playlistItems().list(**kwargs).execute()
                for item in response.get("items", []):
                    vid = item["contentDetails"].get("videoId")
                    if vid:
                        video_ids.append(vid)

                next_page_token = response.get("nextPageToken")
                if not next_page_token:
                    break
            except HttpError as exc:
                print(f"[YouTubeService] Playlist paging error: {exc}")
                break

        return video_ids[:max_results]

    def _fetch_video_details(self, video_ids: list[str]) -> list[dict]:
        """Fetch full statistics and snippet for a list of video IDs (batch 50)."""
        results: list[dict] = []

        for i in range(0, len(video_ids), 50):
            batch = video_ids[i : i + 50]
            try:
                response = (
                    self.youtube.videos()
                    .list(
                        id=",".join(batch),
                        part="snippet,statistics,contentDetails",
                    )
                    .execute()
                )
                for item in response.get("items", []):
                    results.append(self._parse_video_item(item))
            except HttpError as exc:
                print(f"[YouTubeService] Video details error (batch {i}): {exc}")

        return results

    def _parse_video_item(self, item: dict) -> dict:
        """Extract relevant fields from a raw video API item."""
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})

        return {
            "video_id": item.get("id", ""),
            "title": snippet.get("title", "").strip(),
            "description": snippet.get("description", "").strip(),
            "published_at": snippet.get("publishedAt", ""),
            "view_count": int(stats.get("viewCount", 0)),
            # YouTube hides like counts on some videos — default to 0
            "like_count": int(stats.get("likeCount", 0)),
            "comment_count": int(stats.get("commentCount", 0)),
            "duration_seconds": self._iso8601_duration_to_seconds(
                content.get("duration", "PT0S")
            ),
            "tags": snippet.get("tags", []),
        }

    @staticmethod
    def _iso8601_duration_to_seconds(duration: str) -> int:
        """
        Convert an ISO 8601 duration string (e.g. 'PT4M13S') to total seconds.

        Args:
            duration: ISO 8601 duration string from the YouTube API.

        Returns:
            Total duration in seconds (int).
        """
        pattern = re.compile(
            r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?",
            re.IGNORECASE,
        )
        match = pattern.fullmatch(duration)
        if not match:
            return 0
        days, hours, minutes, seconds = (int(g or 0) for g in match.groups())
        return days * 86_400 + hours * 3_600 + minutes * 60 + seconds
