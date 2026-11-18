import asyncio
import io
import json

import pandas as pd
import pytest
from fastapi import HTTPException

from app.core import ai_categorize, categorize
from app.core.session_store import session_store
from app.routes.session import AISuggestionBody, CategorizeBody, get_ai_suggestions, submit_categorize


def test_redaction_removes_common_identifiers():
    redacted = ai_categorize.redact_description("UPI-RAZORPAY user@okbank REF 123456789 9876543210")
    assert "RAZORPAY" in redacted
    assert "user@okbank" not in redacted
    assert "123456789" not in redacted
    assert "9876543210" not in redacted


def test_groq_receives_one_structured_batch_and_validates_result(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    captured = []

    def fake_urlopen(request, timeout):
        captured.append(request)
        response = {"choices": [{"message": {"content": json.dumps({"suggestions": [
            {"id": 0, "category": "Food"}, {"id": 1, "category": "unsure"}
        ]})}}]}
        return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(ai_categorize, "urlopen", fake_urlopen)
    result = ai_categorize.suggest_redacted(["CAFE", "UNKNOWN"])
    assert result == [{"id": 0, "category": "Food"}, {"id": 1, "category": "unsure"}]
    assert len(captured) == 1
    assert json.loads(captured[0].data)["response_format"]["json_schema"]["strict"] is True
    assert captured[0].get_header("User-agent") == "ExpenditureAnalyzer/1.0"


def test_invalid_provider_category_falls_back_to_manual(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")

    def fake_urlopen(request, timeout):
        response = {"choices": [{"message": {"content": '{"suggestions":[{"id":0,"category":"Investments"}]}'}}]}
        return io.BytesIO(json.dumps(response).encode())

    monkeypatch.setattr(ai_categorize, "urlopen", fake_urlopen)
    with pytest.raises(ai_categorize.SuggestionUnavailable):
        ai_categorize.suggest_redacted(["UNKNOWN"])


def test_suggestions_need_consent_and_do_not_apply(monkeypatch):
    data = session_store.create()
    try:
        frame = pd.DataFrame({
            "description": ["UPI-BLURP-123456", "UPI-BLURP-654321", "SALARY CREDIT"],
            "direction": ["debit", "debit", "credit"],
        })
        data.df = categorize.categorize(frame)
        with pytest.raises(HTTPException) as error:
            asyncio.run(get_ai_suggestions(data.session_id, AISuggestionBody()))
        assert error.value.status_code == 400

        batches = []

        def fake_suggest(descriptions):
            batches.append(descriptions)
            return [{"id": 0, "category": "Food"}]

        monkeypatch.setattr(ai_categorize, "suggest_redacted", fake_suggest)
        answer = asyncio.run(get_ai_suggestions(data.session_id, AISuggestionBody(share_redacted_descriptions=True)))
        assert batches == [["UPI-BLURP-[number]"]]
        assert len(answer["suggestions"]) == 2
        assert set(answer["suggestions"][0]) == {"vendor", "category"}
        assert data.df["category"].isna().all()
    finally:
        session_store.delete(data.session_id)


def test_evaluation_examples_require_separate_choice():
    data = session_store.create()
    try:
        data.df = categorize.categorize(pd.DataFrame({
            "description": ["UPI-BLURP-123456", "UPI-ZORK-987654"],
            "direction": ["debit", "debit"],
        }))
        asyncio.run(submit_categorize(data.session_id, CategorizeBody(mappings={"UPI-BLURP-123456": "Food"})))
        assert data.evaluation_examples == []
        assert data.category_overrides["UPI-BLURP-123456"] == "Food"

        asyncio.run(submit_categorize(data.session_id, CategorizeBody(
            mappings={"UPI-ZORK-987654": "Shopping"}, keep_evaluation_examples=True
        )))
        assert data.evaluation_examples == [{"description": "UPI-ZORK-[number]", "category": "Shopping"}]
        assert "987654" not in str(data.evaluation_examples)
    finally:
        session_store.delete(data.session_id)
