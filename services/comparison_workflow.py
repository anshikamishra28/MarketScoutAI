"""Interpret, clarify, confirm, and guard execution of generic comparisons."""

from copy import deepcopy
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
import math
from typing import Any

from models.comparison import ComparisonRequest
from models.comparison_intent import (
    ComparisonIntent,
    ComparisonIntentState,
    InterpretationIssue,
    Provenance,
)
from services.comparison_intent import build_comparison_intent
from services.comparison_interpreter import ComparisonInterpretationProvider, interpret_comparison_request
from services.comparison_service import execute_comparison
from models.comparison import SourceReference


_CONFIRMATION_ISSUE_CODES = {
    "PROPOSED_IDENTITY_REQUIRES_CONFIRMATION",
    "PROPOSED_ATTRIBUTE_REQUIRES_CONFIRMATION",
    "PROPOSED_SOURCE_REQUIRES_CONFIRMATION",
    "PROPOSED_CONTEXT_REQUIRES_CONFIRMATION",
}


@dataclass
class ConfirmationPayload:
    """Explicit field confirmations keyed by JSON Pointer paths."""

    values: dict[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.values, dict):
            raise ValueError("confirmation values must be an object mapping paths to values")
        for path in self.values:
            if not isinstance(path, str) or not path.startswith("/"):
                raise ValueError("confirmation paths must be absolute JSON Pointer paths")


def _pointer(parts: list[str]) -> str:
    return "/" + "/".join(part.replace("~", "~0").replace("/", "~1") for part in parts)


def _parse_pointer(path: str) -> list[str]:
    if not isinstance(path, str) or not path.startswith("/"):
        raise ValueError("confirmation path must be an absolute JSON Pointer")
    parts = []
    for part in path[1:].split("/"):
        decoded = ""
        index = 0
        while index < len(part):
            if part[index] != "~":
                decoded += part[index]
                index += 1
                continue
            if index + 1 >= len(part) or part[index + 1] not in "01":
                raise ValueError("confirmation path contains an invalid JSON Pointer escape")
            decoded += "~" if part[index + 1] == "0" else "/"
            index += 2
        parts.append(decoded)
    return parts


def _safe_value(value):
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("confirmation values must not contain non-finite numbers")
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [_safe_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _safe_value(item) for key, item in value.items()}
    raise ValueError("confirmation values must be JSON-compatible")


def _provenance_path(parts: list[str]) -> str:
    return ".".join(parts)


def _proposed_fields(request: ComparisonRequest, provenance: dict[str, Provenance | str]) -> list[tuple[str, list[str], Any, str, str]]:
    """Return confirmable proposals as path, request path, value, group, label."""
    result = []
    for entity in request.entities:
        prefix = ["entities", entity.key]
        for identifier, value in entity.identifiers.items():
            parts = [*prefix, "identifiers", identifier]
            if provenance.get(_provenance_path(parts)) is Provenance.PROPOSED:
                result.append((_pointer(parts), parts, value, "identity", entity.display_name))
        for index, value in enumerate(entity.aliases):
            parts = [*prefix, "aliases", str(index)]
            if provenance.get(_provenance_path(parts)) is Provenance.PROPOSED:
                result.append((_pointer(parts), parts, value, "identity", entity.display_name))
        parts = [*prefix, "entity_type"]
        if provenance.get(_provenance_path(parts)) is Provenance.PROPOSED:
            result.append((_pointer(parts), parts, entity.entity_type, "identity", entity.display_name))

    for attribute in request.attributes:
        for field in ("label", "value_type", "unit", "currency", "comparison_rule"):
            parts = ["attributes", attribute.key, field]
            if provenance.get(_provenance_path(parts)) is Provenance.PROPOSED:
                result.append((_pointer(parts), parts, getattr(attribute, field), "attribute", attribute.label))

    for index, source in enumerate(request.source_preferences):
        parts = ["source_preferences", str(index), "key"]
        if provenance.get(_provenance_path(["sources", source.key, "key"])) is Provenance.PROPOSED:
            result.append((_pointer(parts), parts, source.key, "source", source.name))

    if request.context:
        for key, value in request.context.items():
            parts = ["context", key]
            if provenance.get(_provenance_path(parts)) is Provenance.PROPOSED:
                result.append((_pointer(parts), parts, value, "context", key))
    return result


