"""Stage 5 (Analysis/Aggregation) + Stage 6 (Recommendation Engine)."""
from __future__ import annotations

from typing import Optional

import pandas as pd

HIGH_CATEGORY_SHARE_THRESHOLD = 0.30
SPIKE_THRESHOLD = 0.25  # 25% above prior-range average triggers a spike flag
RECURRING_MIN_OCCURRENCES = 3
RECURRING_AMOUNT_TOLERANCE = 0.05  # 5%
RECURRING_INTERVAL_TOLERANCE_DAYS = 3
RECURRING_EXPECTED_INTERVAL_DAYS = 30


def spend_only(df: pd.DataFrame) -> pd.DataFrame:
    return df[df["direction"] == "debit"]


def category_totals(df: pd.DataFrame) -> list[dict]:
    spend = spend_only(df)
    grouped = spend.groupby("category", dropna=False)["amount"].agg(["sum", "count"]).reset_index()
    grouped = grouped.rename(columns={"sum": "total", "count": "transaction_count"})
    grouped["category"] = grouped["category"].fillna("Uncategorized")
    return grouped.sort_values("total", ascending=False).to_dict("records")


def vendor_totals(df: pd.DataFrame, top_n: int = 15) -> dict[str, list[dict]]:
    spend = spend_only(df)
    by_amount = (
        spend.groupby("description")["amount"].sum().sort_values(ascending=False).head(top_n).reset_index()
        .rename(columns={"amount": "total"}).to_dict("records")
    )
    by_count = (
        spend.groupby("description")["amount"].count().sort_values(ascending=False).head(top_n).reset_index()
        .rename(columns={"amount": "transaction_count"}).to_dict("records")
    )
    return {"top_by_amount": by_amount, "top_by_count": by_count}


def time_series(df: pd.DataFrame, freq: str = "D") -> list[dict]:
    """freq: 'D' (day), 'W' (week), or 'M' (month)."""
    spend = spend_only(df).set_index("txn_date")
    resampled = spend["amount"].resample(freq).sum().fillna(0).reset_index()
    resampled["txn_date"] = resampled["txn_date"].dt.strftime("%Y-%m-%d")
    return resampled.rename(columns={"amount": "total"}).to_dict("records")


def available_months(df: pd.DataFrame) -> list[dict]:
    """Distinct calendar months present in the data, oldest first."""
    spend = spend_only(df)
    if spend.empty:
        return []
    periods = spend["txn_date"].dt.to_period("M").drop_duplicates().sort_values()
    return [{"key": str(p), "label": p.strftime("%b %Y")} for p in periods]


