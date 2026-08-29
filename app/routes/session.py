from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import categorize
from app.core.categorize import DEFAULT_CATEGORIES
from app.core.session_store import session_store

router = APIRouter()


def _require_session(session_id: str):
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found or expired.")
    if session.df is None:
        raise HTTPException(400, "Session has no uploaded data yet.")
    return session


class DateRangeBody(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None


@router.post("/session/{session_id}/date-range")
async def set_date_range(session_id: str, body: DateRangeBody):
    session = _require_session(session_id)
    df = session.df
    if body.start:
        df = df[df["txn_date"] >= body.start]
    if body.end:
        df = df[df["txn_date"] <= body.end]
    return {"session_id": session_id, "row_count": len(df)}


@router.get("/session/{session_id}/uncategorized")
async def get_uncategorized(session_id: str):
    session = _require_session(session_id)
    rows = categorize.uncategorized(session.df)
    vendors = sorted(rows["description"].unique().tolist())
    return {
        "session_id": session_id,
        "uncategorized_count": len(rows),
        "vendors": vendors,
        "default_categories": DEFAULT_CATEGORIES + session.custom_categories,
    }


class CategorizeBody(BaseModel):
    mappings: dict[str, str]  # vendor description (or substring) -> category
    new_categories: list[str] = []


@router.post("/session/{session_id}/categorize")
async def submit_categorize(session_id: str, body: CategorizeBody):
    session = _require_session(session_id)
    session.category_overrides.update(body.mappings)
    for cat in body.new_categories:
        if cat and cat not in session.custom_categories and cat not in DEFAULT_CATEGORIES:
            session.custom_categories.append(cat)

    session.df = categorize.categorize(session.df.drop(columns=["category"]), overrides=session.category_overrides)
    remaining = int(session.df["category"].isna().sum())
    return {"session_id": session_id, "uncategorized_count": remaining}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    deleted = session_store.delete(session_id)
    if not deleted:
        raise HTTPException(404, "Session not found or already expired.")
    return {"deleted": True}
