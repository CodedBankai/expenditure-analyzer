from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.core import ai_categorize, categorize
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
    keep_evaluation_examples: bool = False


class AISuggestionBody(BaseModel):
    share_redacted_descriptions: bool = False


@router.post("/session/{session_id}/ai-suggestions")
async def get_ai_suggestions(session_id: str, body: AISuggestionBody):
    session = _require_session(session_id)
    if not body.share_redacted_descriptions:
        raise HTTPException(400, "Choose to share redacted descriptions before requesting AI suggestions.")

    vendors = sorted(categorize.uncategorized(session.df)["description"].astype(str).unique().tolist())
    groups: dict[str, list[str]] = {}
    for vendor in vendors:
        redacted = ai_categorize.redact_description(vendor)
        if redacted:
            groups.setdefault(redacted, []).append(vendor)
    selected = list(groups)[:ai_categorize.MAX_MERCHANTS]
    if not selected:
        return {"suggestions": [], "remaining_count": 0}
    try:
        predictions = await asyncio.to_thread(ai_categorize.suggest_redacted, selected)
    except ai_categorize.SuggestionUnavailable as exc:
        raise HTTPException(503, str(exc)) from exc

    suggestions = [
        {"vendor": vendor, "category": prediction["category"]}
        for prediction in predictions
        for vendor in groups[selected[prediction["id"]]]
    ]
    remaining_count = sum(len(groups[key]) for key in list(groups)[ai_categorize.MAX_MERCHANTS:])
    return {"suggestions": suggestions, "remaining_count": remaining_count}


@router.post("/session/{session_id}/categorize")
async def submit_categorize(session_id: str, body: CategorizeBody):
    session = _require_session(session_id)
    pending = set(categorize.uncategorized(session.df)["description"].astype(str).tolist())
    valid_categories = set(DEFAULT_CATEGORIES + session.custom_categories + body.new_categories)
    if any(vendor not in pending or category not in valid_categories for vendor, category in body.mappings.items()):
        raise HTTPException(400, "Choose a current uncategorized merchant and a valid category.")
    if body.keep_evaluation_examples:
        for vendor, category in body.mappings.items():
            redacted = ai_categorize.redact_description(vendor)
            if redacted:
                example = {"description": redacted, "category": category}
                if example not in session.evaluation_examples:
                    session.evaluation_examples.append(example)
    session.category_overrides.update(body.mappings)
    for cat in body.new_categories:
        if cat and cat not in session.custom_categories and cat not in DEFAULT_CATEGORIES:
            session.custom_categories.append(cat)

    session.df = categorize.categorize(session.df.drop(columns=["category"]), overrides=session.category_overrides)
    remaining = len(categorize.uncategorized(session.df))
    return {"session_id": session_id, "uncategorized_count": remaining}


@router.delete("/session/{session_id}")
async def delete_session(session_id: str):
    deleted = session_store.delete(session_id)
    if not deleted:
        raise HTTPException(404, "Session not found or already expired.")
    return {"deleted": True}
