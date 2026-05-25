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
    """Background task that syncs all Nordigen accounts and refreshes snapshots."""
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

    # Regenerate monthly + net worth snapshots after every sync
    try:
        from datetime import date
        from app.database import get_db
        from app.services.snapshot_service import (
            compute_monthly_snapshot,
            compute_net_worth_snapshot,
        )

        period_month = date.today().strftime("%Y-%m")
        db_gen = get_db()
        db = next(db_gen)
        try:
            compute_monthly_snapshot(db, period_month)
            compute_net_worth_snapshot(db)
            logger.info("Snapshots refreshed for %s", period_month)
        finally:
            db.close()
    except Exception as snap_exc:
        logger.warning("Post-sync snapshot generation failed: %s", snap_exc)


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
