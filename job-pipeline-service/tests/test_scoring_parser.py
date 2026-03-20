import pytest

from services.scoring_parser import ScoringParseError, parse_scoring_response


def test_parse_legacy_scoring_response():
    payload = """
        {
          "total_score": 18,
          "recommendation": "Strong Apply",
          "justification": "Strong alignment in priorities.",
          "strengths": ["clear PM ownership", "customer focus"],
          "gaps": ["team onboarding details"],
          "missing_from_jd": ["security ownership"]
        }
    """
    parsed = parse_scoring_response(payload)

    assert parsed.total_score == 18.0
    assert parsed.role_type is None
    assert parsed.screening_likelihood is None
    assert parsed.dimension_scores is None
    assert parsed.gating_flags is None


def test_parse_new_scoring_response_with_all_fields():
    payload = """
        {
          "role_type": "Product Manager",
          "total_score": 21,
          "screening_likelihood": 20,
          "dimension_scores": {
            "domain_fit": 4,
            "execution_ownership_fit": 5,
            "customer_discovery_fit": 3,
            "environment_fit": 4,
            "role_readiness": 5
          },
          "gating_flags": ["No"],
          "recommendation": "Selective Apply",
          "justification": "Clear PM narrative with minor gaps.",
          "strengths": ["roadmap delivery", "stakeholder alignment"],
          "gaps": ["team scale"],
          "missing_from_jd": ["explicit compliance experience"]
        }
    """
    parsed = parse_scoring_response(payload)

    assert parsed.role_type == "Product Manager"
    assert parsed.screening_likelihood == 20.0
    assert parsed.dimension_scores["domain_fit"] == 4.0
    assert parsed.gating_flags == ["No"]
    assert parsed.recommendation == "Selective Apply"


def test_parse_scoring_response_rejects_invalid_dimension_scores():
    payload = """
        {
          "total_score": 17,
          "dimension_scores": ["not", "a", "dict"]
        }
    """
    with pytest.raises(ScoringParseError, match="Field 'dimension_scores' must be an object or null"):
        parse_scoring_response(payload)


def test_parse_scoring_response_rejects_invalid_gating_flags():
    payload = """
        {
          "total_score": 17,
          "gating_flags": ["ok", 123]
        }
    """
    with pytest.raises(ScoringParseError, match="Field 'gating_flags' must contain only strings"):
        parse_scoring_response(payload)
