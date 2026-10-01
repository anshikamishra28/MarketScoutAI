"""Independent orchestration for retailer price comparisons."""
import uuid
from collections.abc import Mapping

from database import store
from models.price_comparison import (
    ComparisonStatus,
    PriceComparisonRequest,
    ProductIdentity,
    RetailerResult,
    RetailerStatus,
    normalize_capacity_value,
)
from tools.retailer_fetchers import RelianceDigitalFetcher, RetailerFetcher
from tools.retailer_fetchers.base import RetailerFetchOutcome


def _validated_request(request) -> PriceComparisonRequest:
    if isinstance(request, PriceComparisonRequest):
        return request
    if isinstance(request, Mapping):
        return PriceComparisonRequest(**request)
    raise ValueError("request must be a PriceComparisonRequest or mapping")


def start_price_comparison(request) -> dict:
    """Validate and persist a queued comparison without starting network work."""
    validated = _validated_request(request)
    comparison_id = str(uuid.uuid4())
    store.create_price_comparison(comparison_id, validated, status=ComparisonStatus.QUEUED)
    return store.get_price_comparison(comparison_id)


def _normalized_identity(value: str) -> str:
    return " ".join(value.casefold().replace("_", " ").split())


def _normalized_brand(value: str) -> str:
    """Compare brand names exactly after case and whitespace normalization."""
    return "".join(value.casefold().split())


def _offer_matches_request(offer_product: ProductIdentity, target: ProductIdentity) -> bool:
    """Require every supplied identity field to match; omitted fields stay unknown."""
    for field in ("brand", "model", "model_number", "ram", "storage", "variant"):
        expected = getattr(target, field)
        actual = getattr(offer_product, field)
        if field == "brand":
            expected_value = _normalized_brand(expected)
            actual_value = _normalized_brand(actual)
        elif field in {"ram", "storage"}:
            expected_capacity = normalize_capacity_value(expected) if expected else None
            actual_capacity = normalize_capacity_value(actual)
            expected_value = expected_capacity if expected_capacity is not None else _normalized_identity(expected)
            actual_value = actual_capacity if actual_capacity is not None else _normalized_identity(actual)
        else:
            expected_value = _normalized_identity(expected)
            actual_value = _normalized_identity(actual)
        if expected and expected_value != actual_value:
            return False
    return True


def _offer_matches_adapter_confirmation(offer_product: ProductIdentity, diagnostics) -> bool:
    """Accept an adapter-approved page identity when its offer preserves that identity.

    Retailer adapters perform the page-context match. Requiring the flattened
    ProductIdentity to equal the request again here can contradict that result
    (for example, a page title's "Nord 6 5G" model contains the requested "Nord
    6"). This check only trusts an explicit successful adapter match and then
    verifies the offer identity is exactly the identity recorded for that page.
    """
    if not isinstance(diagnostics, dict) or diagnostics.get("exact_product_found") is not True:
        return False
    for candidate in diagnostics.get("candidates", []):
        if not isinstance(candidate, dict) or candidate.get("match") != "matched":
            continue
        extracted = candidate.get("extracted_identity")
        if not isinstance(extracted, dict):
            continue
        try:
            extracted_identity = ProductIdentity(**extracted)
        except (TypeError, ValueError):
            continue
        same_identity = True
        for field in ("brand", "model", "model_number", "ram", "storage", "variant"):
            offer_value = getattr(offer_product, field)
            extracted_value = getattr(extracted_identity, field)
            if field == "brand":
                equal = _normalized_brand(offer_value) == _normalized_brand(extracted_value)
            elif field in {"ram", "storage"}:
                offer_capacity = normalize_capacity_value(offer_value)
                extracted_capacity = normalize_capacity_value(extracted_value)
                if offer_capacity is not None or extracted_capacity is not None:
                    equal = offer_capacity == extracted_capacity
                else:
                    equal = _normalized_identity(offer_value) == _normalized_identity(extracted_value)
            else:
                equal = _normalized_identity(offer_value) == _normalized_identity(extracted_value)
            if not equal:
                same_identity = False
                break
        if same_identity:
            return True
    return False


def _default_fetchers() -> dict[str, RetailerFetcher]:
    fetcher = RelianceDigitalFetcher()
    return {_normalized_identity(fetcher.retailer): fetcher}


def _retailer_outcome(retailer: str, status: RetailerStatus, message: str) -> RetailerFetchOutcome:
    return RetailerFetchOutcome(RetailerResult(retailer, status, message=message), [])


