"""APScheduler-based background job scheduler.

Runs a 6-hour Nordigen sync job. Started from the FastAPI lifespan.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def _sync_job() -> None:
    """Background task that syncs all Nordigen accounts."""
    try:
        from app.services.sync_service import sync_all

        results = await sync_all()
        total_added = sum(r.transactions_added for r in results)
        errors = [r for r in results if r.status == "error"]
        logger.info(
            "Scheduled sync complete: %d account(s), %d new transaction(s), %d error(s)",
            len(results),
            total_added,
            len(errors),
        )
        for r in errors:
            logger.warning("Sync error for account_id=%s: %s", r.account_id, r.error_message)
    except Exception as exc:
        logger.exception("Unhandled error in scheduled sync job: %s", exc)


def start_scheduler() -> None:
    """Create and start the APScheduler AsyncIOScheduler.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        return

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        _sync_job,
        trigger=IntervalTrigger(hours=6),
        id="nordigen_sync",
        name="Nordigen 6-hour sync",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Scheduler started — Nordigen sync every 6 hours")


def stop_scheduler() -> None:
    """Gracefully shut down the scheduler if it is running."""
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None
