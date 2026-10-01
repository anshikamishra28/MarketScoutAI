"""Standalone models for observed retailer price comparisons.

These records intentionally remain separate from research evidence. Prices are
observations tied to a retailer page and timestamp, not analytical claims.
"""
from dataclasses import dataclass, field, fields, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
from typing import Any
from urllib.parse import urlparse


_CAPACITY_VALUE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(GB|TB)\s*$", re.IGNORECASE)


def normalize_capacity_value(value: str) -> str | None:
    """Normalize formatting for a standalone RAM/storage capacity only."""
    match = _CAPACITY_VALUE.fullmatch(value)
    if not match:
        return None
    amount = Decimal(match.group(1)).normalize()
    return f"{format(amount, 'f')}{match.group(2).casefold()}"


class ComparisonStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RetailerStatus(str, Enum):
    CHECKED = "checked"
    UNAVAILABLE = "unavailable"
    BLOCKED = "blocked"
    FAILED = "failed"


def _timestamp(value: str | None, field_name: str) -> str:
    if value is None:
        return datetime.now(timezone.utc).isoformat()
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty ISO 8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat()


def _http_url(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty HTTP(S) URL")
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{field_name} must be a valid HTTP(S) URL")
    return value.strip()


def _serialize(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Decimal):
        return format(value, "f")
    if is_dataclass(value) and not isinstance(value, type):
        return {item.name: _serialize(getattr(value, item.name)) for item in fields(value)}
    if isinstance(value, list):
        return [_serialize(item) for item in value]
    if isinstance(value, dict):
        return {key: _serialize(item) for key, item in value.items()}
    return value


def product_identity_from_mapping(value: dict[str, Any]) -> "ProductIdentity":
    """Normalize accepted request aliases to canonical identity fields.

    ``ram`` and ``storage`` are the canonical string fields. API requests may
    supply numeric ``ram_gb``/``storage_gb`` values; those are converted here
    so the service, persistence, and retailer adapters share ProductIdentity.
    """
    if not isinstance(value, dict):
        raise ValueError("product identity must be an object")
    data = dict(value)
    for alias, canonical in (("ram_gb", "ram"), ("storage_gb", "storage")):
        if alias not in data:
            continue
        if canonical in data:
            raise ValueError(f"provide either {canonical} or {alias}, not both")
        amount = data.pop(alias)
        if isinstance(amount, bool) or not isinstance(amount, (str, int, float, Decimal)):
            raise ValueError(f"{alias} must be a positive GB amount")
        text = str(amount).strip()
        if not re.fullmatch(r"\d+(?:\.\d+)?\s*(?:GB)?", text, re.IGNORECASE):
            raise ValueError(f"{alias} must be a positive GB amount")
        numeric = Decimal(re.sub(r"\s*GB$", "", text, flags=re.IGNORECASE))
        if not numeric.is_finite() or numeric <= 0:
            raise ValueError(f"{alias} must be a positive GB amount")
        data[canonical] = f"{format(numeric, 'f')}GB"
    return ProductIdentity(**data)


@dataclass
class ProductIdentity:
    """Canonical product/variant identifiers used to match retailer offers."""

    brand: str
    model: str = ""
    model_number: str = ""
    ram: str = ""
    storage: str = ""
    variant: str = ""

    def __post_init__(self) -> None:
        for name in ("brand", "model", "model_number", "ram", "storage", "variant"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"{name} must be a string")
            setattr(self, name, value.strip())
        if not self.brand:
            raise ValueError("brand is required")
        if not self.model and not self.model_number:
            raise ValueError("model or model_number is required")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class RetailerResult:
    """Outcome for one retailer, including explicit non-price states."""

    retailer: str
    status: RetailerStatus | str
    checked_at: str | None = None
    message: str | None = None
    source_url: str | None = None
    diagnostics: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        self.retailer = self.retailer.strip() if isinstance(self.retailer, str) else ""
        if not self.retailer:
            raise ValueError("retailer is required")
        try:
            self.status = RetailerStatus(self.status)
        except (ValueError, TypeError) as exc:
            raise ValueError("status must be checked, unavailable, blocked, or failed") from exc
        self.checked_at = _timestamp(self.checked_at, "checked_at")
        if self.source_url is not None:
            self.source_url = _http_url(self.source_url, "source_url")
        if self.diagnostics is not None and not isinstance(self.diagnostics, dict):
            raise ValueError("diagnostics must be a structured object")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class PriceOffer:
    """One timestamped price observation for an exact product variant."""

    retailer: str
    product: ProductIdentity
    price: Decimal | int | float | str
    source_url: str
    currency: str = "INR"
    seller: str | None = None
    discount: str | None = None
    observed_at: str | None = None

    def __post_init__(self) -> None:
        self.retailer = self.retailer.strip() if isinstance(self.retailer, str) else ""
        if not self.retailer:
            raise ValueError("retailer is required")
        if isinstance(self.product, dict):
            self.product = product_identity_from_mapping(self.product)
        if not isinstance(self.product, ProductIdentity):
            raise ValueError("product must be a ProductIdentity")
        try:
            self.price = Decimal(str(self.price))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("price must be a valid positive amount") from exc
        if not self.price.is_finite() or self.price <= 0:
            raise ValueError("price must be a valid positive amount")
        if not isinstance(self.currency, str) or len(self.currency.strip()) != 3 or not self.currency.strip().isalpha():
            raise ValueError("currency must be a three-letter code")
        self.currency = self.currency.strip().upper()
        self.source_url = _http_url(self.source_url, "source_url")
        self.observed_at = _timestamp(self.observed_at, "observed_at")
        if self.seller is not None:
            self.seller = self.seller.strip() or None
        if self.discount is not None:
            self.discount = self.discount.strip() or None

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class PriceComparisonRequest:
    products: list[ProductIdentity]
    retailers: list[str]

    def __post_init__(self) -> None:
        self.products = [product_identity_from_mapping(item) if isinstance(item, dict) else item for item in self.products]
        if not self.products or not all(isinstance(item, ProductIdentity) for item in self.products):
            raise ValueError("at least one valid product is required")
        self.retailers = [name.strip() for name in self.retailers if isinstance(name, str) and name.strip()]
        if not self.retailers:
            raise ValueError("at least one retailer is required")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)


