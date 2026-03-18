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


def _validate_collection(value: Any, field_name: str) -> list[Any] | dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    raise ScoringParseError(f"Field '{field_name}' must be a list, object, or null")


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

    return ParsedScore(
        total_score=float(total_score),
        recommendation=recommendation,
        justification=justification,
        strengths=_validate_collection(payload.get("strengths"), "strengths"),
        gaps=_validate_collection(payload.get("gaps"), "gaps"),
        missing_from_jd=_validate_collection(payload.get("missing_from_jd"), "missing_from_jd"),
    )