def _confirmation_issues(proposed: list[tuple[str, list[str], Any, str, str]]) -> list[InterpretationIssue]:
    grouped: dict[tuple[str, str], list[str]] = {}
    for path, _parts, _value, group, label in proposed:
        grouped.setdefault((group, label), []).append(path)
    issues = []
    for (group, label), paths in grouped.items():
        if group == "identity":
            code, target = "PROPOSED_IDENTITY_REQUIRES_CONFIRMATION", "identifier"
            message = f"Identity details for '{label}' are proposals and need confirmation before execution."
            question = f"Please confirm the identity/variant to use for '{label}' before the comparison is executed."
        elif group == "attribute":
            code, target = "PROPOSED_ATTRIBUTE_REQUIRES_CONFIRMATION", "attribute"
            message = f"The interpretation of attribute '{label}' includes proposed details that need confirmation."
            question = f"Please confirm how '{label}' should be interpreted for this comparison."
        elif group == "source":
            code, target = "PROPOSED_SOURCE_REQUIRES_CONFIRMATION", "source"
            message = f"The source selection '{label}' is a proposal and needs confirmation."
            question = f"Please confirm that '{label}' is the source to check."
        else:
            code, target = "PROPOSED_CONTEXT_REQUIRES_CONFIRMATION", "request"
            message = f"The interpreted context '{label}' is a proposal and needs confirmation."
            question = f"Please confirm whether '{label}' is relevant context for this comparison."
        issues.append(InterpretationIssue(
            code=code,
            target=target,
            message=message,
            candidates=paths,
            clarification_question=question,
        ))
    return issues


def _compose_intent(
    request: ComparisonRequest,
    provenance: dict[str, Provenance | str],
    retained_issues: list[InterpretationIssue],
) -> ComparisonIntent:
    deterministic = build_comparison_intent(request)
    unresolved = [issue for issue in retained_issues if issue.code not in _CONFIRMATION_ISSUE_CODES]
    known = {(issue.code, issue.target, issue.message) for issue in unresolved}
    for issue in deterministic.unresolved:
        signature = (issue.code, issue.target, issue.message)
        if signature not in known:
            unresolved.append(issue)
            known.add(signature)
    proposed = _proposed_fields(request, provenance)
    for issue in _confirmation_issues(proposed):
        signature = (issue.code, issue.target, issue.message)
        if signature not in known:
            unresolved.append(issue)
            known.add(signature)
    state = ComparisonIntentState.NEEDS_CLARIFICATION if unresolved else ComparisonIntentState.READY
    return ComparisonIntent(request, state, unresolved, provenance)


def interpret_comparison_workflow(
    user_request: str,
    *,
    context: dict | None = None,
    source_preferences: list[SourceReference] | None = None,
    allowed_sources: tuple[SourceReference, ...] = (),
    provider: ComparisonInterpretationProvider | None = None,
) -> ComparisonIntent:
    """Interpret a request and add workflow confirmation requirements."""
    intent = interpret_comparison_request(
        user_request,
        context=context,
        source_preferences=source_preferences,
        allowed_sources=allowed_sources,
        provider=provider,
    )
    return _compose_intent(intent.request, intent.provenance, intent.unresolved)


def get_clarification_details(intent: ComparisonIntent) -> dict[str, Any]:
    """Return unresolved issues and the exact proposed fields awaiting confirmation."""
    if not isinstance(intent, ComparisonIntent):
        raise ValueError("intent must be a ComparisonIntent")
    proposed = _proposed_fields(intent.request, intent.provenance)
    return {
        "state": intent.state.value,
        "ready_for_execution": intent.state is ComparisonIntentState.READY and not intent.unresolved,
        "unresolved": [issue.to_dict() for issue in intent.unresolved],
        "confirmations_required": [
            {"path": path, "proposed_value": _safe_value(value), "provenance": Provenance.PROPOSED.value}
            for path, _parts, value, _group, _label in proposed
        ],
    }


def _lookup_target(request: ComparisonRequest, parts: list[str]):
    if len(parts) == 4 and parts[0] == "entities" and parts[2] == "identifiers":
        entity = next((item for item in request.entities if item.key == parts[1]), None)
        if entity is not None and parts[3] in entity.identifiers:
            return entity.identifiers[parts[3]], "entity_identifier", entity
    if len(parts) == 3 and parts[0] == "entities" and parts[2] == "entity_type":
        entity = next((item for item in request.entities if item.key == parts[1]), None)
        if entity is not None and entity.entity_type is not None:
            return entity.entity_type, "entity_type", entity
    if len(parts) == 4 and parts[0] == "entities" and parts[2] == "aliases":
        entity = next((item for item in request.entities if item.key == parts[1]), None)
        if entity is not None and parts[3].isdigit() and int(parts[3]) < len(entity.aliases):
            return entity.aliases[int(parts[3])], "entity_alias", entity
    if len(parts) == 3 and parts[0] == "attributes":
        attribute = next((item for item in request.attributes if item.key == parts[1]), None)
        if attribute is not None and parts[2] in {"label", "value_type", "unit", "currency", "comparison_rule"}:
            return getattr(attribute, parts[2]), "attribute", attribute
    if len(parts) == 3 and parts[0] == "source_preferences" and parts[2] == "key":
        if parts[1].isdigit() and int(parts[1]) < len(request.source_preferences):
            source = request.source_preferences[int(parts[1])]
            return source.key, "source", source
    if len(parts) == 2 and parts[0] == "context" and request.context is not None and parts[1] in request.context:
        return request.context[parts[1]], "context", request.context
    return None


