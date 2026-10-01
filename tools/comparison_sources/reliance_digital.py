"""Bridge Reliance Digital's legacy product fetcher to generic comparisons."""
from datetime import datetime, timezone
from decimal import Decimal
import re

from models.comparison import (
    AttributeDefinition,
    ComparisonRequest,
    Observation,
    SourceCheck,
    SourceReference,
    SourceStatus,
)
from models.price_comparison import (
    PriceOffer,
    ProductIdentity,
    RetailerStatus,
    normalize_capacity_value,
)
from tools.comparison_sources.base import ComparisonSourceOutcome
from tools.retailer_fetchers import RelianceDigitalFetcher
from tools.retailer_fetchers.base import RetailerFetchOutcome


_SOURCE = SourceReference(
    key="reliance_digital",
    name="Reliance Digital",
    source_type="retailer",
    url="https://www.reliancedigital.in/",
)
_IDENTITY_FIELDS = ("brand", "model", "model_number", "ram", "storage", "variant")
_CAPACITY = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*(GB|TB)\s*$", re.IGNORECASE)


def _entity_product_identity(entity) -> tuple[ProductIdentity | None, str | None]:
    """Convert only explicitly supplied generic identifiers; never infer names."""
    identifiers = entity.identifiers
    values = {key: identifiers[key] for key in _IDENTITY_FIELDS if key in identifiers}
    try:
        return ProductIdentity(**values), None
    except (TypeError, ValueError) as exc:
        return None, str(exc)


def _json_number(value: Decimal):
    """Return an exact JSON numeric primitive where representable, else None."""
    if not value.is_finite():
        return None
    if value == value.to_integral_value():
        try:
            return int(value)
        except (OverflowError, ValueError):
            return None
    numeric = float(value)
    if not Decimal(str(numeric)) == value:
        return None
    return numeric


def _storage_value(raw: str, attribute: AttributeDefinition):
    normalized = normalize_capacity_value(raw)
    match = _CAPACITY.fullmatch(raw or "")
    if normalized is None or match is None:
        return None
    unit = match.group(2).upper()
    if attribute.unit and attribute.unit.casefold() != unit.casefold():
        return None
    try:
        amount = Decimal(match.group(1))
    except Exception:
        return None
    number = _json_number(amount)
    if number is None:
        return None
    return number, unit


def _generic_status(status: RetailerStatus) -> SourceStatus:
    return {
        RetailerStatus.CHECKED: SourceStatus.CHECKED,
        RetailerStatus.UNAVAILABLE: SourceStatus.UNAVAILABLE,
        RetailerStatus.BLOCKED: SourceStatus.BLOCKED,
        RetailerStatus.FAILED: SourceStatus.FAILED,
    }[status]


def _aggregate_status(statuses: list[SourceStatus], observations: list[Observation]) -> SourceStatus:
    if statuses and all(status is SourceStatus.CHECKED for status in statuses):
        return SourceStatus.CHECKED
    if (
        observations
        and any(status is SourceStatus.CHECKED for status in statuses)
        and any(status is not SourceStatus.CHECKED for status in statuses)
    ):
        return SourceStatus.PARTIAL
    # The single source check must not conceal any entity-level failure state.
    for status in (SourceStatus.FAILED, SourceStatus.BLOCKED, SourceStatus.UNAVAILABLE, SourceStatus.UNSUPPORTED):
        if status in statuses:
            return status
    return SourceStatus.UNSUPPORTED


