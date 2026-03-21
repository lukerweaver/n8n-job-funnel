import json
from dataclasses import dataclass
from typing import Any


class ScoringParseError(Exception):
    pass


@dataclass
class ParsedScore:
    total_score: float
    recommendation: str | None
    justification: str | None
    strengths: list[Any] | dict[str, Any] | None
    gaps: list[Any] | dict[str, Any] | None
    missing_from_jd: list[Any] | dict[str, Any] | None
    role_type: str | None
    screening_likelihood: float | None
    dimension_scores: dict[str, float] | None
    gating_flags: list[str] | None


def _validate_collection(value: Any, field_name: str) -> list[Any] | dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    raise ScoringParseError(f"Field '{field_name}' must be a list, object, or null")


def _validate_dimension_scores(value: Any, field_name: str) -> dict[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ScoringParseError(f"Field '{field_name}' must be an object or null")

    validated: dict[str, float] = {}
    for dimension, score in value.items():
        if not isinstance(dimension, str):
            raise ScoringParseError(f"Field '{field_name}' keys must be strings")
        if not isinstance(score, (int, float)):
            raise ScoringParseError(f"Field '{field_name}' values must be numbers")
        validated[dimension] = float(score)

    return validated


def _validate_string_list(value: Any, field_name: str) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ScoringParseError(f"Field '{field_name}' must be a list of strings or null")
    if any(not isinstance(item, str) for item in value):
        raise ScoringParseError(f"Field '{field_name}' must contain only strings")
    return value


def _validate_optional_number(value: Any, field_name: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)):
        raise ScoringParseError(f"Field '{field_name}' must be a number or null")
    return float(value)


def parse_scoring_response(raw_response: str) -> ParsedScore:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ScoringParseError("Model response was not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ScoringParseError("Model response must be a JSON object")

    if payload.get("error"):
        raise ScoringParseError(f"Model returned error '{payload['error']}'")

    total_score = payload.get("total_score")
    if not isinstance(total_score, (int, float)):
        raise ScoringParseError("Field 'total_score' must be a number")

    recommendation = payload.get("recommendation")
    if recommendation is not None and not isinstance(recommendation, str):
        raise ScoringParseError("Field 'recommendation' must be a string or null")

    justification = payload.get("justification")
    if justification is not None and not isinstance(justification, str):
        raise ScoringParseError("Field 'justification' must be a string or null")

    role_type = payload.get("role_type")
    if role_type is not None and not isinstance(role_type, str):
        raise ScoringParseError("Field 'role_type' must be a string or null")

    screening_likelihood = _validate_optional_number(payload.get("screening_likelihood"), "screening_likelihood")
    dimension_scores = _validate_dimension_scores(payload.get("dimension_scores"), "dimension_scores")
    gating_flags = _validate_string_list(payload.get("gating_flags"), "gating_flags")

    return ParsedScore(
        total_score=float(total_score),
        recommendation=recommendation,
        justification=justification,
        strengths=_validate_collection(payload.get("strengths"), "strengths"),
        gaps=_validate_collection(payload.get("gaps"), "gaps"),
        missing_from_jd=_validate_collection(payload.get("missing_from_jd"), "missing_from_jd"),
        role_type=role_type,
        screening_likelihood=screening_likelihood,
        dimension_scores=dimension_scores,
        gating_flags=gating_flags,
    )