def _apply_confirmation(request: ComparisonRequest, parts: list[str], value: Any) -> ComparisonRequest:
    data = request.to_dict()
    if len(parts) == 4 and parts[0] == "entities" and parts[2] == "identifiers":
        entity = next(item for item in data["entities"] if item["key"] == parts[1])
        entity["identifiers"][parts[3]] = _safe_value(value)
    elif len(parts) == 3 and parts[0] == "entities" and parts[2] == "entity_type":
        entity = next(item for item in data["entities"] if item["key"] == parts[1])
        entity["entity_type"] = value
    elif len(parts) == 4 and parts[0] == "entities" and parts[2] == "aliases":
        entity = next(item for item in data["entities"] if item["key"] == parts[1])
        if not isinstance(value, str) or not value.strip():
            raise ValueError("confirmed alias must be non-empty text")
        entity["aliases"][int(parts[3])] = value
    elif len(parts) == 3 and parts[0] == "attributes":
        attribute = next(item for item in data["attributes"] if item["key"] == parts[1])
        attribute[parts[2]] = value.value if isinstance(value, Enum) else value
    elif len(parts) == 3 and parts[0] == "source_preferences":
        source = data["source_preferences"][int(parts[1])]
        if value != source["key"]:
            raise ValueError("source confirmation must match the proposed allowed source")
    elif len(parts) == 2 and parts[0] == "context":
        data["context"][parts[1]] = _safe_value(value)
    else:
        raise ValueError("confirmation path is not supported")
    return ComparisonRequest(**data)


def confirm_comparison_intent(
    intent: ComparisonIntent,
    confirmations: ConfirmationPayload,
) -> ComparisonIntent:
    """Apply explicit user confirmations only to existing proposed fields."""
    if not isinstance(intent, ComparisonIntent):
        raise ValueError("intent must be a ComparisonIntent")
    if not isinstance(confirmations, ConfirmationPayload):
        raise ValueError("an explicit ConfirmationPayload is required")

    request = deepcopy(intent.request)
    provenance = dict(intent.provenance)
    if not confirmations.values:
        return _compose_intent(request, provenance, intent.unresolved)

    for path, value in confirmations.values.items():
        parts = _parse_pointer(path)
        target = _lookup_target(request, parts)
        if target is None:
            raise ValueError(f"confirmation path does not identify an existing request field: {path}")
        _current, kind, subject = target
        ppath = None
        if kind == "entity_identifier":
            ppath = _provenance_path(["entities", subject.key, "identifiers", parts[3]])
        elif kind == "entity_alias":
            ppath = _provenance_path(["entities", subject.key, "aliases", parts[3]])
        elif kind == "entity_type":
            ppath = _provenance_path(["entities", subject.key, "entity_type"])
        elif kind == "attribute":
            ppath = _provenance_path(["attributes", subject.key, parts[2]])
        elif kind == "source":
            ppath = _provenance_path(["sources", subject.key, "key"])
        elif kind == "context":
            ppath = _provenance_path(["context", parts[1]])
        if provenance.get(ppath) is not Provenance.PROPOSED:
            raise ValueError(f"confirmation does not correspond to a proposed field: {path}")
        updated_request = _apply_confirmation(request, parts, value)
        provenance[ppath] = Provenance.USER_CONFIRMED
        request = updated_request

    return _compose_intent(request, provenance, intent.unresolved)


def execute_confirmed_comparison(intent: ComparisonIntent, *, adapters, comparison_id=None) -> dict:
    """Delegate to the existing comparison service only for a confirmed-ready intent."""
    if not isinstance(intent, ComparisonIntent):
        raise ValueError("intent must be a ComparisonIntent")
    pending = _proposed_fields(intent.request, intent.provenance)
    if intent.state is not ComparisonIntentState.READY or intent.unresolved or pending:
        raise ValueError("comparison intent is not fully resolved and confirmed")
    return execute_comparison(intent.request, adapters=adapters, comparison_id=comparison_id)
