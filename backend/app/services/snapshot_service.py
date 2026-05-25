"""Snapshot service — Phase 2 Module 3.

Behavioral economics:
  Mental Accounting (Thaler 1999)       — 50/30/20 breakdown externalises mental buckets
  Loss Aversion (Kahneman & Tversky 1979) — visible net worth trend makes losses salient
"""
from __future__ import annotations

import time
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.orm import Session


def _dec(value: str | None, default: str = "0.00") -> Decimal:
    try:
        return Decimal(value or default)
    except InvalidOperation:
        return Decimal(default)


def _today() -> date:
    return date.today()


# ------------------------------------------------------------------ #
# compute_monthly_snapshot
# Mental Accounting (Thaler 1999) — 50/30/20 breakdown
# ------------------------------------------------------------------ #

def compute_monthly_snapshot(db: Session, period_month: str):
    """Upsert a MonthlySnapshot for *period_month*.

    Aggregates transactions by category framework_type.
    # Mental Accounting: Thaler 1999 — externalising budget buckets changes spending
    """
    from app.models.categories import Category
    from app.models.snapshots import MonthlySnapshot
    from app.models.transactions import Transaction
    from app.services.budget_service import get_budget_summary

    prefix = f"{period_month}-%"

    # Aggregate amounts by framework_type for the month
    rows = (
        db.query(Category.framework_type, func.sum(Transaction.amount))
        .join(Category, Transaction.category_id == Category.id)
        .filter(
            Transaction.booking_date.like(prefix),
            Transaction.is_pending == 0,
            Transaction.category_id.isnot(None),
        )
        .group_by(Category.framework_type)
        .all()
    )

    framework_totals: dict[str, Decimal] = {}
    for ftype, total in rows:
        if ftype is None:
            continue
        try:
            framework_totals[ftype] = abs(Decimal(str(total or "0")))
        except InvalidOperation:
            framework_totals[ftype] = Decimal("0")

    income_total = framework_totals.get("income", Decimal("0"))
    needs_total = framework_totals.get("needs", Decimal("0"))
    wants_total = framework_totals.get("wants", Decimal("0"))
    savings_total = framework_totals.get("savings", Decimal("0"))
    expenses_total = needs_total + wants_total + savings_total
    net_cash_flow = income_total - expenses_total

    if income_total > 0:
        savings_rate = (savings_total / income_total * 100).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        savings_rate = Decimal("0.00")

    # Budget score: % of budgets within their limit
    # Goal Gradient Effect (Hull 1932) — score near 100 increases motivation
    summaries = get_budget_summary(db, period_month)
    budgets_evaluated = len(summaries)
    budgets_within_limit = sum(1 for s in summaries if not s["is_over_budget"])
    if budgets_evaluated > 0:
        budget_score = int(budgets_within_limit / budgets_evaluated * 100)
    else:
        budget_score = None

    now = int(time.time())

    existing = (
        db.query(MonthlySnapshot)
        .filter(MonthlySnapshot.period_month == period_month)
        .first()
    )

    if existing:
        existing.total_income = str(income_total)
        existing.total_expenses = str(expenses_total)
        existing.net_cash_flow = str(net_cash_flow)
        existing.savings_rate = str(savings_rate)
        existing.needs_total = str(needs_total)
        existing.wants_total = str(wants_total)
        existing.savings_total = str(savings_total)
        existing.budget_score = budget_score
        existing.budgets_evaluated = budgets_evaluated
        existing.budgets_within_limit = budgets_within_limit
        existing.updated_at = now
        db.commit()
        db.refresh(existing)
        return existing

    snapshot = MonthlySnapshot(
        period_month=period_month,
        total_income=str(income_total),
        total_expenses=str(expenses_total),
        net_cash_flow=str(net_cash_flow),
        savings_rate=str(savings_rate),
        needs_total=str(needs_total),
        wants_total=str(wants_total),
        savings_total=str(savings_total),
        budget_score=budget_score,
        budgets_evaluated=budgets_evaluated,
        budgets_within_limit=budgets_within_limit,
        created_at=now,
        updated_at=now,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


# ------------------------------------------------------------------ #
# compute_net_worth_snapshot
# Loss Aversion (Kahneman & Tversky 1979) — visible losses motivate action
# ------------------------------------------------------------------ #

def compute_net_worth_snapshot(db: Session, snapshot_date: str | None = None):
    """Upsert a NetWorthSnapshot for *snapshot_date* (defaults to today).

    # Loss Aversion: Kahneman & Tversky 1979 — seeing losses on a trend chart is a motivator
    """
    from app.models.accounts import Account
    from app.models.liabilities import Liability
    from app.models.snapshots import NetWorthSnapshot

    if snapshot_date is None:
        snapshot_date = _today().isoformat()

    accounts = db.query(Account).filter(Account.is_active == 1).all()
    total_assets = Decimal("0")
    for acc in accounts:
        if acc.balance_amount:
            try:
                total_assets += abs(Decimal(str(acc.balance_amount)))
            except InvalidOperation:
                pass

    liabilities = db.query(Liability).filter(Liability.is_active == 1).all()
    total_liabilities = Decimal("0")
    for lib in liabilities:
        try:
            total_liabilities += abs(_dec(lib.current_balance))
        except InvalidOperation:
            pass

    net_worth = total_assets - total_liabilities
    now = int(time.time())

    existing = (
        db.query(NetWorthSnapshot)
        .filter(NetWorthSnapshot.snapshot_date == snapshot_date)
        .first()
    )

    if existing:
        existing.total_assets = str(total_assets)
        existing.total_liabilities = str(total_liabilities)
        existing.net_worth = str(net_worth)
        db.commit()
        db.refresh(existing)
        return existing

    snapshot = NetWorthSnapshot(
        snapshot_date=snapshot_date,
        total_assets=str(total_assets),
        total_liabilities=str(total_liabilities),
        net_worth=str(net_worth),
        created_at=now,
    )
    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return snapshot


# ------------------------------------------------------------------ #
# get_cash_flow_history
# ------------------------------------------------------------------ #

def get_cash_flow_history(db: Session, n_months: int = 6) -> list[dict]:
    """Return the last *n_months* monthly snapshots, oldest → newest."""
    from app.models.snapshots import MonthlySnapshot

    rows = (
        db.query(MonthlySnapshot)
        .order_by(MonthlySnapshot.period_month.desc())
        .limit(n_months)
        .all()
    )
    rows = sorted(rows, key=lambda r: r.period_month)

    return [
        {
            "period_month": r.period_month,
            "total_income": r.total_income,
            "total_expenses": r.total_expenses,
            "net_cash_flow": r.net_cash_flow,
            "savings_rate": r.savings_rate,
            "budget_score": r.budget_score,
        }
        for r in rows
    ]


# ------------------------------------------------------------------ #
# get_category_trends
# ------------------------------------------------------------------ #

def get_category_trends(db: Session, n_months: int = 6) -> list[dict]:
    """Return per-month needs/wants/savings totals for the last *n_months*."""
    from app.models.snapshots import MonthlySnapshot

    rows = (
        db.query(MonthlySnapshot)
        .order_by(MonthlySnapshot.period_month.desc())
        .limit(n_months)
        .all()
    )
    rows = sorted(rows, key=lambda r: r.period_month)

    return [
        {
            "period_month": r.period_month,
            "needs_total": r.needs_total,
            "wants_total": r.wants_total,
            "savings_total": r.savings_total,
            "total_income": r.total_income,
        }
        for r in rows
    ]


# ------------------------------------------------------------------ #
# get_net_worth_history
# ------------------------------------------------------------------ #

def get_net_worth_history(db: Session, n_snapshots: int = 12) -> list[dict]:
    """Return the last *n_snapshots* net worth records, oldest → newest."""
    from app.models.snapshots import NetWorthSnapshot

    rows = (
        db.query(NetWorthSnapshot)
        .order_by(NetWorthSnapshot.snapshot_date.desc())
        .limit(n_snapshots)
        .all()
    )
    rows = sorted(rows, key=lambda r: r.snapshot_date)

    return [
        {
            "snapshot_date": r.snapshot_date,
            "total_assets": r.total_assets,
            "total_liabilities": r.total_liabilities,
            "net_worth": r.net_worth,
        }
        for r in rows
    ]


# ------------------------------------------------------------------ #
# SVG coordinate helpers (used by router to build chart data)
# ------------------------------------------------------------------ #

_SVG_W = 600
_SVG_H = 200
_MX = 40  # horizontal margin
_MY = 25  # vertical margin
_DW = _SVG_W - 2 * _MX  # drawable width  = 520
_DH = _SVG_H - 2 * _MY  # drawable height = 150


def build_net_worth_svg(snapshots: list[dict]) -> dict:
    """Return SVG rendering data for the net worth line chart.

    Returns {"points": "x,y x,y ...", "v_min": float, "v_max": float,
             "labels": [{"x": float, "label": str}], "baseline_y": float,
             "positive": bool, "has_data": bool}
    """
    if not snapshots:
        return {"has_data": False}

    values = [float(s["net_worth"]) for s in snapshots]
    n = len(values)
    v_min, v_max = min(values), max(values)
    v_range = v_max - v_min or 1.0

    pts = []
    labels = []
    for i, (s, v) in enumerate(zip(snapshots, values)):
        x = _MX + (i / max(n - 1, 1)) * _DW
        y = _MY + (1 - (v - v_min) / v_range) * _DH
        pts.append(f"{x:.1f},{y:.1f}")
        if i == 0 or i == n - 1 or n <= 6:
            labels.append({"x": round(x, 1), "label": s["snapshot_date"][5:]})  # MM-DD

    baseline_y = _MY + _DH  # bottom of chart

    return {
        "has_data": True,
        "points": " ".join(pts),
        "v_min": v_min,
        "v_max": v_max,
        "baseline_y": round(baseline_y, 1),
        "positive": values[-1] >= 0 if values else True,
        "labels": labels,
        "latest": f"{values[-1]:,.2f}" if values else "0.00",
    }


def build_cash_flow_svg(snapshots: list[dict]) -> dict:
    """Return SVG bar chart data for income vs expenses.

    Returns {"bars": [...], "baseline_y": float, "labels": [...], "has_data": bool}
    Each bar: {"x", "y", "w", "h", "color", "month"}
    """
    if not snapshots:
        return {"has_data": False}

    incomes = [float(s["total_income"]) for s in snapshots]
    expenses = [float(s["total_expenses"]) for s in snapshots]
    v_max = max(incomes + expenses + [0.01])

    n = len(snapshots)
    slot = _DW / n
    bar_w = slot * 0.30
    baseline_y = _MY + _DH

    bars = []
    labels = []
    for i, s in enumerate(snapshots):
        x_base = _MX + i * slot + slot * 0.05

        inc = incomes[i]
        inc_h = max(inc / v_max * _DH, 0)
        bars.append({
            "x": round(x_base, 1),
            "y": round(baseline_y - inc_h, 1),
            "w": round(bar_w, 1),
            "h": round(inc_h, 1),
            "color": "var(--color-success)",
        })

        exp = expenses[i]
        exp_h = max(exp / v_max * _DH, 0)
        bars.append({
            "x": round(x_base + bar_w + 2, 1),
            "y": round(baseline_y - exp_h, 1),
            "w": round(bar_w, 1),
            "h": round(exp_h, 1),
            "color": "var(--color-danger)",
        })

        labels.append({"x": round(x_base + bar_w, 1), "label": s["period_month"][5:]})

    return {
        "has_data": True,
        "bars": bars,
        "baseline_y": round(baseline_y, 1),
        "labels": labels,
        "svg_w": _SVG_W,
        "svg_h": _SVG_H,
    }
