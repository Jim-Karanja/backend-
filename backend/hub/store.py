"""Thread-safe in-memory storage for complaints and collection runs."""
import threading
from datetime import datetime, timezone

HIDDEN_FIELDS = {"author_hash", "raw"}  # never sent to browsers, MCP clients or OpenAI


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_view(complaint: dict) -> dict:
    return {k: v for k, v in complaint.items() if k not in HIDDEN_FIELDS}


class MemoryStore:
    kind = "memory"

    def __init__(self):
        self._lock = threading.RLock()
        self._complaints: list = []
        self._runs: list = []
        self.seeded = False

    # ---- complaints -------------------------------------------------------------------------
    def add_complaint(self, data: dict) -> bool:
        """Insert unless (platform, external_id) already exists. Returns True when inserted."""
        with self._lock:
            if any(c["platform"] == data["platform"] and c["external_id"] == data["external_id"]
                   for c in self._complaints):
                return False
            row = {"parent_post_id": None, "lang": None, "raw": {}, "category": None, "urgency": None,
                   "draft_reply": None, "status": "new", "first_response_at": None, "ai_reason": None,
                   "ai_model": None, "ai_classified_at": None, "fetched_at": now_iso(), **data}
            row["id"] = len(self._complaints) + 1
            self._complaints.append(row)
            return True

    def _sorted(self, rows):
        return sorted(rows, key=lambda c: (c["created_at"], c["id"]))

    def list_complaints(self, platform=None, search="", limit=20, offset=0):
        needle = (search or "").strip().lower()
        with self._lock:
            rows = [c for c in self._complaints
                    if (not platform or c["platform"] == platform)
                    and (not needle or needle in c["text"].lower() or needle in c["external_id"].lower())]
            rows = self._sorted(rows)
            return [dict(c) for c in rows[offset:offset + limit]], len(rows)

    def get(self, platform, external_id):
        with self._lock:
            for c in self._complaints:
                if c["platform"] == platform and c["external_id"] == external_id:
                    return dict(c)
        return None

    def overview(self) -> dict:
        with self._lock:
            finished = [r["finished_at"] for r in self._runs if r.get("finished_at")]
            return {"total": len(self._complaints),
                    "new": sum(c["status"] == "new" for c in self._complaints),
                    "facebook": sum(c["platform"] == "facebook" for c in self._complaints),
                    "x": sum(c["platform"] == "x" for c in self._complaints),
                    "last_collection": max(finished) if finished else None}

    # ---- triage -----------------------------------------------------------------------------
    def unclassified(self, limit):
        with self._lock:
            rows = self._sorted([c for c in self._complaints if c["urgency"] is None])
            return [dict(c) for c in rows[:limit]]

    def count_unclassified(self) -> int:
        with self._lock:
            return sum(c["urgency"] is None for c in self._complaints)

    def save_classification(self, platform, external_id, expected_text, category, urgency, reason, model) -> bool:
        """Save only if the complaint still has the text that was sent to the classifier."""
        with self._lock:
            for c in self._complaints:
                if c["platform"] == platform and c["external_id"] == external_id:
                    if c["text"] != expected_text:
                        return False
                    c.update(category=category, urgency=urgency, ai_reason=reason, ai_model=model,
                             ai_classified_at=now_iso())
                    return True
        return False

    def mark_replied(self, platform, external_id, text) -> bool:
        with self._lock:
            for c in self._complaints:
                if c["platform"] == platform and c["external_id"] == external_id:
                    c["draft_reply"] = text
                    c["status"] = "replied"
                    c["first_response_at"] = c["first_response_at"] or now_iso()
                    return True
        return False

    # ---- collection runs --------------------------------------------------------------------
    def add_run(self, run: dict) -> dict:
        with self._lock:
            row = {**run, "id": len(self._runs) + 1}
            self._runs.append(row)
            return dict(row)

    def list_runs(self, limit=20, offset=0):
        with self._lock:
            rows = sorted(self._runs, key=lambda r: (r["started_at"], r["id"]), reverse=True)
            return [dict(r) for r in rows[offset:offset + limit]], len(rows)