def week_of_month(day: int) -> int:
    """Maps a day-of-month (1-31) to a week bucket 1-4 (week 4 absorbs days 22-31)."""
    return min((day - 1) // 7 + 1, 4)


def day_of_week_pattern(df: pd.DataFrame, month: Optional[str] = None, week: Optional[int] = None) -> list[dict]:
    """month: 'YYYY-MM' string to restrict to a single calendar month.
    week: 1-4, restricts further to that week-of-month (only meaningful together with `month`)."""
    spend = spend_only(df).copy()
    if month:
        spend = spend[spend["txn_date"].dt.to_period("M").astype(str) == month]
    if week:
        spend = spend[spend["txn_date"].dt.day.apply(week_of_month) == week]

    spend["dow"] = spend["txn_date"].dt.day_name()
    order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    grouped = spend.groupby("dow")["amount"].sum().reindex(order, fill_value=0).reset_index()
    return grouped.rename(columns={"dow": "day_of_week", "amount": "total"}).to_dict("records")


def monthly_totals(df: pd.DataFrame) -> list[dict]:
    """Total spend per calendar month across the whole uploaded range."""
    spend = spend_only(df).copy()
    if spend.empty:
        return []
    spend["month"] = spend["txn_date"].dt.to_period("M")
    grouped = spend.groupby("month")["amount"].sum().sort_index().reset_index()
    return [
        {"month": str(row["month"]), "label": row["month"].strftime("%b %Y"), "total": row["amount"]}
        for _, row in grouped.iterrows()
    ]


def credit_vs_debit_totals(df: pd.DataFrame) -> dict:
    """Totals across BOTH directions (unlike spend_only-based helpers above)."""
    grouped = df.groupby("direction")["amount"].agg(["sum", "count"])
    credit_total = float(grouped["sum"].get("credit", 0.0))
    debit_total = float(grouped["sum"].get("debit", 0.0))
    credit_count = int(grouped["count"].get("credit", 0))
    debit_count = int(grouped["count"].get("debit", 0))
    return {
        "credit_total": round(credit_total, 2),
        "debit_total": round(debit_total, 2),
        "credit_count": credit_count,
        "debit_count": debit_count,
        "net": round(credit_total - debit_total, 2),
    }


def day_of_month_pattern(df: pd.DataFrame) -> list[dict]:
    spend = spend_only(df).copy()
    spend["dom"] = spend["txn_date"].dt.day
    grouped = spend.groupby("dom")["amount"].sum().reindex(range(1, 32), fill_value=0).reset_index()
    return grouped.rename(columns={"dom": "day_of_month", "amount": "total"}).to_dict("records")


def detect_recurring(df: pd.DataFrame) -> list[dict]:
    spend = spend_only(df)
    results = []
    for vendor, group in spend.groupby("description"):
        group = group.sort_values("txn_date")
        if len(group) < 2:
            continue
        amounts = group["amount"].values
        avg_amount = float(amounts.mean())
        if avg_amount == 0:
            continue
        amount_consistent = all(abs(a - avg_amount) / avg_amount <= RECURRING_AMOUNT_TOLERANCE for a in amounts)
        if not amount_consistent:
            continue

        dates = group["txn_date"].tolist()
        intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        interval_consistent = all(
            abs(i - RECURRING_EXPECTED_INTERVAL_DAYS) <= RECURRING_INTERVAL_TOLERANCE_DAYS for i in intervals
        )
        if not interval_consistent:
            continue

        occurrences = len(group)
        entry = {
            "vendor": vendor,
            "average_amount": round(avg_amount, 2),
            "occurrences": occurrences,
            "avg_interval_days": round(sum(intervals) / len(intervals), 1) if intervals else None,
        }
        if occurrences >= RECURRING_MIN_OCCURRENCES:
            entry["confidence"] = "high"
            results.append(entry)
        elif occurrences == 2:
            entry["confidence"] = "possible"
            results.append(entry)
    return sorted(results, key=lambda r: r["average_amount"], reverse=True)


def build_recommendations(
    df: pd.DataFrame,
    cat_totals: list[dict],
    recurring: list[dict],
    prior_range_df: Optional[pd.DataFrame] = None,
) -> list[dict]:
    recs: list[dict] = []
    total_spend = sum(c["total"] for c in cat_totals) or 1

    for c in cat_totals:
        share = c["total"] / total_spend
        if share > HIGH_CATEGORY_SHARE_THRESHOLD:
            recs.append({
                "type": "high_spend_category",
                "message": f"{c['category']} makes up {share:.0%} of your spending — worth a closer look.",
                "data_point": {"category": c["category"], "share": round(share, 3), "total": c["total"]},
            })

    for r in recurring:
        if r["confidence"] == "high":
            recs.append({
                "type": "recurring_charge",
                "message": f"'{r['vendor']}' looks like a recurring charge (~{r['average_amount']:.0f} every ~{r['avg_interval_days']:.0f} days). Check if you still need this subscription.",
                "data_point": r,
            })
        else:
            recs.append({
                "type": "possible_recurring_charge",
                "message": f"'{r['vendor']}' billed you twice at a similar amount and interval — possibly recurring, but not enough history to be sure yet.",
                "data_point": r,
            })

    if prior_range_df is not None and not prior_range_df.empty:
        prior_spend = spend_only(prior_range_df)["amount"].sum()
        current_spend = total_spend
        if prior_spend > 0:
            change = (current_spend - prior_spend) / prior_spend
            if change > SPIKE_THRESHOLD:
                recs.append({
                    "type": "spend_spike",
                    "message": f"Your spending this period is {change:.0%} higher than the previous period.",
                    "data_point": {"current": current_spend, "prior": prior_spend, "change": round(change, 3)},
                })
            elif change < -SPIKE_THRESHOLD:
                recs.append({
                    "type": "spend_drop",
                    "message": f"Your spending this period is {abs(change):.0%} lower than the previous period. Nice work.",
                    "data_point": {"current": current_spend, "prior": prior_spend, "change": round(change, 3)},
                })

    return recs
