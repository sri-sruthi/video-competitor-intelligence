from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from test import classify_match


class SmokeLabelTests(unittest.TestCase):
    def test_exact_match_label(self) -> None:
        self.assertEqual(classify_match("HubSpot", "HubSpot"), "exact")

    def test_parent_brand_label(self) -> None:
        self.assertEqual(
            classify_match("Mailchimp", "Intuit Mailchimp"),
            "parent-brand",
        )

    def test_brand_prefix_label(self) -> None:
        self.assertEqual(
            classify_match("Mailchimp", "Mailchimp Studio"),
            "brand-prefix",
        )

    def test_contains_brand_label(self) -> None:
        self.assertEqual(
            classify_match("HubSpot", "The HubSpot Podcast Network"),
            "contains-brand",
        )

    def test_weak_label(self) -> None:
        self.assertEqual(classify_match("HubSpot", "Inbound Leaders"), "weak")


if __name__ == "__main__":
    unittest.main()
