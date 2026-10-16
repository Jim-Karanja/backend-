import json
import unittest
from types import SimpleNamespace

from hub import ai, demo
from hub.errors import HubError
from hub.store import MemoryStore, public_view


def settings(key="k"):
    return SimpleNamespace(openai_api_key=key, openai_model="test-model")


class DemoAndStoreTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        demo.seed(self.store)

    def test_seed_counts_and_idempotence(self):
        demo.seed(self.store)
        o = self.store.overview()
        self.assertEqual((o["total"], o["new"], o["facebook"], o["x"]), (32, 32, 16, 16))
        self.assertEqual(self.store.list_runs()[1], 2)

    def test_oldest_first_and_pagination(self):
        items, total = self.store.list_complaints(limit=20, offset=0)
        self.assertEqual((len(items), total), (20, 32))
        self.assertEqual(sorted(c["created_at"] for c in items), [c["created_at"] for c in items])
        self.assertEqual(len(self.store.list_complaints(limit=20, offset=20)[0]), 12)

    def test_search_and_platform_filter(self):
        items, total = self.store.list_complaints(search="home fibre")
        self.assertEqual(total, 4)
        self.assertEqual(self.store.list_complaints(platform="x")[1], 16)

    def test_public_view_hides_author_hash(self):
        c = self.store.list_complaints(limit=1)[0][0]
        self.assertNotIn("author_hash", public_view(c))
        self.assertNotIn("raw", public_view(c))

    def test_resume_adds_remaining_eight_then_detects_duplicates(self):
        params = {"query": "Safaricom M-Pesa"}
        run = demo.collect(self.store, "x", "search", params, 100, 3, cursor="16")
        self.assertEqual((run["fetched"], run["inserted"], run["complete"]), (8, 8, True))
        again = demo.collect(self.store, "x", "search", params, 100, 3)
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(self.store.overview()["x"], 24)

    def test_collect_limits_pause_run_with_cursor(self):
        run = demo.collect(self.store, "facebook", "posts", {"page_id": "p"}, 100, 1)
        self.assertFalse(run["complete"])
        self.assertEqual((run["pages"], run["next_cursor"], run["stop_reason"]), (1, "10", "max_pages"))

    def test_collect_validation(self):
        with self.assertRaises(HubError):
            demo.validate_collect("x", "comments", {"post_id": "1"}, None)
        with self.assertRaises(HubError):
            demo.validate_collect("x", "search", {"query": "  "}, None)
        with self.assertRaises(HubError):
            demo.validate_collect("x", "search", {"query": "a"}, "abc")

    def test_manual_post_and_reply(self):
        post = demo.add_manual_post(self.store, "x", "A new presentation post")
        self.assertEqual(post["status"], "new")
        self.assertTrue(self.store.mark_replied("x", post["external_id"], "Thanks"))
        self.assertEqual(self.store.get("x", post["external_id"])["status"], "replied")
        self.assertFalse(self.store.mark_replied("x", "missing", "Thanks"))


class ClassificationTests(unittest.TestCase):
    def setUp(self):
        self.store = MemoryStore()
        demo.seed(self.store)

    def fake(self, urgency=4, drop=None):
        def caller(key, payload):
            rows = json.loads(payload["input"][1]["content"])
            self.assertTrue(payload["store"] is False)
            self.assertNotIn("author_hash", json.dumps(payload))
            results = [{"ref": r["ref"], "category": "M-Pesa account & app", "urgency": urgency, "reason": "x"}
                       for r in rows if r["ref"] != drop]
            return {"output": [{"content": [{"type": "output_text", "text": json.dumps({"results": results})}]}]}
        return caller

    def test_batch_classifies_oldest_and_reports_remaining(self):
        result = ai.classify_batch(self.store, settings(), 10, self.fake())
        self.assertEqual(result, {"classified": 10, "skipped_changed": 0, "has_more": True})
        self.assertEqual(self.store.count_unclassified(), 22)

    def test_single_reclassify(self):
        c = self.store.list_complaints(limit=1)[0][0]
        ai.classify_one(self.store, settings(), c["platform"], c["external_id"], self.fake(2))
        self.assertEqual(self.store.get(c["platform"], c["external_id"])["urgency"], 2)

    def test_incomplete_response_saves_nothing(self):
        with self.assertRaises(HubError):
            ai.classify_batch(self.store, settings(), 3, self.fake(drop="c2"))
        self.assertEqual(self.store.count_unclassified(), 32)

    def test_invalid_urgency_rejected(self):
        with self.assertRaises(HubError):
            ai.classify_batch(self.store, settings(), 2, self.fake(urgency=9))
        self.assertEqual(self.store.count_unclassified(), 32)

    def test_missing_key(self):
        with self.assertRaises(HubError) as ctx:
            ai.classify_batch(self.store, settings(key=""), 10, self.fake())
        self.assertEqual(ctx.exception.status, 400)

    def test_complaint_changed_midway_is_skipped(self):
        first = self.store.unclassified(1)[0]
        def caller(key, payload):
            self.store._complaints[first["id"] - 1]["text"] = "edited meanwhile"
            return self.fake()(key, payload)
        result = ai.classify_batch(self.store, settings(), 2, caller)
        self.assertEqual((result["classified"], result["skipped_changed"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
