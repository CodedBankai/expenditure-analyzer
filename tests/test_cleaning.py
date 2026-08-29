import pandas as pd

from app.core import cleaning


def _df(rows):
    return pd.DataFrame(rows)


def test_drops_bad_status_rows():
    df = _df([
        {"txn_date": "2026-06-01", "description": "A", "amount": 100, "direction": "debit", "status": "SUCCESS"},
        {"txn_date": "2026-06-02", "description": "B", "amount": 100, "direction": "debit", "status": "failed"},
        {"txn_date": "2026-06-03", "description": "C", "amount": 100, "direction": "debit", "status": "Pending"},
    ])
    cleaned, stats = cleaning.clean(df)
    assert len(cleaned) == 1
    assert stats["dropped"]["bad_status"] == 2


def test_drops_null_and_zero_amounts():
    df = _df([
        {"txn_date": "2026-06-01", "description": "A", "amount": 0, "direction": "debit", "status": "SUCCESS"},
        {"txn_date": "2026-06-02", "description": "B", "amount": None, "direction": "debit", "status": "SUCCESS"},
        {"txn_date": "2026-06-03", "description": "C", "amount": 50, "direction": "debit", "status": "SUCCESS"},
    ])
    cleaned, stats = cleaning.clean(df)
    assert len(cleaned) == 1
    assert stats["dropped"]["null_or_zero_amount"] == 2


def test_drops_unparseable_dates():
    df = _df([
        {"txn_date": "not-a-date", "description": "A", "amount": 50, "direction": "debit", "status": "SUCCESS"},
        {"txn_date": "2026-06-03", "description": "C", "amount": 50, "direction": "debit", "status": "SUCCESS"},
    ])
    cleaned, stats = cleaning.clean(df)
    assert len(cleaned) == 1
    assert stats["dropped"]["unparseable_date"] == 1
