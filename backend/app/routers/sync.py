"""Sync router — trigger manual sync and check sync status (protected)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/sync",
    tags=["sync"],
    dependencies=[Depends(require_session)],
)


@router.post("/trigger")
async def trigger_sync(request: Request, db: Session = Depends(get_db)):
    """Manually trigger a full Nordigen sync for all accounts."""
    import asyncio

    from app.services.sync_service import sync_all

    results = await sync_all()

    total_added = sum(r.transactions_added for r in results)
    errors = [
        {"account_id": r.account_id, "error": r.error_message}
        for r in results
        if r.status == "error"
    ]

    return JSONResponse(
        {
            "status": "ok",
            "accounts_synced": len(results),
            "transactions_added": total_added,
            "errors": errors,
        }
    )


@router.get("/status")
async def sync_status(request: Request, db: Session = Depends(get_db)):
    """Return the 10 most recent sync log entries."""
    from app.models.nordigen import SyncLog

    logs = (
        db.query(SyncLog)
        .order_by(SyncLog.synced_at.desc())
        .limit(10)
        .all()
    )

    return JSONResponse(
        {
            "sync_log": [
                {
                    "id": log.id,
                    "account_id": log.account_id,
                    "synced_at": log.synced_at,
                    "status": log.status,
                    "transactions_added": log.transactions_added,
                }
                for log in logs
            ]
        }
    )
