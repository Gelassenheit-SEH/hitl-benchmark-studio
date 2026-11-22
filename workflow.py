"""Review helpers adapted from the two Studio source versions."""
import copy
import math
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

CONTROLLED_ERROR_CATEGORIES = {
    "C1": "Scientific law",
    "C2": "Applicability condition",
    "C3": "Feasibility",
    "C4": "Quantitative constraint",
}
REVIEWABLE_FIELDS = (
    "error_span_or_step", "error_explanation", "scientific_constraint", "minimal_repair",
)
ERROR_FIELDS = (
    "error_span_or_step", "error_category", "error_subtype", "error_explanation",
    "scientific_constraint", "applicability_conditions", "minimal_repair",
)

class ApiError(Exception):
    def __init__(self, status, message, details=None):
        super().__init__(message)
        self.status = status
        self.details = details


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")



def append_annotation_version(
    record: dict[str, Any],
    annotation: dict[str, Any],
    version_type: str,
    review_round_id: str | None = None,
) -> int:
    versions = record.setdefault("ai_preannotation_versions", [])
    version = len(versions) + 1
    versions.append({
        "version": version,
        "version_type": version_type,
        "created_at": now_iso(),
        "parent_version": version - 1 if version > 1 else None,
        "review_round_id": review_round_id,
        "annotation": copy.deepcopy(annotation),
    })
    record["ai_preannotation"] = copy.deepcopy(annotation)
    return version


def validate_field_reviews(value: Any) -> dict[str, dict[str, str]]:
    if not isinstance(value, dict) or set(value) != set(REVIEWABLE_FIELDS):
        raise ApiError(HTTPStatus.BAD_REQUEST, "All four field reviews are required")
    normalized: dict[str, dict[str, str]] = {}
    changed = 0
    for field in REVIEWABLE_FIELDS:
        review = value.get(field)
        if not isinstance(review, dict) or set(review) != {"decision", "revision_instruction"}:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Invalid field review for {field}")
        decision = str(review.get("decision", ""))
        instruction = str(review.get("revision_instruction", "")).strip()
        if decision not in ("agree", "needs_revision"):
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Invalid field decision for {field}")
        if decision == "agree" and instruction:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Agreed field {field} cannot include a revision instruction")
        if decision == "needs_revision" and not instruction:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"Revision instruction is required for {field}")
        changed += decision == "needs_revision"
        normalized[field] = {"decision": decision, "revision_instruction": instruction}
    if not changed:
        raise ApiError(HTTPStatus.BAD_REQUEST, "At least one field must need revision")
    return normalized


def validate_revision_draft(draft: Any) -> dict[str, str]:
    if not isinstance(draft, dict) or set(draft) != set(REVIEWABLE_FIELDS):
        raise ApiError(HTTPStatus.BAD_GATEWAY, "AI revision must return exactly the four reviewable fields")
    invalid = [field for field in REVIEWABLE_FIELDS if not isinstance(draft.get(field), str)]
    if invalid:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "AI revision fields must be strings", invalid)
    normalized = {field: draft[field].strip() for field in REVIEWABLE_FIELDS}
    empty = [field for field, value in normalized.items() if not value]
    if empty:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "AI revision returned empty fields", empty)
    return normalized


def allocate_controlled_error_counts(total: int, ratios: dict[str, Any]) -> dict[str, int]:
    if isinstance(total, bool) or not isinstance(total, int) or total < 1:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Controlled error total must be a positive integer")
    if not isinstance(ratios, dict) or set(ratios) != set(CONTROLLED_ERROR_CATEGORIES):
        raise ApiError(HTTPStatus.BAD_REQUEST, "Ratios must contain exactly C1, C2, C3, and C4")
    normalized: dict[str, float] = {}
    for code in CONTROLLED_ERROR_CATEGORIES:
        value = ratios[code]
        if isinstance(value, bool):
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{code} ratio must be a finite non-negative number")
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{code} ratio must be a finite non-negative number") from exc
        if not math.isfinite(number) or number < 0:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"{code} ratio must be a finite non-negative number")
        normalized[code] = number
    if not math.isclose(sum(normalized.values()), 100.0, rel_tol=0.0, abs_tol=1e-6):
        raise ApiError(HTTPStatus.BAD_REQUEST, "C1-C4 ratios must sum to 100")
    exact = {code: total * normalized[code] / 100.0 for code in CONTROLLED_ERROR_CATEGORIES}
    result = {code: math.floor(exact[code]) for code in CONTROLLED_ERROR_CATEGORIES}
    remaining = total - sum(result.values())
    order = sorted(CONTROLLED_ERROR_CATEGORIES, key=lambda code: (-(exact[code] - result[code]), code))
    for code in order[:remaining]:
        result[code] += 1
    return result


def validate_controlled_error_draft(draft: Any, expected_category: str) -> tuple[str, dict[str, Any]]:
    required_top = {"candidate_output", "suggested_judgment", "suggested_errors", "uncertainties"}
    if not isinstance(draft, dict) or set(draft) != required_top:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Controlled error generation returned an invalid field set")
    candidate = draft.get("candidate_output")
    if not isinstance(candidate, str) or not candidate.strip():
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Controlled error generation returned an empty candidate_output")
    if draft.get("suggested_judgment") != "clear_violation":
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Controlled error generation must return clear_violation")
    errors = draft.get("suggested_errors")
    if not isinstance(errors, list) or len(errors) != 1 or not isinstance(errors[0], dict):
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Controlled error generation must return exactly one suggested error")
    required_error = {
        "error_span_or_step", "error_category", "error_subtype", "error_explanation",
        "scientific_constraint", "applicability_conditions", "minimal_repair",
    }
    if set(errors[0]) != required_error:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Controlled error generation returned an invalid suggested error field set")
    normalized_error = {}
    for field in required_error:
        value = errors[0].get(field)
        if not isinstance(value, str) or not value.strip():
            raise ApiError(HTTPStatus.BAD_GATEWAY, f"Controlled error generation returned an empty {field}")
        normalized_error[field] = value.strip()
    if normalized_error["error_category"] != expected_category:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Controlled error generation returned the wrong error category")
    uncertainties = draft.get("uncertainties")
    if not isinstance(uncertainties, list) or any(not isinstance(item, str) for item in uncertainties):
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Controlled error uncertainties must be an array of strings")
    return candidate.strip(), {
        "suggested_judgment": "clear_violation",
        "suggested_errors": [normalized_error],
        "uncertainties": [item.strip() for item in uncertainties if item.strip()],
    }
