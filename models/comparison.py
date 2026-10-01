"""Domain-neutral comparison request, source, and observation models.

These contracts are separate from the legacy retailer price-comparison models
and from research evidence. They describe entities, attributes, and sourced
observations without assigning meaning to any particular domain.
"""
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
import math
import re
from typing import Any
from urllib.parse import urlparse


class ComparisonStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceStatus(str, Enum):
    PENDING = "pending"
    CHECKED = "checked"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    FAILED = "failed"
    UNSUPPORTED = "unsupported"


class ValueType(str, Enum):
    SCALAR = "scalar"
    RANGE = "range"
    CATEGORICAL = "categorical"
    BOOLEAN = "boolean"
    STRUCTURED = "structured"


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value.strip() or None


def _timestamp(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _http_url(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a valid HTTP(S) URL")
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be a valid HTTP(S) URL")
    return value.strip()


def _validate_json_value(value: Any, field_name: str) -> None:
    """Ensure generic payload fields can be represented in JSON safely."""
    if value is None or isinstance(value, (str, bool, int, Decimal, Enum)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{field_name} must not contain a non-finite number")
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item, field_name)
        return
    if isinstance(value, tuple):
        for item in value:
            _validate_json_value(item, field_name)
        return
    if isinstance(value, dict):
        if not all(isinstance(key, str) for key in value):
            raise ValueError(f"{field_name} object keys must be strings")
        for item in value.values():
            _validate_json_value(item, field_name)
        return
    raise ValueError(f"{field_name} must contain JSON-compatible values")


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _serialize(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, (list, tuple)):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


@dataclass
class EntityReference:
    """A request-local entity name and optional generic identifiers."""

    key: str
    display_name: str
    entity_type: str | None = None
    identifiers: dict[str, Any] = field(default_factory=dict)
    aliases: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.key = _required_text(self.key, "key")
        self.display_name = _required_text(self.display_name, "display_name")
        self.entity_type = _optional_text(self.entity_type, "entity_type")
        if not isinstance(self.identifiers, dict) or not all(isinstance(key, str) and key.strip() for key in self.identifiers):
            raise ValueError("identifiers must be a mapping with non-empty string keys")
        _validate_json_value(self.identifiers, "identifiers")
        if not isinstance(self.aliases, list) or not all(isinstance(alias, str) and alias.strip() for alias in self.aliases):
            raise ValueError("aliases must be a list of non-empty strings")
        self.aliases = [alias.strip() for alias in self.aliases]

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class AttributeDefinition:
    """One named comparison dimension, with generic value interpretation."""

    key: str
    label: str
    value_type: ValueType | str
    unit: str | None = None
    currency: str | None = None
    comparison_rule: str | None = None

    def __post_init__(self) -> None:
        self.key = _required_text(self.key, "key")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.key):
            raise ValueError("key must be a lowercase machine-readable identifier")
        self.label = _required_text(self.label, "label")
        try:
            self.value_type = ValueType(self.value_type)
        except (ValueError, TypeError) as exc:
            raise ValueError("value_type must be scalar, range, categorical, boolean, or structured") from exc
        self.unit = _optional_text(self.unit, "unit")
        self.currency = _optional_text(self.currency, "currency")
        if self.currency is not None:
            if len(self.currency) != 3 or not self.currency.isalpha():
                raise ValueError("currency must be a three-letter code")
            self.currency = self.currency.upper()
        self.comparison_rule = _optional_text(self.comparison_rule, "comparison_rule")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class SourceReference:
    """An identifiable source that may be consulted for observations."""

    key: str
    name: str
    source_type: str | None = None
    url: str | None = None

    def __post_init__(self) -> None:
        self.key = _required_text(self.key, "key")
        self.name = _required_text(self.name, "name")
        self.source_type = _optional_text(self.source_type, "source_type")
        self.url = _http_url(self.url, "url")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class SourceCheck:
    """The outcome of an attempted or planned check against a source."""

    source: SourceReference
    status: SourceStatus | str = SourceStatus.PENDING
    checked_at: str | None = None
    diagnostics: dict[str, Any] | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        if isinstance(self.source, dict):
            self.source = SourceReference(**self.source)
        if not isinstance(self.source, SourceReference):
            raise ValueError("source must be a SourceReference")
        try:
            self.status = SourceStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("status must be pending, checked, partial, unavailable, blocked, failed, or unsupported") from exc
        self.checked_at = _timestamp(self.checked_at, "checked_at")
        if self.diagnostics is not None:
            if not isinstance(self.diagnostics, dict):
                raise ValueError("diagnostics must be an object")
            _validate_json_value(self.diagnostics, "diagnostics")
        self.error = _optional_text(self.error, "error")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class Observation:
    """A raw and optionally normalized value for one entity/attribute/source."""

    entity_key: str
    attribute_key: str
    source_key: str
    raw_value: Any
    normalized_value: Any = None
    value_type: ValueType | str = ValueType.STRUCTURED
    unit: str | None = None
    currency: str | None = None
    observed_at: str | None = None
    source_url: str | None = None
    context: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.entity_key = _required_text(self.entity_key, "entity_key")
        self.attribute_key = _required_text(self.attribute_key, "attribute_key")
        if not re.fullmatch(r"[a-z][a-z0-9_]*", self.attribute_key):
            raise ValueError("attribute_key must be a lowercase machine-readable identifier")
        self.source_key = _required_text(self.source_key, "source_key")
        if self.raw_value is None:
            raise ValueError("raw_value is required")
        _validate_json_value(self.raw_value, "raw_value")
        _validate_json_value(self.normalized_value, "normalized_value")
        try:
            self.value_type = ValueType(self.value_type)
        except (TypeError, ValueError) as exc:
            raise ValueError("value_type must be scalar, range, categorical, boolean, or structured") from exc
        self.unit = _optional_text(self.unit, "unit")
        self.currency = _optional_text(self.currency, "currency")
        if self.currency is not None:
            if len(self.currency) != 3 or not self.currency.isalpha():
                raise ValueError("currency must be a three-letter code")
            self.currency = self.currency.upper()
        self.observed_at = _timestamp(self.observed_at, "observed_at") or datetime.now(timezone.utc).isoformat()
        self.source_url = _http_url(self.source_url, "source_url")
        if self.context is not None:
            if not isinstance(self.context, dict):
                raise ValueError("context must be an object")
            _validate_json_value(self.context, "context")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class ComparisonRequest:
    """Original user request plus optional resolved entities and dimensions."""

    user_request: str
    entities: list[EntityReference] = field(default_factory=list)
    attributes: list[AttributeDefinition] = field(default_factory=list)
    context: dict[str, Any] | None = None
    source_preferences: list[SourceReference] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.user_request, str) or not self.user_request.strip():
            raise ValueError("user_request must not be empty")
        # Keep the original untrimmed text for traceability; validation only checks whitespace.
        self.entities = [EntityReference(**item) if isinstance(item, dict) else item for item in self.entities]
        self.attributes = [AttributeDefinition(**item) if isinstance(item, dict) else item for item in self.attributes]
        self.source_preferences = [SourceReference(**item) if isinstance(item, dict) else item for item in self.source_preferences]
        if not all(isinstance(item, EntityReference) for item in self.entities):
            raise ValueError("entities must contain EntityReference values")
        if len({entity.key for entity in self.entities}) != len(self.entities):
            raise ValueError("entity keys must be unique within a request")
        if not all(isinstance(item, AttributeDefinition) for item in self.attributes):
            raise ValueError("attributes must contain AttributeDefinition values")
        if len({attribute.key for attribute in self.attributes}) != len(self.attributes):
            raise ValueError("attribute keys must be unique within a request")
        if not all(isinstance(item, SourceReference) for item in self.source_preferences):
            raise ValueError("source_preferences must contain SourceReference values")
        if self.context is not None:
            if not isinstance(self.context, dict):
                raise ValueError("context must be an object")
            _validate_json_value(self.context, "context")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class ComparisonResult:
    """Domain-neutral result envelope; it does not rank or choose entities."""

    comparison_id: str
    status: ComparisonStatus | str
    request: ComparisonRequest
    entities: list[EntityReference] = field(default_factory=list)
    attributes: list[AttributeDefinition] = field(default_factory=list)
    source_checks: list[SourceCheck] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    analysis: str | None = None
    unresolved: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None

    def __post_init__(self) -> None:
        self.comparison_id = _required_text(self.comparison_id, "comparison_id")
        try:
            self.status = ComparisonStatus(self.status)
        except (TypeError, ValueError) as exc:
            raise ValueError("status must be queued, running, completed, or failed") from exc
        if isinstance(self.request, dict):
            self.request = ComparisonRequest(**self.request)
        if not isinstance(self.request, ComparisonRequest):
            raise ValueError("request must be a ComparisonRequest")
        self.entities = [EntityReference(**item) if isinstance(item, dict) else item for item in self.entities]
        self.attributes = [AttributeDefinition(**item) if isinstance(item, dict) else item for item in self.attributes]
        self.source_checks = [SourceCheck(**item) if isinstance(item, dict) else item for item in self.source_checks]
        self.observations = [Observation(**item) if isinstance(item, dict) else item for item in self.observations]
        groups = (
            (self.entities, EntityReference, "entities"),
            (self.attributes, AttributeDefinition, "attributes"),
            (self.source_checks, SourceCheck, "source_checks"),
            (self.observations, Observation, "observations"),
        )
        for values, expected_type, name in groups:
            if not all(isinstance(item, expected_type) for item in values):
                raise ValueError(f"{name} contain invalid model values")
        self.analysis = _optional_text(self.analysis, "analysis")
        for name in ("unresolved", "errors"):
            values = getattr(self, name)
            if not isinstance(values, list) or not all(isinstance(item, str) and item.strip() for item in values):
                raise ValueError(f"{name} must be a list of non-empty strings")
            setattr(self, name, [item.strip() for item in values])
        self.created_at = _timestamp(self.created_at, "created_at") or datetime.now(timezone.utc).isoformat()
        self.updated_at = _timestamp(self.updated_at, "updated_at") or self.created_at

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)
