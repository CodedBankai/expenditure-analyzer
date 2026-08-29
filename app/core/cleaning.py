"""Stage 3: Cleaning."""
from __future__ import annotations

import pandas as pd

BAD_STATUS_KEYWORDS = ["failed", "reversed", "pending", "none"]


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = {"rows_in": len(df), "dropped": {}}
    working = df.copy()

    working["txn_date"] = pd.to_datetime(working["txn_date"], errors="coerce", dayfirst=True, format="mixed")

    bad_status_mask = working["status"].astype(str).str.lower().str.strip().isin(BAD_STATUS_KEYWORDS)
    stats["dropped"]["bad_status"] = int(bad_status_mask.sum())
    working = working[~bad_status_mask]

    null_amount_mask = working["amount"].isna() | (working["amount"] == 0)
    stats["dropped"]["null_or_zero_amount"] = int(null_amount_mask.sum())
    working = working[~null_amount_mask]

    bad_date_mask = working["txn_date"].isna()
    stats["dropped"]["unparseable_date"] = int(bad_date_mask.sum())
    working = working[~bad_date_mask]

    working = working.reset_index(drop=True)
    stats["rows_out"] = len(working)
    stats["total_dropped"] = stats["rows_in"] - stats["rows_out"]
    return working, stats
