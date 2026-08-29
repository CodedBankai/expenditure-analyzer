from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.core import analysis as core_analysis
from app.core.session_store import session_store

router = APIRouter()


@router.get("/session/{session_id}/analysis")
async def get_analysis(
    session_id: str,
    freq: str = Query("D", pattern="^[DWM]$"),
    month: Optional[str] = Query(None, pattern="^\\d{4}-\\d{2}$"),
    week: Optional[int] = Query(None, ge=1, le=4),
    prior_start: Optional[str] = None,
    prior_end: Optional[str] = None,
):
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found or expired.")
    if session.df is None or session.df.empty:
        return {
            "session_id": session_id,
            "empty": True,
            "category_totals": [],
            "vendor_totals": {"top_by_amount": [], "top_by_count": []},
            "time_series": [],
            "day_of_week": [],
            "day_of_month": [],
            "available_months": [],
            "monthly_totals": [],
            "credit_vs_debit": {"credit_total": 0, "debit_total": 0, "credit_count": 0, "debit_count": 0, "net": 0},
            "recurring": [],
            "recommendations": [],
        }

    df = session.df
    cat_totals = core_analysis.category_totals(df)
    vendor_totals = core_analysis.vendor_totals(df)
    series = core_analysis.time_series(df, freq=freq)
    dow = core_analysis.day_of_week_pattern(df, month=month, week=week)
    dom = core_analysis.day_of_month_pattern(df)
    months = core_analysis.available_months(df)
    month_totals = core_analysis.monthly_totals(df)
    credit_debit = core_analysis.credit_vs_debit_totals(df)
    recurring = core_analysis.detect_recurring(df)

    prior_df = None
    if prior_start and prior_end:
        prior_df = df[(df["txn_date"] >= prior_start) & (df["txn_date"] <= prior_end)]

    recs = core_analysis.build_recommendations(df, cat_totals, recurring, prior_range_df=prior_df)

    return {
        "session_id": session_id,
        "empty": False,
        "category_totals": cat_totals,
        "vendor_totals": vendor_totals,
        "time_series": series,
        "day_of_week": dow,
        "day_of_week_filter": {"month": month, "week": week},
        "day_of_month": dom,
        "available_months": months,
        "monthly_totals": month_totals,
        "credit_vs_debit": credit_debit,
        "recurring": recurring,
        "recommendations": recs,
        "cleaning_summary": session.cleaning_stats,
    }
