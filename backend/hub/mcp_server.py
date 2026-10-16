"""MCP server (Streamable HTTP) sharing the same store and AI configuration as the REST API."""
from . import ai
from .config import get_settings
from .errors import HubError
from .store import public_view


def build_mcp(store):
    from mcp.server.fastmcp import FastMCP

    mcp = FastMCP("complaints-hub", streamable_http_path="/")

    def guarded(fn):
        try:
            return fn()
        except HubError as exc:
            raise ValueError(exc.message)

    @mcp.tool()
    def list_complaints(platform: str = "", search: str = "", limit: int = 20, offset: int = 0) -> dict:
        """List complaints oldest-first. platform: 'facebook' or 'x' (optional). limit 1-100."""
        items, total = store.list_complaints(platform or None, search, max(1, min(limit, 100)), max(0, offset))
        return {"items": [public_view(c) for c in items], "total": total}

    @mcp.tool()
    def get_complaint(platform: str, external_id: str) -> dict:
        """Get one complaint by platform and external_id."""
        complaint = store.get(platform, external_id)
        if not complaint:
            raise ValueError("Complaint not found.")
        return public_view(complaint)

    @mcp.tool()
    def complaint_overview() -> dict:
        """Counts by platform/status and the latest collection time."""
        return store.overview()

    @mcp.tool()
    def classify_complaints(limit: int = 10) -> dict:
        """Classify the oldest unclassified complaints with OpenAI (sends text to OpenAI, saves results)."""
        return guarded(lambda: ai.classify_batch(store, get_settings(), limit))

    return mcp
