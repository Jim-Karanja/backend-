"""PostgreSQL storage for complaints and collection runs (schema.sql). Used when DATABASE_URL is set."""
import re
from datetime import datetime
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .store import now_iso

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"
SEED_NAME = "default"  # row in demo_seeds marks that demo.seed() has run


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value


def _complaint(row):
    if row is None:
        return None
    out = dict(row)
    for key in ("created_at", "fetched_at", "first_response_at", "ai_classified_at"):
        out[key] = _iso(out[key])
    return out


def _run(row):
    out = dict(row)
    out["started_at"] = _iso(out["started_at"])
    out["finished_at"] = _iso(out["finished_at"])
    return out


def _like(needle):
    return "%" + needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def redact(url):
    return re.sub(r"://[^@/]+@", "://***@", url)


class PostgresStore:
    kind = "postgresql"

    def __init__(self, database_url):
        self._url = database_url
        self.apply_schema()

    def _connect(self):
        return psycopg.connect(self._url, row_factory=dict_row, autocommit=True)

    def apply_schema(self):
        sql = SCHEMA_PATH.read_text(encoding="utf-8")
        with self._connect() as conn:
            conn.execute(sql)

    # ---- demo seeding marker ---------------------------------------------------------------
    @property
    def seeded(self):
        with self._connect() as conn:
            return conn.execute("SELECT 1 FROM demo_seeds WHERE name = %(name)s",
                                {"name": SEED_NAME}).fetchone() is not None

    @seeded.setter
    def seeded(self, value):
        with self._connect() as conn:
            if value:
                conn.execute("INSERT INTO demo_seeds (name) VALUES (%(name)s) ON CONFLICT DO NOTHING",
                             {"name": SEED_NAME})
            else:
                conn.execute("DELETE FROM demo_seeds WHERE name = %(name)s", {"name": SEED_NAME})

    # ---- complaints -------------------------------------------------------------------------
    def add_complaint(self, data):
        """Insert unless (platform, external_id) already exists. Returns True when inserted."""
        row = {"parent_post_id": None, "lang": None, "raw": {}, "category": None, "urgency": None,
               "draft_reply": None, "status": "new", "first_response_at": None, "ai_reason": None,
               "ai_model": None, "ai_classified_at": None, "fetched_at": now_iso(), **data}
        row["raw"] = Jsonb(row["raw"])
        with self._connect() as conn:
            cur = conn.execute(
                """INSERT INTO complaints (platform, external_id, parent_post_id, post_url, author_hash,
                                           text, lang, created_at, fetched_at, raw, category, urgency,
                                           draft_reply, status, first_response_at, ai_reason, ai_model,
                                           ai_classified_at)
                   VALUES (%(platform)s, %(external_id)s, %(parent_post_id)s, %(post_url)s, %(author_hash)s,
                           %(text)s, %(lang)s, %(created_at)s, %(fetched_at)s, %(raw)s, %(category)s,
                           %(urgency)s, %(draft_reply)s, %(status)s, %(first_response_at)s, %(ai_reason)s,
                           %(ai_model)s, %(ai_classified_at)s)
                   ON CONFLICT (platform, external_id) DO NOTHING""", row)
            return cur.rowcount > 0

    def list_complaints(self, platform=None, search="", limit=20, offset=0):
        conditions, args = [], {}
        if platform:
            conditions.append("platform = %(platform)s")
            args["platform"] = platform
        needle = (search or "").strip()
        if needle:
            conditions.append("(text ILIKE %(needle)s OR external_id ILIKE %(needle)s)")
            args["needle"] = _like(needle)
        base = " FROM complaints" + (" WHERE " + " AND ".join(conditions) if conditions else "")
        with self._connect() as conn:
            total = conn.execute("SELECT count(*) AS n" + base, args).fetchone()["n"]
            rows = conn.execute("SELECT *" + base + " ORDER BY created_at, id LIMIT %(limit)s OFFSET %(offset)s",
                                {**args, "limit": limit, "offset": offset}).fetchall()
        return [_complaint(r) for r in rows], total

    def get(self, platform, external_id):
        with self._connect() as conn:
            return _complaint(conn.execute("SELECT * FROM complaints WHERE platform = %s AND external_id = %s",
                                           (platform, external_id)).fetchone())

    def overview(self):
        with self._connect() as conn:
            counts = conn.execute(
                """SELECT count(*) AS total,
                          count(*) FILTER (WHERE status = 'new') AS "new",
                          count(*) FILTER (WHERE platform = 'facebook') AS facebook,
                          count(*) FILTER (WHERE platform = 'x') AS x
                   FROM complaints""").fetchone()
            last = conn.execute("SELECT max(finished_at) AS last FROM collection_runs"
                                " WHERE finished_at IS NOT NULL").fetchone()["last"]
        return {**counts, "last_collection": _iso(last)}

    # ---- triage -----------------------------------------------------------------------------
    def unclassified(self, limit):
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM complaints WHERE urgency IS NULL"
                                " ORDER BY created_at, id LIMIT %s", (limit,)).fetchall()
        return [_complaint(r) for r in rows]

    def count_unclassified(self):
        with self._connect() as conn:
            return conn.execute("SELECT count(*) AS n FROM complaints WHERE urgency IS NULL").fetchone()["n"]

    def save_classification(self, platform, external_id, expected_text, category, urgency, reason, model):
        """Save only if the complaint still has the text that was sent to the classifier."""
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE complaints
                   SET category = %s, urgency = %s, ai_reason = %s, ai_model = %s, ai_classified_at = %s
                   WHERE platform = %s AND external_id = %s AND text = %s""",
                (category, urgency, reason, model, now_iso(), platform, external_id, expected_text))
            return cur.rowcount > 0

    def mark_replied(self, platform, external_id, text):
        with self._connect() as conn:
            cur = conn.execute(
                """UPDATE complaints
                   SET draft_reply = %s, status = 'replied',
                       first_response_at = COALESCE(first_response_at, %s)
                   WHERE platform = %s AND external_id = %s""",
                (text, now_iso(), platform, external_id))
            return cur.rowcount > 0

    # ---- collection runs --------------------------------------------------------------------
    def add_run(self, run):
        row = {"finished_at": None, "fetched": 0, "inserted": 0, "pages": 0, "stop_reason": None,
               "next_cursor": None, "complete": False, **run}
        row["params"] = Jsonb(row["params"])
        with self._connect() as conn:
            stored = conn.execute(
                """INSERT INTO collection_runs (platform, resource, params, started_at, finished_at,
                                                fetched, inserted, pages, stop_reason, next_cursor, complete)
                   VALUES (%(platform)s, %(resource)s, %(params)s, %(started_at)s, %(finished_at)s,
                           %(fetched)s, %(inserted)s, %(pages)s, %(stop_reason)s, %(next_cursor)s,
                           %(complete)s)
                   RETURNING *""", row).fetchone()
        return _run(stored)

    def list_runs(self, limit=20, offset=0):
        with self._connect() as conn:
            total = conn.execute("SELECT count(*) AS n FROM collection_runs").fetchone()["n"]
            rows = conn.execute("SELECT * FROM collection_runs ORDER BY started_at DESC, id DESC"
                                " LIMIT %s OFFSET %s", (limit, offset)).fetchall()
        return [_run(r) for r in rows], total


def open_store(database_url):
    """Apply schema.sql and return a PostgresStore, or raise with a readable error."""
    try:
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
    except psycopg.OperationalError as exc:
        raise RuntimeError(f"Cannot connect to PostgreSQL ({redact(database_url)}): {exc}"
                           "\nCheck DATABASE_URL in backend/.env and that the server is running."
                           "\nSet DATABASE_URL empty to fall back to in-memory storage.") from exc
    return PostgresStore(database_url)
