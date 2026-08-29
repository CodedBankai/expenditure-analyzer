import pandas as pd

from app.core import analysis


def _df(rows):
    df = pd.DataFrame(rows)
    df["txn_date"] = pd.to_datetime(df["txn_date"])
    return df


def test_category_totals_only_counts_debits():
    df = _df([
        {"txn_date": "2026-06-01", "description": "A", "amount": 100, "direction": "debit", "category": "Food"},
        {"txn_date": "2026-06-02", "description": "B", "amount": 500, "direction": "credit", "category": "Transfers"},
    ])
    totals = analysis.category_totals(df)
    assert len(totals) == 1
    assert totals[0]["category"] == "Food"
    assert totals[0]["total"] == 100


def test_recurring_detection_requires_three_for_high_confidence():
    rows = []
    for i in range(3):
        rows.append({
            "txn_date": f"2026-0{6+i}-05",
            "description": "Netflix",
            "amount": 499,
            "direction": "debit",
            "category": "Entertainment",
        })
    df = _df(rows)
    recurring = analysis.detect_recurring(df)
    assert len(recurring) == 1
    assert recurring[0]["confidence"] == "high"
    assert recurring[0]["occurrences"] == 3


def test_two_occurrences_marked_possible():
    rows = [
        {"txn_date": "2026-06-05", "description": "Spotify", "amount": 119, "direction": "debit", "category": "Subscriptions"},
        {"txn_date": "2026-07-05", "description": "Spotify", "amount": 119, "direction": "debit", "category": "Subscriptions"},
    ]
    df = _df(rows)
    recurring = analysis.detect_recurring(df)
    assert len(recurring) == 1
    assert recurring[0]["confidence"] == "possible"


def test_high_spend_category_recommendation():
    df = _df([
        {"txn_date": "2026-06-01", "description": "Rent", "amount": 15000, "direction": "debit", "category": "Rent"},
        {"txn_date": "2026-06-02", "description": "Coffee", "amount": 100, "direction": "debit", "category": "Food"},
    ])
    totals = analysis.category_totals(df)
    recs = analysis.build_recommendations(df, totals, recurring=[])
    assert any(r["type"] == "high_spend_category" and r["data_point"]["category"] == "Rent" for r in recs)


def test_available_months_and_monthly_totals():
    df = _df([
        {"txn_date": "2026-06-01", "description": "A", "amount": 100, "direction": "debit", "category": "Food"},
        {"txn_date": "2026-06-15", "description": "B", "amount": 50, "direction": "debit", "category": "Food"},
        {"txn_date": "2026-07-01", "description": "C", "amount": 200, "direction": "debit", "category": "Food"},
    ])
    months = analysis.available_months(df)
    assert [m["key"] for m in months] == ["2026-06", "2026-07"]

    totals = analysis.monthly_totals(df)
    assert totals == [
        {"month": "2026-06", "label": "Jun 2026", "total": 150},
        {"month": "2026-07", "label": "Jul 2026", "total": 200},
    ]


def test_day_of_week_pattern_filters_by_month_and_week():
    df = _df([
        {"txn_date": "2026-06-01", "description": "A", "amount": 100, "direction": "debit", "category": "Food"},  # Mon, week1
        {"txn_date": "2026-06-22", "description": "B", "amount": 300, "direction": "debit", "category": "Food"},  # week4
        {"txn_date": "2026-07-01", "description": "C", "amount": 999, "direction": "debit", "category": "Food"},  # different month
    ])
    dow_june = analysis.day_of_week_pattern(df, month="2026-06")
    total_june = sum(d["total"] for d in dow_june)
    assert total_june == 400

    dow_june_week1 = analysis.day_of_week_pattern(df, month="2026-06", week=1)
    total_week1 = sum(d["total"] for d in dow_june_week1)
    assert total_week1 == 100


def test_credit_vs_debit_totals():
    df = _df([
        {"txn_date": "2026-06-01", "description": "A", "amount": 100, "direction": "debit", "category": "Food"},
        {"txn_date": "2026-06-02", "description": "B", "amount": 5000, "direction": "credit", "category": "Transfers"},
    ])
    result = analysis.credit_vs_debit_totals(df)
    assert result["debit_total"] == 100
    assert result["credit_total"] == 5000
    assert result["net"] == 4900
