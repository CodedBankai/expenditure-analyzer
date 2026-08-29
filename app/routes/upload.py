from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException, Response, UploadFile

from app.core import categorize, cleaning, parsing
from app.core.session_store import SessionLimitExceeded, session_store

router = APIRouter()

MAX_TOTAL_BYTES = 5 * 1024 * 1024  # 5MB
MAX_TOTAL_ROWS = 10_000


@router.post("/upload")
async def upload(response: Response, files: list[UploadFile]):
    if not files:
        raise HTTPException(400, "No files provided.")

    total_bytes = 0
    file_payloads: list[tuple[str, bytes]] = []
    for f in files:
        content = await f.read()
        total_bytes += len(content)
        if total_bytes > MAX_TOTAL_BYTES:
            raise HTTPException(400, f"Upload exceeds the {MAX_TOTAL_BYTES // (1024*1024)}MB limit.")
        file_payloads.append((f.filename or "upload", content))

    try:
        session = session_store.create()
    except SessionLimitExceeded as exc:
        raise HTTPException(503, str(exc)) from exc

    normalized_frames = []
    needs_mapping_files: list[dict] = []
    detected_columns: list[str] = []
    for filename, content in file_payloads:
        try:
            normalized, needs_mapping, columns, profile = parsing.parse_and_normalize(content, filename)
        except parsing.ParseError as exc:
            session_store.delete(session.session_id)
            raise HTTPException(400, str(exc)) from exc

        if needs_mapping:
            needs_mapping_files.append({"filename": filename, "columns": columns})
            detected_columns = columns
            session.raw_files[filename] = content
        else:
            normalized_frames.append(normalized)

    if needs_mapping_files:
        session.needs_mapping = True
        session.detected_columns = detected_columns
        return {
            "session_id": session.session_id,
            "needs_mapping": True,
            "files_needing_mapping": needs_mapping_files,
        }

    combined = pd.concat(normalized_frames, ignore_index=True)
    if len(combined) > MAX_TOTAL_ROWS:
        session_store.delete(session.session_id)
        raise HTTPException(400, f"Upload exceeds the {MAX_TOTAL_ROWS}-row limit ({len(combined)} rows found).")

    cleaned, stats = cleaning.clean(combined)
    session.df = categorize.categorize(cleaned)
    session.cleaning_stats = stats

    response.set_cookie("session_id", session.session_id, httponly=True, max_age=1800, samesite="lax")
    uncategorized_count = int(session.df["category"].isna().sum())
    return {
        "session_id": session.session_id,
        "needs_mapping": False,
        "row_count": len(cleaned),
        "cleaning_summary": stats,
        "uncategorized_count": uncategorized_count,
    }


@router.post("/session/{session_id}/column-mapping")
async def column_mapping(session_id: str, mapping_by_file: dict[str, dict[str, str]]):
    session = session_store.get(session_id)
    if session is None:
        raise HTTPException(404, "Session not found or expired.")
    if not session.raw_files:
        raise HTTPException(400, "No files pending mapping for this session.")

    normalized_frames = []
    for filename, content in session.raw_files.items():
        mapping = mapping_by_file.get(filename)
        if not mapping:
            raise HTTPException(400, f"Missing column mapping for '{filename}'.")
        try:
            normalized, _, _, _ = parsing.parse_and_normalize(content, filename, manual_mapping=mapping)
        except parsing.ParseError as exc:
            raise HTTPException(400, str(exc)) from exc
        normalized_frames.append(normalized)

    combined = pd.concat(normalized_frames, ignore_index=True)
    if len(combined) > MAX_TOTAL_ROWS:
        raise HTTPException(400, f"Upload exceeds the {MAX_TOTAL_ROWS}-row limit ({len(combined)} rows found).")

    cleaned, stats = cleaning.clean(combined)
    session.df = categorize.categorize(cleaned)
    session.cleaning_stats = stats
    session.needs_mapping = False
    session.raw_files.clear()

    uncategorized_count = int(session.df["category"].isna().sum())
    return {
        "session_id": session.session_id,
        "row_count": len(cleaned),
        "cleaning_summary": stats,
        "uncategorized_count": uncategorized_count,
    }
