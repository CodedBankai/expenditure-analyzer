from pathlib import Path

from app.core import parsing

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"


def test_known_bank_profile_detected():
    content = (SAMPLE_DIR / "sample_bank_format.csv").read_bytes()
    df, needs_mapping, columns, profile = parsing.parse_and_normalize(content, "sample_bank_format.csv")
    assert needs_mapping is False
    assert profile == "bank_debit_credit"
    assert set(parsing.STANDARD_COLUMNS).issubset(df.columns)
    assert (df["direction"].isin(["debit", "credit"]) | df["direction"].isna()).all()


def test_known_upi_profile_detected():
    content = (SAMPLE_DIR / "sample_upi_format.csv").read_bytes()
    df, needs_mapping, columns, profile = parsing.parse_and_normalize(content, "sample_upi_format.csv")
    assert needs_mapping is False
    assert profile == "upi_signed_amount"
    assert (df["amount"] >= 0).all()


def test_generic_fallback_needs_mapping_when_unconfident():
    csv_bytes = b"col1,col2,col3\nfoo,bar,baz\n"
    df, needs_mapping, columns, profile = parsing.parse_and_normalize(csv_bytes, "weird.csv")
    assert needs_mapping is True
    assert df is None
    assert columns == ["col1", "col2", "col3"]


def test_unsupported_extension_raises():
    try:
        parsing.parse_and_normalize(b"data", "file.txt")
        assert False, "expected ParseError"
    except parsing.ParseError:
        pass
