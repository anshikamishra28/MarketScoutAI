"""Orchestration for generic comparisons through injected source adapters."""
from collections.abc import Mapping
import uuid

from database import store
from services.comparison_analysis import analyze_comparison
from models.comparison import (
    ComparisonRequest,
    ComparisonStatus,
    Observation,
    SourceCheck,
    SourceReference,
    SourceStatus,
)
from tools.comparison_sources import ComparisonSourceAdapter, ComparisonSourceOutcome


def _validated_request(request) -> ComparisonRequest:
    if isinstance(request, ComparisonRequest):
        return request
    if isinstance(request, Mapping):
        return ComparisonRequest(**request)
    raise ValueError("request must be a ComparisonRequest or mapping")


def _adapter_map(adapters) -> dict[str, ComparisonSourceAdapter]:
    result = {}
    for adapter in adapters:
        source = getattr(adapter, "source", None)
        if not isinstance(source, SourceReference):
            raise ValueError("each adapter must declare a SourceReference as source")
        key = source.key
        if key in result:
            raise ValueError(f"duplicate source adapter key: {key}")
        if not callable(getattr(adapter, "supports", None)) or not callable(getattr(adapter, "check", None)):
            raise ValueError(f"adapter {key} must implement supports() and check()")
        result[key] = adapter
    return result


def _unsupported_check(source: SourceReference, message: str) -> SourceCheck:
    return SourceCheck(source=source, status=SourceStatus.UNSUPPORTED, diagnostics={"reason": message})


def _failed_check(source: SourceReference, exc: Exception) -> SourceCheck:
    return SourceCheck(
        source=source,
        status=SourceStatus.FAILED,
        error=str(exc) or exc.__class__.__name__,
        diagnostics={"error_type": exc.__class__.__name__},
    )


def start_generic_comparison(request, comparison_id=None) -> dict:
    """Validate and persist a queued generic comparison without running sources."""
    validated = _validated_request(request)
    comparison_id = comparison_id or str(uuid.uuid4())
    store.create_comparison_run(comparison_id, validated, status=ComparisonStatus.QUEUED)
    result = store.get_comparison_result(comparison_id)
    if result is None:
        raise RuntimeError("queued comparison could not be read after creation")
    return result


def _observation_validation_error(observations, source_key, entity_keys, attribute_keys):
    for item in observations:
        if not isinstance(item, Observation):
            return "adapter returned a non-Observation value"
        if item.source_key != source_key:
            return "observation source_key does not match the adapter source"
        if item.entity_key not in entity_keys:
            return f"observation refers to an unrequested entity: {item.entity_key}"
        if item.attribute_key not in attribute_keys:
            return f"observation refers to an unrequested attribute: {item.attribute_key}"
    return None


def execute_comparison(request, adapters=(), comparison_id=None) -> dict:
    """Persist a generic comparison run and execute its requested source checks.

    Adapters are injected by callers. With no source preferences, each supplied
    adapter is considered once. With preferences, only those exact source keys
    are checked; missing or unsupported adapters remain explicitly unsupported.
    """
    validated = _validated_request(request)
    selected = _adapter_map(adapters)
    comparison_id = comparison_id or str(uuid.uuid4())
    existing = store.get_comparison_result(comparison_id)
    if existing is None:
        store.create_comparison_run(comparison_id, validated)
    elif existing["request"] != validated.to_dict():
        raise ValueError("comparison_id already belongs to a different request")
    elif existing["status"] != ComparisonStatus.QUEUED.value:
        return existing
    store.update_comparison_run(comparison_id, status=ComparisonStatus.RUNNING.value)

    targets = validated.source_preferences or [adapter.source for adapter in selected.values()]
    # Keep source preference order while ensuring a source is checked once.
    unique_targets = []
    seen_source_keys = set()
    for source in targets:
        if source.key not in seen_source_keys:
            unique_targets.append(source)
            seen_source_keys.add(source.key)
    entity_keys = {entity.key for entity in validated.entities}
    attribute_keys = {attribute.key for attribute in validated.attributes}
    errors = []
    observations_saved = []

    try:
        for source in unique_targets:
            adapter = selected.get(source.key)
            if adapter is None:
                check = _unsupported_check(source, "No adapter is registered for this source.")
                store.upsert_comparison_source_check(comparison_id, check)
                continue
            try:
                if not adapter.supports(validated, source):
                    check = _unsupported_check(source, "The registered adapter does not support this request/source.")
                    store.upsert_comparison_source_check(comparison_id, check)
                    continue
                outcome = adapter.check(validated, source)
                if not isinstance(outcome, ComparisonSourceOutcome):
                    raise TypeError("adapter returned an invalid ComparisonSourceOutcome")
                if outcome.check.source.key != source.key:
                    raise ValueError("adapter returned a check for a different source")
                validation_error = _observation_validation_error(
                    outcome.observations, source.key, entity_keys, attribute_keys
                )
                if validation_error:
                    raise ValueError(validation_error)
                store.upsert_comparison_source_check(comparison_id, outcome.check)
                if outcome.check.status in {SourceStatus.CHECKED, SourceStatus.PARTIAL}:
                    for observation in outcome.observations:
                        store.add_comparison_observation(comparison_id, observation)
                        observations_saved.append(observation)
            except Exception as exc:
                # A source failure is isolated; other requested sources still run.
                failed = _failed_check(source, exc)
                store.upsert_comparison_source_check(comparison_id, failed)
                errors.append(f"{source.name}: {failed.error}")

        observed_pairs = {(item.entity_key, item.attribute_key) for item in observations_saved}
        unresolved = [
            f"{entity.display_name} — {attribute.label}"
            for entity in validated.entities
            for attribute in validated.attributes
            if (entity.key, attribute.key) not in observed_pairs
        ]
        store.update_comparison_run(
            comparison_id,
            status=ComparisonStatus.COMPLETED.value,
            errors=errors,
            unresolved=unresolved,
        )
    except Exception as exc:
        store.update_comparison_run(
            comparison_id,
            status=ComparisonStatus.FAILED.value,
            error=f"Comparison orchestration failed: {exc}",
            errors=errors + [str(exc)],
        )
    result = store.get_comparison_result(comparison_id)
    if result is None:
        raise RuntimeError("comparison result could not be read after execution")
    analysis = analyze_comparison(result)
    store.update_comparison_run(comparison_id, analysis=analysis)
    result = store.get_comparison_result(comparison_id)
    if result is None:
        raise RuntimeError("comparison result could not be read after analysis")
    return result