def _combine_checks(retailer: str, outcomes: list[RetailerFetchOutcome], products: list[ProductIdentity]) -> RetailerResult:
    statuses = [outcome.check.status for outcome in outcomes]
    if RetailerStatus.CHECKED in statuses:
        status = RetailerStatus.CHECKED
    elif statuses and len(set(statuses)) == 1:
        status = statuses[0]
    elif RetailerStatus.BLOCKED in statuses and all(value in {RetailerStatus.BLOCKED, RetailerStatus.UNAVAILABLE} for value in statuses):
        status = RetailerStatus.BLOCKED
    else:
        status = RetailerStatus.FAILED
    messages = [
        f"Product {index + 1}: {outcome.check.message or outcome.check.status.value}"
        for index, outcome in enumerate(outcomes)
        if outcome.check.message or outcome.check.status is not RetailerStatus.CHECKED
    ]
    source_url = next((outcome.check.source_url for outcome in outcomes if outcome.check.source_url), None)
    product_diagnostics = []
    for index, product in enumerate(products):
        outcome = outcomes[index] if index < len(outcomes) else None
        discovery = outcome.check.diagnostics if outcome else None
        if not isinstance(discovery, dict):
            discovery = {"strategies": [], "candidates": [], "exact_product_found": False,
                         "final_outcome": "discovery_or_fetch_failed"}
        product_diagnostics.append({"product": product.to_dict(), "discovery": discovery})
    return RetailerResult(retailer, status, message="; ".join(messages) or None, source_url=source_url,
                          diagnostics={"products": product_diagnostics})


def execute_price_comparison(comparison_id: str, fetchers: Mapping[str, RetailerFetcher] | None = None) -> dict | None:
    """Run configured retailer adapters and persist checks and observed offers.

    Each product fetch is isolated: a failed retailer/product check does not
    stop the remaining requested products or retailers.
    """
    record = store.get_price_comparison(comparison_id)
    if record is None:
        raise KeyError(f"Price comparison not found: {comparison_id}")
    request = PriceComparisonRequest(**record["input_data"])
    selected_fetchers = _default_fetchers() if fetchers is None else fetchers
    adapters = {_normalized_identity(name): adapter for name, adapter in selected_fetchers.items()}
    store.update_price_comparison(comparison_id, status=ComparisonStatus.RUNNING.value)
    try:
        retailers = list(dict.fromkeys(request.retailers))
        for retailer in retailers:
            adapter = adapters.get(_normalized_identity(retailer))
            if adapter is None:
                outcome = _retailer_outcome(retailer, RetailerStatus.UNAVAILABLE, "No retailer adapter is implemented for this retailer yet.")
                unavailable_diagnostics = {"products": [{"product": product.to_dict(), "discovery": {
                    "strategies": [], "candidates": [], "exact_product_found": False,
                    "final_outcome": "retailer_adapter_unavailable"}} for product in request.products]}
                store.upsert_price_retailer_check(comparison_id, RetailerResult(
                    retailer, RetailerStatus.UNAVAILABLE, message=outcome.check.message, diagnostics=unavailable_diagnostics))
                continue

            retailer_name = adapter.retailer

            outcomes: list[RetailerFetchOutcome] = []
            valid_offers = []
            for product in request.products:
                try:
                    outcome = adapter.fetch(product)
                    if not isinstance(outcome, RetailerFetchOutcome):
                        raise TypeError("retailer adapter returned an invalid result")
                    if _normalized_identity(outcome.check.retailer) != _normalized_identity(retailer):
                        raise ValueError("retailer adapter returned a result for a different retailer")
                    outcomes.append(outcome)
                    if outcome.check.status is RetailerStatus.CHECKED:
                        for offer in outcome.offers:
                            if (
                                _normalized_identity(offer.retailer) == _normalized_identity(retailer)
                                and (
                                    _offer_matches_request(offer.product, product)
                                    or _offer_matches_adapter_confirmation(offer.product, outcome.check.diagnostics)
                                )
                            ):
                                valid_offers.append(offer)
                except Exception as exc:
                    failed = _retailer_outcome(retailer_name, RetailerStatus.FAILED, f"Product check failed: {exc}")
                    failed.check.diagnostics = {"strategies": [], "candidates": [], "exact_product_found": False,
                                                "final_outcome": "discovery_or_fetch_failed", "error": str(exc)}
                    outcomes.append(failed)

            retailer_check = _combine_checks(retailer_name, outcomes, request.products)
            store.upsert_price_retailer_check(comparison_id, retailer_check)
            if retailer_check.status is RetailerStatus.CHECKED:
                for offer in valid_offers:
                    store.add_price_observation(comparison_id, offer)

        store.update_price_comparison(comparison_id, status=ComparisonStatus.COMPLETED.value, error=None)
    except Exception as exc:
        store.update_price_comparison(
            comparison_id,
            status=ComparisonStatus.FAILED.value,
            error=f"Comparison could not be completed: {exc}",
        )
    return store.get_price_comparison(comparison_id)
