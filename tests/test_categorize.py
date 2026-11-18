import pandas as pd

from app.core import categorize


def _df(descriptions):
    return pd.DataFrame({
        "txn_date": pd.to_datetime(["2026-06-01"] * len(descriptions)),
        "description": descriptions,
        "amount": [100.0] * len(descriptions),
        "direction": ["debit"] * len(descriptions),
        "status": ["SUCCESS"] * len(descriptions),
    })


def test_keyword_match_assigns_category():
    df = _df(["SWIGGY ORDER 123", "UBER TRIP 456"])
    out = categorize.categorize(df)
    assert out.loc[0, "category"] == "Food"
    assert out.loc[1, "category"] == "Transport"


def test_unmatched_row_is_uncategorized():
    df = _df(["SOME RANDOM VENDOR XYZ"])
    out = categorize.categorize(df)
    assert pd.isna(out.loc[0, "category"])
    assert len(categorize.uncategorized(out)) == 1


def test_override_takes_precedence():
    df = _df(["SWIGGY ORDER 123"])
    out = categorize.categorize(df, overrides={"swiggy order 123": "Custom Category"})
    assert out.loc[0, "category"] == "Custom Category"


def test_upi_channel_does_not_hide_unknown_merchant():
    out = categorize.categorize(_df(["UPI-RAZORPAY-XYZ123", "UPI-SWIGGY-ORDER"] ))
    assert pd.isna(out.loc[0, "category"])
    assert out.loc[1, "category"] == "Food"


def test_credits_do_not_enter_spending_review_queue():
    df = _df(["SALARY CREDIT", "UNKNOWN MERCHANT"])
    df.loc[0, "direction"] = "credit"
    out = categorize.categorize(df)
    assert pd.isna(out.loc[0, "category"])
    assert categorize.uncategorized(out)["description"].tolist() == ["UNKNOWN MERCHANT"]