class RelianceDigitalComparisonAdapter:
    """A source-specific bridge; the existing retailer fetcher remains authoritative."""

    source = _SOURCE

    def __init__(self, fetcher=None):
        self.fetcher = fetcher or RelianceDigitalFetcher()

    def supports(self, request: ComparisonRequest, source: SourceReference) -> bool:
        if source.key != self.source.key or not request.entities:
            return False
        # Allow mixed requests through so check() can record the unsupported
        # entity individually while still evaluating convertible entities.
        return any(_entity_product_identity(entity)[0] is not None for entity in request.entities)

    def check(self, request: ComparisonRequest, source: SourceReference) -> ComparisonSourceOutcome:
        if source.key != self.source.key:
            return ComparisonSourceOutcome(SourceCheck(
                source=source,
                status=SourceStatus.UNSUPPORTED,
                diagnostics={"reason": "This adapter only handles its declared source."},
            ))

        requested_attributes = {attribute.key: attribute for attribute in request.attributes}
        price_attribute = requested_attributes.get("price")
        storage_attribute = requested_attributes.get("storage")
        entity_diagnostics = []
        entity_statuses = []
        observations = []
        checked_times = []

        for entity in request.entities:
            target, identity_error = _entity_product_identity(entity)
            if target is None:
                entity_statuses.append(SourceStatus.UNSUPPORTED)
                entity_diagnostics.append({
                    "entity_key": entity.key,
                    "entity_name": entity.display_name,
                    "status": SourceStatus.UNSUPPORTED.value,
                    "message": "Entity identifiers do not contain a valid retailer product identity.",
                    "identity_error": identity_error,
                    "source_url": None,
                    "diagnostics": None,
                })
                continue

            try:
                result = self.fetcher.fetch(target)
                if not isinstance(result, RetailerFetchOutcome):
                    raise TypeError("Reliance Digital fetcher returned an invalid outcome")
                if result.check.retailer.casefold().strip() != self.source.name.casefold():
                    raise ValueError("fetcher returned a result for a different retailer")
                status = _generic_status(result.check.status)
                entity_statuses.append(status)
                checked_times.append(result.check.checked_at)
                entity_diagnostics.append({
                    "entity_key": entity.key,
                    "entity_name": entity.display_name,
                    "status": status.value,
                    "message": result.check.message,
                    "source_url": result.check.source_url,
                    "diagnostics": result.check.diagnostics,
                    "accepted_offer_count": len(result.offers),
                })

                # The legacy fetcher emits offers only after page fetch, identity
                # matching, and displayed-price validation have succeeded.
                for offer in result.offers:
                    if not isinstance(offer, PriceOffer):
                        raise TypeError("Reliance Digital fetcher returned an invalid price offer")
                    if price_attribute is not None:
                        normalized_price = _json_number(offer.price)
                        observations.append(Observation(
                            entity_key=entity.key,
                            attribute_key="price",
                            source_key=self.source.key,
                            raw_value=format(offer.price, "f"),
                            normalized_value=normalized_price,
                            value_type="scalar",
                            currency=offer.currency,
                            observed_at=offer.observed_at,
                            source_url=offer.source_url,
                            context={
                                "seller": offer.seller,
                                "discount": offer.discount,
                                "matched_identity": offer.product.to_dict(),
                            },
                        ))
                    if storage_attribute is not None:
                        storage = _storage_value(offer.product.storage, storage_attribute)
                        if storage is not None:
                            normalized_storage, unit = storage
                            observations.append(Observation(
                                entity_key=entity.key,
                                attribute_key="storage",
                                source_key=self.source.key,
                                raw_value=offer.product.storage,
                                normalized_value=normalized_storage,
                                value_type="scalar",
                                unit=unit,
                                observed_at=offer.observed_at,
                                source_url=offer.source_url,
                                context={"matched_identity": offer.product.to_dict()},
                            ))
            except Exception as exc:
                entity_statuses.append(SourceStatus.FAILED)
                entity_diagnostics.append({
                    "entity_key": entity.key,
                    "entity_name": entity.display_name,
                    "status": SourceStatus.FAILED.value,
                    "message": str(exc) or exc.__class__.__name__,
                    "source_url": None,
                    "diagnostics": {"error_type": exc.__class__.__name__},
                })

        status = _aggregate_status(entity_statuses, observations)
        # A partial check retains observations from successful entities while
        # the per-entity diagnostics preserve all failed/incomplete outcomes.
        if status not in {SourceStatus.CHECKED, SourceStatus.PARTIAL}:
            observations = []

        checked_at = max((value for value in checked_times if value), default=None)
        diagnostics = {
            "entities": entity_diagnostics,
            "aggregation": "checked only when every requested entity check is checked",
        }
        check = SourceCheck(
            source=self.source,
            status=status,
            checked_at=checked_at or datetime.now(timezone.utc).isoformat(),
            diagnostics=diagnostics,
        )
        return ComparisonSourceOutcome(check=check, observations=observations)
