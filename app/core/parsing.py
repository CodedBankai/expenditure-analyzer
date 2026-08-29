"""Stage 1 (Format Detection & Parsing) + Stage 2 (Schema Normalization).

Output schema for every parsed file:
    txn_date, description, amount, direction (debit/credit), status, raw_row_id, source_file
"""
from __future__ import annotations

import io
import re
from typing import Optional

import pandas as pd

STANDARD_COLUMNS = ["txn_date", "description", "amount", "direction", "status", "raw_row_id", "source_file"]

# Known export column-layout profiles: profile name -> column-name synonyms.
KNOWN_PROFILES = {
    "bank_debit_credit": {
        "date": ["date", "txn date", "transaction date", "value date"],
        "description": ["narration", "description", "particulars", "remarks"],
        "debit": ["withdrawal amt.", "withdrawal amt", "debit", "debit amount"],
        "credit": ["deposit amt.", "deposit amt", "credit", "credit amount"],
        "status": ["status"],
    },
    "upi_signed_amount": {
        "date": ["date", "transaction date", "timestamp"],
        "description": ["description", "payee", "vendor", "merchant name"],
        "amount": ["amount", "amount (inr)", "value"],
        "type": ["type", "transaction type", "direction"],
        "status": ["status", "transaction status"],
    },
}

DATE_HINT_RE = re.compile(r"date|timestamp", re.I)
AMOUNT_HINT_RE = re.compile(r"amount|amt|value|debit|credit|withdrawal|deposit", re.I)
DESC_HINT_RE = re.compile(r"desc|narration|particular|remark|payee|vendor|merchant|\bname\b", re.I)
STATUS_HINT_RE = re.compile(r"status", re.I)


class ParseError(Exception):
    pass


def read_raw(file_bytes: bytes, filename: str) -> pd.DataFrame:
    lower = filename.lower()
    try:
        if lower.endswith(".csv"):
            return pd.read_csv(io.BytesIO(file_bytes))
        if lower.endswith(".xlsx") or lower.endswith(".xls"):
            return pd.read_excel(io.BytesIO(file_bytes))
    except Exception as exc:  # noqa: BLE001 - surfaced as a clear user-facing error
        raise ParseError(f"Could not read '{filename}': {exc}") from exc
    raise ParseError(f"Unsupported file type for '{filename}'. Use .csv, .xlsx, or .xls.")


def _match_profile(columns: list[str]) -> Optional[tuple[str, dict[str, str]]]:
    normalized = {c.strip().lower(): c for c in columns}
    for profile_name, spec in KNOWN_PROFILES.items():
        resolved: dict[str, str] = {}
        required = ["date", "description"]
        ok = True
        for field, synonyms in spec.items():
            for syn in synonyms:
                if syn in normalized:
                    resolved[field] = normalized[syn]
                    break
        for field in required:
            if field not in resolved:
                ok = False
                break
        has_amount = "amount" in resolved or ("debit" in resolved and "credit" in resolved)
        if ok and has_amount:
            return profile_name, resolved
    return None


def detect_columns(df: pd.DataFrame) -> dict[str, Optional[str]]:
    """Heuristic fallback: guess columns by name pattern when no known profile matches."""
    guess: dict[str, Optional[str]] = {"date": None, "description": None, "amount": None, "status": None}
    for col in df.columns:
        name = str(col)
        if guess["date"] is None and DATE_HINT_RE.search(name):
            guess["date"] = col
        elif guess["amount"] is None and AMOUNT_HINT_RE.search(name):
            guess["amount"] = col
        elif guess["description"] is None and DESC_HINT_RE.search(name):
            guess["description"] = col
        elif guess["status"] is None and STATUS_HINT_RE.search(name):
            guess["status"] = col
    return guess


def parse_and_normalize(
    file_bytes: bytes,
    filename: str,
    manual_mapping: Optional[dict[str, str]] = None,
) -> tuple[Optional[pd.DataFrame], bool, list[str], str]:
    """Returns (normalized_df_or_None, needs_mapping, raw_column_list, format_profile)."""
    raw = read_raw(file_bytes, filename)
    if raw.empty:
        raise ParseError(f"'{filename}' has no rows.")
    columns = [str(c) for c in raw.columns]

    if manual_mapping:
        normalized = _normalize_with_mapping(raw, manual_mapping, filename)
        return normalized, False, columns, "manual"

    matched = _match_profile(columns)
    if matched:
        profile_name, resolved = matched
        normalized = _normalize_known_profile(raw, resolved, filename)
        return normalized, False, columns, profile_name

    guess = detect_columns(raw)
    confident = guess["date"] is not None and guess["description"] is not None and guess["amount"] is not None
    if not confident:
        return None, True, columns, "generic"

    mapping = {"date": guess["date"], "description": guess["description"], "amount": guess["amount"]}
    if guess["status"]:
        mapping["status"] = guess["status"]
    normalized = _normalize_with_mapping(raw, mapping, filename)
    return normalized, False, columns, "generic"


def _normalize_known_profile(raw: pd.DataFrame, resolved: dict[str, str], filename: str) -> pd.DataFrame:
    out = pd.DataFrame()
    out["txn_date"] = raw[resolved["date"]]
    out["description"] = raw[resolved["description"]].astype(str)
    out["status"] = raw[resolved["status"]].astype(str) if "status" in resolved else ""

    if "amount" in resolved:
        amount = pd.to_numeric(raw[resolved["amount"]], errors="coerce")
        direction = None
        if "type" in resolved:
            type_col = raw[resolved["type"]].astype(str).str.lower()
            direction = type_col.apply(lambda v: "credit" if "cr" in v or "credit" in v else "debit")
        out["amount"] = amount.abs()
        out["direction"] = direction if direction is not None else amount.apply(
            lambda v: "credit" if v >= 0 else "debit"
        )
    else:
        debit = pd.to_numeric(raw[resolved["debit"]], errors="coerce").fillna(0)
        credit = pd.to_numeric(raw[resolved["credit"]], errors="coerce").fillna(0)
        out["amount"] = debit.where(debit > 0, credit)
        out["direction"] = debit.apply(lambda v: "debit" if v > 0 else None)
        out.loc[credit > 0, "direction"] = "credit"

    out["raw_row_id"] = range(len(out))
    out["source_file"] = filename
    return out[STANDARD_COLUMNS]


def _normalize_with_mapping(raw: pd.DataFrame, mapping: dict[str, str], filename: str) -> pd.DataFrame:
    out = pd.DataFrame()
    out["txn_date"] = raw[mapping["date"]]
    out["description"] = raw[mapping["description"]].astype(str)
    out["status"] = raw[mapping["status"]].astype(str) if mapping.get("status") else ""

    if mapping.get("debit") and mapping.get("credit"):
        debit = pd.to_numeric(raw[mapping["debit"]], errors="coerce").fillna(0)
        credit = pd.to_numeric(raw[mapping["credit"]], errors="coerce").fillna(0)
        out["amount"] = debit.where(debit > 0, credit)
        out["direction"] = "debit"
        out.loc[credit > 0, "direction"] = "credit"
    else:
        amount = pd.to_numeric(raw[mapping["amount"]], errors="coerce")
        out["amount"] = amount.abs()
        out["direction"] = amount.apply(lambda v: "credit" if pd.notna(v) and v >= 0 else "debit")

    out["raw_row_id"] = range(len(out))
    out["source_file"] = filename
    return out[STANDARD_COLUMNS]
