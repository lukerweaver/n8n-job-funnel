import pytest

from services.classification_parser import ClassificationParseError, parse_classification_response


def test_parse_classification_response_accepts_classification_key():
    raw = '{"classification_key": "Product Manager"}'

    assert parse_classification_response(raw) == "Product Manager"


def test_parse_classification_response_accepts_role_type_alias():
    raw = '{"role_type": "Product Manager", "classification_flags": [], "classification_reason": "matches prompt"}'

    assert parse_classification_response(raw) == "Product Manager"


def test_parse_classification_response_rejects_missing_classification_fields():
    raw = '{"classification_flags": [], "classification_reason": "missing role"}'

    with pytest.raises(ClassificationParseError, match="role_type"):
        parse_classification_response(raw)
