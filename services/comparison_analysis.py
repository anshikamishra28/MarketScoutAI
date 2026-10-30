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


from services.product_intelligence import (
    calculate_unit_price,
    currency_symbol,
    generate_executive_verdict,
    generate_safe_retailer_search_links,
    identify_retailer,
    parse_pack_or_variant,
)


@dataclass
class ComparisonAnalysis:
    schema_version: int
    comparison_id: str
    attributes: list[AttributeAnalysis]
    unresolved_information: list[str]
    verdict: dict[str, Any] | None = None
    product_cards: list[dict[str, Any]] = field(default_factory=list)
    variants: list[dict[str, Any]] = field(default_factory=list)
    retailer_offers: list[dict[str, Any]] = field(default_factory=list)

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
            else:
                usable_observations = [
                    item for item in found
                    if item.get("raw_value") not in (None, "", "Not verified", "unresolved")
                ]
                if not usable_observations:
                    complete = False
                    entry.status = "unresolved"
                    entry.note = "Observations contain no usable non-empty value."
            if entry.status != "observed":
                complete = False
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

    req_context = data.get("request", {}).get("context") if isinstance(data.get("request"), dict) else {}
    category = req_context.get("category") if isinstance(req_context, dict) else None

    # 1. Product Cards
    product_cards = []
    discovered_variants = []
    retailer_offers = []

    for entity in entities:
        if not isinstance(entity, dict):
            continue
        ekey = entity.get("key", "")
        ename = entity.get("display_name", ekey)
        entity_obs = [obs for obs in observations if isinstance(obs, dict) and obs.get("entity_key") == ekey]

        # Prices
        price_obs = [
            o for o in entity_obs
            if "price" in str(o.get("attribute_key", "")).lower() and o.get("normalized_value") is not None
        ]
        starting_price = None
        price_range = None
        primary_unit_price = None
        primary_variant = None
        verified_offers_count = 0

        if price_obs:
            prices_nums = []
            curr = price_obs[0].get("currency")
            sym = currency_symbol(curr)
            for o in price_obs:
                p_num = _number(o.get("normalized_value"))
                if p_num is not None:
                    prices_nums.append(p_num)
                    # Check unit price
                    raw_val = str(o.get("raw_value") or "")
                    ctx = o.get("context") or {}
                    quote = str(ctx.get("evidence_quote") or raw_val)
                    up = calculate_unit_price(p_num, quote, curr) or calculate_unit_price(p_num, raw_val, curr)
                    if up and not primary_unit_price:
                        primary_unit_price = up["display"]
                        primary_variant = up["pack_size"]

            if prices_nums:
                prices_nums.sort()
                min_p = prices_nums[0]
                max_p = prices_nums[-1]
                starting_price = f"{sym}{min_p:g}"
                if max_p > min_p:
                    price_range = f"{sym}{min_p:g} – {sym}{max_p:g}"

        # Verified offers count
        valid_urls = {
            o.get("source_url") for o in entity_obs
            if isinstance(o.get("source_url"), str) and o.get("source_url").startswith("http")
        }
        verified_offers_count = len(valid_urls)

        # Highlights
        highlights = []
        avail_obs = [o for o in entity_obs if "avail" in str(o.get("attribute_key", "")).lower()]
        if avail_obs and avail_obs[0].get("raw_value") not in (None, "", "Not verified", "unresolved"):
            highlights.append(f"Stock: {avail_obs[0].get('raw_value')}")

        spec_obs = [
            o for o in entity_obs
            if any(k in str(o.get("attribute_key", "")).lower() for k in ("spec", "proc", "ram", "flavour", "flavor", "feature"))
            and o.get("raw_value") not in (None, "", "Not verified", "unresolved")
        ]
        for s in spec_obs[:2]:
            highlights.append(f"{s.get('raw_value')}")

        product_cards.append({
            "entity_key": ekey,
            "display_name": ename,
            "starting_price": starting_price,
            "price_range": price_range,
            "primary_unit_price": primary_unit_price,
            "primary_variant": primary_variant,
            "verified_offer_count": verified_offers_count,
            "highlights": highlights,
        })

        # Variants extraction
        for o in entity_obs:
            raw_txt = str(o.get("raw_value") or "")
            ctx = o.get("context") or {}
            quote = str(ctx.get("evidence_quote") or raw_txt)
            parsed_q = parse_pack_or_variant(quote) or parse_pack_or_variant(raw_txt)
            if parsed_q:
                p_num = _number(o.get("normalized_value"))
                up = calculate_unit_price(p_num, parsed_q, o.get("currency")) if p_num else None
                variant_entry = {
                    "entity_key": ekey,
                    "entity_name": ename,
                    "variant_name": f"{ename} ({parsed_q.display})",
                    "pack_size": parsed_q.display,
                    "price": f"{currency_symbol(o.get('currency'))}{p_num:g}" if p_num else None,
                    "unit_price_display": up["display"] if up else None,
                    "source_url": o.get("source_url"),
                    "observed_at": o.get("observed_at"),
                }
                if not any(v["entity_key"] == ekey and v["pack_size"] == parsed_q.display for v in discovered_variants):
                    discovered_variants.append(variant_entry)

        # Retailer offers extraction
        for o in entity_obs:
            url = o.get("source_url")
            if not isinstance(url, str) or not url.startswith("http"):
                continue
            ret_name, is_product_url = identify_retailer(url)
            p_val = o.get("raw_value") if "price" in str(o.get("attribute_key", "")).lower() else None
            offer_entry = {
                "entity_key": ekey,
                "entity_name": ename,
                "retailer": ret_name,
                "price": str(p_val) if p_val else starting_price,
                "currency": o.get("currency"),
                "url": url,
                "is_verified_product_url": is_product_url,
                "link_type": "verified_listing" if is_product_url else "source_link",
                "label": "Verified Listing" if is_product_url else "Source Reference",
                "observed_at": o.get("observed_at"),
            }
            if not any(ro["entity_key"] == ekey and ro["url"] == url for ro in retailer_offers):
                retailer_offers.append(offer_entry)

        # Append safe search links for major retailers as transparent search fallbacks
        search_fallbacks = generate_safe_retailer_search_links(ename, category)
        for fb in search_fallbacks:
            retailer_offers.append({
                "entity_key": ekey,
                "entity_name": ename,
                "retailer": fb["retailer"],
                "price": "Check live price",
                "currency": None,
                "url": fb["url"],
                "is_verified_product_url": False,
                "link_type": "search_fallback",
                "label": fb["label"],
                "note": fb["note"],
                "observed_at": None,
            })

        # Collect unresolved entity-attribute information
    unresolved_information = []

    for analysis in analyses:
        for entity_result in analysis.entities:
            if entity_result.status != "observed":
                entity_name = entity_result.entity_name
                attribute_label = analysis.label
                unresolved_information.append(
                    f"{entity_name} — {attribute_label}"
                )

    # 2. Executive Verdict
    raw_analyses = _plain(analyses)
    verdict = generate_executive_verdict(entities, attributes, observations, raw_analyses, category=category)

    return ComparisonAnalysis(
        schema_version=1,
        comparison_id=str(data.get("comparison_id", "")),
        attributes=analyses,
        unresolved_information=list(dict.fromkeys(unresolved_information)),
        verdict=verdict,
        product_cards=product_cards,
        variants=discovered_variants,
        retailer_offers=retailer_offers,
    ).to_dict()
