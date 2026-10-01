"""Deterministic readiness checks for generic comparison intent."""

from models.comparison import ComparisonRequest
from models.comparison_intent import (
    ComparisonIntent,
    ComparisonIntentState,
    InterpretationIssue,
    Provenance,
)


def _has_identity_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (bool, int, float)):
        return True
    if isinstance(value, list):
        return any(_has_identity_value(item) for item in value)
    if isinstance(value, dict):
        return any(_has_identity_value(item) for item in value.values())
    return False


def _has_explicit_identity(entity) -> bool:
    """Check only for supplied generic identity data; never inspect the name."""
    if entity.aliases:
        return True
    return any(_has_identity_value(value) for value in entity.identifiers.values())


def _user_provenance(request: ComparisonRequest) -> dict[str, Provenance]:
    paths = {"user_request": Provenance.USER_PROVIDED}
    if request.context is not None:
        paths["context"] = Provenance.USER_PROVIDED
    for entity in request.entities:
        prefix = f"entities.{entity.key}"
        paths[f"{prefix}.display_name"] = Provenance.USER_PROVIDED
        if entity.entity_type is not None:
            paths[f"{prefix}.entity_type"] = Provenance.USER_PROVIDED
        for key in entity.identifiers:
            paths[f"{prefix}.identifiers.{key}"] = Provenance.USER_PROVIDED
        for index, _alias in enumerate(entity.aliases):
            paths[f"{prefix}.aliases.{index}"] = Provenance.USER_PROVIDED
    for attribute in request.attributes:
        prefix = f"attributes.{attribute.key}"
        for field in ("key", "label", "value_type", "unit", "currency", "comparison_rule"):
            if getattr(attribute, field) is not None:
                paths[f"{prefix}.{field}"] = Provenance.USER_PROVIDED
    for source in request.source_preferences:
        prefix = f"sources.{source.key}"
        for field in ("key", "name", "source_type", "url"):
            if getattr(source, field) is not None:
                paths[f"{prefix}.{field}"] = Provenance.USER_PROVIDED
    return paths


def build_comparison_intent(request: ComparisonRequest) -> ComparisonIntent:
    """Represent whether an explicit request is ready for source execution.

    This function only validates and wraps supplied data. It performs no
    interpretation, network access, adapter invocation, or mutation.
    """
    if not isinstance(request, ComparisonRequest):
        raise ValueError("request must be a ComparisonRequest")

    issues = []
    if len(request.entities) < 2:
        issues.append(InterpretationIssue(
            code="ENTITIES_REQUIRED",
            target="entity",
            message="At least two explicitly named entities are required for a comparison.",
            clarification_question="Which entities would you like to compare? Please provide at least two.",
        ))
    for entity in request.entities:
        if not _has_explicit_identity(entity):
            issues.append(InterpretationIssue(
                code="ENTITY_IDENTITY_UNRESOLVED",
                target="identifier",
                message=f"No explicit identity information was supplied for entity '{entity.key}'.",
                candidates=[entity.display_name],
                clarification_question=(
                    f"How should '{entity.display_name}' be identified for the selected source? "
                    "Provide an explicit identifier or confirm an appropriate identity."
                ),
            ))
    if not request.attributes:
        issues.append(InterpretationIssue(
            code="ATTRIBUTES_REQUIRED",
            target="attribute",
            message="No comparison attributes were explicitly supplied.",
            clarification_question="Which attributes should be compared?",
        ))
    if not request.source_preferences:
        issues.append(InterpretationIssue(
            code="SOURCE_SELECTION_REQUIRED",
            target="source",
            message="No source preference was explicitly supplied.",
            clarification_question="Which sources should be checked?",
        ))

    state = ComparisonIntentState.NEEDS_CLARIFICATION if issues else ComparisonIntentState.READY
    return ComparisonIntent(
        request=request,
        state=state,
        unresolved=issues,
        provenance=_user_provenance(request),
    )