@dataclass
class PriceComparisonResult:
    comparison_id: str
    status: ComparisonStatus | str = ComparisonStatus.QUEUED
    products: list[ProductIdentity] = field(default_factory=list)
    retailers: list[RetailerResult] = field(default_factory=list)
    offers: list[PriceOffer] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    error: str | None = None

    def __post_init__(self) -> None:
        self.comparison_id = self.comparison_id.strip() if isinstance(self.comparison_id, str) else ""
        if not self.comparison_id:
            raise ValueError("comparison_id is required")
        try:
            self.status = ComparisonStatus(self.status)
        except (ValueError, TypeError) as exc:
            raise ValueError("status must be queued, running, completed, or failed") from exc
        self.products = [product_identity_from_mapping(item) if isinstance(item, dict) else item for item in self.products]
        self.retailers = [RetailerResult(**item) if isinstance(item, dict) else item for item in self.retailers]
        self.offers = [PriceOffer(**item) if isinstance(item, dict) else item for item in self.offers]
        if not all(isinstance(item, ProductIdentity) for item in self.products):
            raise ValueError("products must contain ProductIdentity records")
        if not all(isinstance(item, RetailerResult) for item in self.retailers):
            raise ValueError("retailers must contain RetailerResult records")
        if not all(isinstance(item, PriceOffer) for item in self.offers):
            raise ValueError("offers must contain PriceOffer records")
        self.created_at = _timestamp(self.created_at, "created_at")
        self.updated_at = _timestamp(self.updated_at, "updated_at")

    def to_dict(self) -> dict[str, Any]:
        return _serialize(self)
