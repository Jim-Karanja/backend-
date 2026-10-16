"""Fictional Safaricom PLC / M-Pesa demo data and the simulated collector."""
import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from .errors import HubError
from .store import now_iso

RESOURCES = {  # platform -> resource -> name of the required param
    "x": {"search": "query", "mentions": "user_id"},
    "facebook": {"comments": "post_id", "posts": "page_id"},
}
TOKENS = {"facebook": "f7bd8a11", "x": "417c9233"}
PLATFORM_OFFSET_MIN = {"x": 0, "facebook": 15}
SEEDED_CASES = 16  # cases 1-16 are seeded on both platforms (32 posts); 17-24 arrive via collection

CASES = [
    "My Safaricom voice calls keep dropping after a few seconds in Kisumu. Please check the network.",
    "I bought a daily data bundle but it was not credited. Please help me recover the data.",
    "A Paybill payment I made through M-Pesa has not reached the biller. Please trace it.",
    "I sent M-Pesa to a wrong number by mistake. Please help me request a reversal.",
    "My Safaricom Home Fibre router has no internet light since morning. Please send a technician.",
    "My M-Pesa reversal request is still pending. Could support update me on the refund status?",
    "My replacement Safaricom SIM has not activated, and I cannot receive calls or verification messages.",
    "An M-Pesa Buy Goods payment to a till appears twice in my statement. Please investigate the duplicate debit.",
    "Safaricom mobile data is very slow in Nakuru today. Pages keep timing out despite having an active bundle.",
    "An M-Pesa agent withdrawal reduced my balance, but the transaction failed before cash was issued.",
    "My Safaricom airtime balance reduced unexpectedly. Please explain the charges and help stop any unwanted subscription.",
    "The M-Pesa app keeps showing a connection error when I try to view my transaction history.",
    "My Safaricom Home Fibre payment went through, but the connection still shows as suspended.",
    "The M-Pesa transaction charge shown in my receipt differs from what I expected. Please clarify the charge.",
    "I cannot send SMS from my Safaricom line even though I have airtime. Incoming messages work normally.",
    "My M-Pesa account is locked after a PIN issue. I need help with the official account recovery process.",
    "My Okoa Jahazi airtime advance was deducted twice from my next top-up. Please correct it.",
    "I received an M-Pesa confirmation message but the money is not in my account.",
    "The Safaricom 4G signal in my estate disappears every evening. Is any maintenance planned?",
    "My Fuliza limit changed without notice. Please explain how limits are reviewed.",
    "An M-Pesa till number I paid shows a different business name. Please confirm it is genuine.",
    "My Home Fibre speed is much lower than my package. Please run a line check.",
    "I changed phones and my M-Pesa app will not register. I keep getting an error after entering my ID.",
    "A suspicious SMS claiming to be from M-Pesa asked for my PIN. How do I report it?",
]


def _author_hash(salt, platform, n):
    return hashlib.sha256(f"{salt or 'demo-salt'}:{platform}:demo-user-{n}".encode()).hexdigest()[:24]


def make_case(platform, n, created_at, salt=""):
    external_id = f"demo-{platform}-{TOKENS[platform]}-{n:02d}"
    return {
        "platform": platform,
        "external_id": external_id,
        "post_url": f"https://example.com/demo/{platform}/{external_id}",
        "author_hash": _author_hash(salt, platform, n),
        "text": f"{CASES[n - 1]} [Fictional demo case SF-{1000 + n}]",
        "lang": "en",
        "created_at": created_at.isoformat(),
        "raw": {"demo": True},
    }


def _created(platform, n, now):
    return now - timedelta(hours=40) + timedelta(minutes=55 * n + PLATFORM_OFFSET_MIN[platform])


def seed(store, salt="", now=None):
    """Seed 32 fictional complaints and two paused collection runs, once."""
    if store.seeded:
        return
    now = now or datetime.now(timezone.utc)
    for n in range(1, SEEDED_CASES + 1):
        for platform in ("x", "facebook"):
            store.add_complaint(make_case(platform, n, _created(platform, n, now), salt))
    stamp = now.isoformat()
    for platform, resource, params in (("x", "search", {"query": "Safaricom M-Pesa"}),
                                       ("facebook", "comments", {"post_id": "demo-page_demo-post"})):
        store.add_run({"platform": platform, "resource": resource, "params": params, "started_at": stamp,
                       "finished_at": stamp, "fetched": SEEDED_CASES, "inserted": SEEDED_CASES, "pages": 2,
                       "stop_reason": "max_pages", "next_cursor": str(SEEDED_CASES), "complete": False})
    store.seeded = True


def add_manual_post(store, platform, text, salt=""):
    created = datetime.now(timezone.utc)
    external_id = f"demo-manual-{uuid.uuid4().hex[:24]}"
    store.add_complaint({
        "platform": platform, "external_id": external_id,
        "post_url": f"https://example.com/demo/{platform}/{external_id}",
        "author_hash": _author_hash(salt, platform, external_id), "text": text, "lang": "en",
        "created_at": created.isoformat(), "raw": {"demo": True, "manual": True}})
    return store.get(platform, external_id)


def validate_collect(platform, resource, params, cursor):
    if platform not in RESOURCES or resource not in RESOURCES[platform]:
        raise HubError(400, "Choose a valid channel and collection source.")
    key = RESOURCES[platform][resource]
    value = (params or {}).get(key)
    if not isinstance(value, str) or not value.strip():
        raise HubError(400, f"Enter a value for {key}.")
    start = 0
    if cursor not in (None, ""):
        if not str(cursor).isdigit() or int(cursor) > len(CASES):
            raise HubError(400, "The resume cursor is not valid for this source.")
        start = int(cursor)
    return start


def collect(store, platform, resource, params, max_items, max_pages, cursor=None, salt="", page_size=10):
    """Simulated collection: walks the 24 fictional cases, inserting only unseen ones."""
    index = validate_collect(platform, resource, params, cursor)
    started = now_iso()
    now = datetime.now(timezone.utc)
    fetched = inserted = pages = 0
    reason = "complete"
    while index < len(CASES):
        if fetched >= max_items:
            reason = "max_items"
            break
        if pages >= max_pages:
            reason = "max_pages"
            break
        take = min(page_size, max_items - fetched, len(CASES) - index)
        for n in range(index + 1, index + take + 1):
            inserted += store.add_complaint(make_case(platform, n, _created(platform, n, now), salt))
        fetched += take
        index += take
        pages += 1
    complete = index >= len(CASES)
    run = {"platform": platform, "resource": resource, "params": params, "started_at": started,
           "finished_at": now_iso(), "fetched": fetched, "inserted": inserted, "pages": pages,
           "stop_reason": "complete" if complete else reason,
           "next_cursor": None if complete else str(index), "complete": complete}
    return store.add_run(run)
