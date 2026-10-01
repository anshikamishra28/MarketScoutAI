"""Deterministic, network-free analysis of persisted generic observations."""
from dataclasses import dataclass, field, fields, is_dataclass
from decimal import Decimal, InvalidOperation
from typing import Any


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return value.to_dict()
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _plain(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return value


def _number(value: Any) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, Decimal):
        number = value
    elif isinstance(value, (int, float, str)):
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    else:
        return None
    return number if number.is_finite() else None


def _json_number(value: Decimal | None) -> int | float | str | None:
    if value is None:
        return None
    if value == value.to_integral_value():
        return int(value)
    return format(value, "f")


@dataclass
class ObservedValue:
    raw_value: Any
    normalized_value: Any
    value_type: str
    source_key: str
    source_url: str | None
    observed_at: str | None
    unit: str | None = None
    currency: str | None = None


@dataclass
class EntityAttributeAnalysis:
    entity_key: str
    entity_name: str
    status: str
    observations: list[ObservedValue] = field(default_factory=list)
    comparable_value: int | float | str | None = None
    note: str | None = None


@dataclass
class AttributeAnalysis:
    attribute_key: str
    label: str
    value_type: str
    comparison_rule: str | None
    status: str
    entities: list[EntityAttributeAnalysis]
    ranking: list[dict[str, Any]] = field(default_factory=list)
    winner_entity_key: str | None = None
    limitations: list[str] = field(default_factory=list)


@dataclass
class ComparisonAnalysis:
    schema_version: int
    comparison_id: str
    attributes: list[AttributeAnalysis]
    unresolved_information: list[str]

    def to_dict(self) -> dict[str, Any]:
        def serialize(value):
            if is_dataclass(value) and not isinstance(value, type):
                return {item.name: serialize(getattr(value, item.name)) for item in fields(value)}
            if isinstance(value, list):
                return [serialize(item) for item in value]
            if isinstance(value, dict):
                return {key: serialize(item) for key, item in value.items()}
            return value
        return serialize(self)


def analyze_comparison(comparison: Any) -> dict[str, Any]:
    """Analyze a complete persisted result without fetching or mutating evidence."""
    data = _plain(comparison)
    if not isinstance(data, dict):
        raise ValueError("comparison must be a result mapping or model")
    entities = data.get("entities") or []
    attributes = data.get("attributes") or []
    observations = data.get("observations") or []
    if not isinstance(entities, list) or not isinstance(attributes, list) or not isinstance(observations, list):
        raise ValueError("comparison entities, attributes, and observations must be lists")

    entities_by_key = {item["key"]: item for item in entities if isinstance(item, dict) and item.get("key")}
    observations_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        pair = (observation.get("entity_key"), observation.get("attribute_key"))
        if pair[0] in entities_by_key and pair[1]:
            observations_by_pair.setdefault(pair, []).append(observation)

    analyses = []
    for attribute in attributes:
        if not isinstance(attribute, dict) or not attribute.get("key"):
            continue
        key = attribute["key"]
        value_type = getattr(attribute.get("value_type"), "value", attribute.get("value_type", "structured"))
        rule = attribute.get("comparison_rule")
        entity_results = []
        all_numeric: dict[str, Decimal] = {}
        complete = bool(entities_by_key)
        for entity_key, entity in entities_by_key.items():
            found = observations_by_pair.get((entity_key, key), [])
            observed = [ObservedValue(
                raw_value=item.get("raw_value"),
                normalized_value=item.get("normalized_value"),
                value_type=getattr(item.get("value_type"), "value", item.get("value_type", "structured")),
                source_key=item.get("source_key", ""),
                source_url=item.get("source_url"),
                observed_at=item.get("observed_at"),
                unit=item.get("unit"), currency=item.get("currency"),
            ) for item in found]
            entry = EntityAttributeAnalysis(
                entity_key=entity_key,
                entity_name=entity.get("display_name", entity_key),
                status="observed" if found else "unresolved",
                observations=observed,
            )
            if not found:
                complete = False
                entry.note = "No persisted observation is available for this entity and attribute."
            elif value_type == "scalar":
                parsed = [_number(item.get("normalized_value")) for item in found]
                if any(number is None for number in parsed):
                    complete = False
                    entry.status = "unresolved"
                    entry.note = "One or more scalar observations are not safely comparable numeric values."
                else:
                    unique = set(parsed)
                    if len(unique) > 1:
                        complete = False
                        entry.status = "conflicting"
                        entry.note = "Sources report different scalar values; no value was selected."
                    else:
                        number = parsed[0]
                        all_numeric[entity_key] = number
                        entry.comparable_value = _json_number(number)
            entity_results.append(entry)

        limitations = []
        ranking = []
        winner = None
        if not entities_by_key:
            limitations.append("No entities are available for this attribute.")
        if not complete:
            limitations.append("Comparison is incomplete or contains values that cannot be safely reconciled.")
        elif value_type != "scalar":
            limitations.append("Values are reported as observed; automatic ranking is limited to scalar numeric values.")
        elif rule is None:
            limitations.append("No comparison_rule is defined; values are reported without ranking.")
        elif rule not in {"lower_is_better", "higher_is_better"}:
            limitations.append(f"Unsupported comparison_rule '{rule}'; values are reported without ranking.")
        elif len(all_numeric) >= 2:
            ordered = sorted(all_numeric.items(), key=lambda pair: pair[1], reverse=rule == "higher_is_better")
            best_value = ordered[0][1]
            ranking = [
                {"rank": 1 if value == best_value else index + 1, "entity_key": entity_key, "value": _json_number(value)}
                for index, (entity_key, value) in enumerate(ordered)
            ]
            best_entities = [entity_key for entity_key, value in ordered if value == best_value]
            if len(best_entities) == 1:
                winner = best_entities[0]
            else:
                limitations.append("The best value is tied; no single winner is identified.")
        else:
            limitations.append("At least two entities with usable values are required for ranking.")

        analyses.append(AttributeAnalysis(
            attribute_key=key,
            label=attribute.get("label", key),
            value_type=str(value_type),
            comparison_rule=rule,
            status="complete" if complete else "unresolved",
            entities=entity_results,
            ranking=ranking,
            winner_entity_key=winner,
            limitations=limitations,
        ))

    unresolved = data.get("unresolved") or []
    unresolved_information = [item for item in unresolved if isinstance(item, str)]
    if not entities:
        unresolved_information.append("No entities are available for comparison.")
    if not attributes:
        unresolved_information.append("No comparison attributes are available.")
    return ComparisonAnalysis(
        schema_version=1,
        comparison_id=str(data.get("comparison_id", "")),
        attributes=analyses,
        unresolved_information=list(dict.fromkeys(unresolved_information)),
    ).to_dict()
