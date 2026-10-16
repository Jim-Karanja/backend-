"""Integration tests for the PostgreSQL store. Skipped unless TEST_DATABASE_URL is set, e.g.:
   set TEST_DATABASE_URL=postgresql://postgres:password@localhost:5432/complaints_test"""
import os
import unittest

import psycopg

from hub import demo
from hub.db import PostgresStore, open_store
from hub.store import public_view

TEST_URL = os.environ.get("TEST_DATABASE_URL", "")


@unittest.skipUnless(TEST_URL, "set TEST_DATABASE_URL to run PostgreSQL store tests")
class PostgresStoreTests(unittest.TestCase):
    def setUp(self):
        with psycopg.connect(TEST_URL, autocommit=True) as conn:
            conn.execute("DROP TABLE IF EXISTS complaints, collection_runs, demo_seeds CASCADE")
        self.store = open_store(TEST_URL)
        demo.seed(self.store)

    def test_schema_seeded_flag_and_idempotent_seed(self):
        self.assertTrue(self.store.seeded)
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
        self.assertEqual(self.store.list_complaints(search="home fibre")[1], 4)
        self.assertEqual(self.store.list_complaints(platform="x")[1], 16)

    def test_public_view_hides_author_hash(self):
        c = self.store.list_complaints(limit=1)[0][0]
        self.assertNotIn("author_hash", public_view(c))
        self.assertNotIn("raw", public_view(c))
        self.assertIn("author_hash", c)  # present internally, hidden only in public_view

    def test_get_and_missing(self):
        c = self.store.list_complaints(limit=1)[0][0]
        fetched = self.store.get(c["platform"], c["external_id"])
        self.assertEqual(fetched["text"], c["text"])
        self.assertIsNone(self.store.get("x", "does-not-exist"))

    def test_collect_resume_and_duplicate_detection(self):
        params = {"query": "Safaricom M-Pesa"}
        run = demo.collect(self.store, "x", "search", params, 100, 3, cursor="16")
        self.assertEqual((run["fetched"], run["inserted"], run["complete"]), (8, 8, True))
        again = demo.collect(self.store, "x", "search", params, 100, 3)
        self.assertEqual(again["inserted"], 0)
        self.assertEqual(self.store.overview()["x"], 24)

    def test_classification_requires_same_text(self):
        c = self.store.unclassified(1)[0]
        self.assertTrue(self.store.save_classification(
            c["platform"], c["external_id"], c["text"], "M-Pesa reversals & disputes", 4, "reason", "model-x"))
        saved = self.store.get(c["platform"], c["external_id"])
        self.assertEqual((saved["category"], saved["urgency"], saved["ai_model"]),
                         ("M-Pesa reversals & disputes", 4, "model-x"))
        self.assertIsNotNone(saved["ai_classified_at"])
        self.assertFalse(self.store.save_classification(
            c["platform"], c["external_id"], "edited text", "Other", 1, "r", "m"))
        self.assertEqual(self.store.count_unclassified(), 31)

    def test_mark_replied(self):
        post = demo.add_manual_post(self.store, "x", "A presentation post")
        self.assertTrue(self.store.mark_replied("x", post["external_id"], "Thanks"))
        saved = self.store.get("x", post["external_id"])
        self.assertEqual(saved["status"], "replied")
        self.assertIsNotNone(saved["first_response_at"])
        self.assertFalse(self.store.mark_replied("x", "missing", "Thanks"))

    def test_overview_last_collection_and_runs_listing(self):
        o = self.store.overview()
        self.assertIsNotNone(o["last_collection"])
        runs, total = self.store.list_runs()
        self.assertEqual(total, 2)
        self.assertGreaterEqual(runs[0]["started_at"], runs[1]["started_at"])

    def test_data_survives_new_store_instance(self):
        demo.add_manual_post(self.store, "facebook", "Persistence check")
        reopened = PostgresStore(TEST_URL)
        self.assertTrue(reopened.seeded)  # no reseed needed
        self.assertEqual(reopened.overview()["total"], 33)
        items, total = reopened.list_complaints(search="Persistence check")
        self.assertEqual(total, 1)


if __name__ == "__main__":
    unittest.main()
