import unittest
from datetime import datetime, timezone

from integrations.briefing_engine import build_briefing


class BriefingEngineTests(unittest.TestCase):
    def test_prioritizes_urgent_and_truncates(self):
        result = build_briefing([
            {"source": "gmail", "title": "normal"},
            {"source": "calendar", "title": "urgent", "priority": "urgent"},
            {"source": "github", "title": "high", "priority": "high"},
        ], max_items=2, now=datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual([x["title"] for x in result["items"]], ["urgent", "high"])
        self.assertEqual(result["omitted_items"], 1)
        self.assertTrue(result["requires_approval_to_send"])

    def test_rejects_unknown_source_and_blank_title(self):
        result = build_briefing([
            {"source": "unknown", "title": "not allowed"},
            {"source": "drive", "title": "   "},
        ])
        self.assertEqual(result["total_items"], 0)
        self.assertIn("No items were supplied", result["text"])

    def test_cleans_control_characters_and_caps_fields(self):
        result = build_briefing([{
            "source": "gmail", "title": "A\nB\x00C", "detail": "x" * 1000,
            "url": "javascript:alert(1)",
        }])
        item = result["items"][0]
        self.assertEqual(item["title"], "A B C")
        self.assertEqual(len(item["detail"]), 360)
        self.assertIsNone(item["url"])

    def test_clamps_item_limit(self):
        items = [{"source": "system", "title": f"item {i}"} for i in range(40)]
        result = build_briefing(items, max_items=1000)
        self.assertEqual(result["included_items"], 30)
        self.assertEqual(result["omitted_items"], 10)

    def test_uses_utc_for_naive_timestamp(self):
        result = build_briefing([], now=datetime(2026, 2, 3, 4, 5))
        self.assertTrue(result["generated_at"].endswith("+00:00"))


if __name__ == "__main__":
    unittest.main()
