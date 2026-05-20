from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.youtube_service import YouTubeService


class YouTubeServiceChannelScoringTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = object.__new__(YouTubeService)

    @staticmethod
    def _peer_context(*, max_subscribers: int, max_videos: int, max_views: int = 0) -> dict:
        return {
            "max_subscribers": max_subscribers,
            "max_videos": max_videos,
            "max_views": max_views,
        }

    def test_exact_brand_title_beats_topic_subchannel(self) -> None:
        company_name = "HubSpot"
        main_channel = {
            "snippet": {
                "title": "HubSpot",
                "description": "The official HubSpot YouTube channel.",
            }
        }
        subchannel = {
            "snippet": {
                "title": "HubSpot Marketing",
                "description": "Official marketing videos from HubSpot.",
            }
        }

        main_score = self.service._score_channel_candidate(
            company_name,
            main_channel,
            {"subscriberCount": "300000"},
        )
        subchannel_score = self.service._score_channel_candidate(
            company_name,
            subchannel,
            {"subscriberCount": "600000"},
        )

        self.assertGreater(main_score, subchannel_score)

    def test_brand_words_inside_longer_unrelated_title_rank_lower(self) -> None:
        company_name = "Notion"
        brand_channel = {
            "snippet": {
                "title": "Notion",
                "description": "Official videos from Notion.",
            }
        }
        unrelated_channel = {
            "snippet": {
                "title": "Notion Training School",
                "description": "Community training and walkthroughs.",
            }
        }

        brand_score = self.service._score_channel_candidate(
            company_name,
            brand_channel,
            {"subscriberCount": "150000"},
        )
        unrelated_score = self.service._score_channel_candidate(
            company_name,
            unrelated_channel,
            {"subscriberCount": "500000"},
        )

        self.assertGreater(brand_score, unrelated_score)

    def test_tiny_exact_semrush_channel_loses_to_large_official_variant(self) -> None:
        company_name = "Semrush"
        tiny_exact_channel = {
            "snippet": {
                "title": "Semrush",
                "description": "Welcome to the official Semrush Youtube channel.",
            },
            "statistics": {
                "subscriberCount": "11",
                "videoCount": "13",
                "viewCount": "632",
            },
        }
        large_official_channel = {
            "snippet": {
                "title": "SEMrush",
                "description": "Official Semrush tutorials, webinars, and product videos.",
                "customUrl": "semrush",
            },
            "statistics": {
                "subscriberCount": "207000",
                "videoCount": "403",
                "viewCount": "11103082",
            },
        }
        peer_context = self._peer_context(
            max_subscribers=207000,
            max_videos=403,
            max_views=11103082,
        )

        tiny_score = self.service._score_channel_candidate(
            company_name,
            tiny_exact_channel,
            peer_context=peer_context,
        )
        large_score = self.service._score_channel_candidate(
            company_name,
            large_official_channel,
            peer_context=peer_context,
        )

        self.assertGreater(large_score, tiny_score)

    def test_parent_brand_mailchimp_channel_beats_tiny_exact_clone(self) -> None:
        company_name = "Mailchimp"
        tiny_exact_channel = {
            "snippet": {
                "title": "MailChimp",
                "description": "",
            },
            "statistics": {
                "subscriberCount": "2",
                "videoCount": "4",
                "viewCount": "101",
            },
        }
        parent_brand_channel = {
            "snippet": {
                "title": "Intuit Mailchimp",
                "description": "Official Mailchimp videos, product updates, and inspiration.",
                "customUrl": "Mailchimp",
            },
            "statistics": {
                "subscriberCount": "80000",
                "videoCount": "500",
                "viewCount": "25000000",
            },
        }
        peer_context = self._peer_context(
            max_subscribers=80000,
            max_videos=500,
            max_views=25000000,
        )

        tiny_score = self.service._score_channel_candidate(
            company_name,
            tiny_exact_channel,
            peer_context=peer_context,
        )
        parent_score = self.service._score_channel_candidate(
            company_name,
            parent_brand_channel,
            peer_context=peer_context,
        )

        self.assertGreater(parent_score, tiny_score)

    def test_generic_variants_handle_dot_com_names_without_exploding_queries(self) -> None:
        queries = self.service._build_search_queries("monday.com")

        self.assertIn("monday.com", queries)
        self.assertIn("monday.com official", queries)
        self.assertLessEqual(len(queries), 3)

    def test_generic_variants_strip_punctuation_for_arbitrary_names(self) -> None:
        queries = self.service._build_search_queries("Acme, Inc.")

        self.assertIn("Acme, Inc.", queries)
        self.assertIn("Acme, Inc. official", queries)
        self.assertIn("Acme Inc", queries)

    def test_parent_brand_alias_queries_can_add_official_suffix(self) -> None:
        queries = self.service._build_search_queries("Mailchimp")

        self.assertIn("Mailchimp", queries)
        self.assertIn("Mailchimp official", queries)
        self.assertIn("Intuit Mailchimp", queries)

    def test_repeated_brand_title_is_penalized_against_parent_brand(self) -> None:
        company_name = "Mailchimp"
        repeated_brand_channel = {
            "snippet": {
                "title": "MailChimp MailChimp",
                "description": "",
            },
            "statistics": {
                "subscriberCount": "35",
                "videoCount": "44",
                "viewCount": "11688",
            },
        }
        parent_brand_channel = {
            "snippet": {
                "title": "Intuit Mailchimp",
                "description": "Official Mailchimp videos, product updates, and inspiration.",
                "customUrl": "Mailchimp",
            },
            "statistics": {
                "subscriberCount": "80000",
                "videoCount": "500",
                "viewCount": "25000000",
            },
        }
        peer_context = self._peer_context(
            max_subscribers=80000,
            max_videos=500,
            max_views=25000000,
        )

        repeated_score = self.service._score_channel_candidate(
            company_name,
            repeated_brand_channel,
            peer_context=peer_context,
        )
        parent_score = self.service._score_channel_candidate(
            company_name,
            parent_brand_channel,
            peer_context=peer_context,
        )

        self.assertGreater(parent_score, repeated_score)

    def test_creator_style_loom_channel_loses_to_company_channel(self) -> None:
        company_name = "Loom"
        creator_channel = {
            "snippet": {
                "title": "Loom",
                "description": (
                    "I make content on virtual cardboard. Master Duel + Duel Links "
                    "Decks, Guides, Streams, Memes + More. Just subscribe already please :)"
                ),
            },
            "statistics": {
                "subscriberCount": "112000",
                "videoCount": "1612",
                "viewCount": "39443871",
            },
        }
        company_channel = {
            "snippet": {
                "title": "Atlassian Loom",
                "description": (
                    "Loom is an AI-powered video messaging platform for work. "
                    "Record your screen, share with your team, and move work forward."
                ),
                "customUrl": "loom",
            },
            "statistics": {
                "subscriberCount": "55000",
                "videoCount": "420",
                "viewCount": "8200000",
            },
        }
        peer_context = self._peer_context(
            max_subscribers=112000,
            max_videos=1612,
            max_views=39443871,
        )

        creator_score = self.service._score_channel_candidate(
            company_name,
            creator_channel,
            peer_context=peer_context,
        )
        company_score = self.service._score_channel_candidate(
            company_name,
            company_channel,
            peer_context=peer_context,
        )

        self.assertGreater(company_score, creator_score)

    def test_loom_queries_include_parent_brand_alias(self) -> None:
        queries = self.service._build_search_queries("Loom")

        self.assertIn("Loom", queries)
        self.assertIn("Loom official", queries)
        self.assertIn("Atlassian Loom", queries)


if __name__ == "__main__":
    unittest.main()
