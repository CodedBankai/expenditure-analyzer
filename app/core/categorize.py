"""Stage 4: Categorization — keyword/regex matching against config/categories.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

CATEGORIES_PATH = Path(__file__).resolve().parent.parent / "config" / "categories.yaml"

DEFAULT_CATEGORIES = [
    "Food", "Transport", "Shopping", "Bills/Utilities", "Rent",
    "Entertainment", "Subscriptions", "Transfers", "Other",
]


def load_keyword_map() -> dict[str, list[str]]:
    with open(CATEGORIES_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {k: [s.lower() for s in (v or [])] for k, v in data.items()}


def categorize(
    df: pd.DataFrame,
    overrides: Optional[dict[str, str]] = None,
    keyword_map: Optional[dict[str, list[str]]] = None,
) -> pd.DataFrame:
    """Adds a `category` column. Unmatched rows get category=None (uncategorized)."""
    keyword_map = keyword_map or load_keyword_map()
    overrides = overrides or {}
    out = df.copy()

    def match(description: str) -> Optional[str]:
        desc_lower = str(description).lower()
        for vendor_key, category in overrides.items():
            if vendor_key.lower() in desc_lower:
                return category
        for category, keywords in keyword_map.items():
            for kw in keywords:
                if kw and kw in desc_lower:
                    return category
        return None

    out["category"] = out["description"].apply(match)
    return out


def vendor_key(description: str) -> str:
    """Derives a short vendor key from a free-text description, for grouping/overrides."""
    text = str(description).strip().lower()
    return text[:40]


def uncategorized(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["category"].isna()]
