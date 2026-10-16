"""Optional background auto-classification loop, started from the FastAPI lifespan."""
import asyncio
import logging

from . import ai
from .errors import HubError

log = logging.getLogger("hub")


async def auto_classify_loop(store, settings):
    """Classify the oldest unclassified complaints on a timer; never crashes the app."""
    while True:
        await asyncio.sleep(settings.auto_classify_interval)
        try:
            result = await asyncio.to_thread(ai.classify_batch, store, settings, settings.auto_classify_batch)
            if result["classified"]:
                log.info("Auto-classified %s complaint(s)", result["classified"])
        except HubError as exc:
            log.warning("Auto-classification skipped: %s", exc.message)
        except Exception as exc:  # keep the timer alive regardless of API/network errors
            log.warning("Auto-classification failed: %s", exc)
