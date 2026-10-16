import unittest

try:
    from fastapi.testclient import TestClient
    from hub.main import create_app
    from hub.store import MemoryStore
    HAVE_FASTAPI = True
except ImportError:
    HAVE_FASTAPI = False


@unittest.skipUnless(HAVE_FASTAPI, "fastapi/httpx not installed")
class HttpTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(create_app(MemoryStore()))

    def test_setup_overview_and_pages(self):
        self.assertEqual(self.client.get("/health").json(), {"status": "ok"})
        setup = self.client.get("/api/setup").json()
        self.assertTrue(setup["demo"])
        self.assertEqual(setup["storage"], "memory")
        self.assertEqual(self.client.get("/api/overview").json()["total"], 32)
        page = self.client.get("/api/complaints", params={"limit": 20, "offset": 0, "search": ""}).json()
        self.assertEqual((len(page["items"]), page["total"]), (20, 32))
        self.assertNotIn("author_hash", page["items"][0])

    def test_collect_dry_run_then_real_run(self):
        body = {"platform": "x", "resource": "search", "params": {"query": "q"}, "max_items": 100,
                "max_pages": 3, "dry_run": True}
        self.assertEqual(self.client.post("/collect", json=body).json()["max_calls"], 3)
        self.assertEqual(self.client.get("/api/overview").json()["x"], 16)
        body["dry_run"] = False
        run = self.client.post("/collect", json=body).json()
        self.assertEqual((run["inserted"], run["complete"]), (8, True))

    def test_demo_post_reply_and_errors(self):
        post = self.client.post("/api/demo/posts", json={"platform": "facebook", "text": "Hello"})
        self.assertEqual(post.status_code, 201)
        reply = self.client.post("/reply", json={"platform": "facebook", "reply_to": post.json()["external_id"],
                                                 "text": "Thanks"})
        self.assertTrue(reply.json()["demo"])
        missing = self.client.post("/reply", json={"platform": "x", "reply_to": "nope", "text": "Hi"})
        self.assertEqual(missing.status_code, 404)
        self.assertIsInstance(missing.json()["detail"], str)
        self.assertEqual(self.client.post("/api/ai/classify", json={"limit": 10}).status_code, 400)

    def test_cors_allows_frontend_origin(self):
        r = self.client.get("/health", headers={"Origin": "http://127.0.0.1:5173"})
        self.assertEqual(r.headers.get("access-control-allow-origin"), "http://127.0.0.1:5173")


if __name__ == "__main__":
    unittest.main()
