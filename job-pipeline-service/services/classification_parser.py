import json


class ClassificationParseError(Exception):
    pass


def parse_classification_response(raw_response: str) -> str:
    try:
        payload = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise ClassificationParseError("Model response was not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ClassificationParseError("Model response must be a JSON object")

    if payload.get("error"):
        raise ClassificationParseError(f"Model returned error '{payload['error']}'")

    classification_key = payload.get("classification_key")
    if classification_key is None:
        # The active classification prompt currently emits `role_type`.
        # Accept both keys so prompt/schema drift does not break runs.
        classification_key = payload.get("role_type")
    if classification_key is None or not isinstance(classification_key, str) or not classification_key.strip():
        raise ClassificationParseError("Field 'role_type' or 'classification_key' must be a non-empty string")

    return classification_key.strip()
