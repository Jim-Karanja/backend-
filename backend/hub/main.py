"""FastAPI application: REST API for the dashboard plus an MCP endpoint at /mcp/."""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any, Literal, Optional

from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

from . import ai, demo
from .config import get_settings, load_env
from .errors import HubError
from .store import MemoryStore, public_view

log = logging.getLogger("hub")
Platform = Literal["facebook", "x"]


class DemoPost(BaseModel):
    platform: Platform
    text: str = Field(min_length=1, max_length=5000)

    @field_validator("text")
    @classmethod
    def not_blank(cls, v):
        if not v.strip():
            raise ValueError("text must not be blank")
        return v.strip()


class CollectRequest(BaseModel):
    platform: Platform
    resource: str
    params: dict[str, Any] = {}
    max_items: int = Field(100, ge=0, le=10000)
    max_pages: int = Field(3, ge=1, le=100)
    dry_run: bool = False
    cursor: Optional[str] = None


class ReplyRequest(BaseModel):
    platform: Platform
    reply_to: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=5000)


class ClassifyRequest(BaseModel):
    limit: Optional[int] = Field(None, ge=1, le=25)
    platform: Optional[Platform] = None
    external_id: Optional[str] = None


def default_store():
    """DATABASE_URL set -> PostgreSQL (schema applied at startup); otherwise in-memory."""
    settings = get_settings()
    if settings.database_url:
        from .db import open_store
        return open_store(settings.database_url)
    return MemoryStore()


def create_app(store=None) -> FastAPI:
    load_env()
    store = store or default_store()
    if get_settings().demo_mode:
        demo.seed(store, get_settings().author_salt)

    mcp = mcp_app = None
    try:
        from .mcp_server import build_mcp
        mcp = build_mcp(store)
        mcp_app = mcp.streamable_http_app()
    except Exception as exc:  # the REST API still works without MCP
        log.warning("MCP endpoint disabled: %s", exc)
        mcp = None

    @asynccontextmanager
    async def lifespan(_app):
        settings = get_settings()
        auto_task = None
        if settings.auto_classify and settings.openai_api_key:
            from .scheduler import auto_classify_loop
            auto_task = asyncio.create_task(auto_classify_loop(store, settings))
            log.info("Auto-classification enabled every %ss (batch %s)",
                     settings.auto_classify_interval, settings.auto_classify_batch)
        try:
            if mcp is not None:
                async with mcp.session_manager.run():
                    yield
            else:
                yield
        finally:
            if auto_task is not None:
                auto_task.cancel()
                with suppress(asyncio.CancelledError):
                    await auto_task

    app = FastAPI(title="Complaints Hub API", lifespan=lifespan)
    app.state.store = store
    app.add_middleware(CORSMiddleware, allow_origins=list(get_settings().frontend_origins),
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(HubError)
    async def hub_error(_request, exc: HubError):
        return JSONResponse({"detail": exc.message}, status_code=exc.status)

    @app.get("/")
    def root():
        return {"name": "Complaints Hub API", "docs": "/docs", "health": "/health", "mcp": "/mcp/"}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/setup")
    def setup():
        s = get_settings()
        return {"demo": s.demo_mode, "storage": store.kind,
                "ai": {"configured": bool(s.openai_api_key), "model": s.openai_model,
                       "base_url": s.openai_base_url, "api": s.openai_api_style,
                       "auto_classify": {"enabled": s.auto_classify,
                                         "interval_seconds": s.auto_classify_interval,
                                         "batch": s.auto_classify_batch}},
                "mcp": {"path": "/mcp/", "enabled": mcp is not None},
                "platforms": {"facebook": {"read": bool(s.fb_page_token), "reply": bool(s.fb_page_token)},
                              "x": {"read": bool(s.x_bearer_token), "reply": bool(s.x_user_token)}},
                "author_salt_configured": bool(s.author_salt)}

    @app.get("/api/overview")
    def overview():
        return store.overview()

    @app.get("/api/complaints")
    def complaints(platform: Optional[Platform] = None, search: str = Query("", max_length=300),
                   limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        items, total = store.list_complaints(platform, search, limit, offset)
        return {"items": [public_view(c) for c in items], "total": total, "limit": limit, "offset": offset}

    @app.get("/api/runs")
    def runs(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        items, total = store.list_runs(limit, offset)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    @app.post("/api/demo/posts", status_code=201)
    def demo_post(body: DemoPost):
        s = get_settings()
        if not s.demo_mode:
            raise HubError(403, "Demo posts are only available when HUB_DEMO_MODE=true.")
        return public_view(demo.add_manual_post(store, body.platform, body.text, s.author_salt))

    @app.post("/collect")
    def collect(body: CollectRequest):
        s = get_settings()
        if not s.demo_mode:
            raise HubError(501, "Live platform collection is not included in this rebuilt backend. "
                                "Set HUB_DEMO_MODE=true to use the simulated collector.")
        demo.validate_collect(body.platform, body.resource, body.params, body.cursor)
        if body.dry_run:
            return {"dry_run": True, "valid": True, "platform": body.platform, "resource": body.resource,
                    "max_calls": body.max_pages, "max_items": body.max_items}
        return {"dry_run": False, **demo.collect(store, body.platform, body.resource, body.params,
                                                  body.max_items, body.max_pages, body.cursor, s.author_salt)}

    @app.post("/reply")
    def reply(body: ReplyRequest):
        if not get_settings().demo_mode:
            raise HubError(501, "Publishing live replies is not included in this rebuilt backend. "
                                "Set HUB_DEMO_MODE=true to simulate replies.")
        if not store.mark_replied(body.platform, body.reply_to.strip(), body.text.strip()):
            raise HubError(404, "No complaint with that post or comment ID was found.")
        return {"demo": True, "simulated": True, "platform": body.platform,
                "reply_to": body.reply_to.strip(), "text": body.text.strip()}

    @app.post("/api/ai/classify")
    def classify(body: ClassifyRequest):
        s = get_settings()
        if body.platform and body.external_id:
            return ai.classify_one(store, s, body.platform, body.external_id)
        return ai.classify_batch(store, s, body.limit or 10)

    if mcp_app is not None:
        app.mount("/mcp", mcp_app)  # MCP clients use /mcp/ (trailing slash)
    return app


app = create_app()
