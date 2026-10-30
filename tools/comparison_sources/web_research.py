"""Free public-web source adapter for generic comparison observations.

Search results are used only to discover page URLs. An observation is emitted
only after fetching readable page text and anchoring its raw value to that text.
"""
from datetime import datetime, timezone
import json
import re
from typing import Any, Callable
from urllib.parse import urldefrag, urlparse

from models.comparison import (
    ComparisonRequest,
    Observation,
    SourceCheck,
    SourceReference,
    SourceStatus,
    ValueType,
)
from tools.comparison_sources.base import ComparisonSourceOutcome


WEB_RESEARCH_SOURCE = SourceReference(
    key="web_research",
    name="Web Research",
    source_type="web",
)
_MAX_RESULTS_PER_QUERY = 2
_MAX_PAGES_PER_ENTITY = 5
_NON_PRICE_SPEC_UNITS = re.compile(
    r"(?:\b|\d)\s*(?:Gbps|Gb/s|Mbps|Mb/s|GHz|MHz|kHz|GB|TB|MB|KB|inches?|inch|\"|Hz|Wh|kWh|mAh|V|W|kW|mW|mm|cm|kg|g\b|lbs?|hours?|hrs?|mins?|sec\b|fps|nits|cores?|threads?|MP\b|megapixels?|px\b|ppi|dpi|rpm|dB|dBA)",
    re.I,
)
_PRICE = re.compile(
    r"(?:((?:₹|Rs\.?\s*|INR\b|\$|USD\b|€|EUR\b|£|GBP\b|¥|JPY\b)\s*(\d[\d,]*(?:\.\d{1,2})?))|((\d[\d,]*(?:\.\d{1,2})?)\s*(?:INR|USD|EUR|GBP|rupees?|cents?|pence)\b))",
    re.I,
)
_COMMERCIAL_AVAILABILITY = re.compile(
    r"\b(in\s*stock|out\s*of\s*stock|currently\s*unavailable|temporarily\s*out\s*of\s*stock|sold\s*out|pre-?order|backordered|on\s*backorder|discontinued)\b",
    re.I,
)
_LABELLED_AVAILABILITY = re.compile(
    r"(?:availability|stock\s*status|stock\s*level|stock)\s*:\s*(in\s*stock|out\s*of\s*stock|available|unavailable|currently\s*unavailable|sold\s*out|pre-?order|backordered)\b",
    re.I,
)
_MARKETING_AVAILABILITY_DISQUALIFIERS = re.compile(
    r"\b(?:now\s*available\s*in\s*(?:india|us|uk|europe|stores|markets?)|available\s*(?:with|in)\s*(?:\d+|intel|amd|m\d|core|snapdragon|oled|gb|tb|colors?|silver|black|graphite|platinum)|specs?\s*and\s*more|review|buyers?\s*guide)\b",
    re.I,
)
_NUTRITION_DIETARY_TERMS = re.compile(
    r"\b(?:nutrients?|essential\s*nutrients?|vitamins?|calcium|potassium|zinc|iron\b|sodium|protein|saturated\s*fat|trans\s*fat|cholesterol|carbohydrates?|calories?|dietary|daily\s*value|daily\s*allowance|nutrition\s*facts?|health\s*benefits?|bone\s*health|immune\s*system)\b",
    re.I,
)
_IRRELEVANT_EVENT_TERMS = re.compile(
    r"\b(?:heist|stolen|theft|robbery|smuggling|arrested|shares\s*fell|stock\s*price|market\s*cap|quarterly\s*revenue)\b",
    re.I,
)
_NUMBER = re.compile(r"(?<![\w/])([+-]?\d[\d,]*(?:\.\d+)?)\s*([A-Za-z%°][A-Za-z0-9%°./-]*)?")
_BLOCKED = re.compile(r"\b(401|403|429|captcha|access denied|robot check|blocked|forbidden)\b", re.I)


def _plain_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _identity_text(value: str) -> str:
    return re.sub(r"[^\w]+", " ", value.casefold()).strip()


def _entity_occurs(entity, content: str) -> bool:
    haystack = _identity_text(content)
    names = [entity.display_name, *entity.aliases]
    return any(_identity_text(name) and _identity_text(name) in haystack for name in names)


def _is_category_relevant(content: str, title: str, url: str, category: str | None) -> bool:
    if not category:
        return True
    cat_terms = [w.casefold() for w in re.findall(r"[A-Za-z0-9]+", category) if len(w) > 2]
    if not cat_terms:
        return True
    text_haystack = (title + " " + url + " " + content[:4000]).casefold()
    for term in cat_terms:
        base = term.rstrip("s") if len(term) > 3 else term
        if base in text_haystack:
            return True
    return False


def _currency_from(raw: str) -> str | None:
    if "₹" in raw or re.search(r"\b(?:INR|Rs\.?|rupees?)\b", raw, re.I):
        return "INR"
    if "$" in raw or re.search(r"\bUSD\b", raw, re.I):
        return "USD"
    if "€" in raw or re.search(r"\bEUR\b", raw, re.I):
        return "EUR"
    if "£" in raw or re.search(r"\b(?:GBP|pence|p\b)\b", raw, re.I):
        return "GBP"
    if "¥" in raw or re.search(r"\bJPY\b", raw, re.I):
        return "JPY"
    return None


def _numeric_value(raw: str, attribute_label: str) -> tuple[int | float, str | None, str | None, str] | None:
    """Safely normalize an explicitly quoted scalar, returning (normalized, unit, currency, concise_raw)."""
    if re.search(r"price|cost|fee|charge|pricing|rate|msrp|mrp", attribute_label, re.I):
        match = _PRICE.search(raw)
        if not match:
            return None
        matched_str = match.group(0).strip()
        end_pos = match.end()
        remainder = raw[end_pos:end_pos + 15]
        if _NON_PRICE_SPEC_UNITS.match(remainder) or _NON_PRICE_SPEC_UNITS.search(matched_str):
            return None
        number_text = match.group(2) or match.group(4)
        if not number_text:
            return None
        concise_raw = matched_str
    else:
        match = _NUMBER.search(raw)
        if not match:
            return None
        number_text = match.group(1)
        concise_raw = match.group(0).strip()

    try:
        number = float(number_text.replace(",", ""))
    except (ValueError, OverflowError):
        return None
    if not (number == number and abs(number) != float("inf")):
        return None
    normalized: int | float = int(number) if number.is_integer() else number
    unit = None
    if not re.search(r"price|cost|fee|charge|pricing|rate|msrp|mrp", attribute_label, re.I):
        if match.lastindex and match.lastindex >= 2:
            unit = match.group(2)
    return normalized, unit, _currency_from(raw), concise_raw


def _split_into_passages(content: str) -> list[str]:
    passages: list[str] = []
    for block in content.splitlines():
        text = _plain_text(block)
        if not text:
            continue
        sentences = re.split(r"(?<=[.!?])\s+", text)
        for s in sentences:
            s_clean = s.strip()
            if s_clean and len(s_clean) >= 4:
                passages.append(s_clean)
    return passages


def _is_single_entity_page(content: str, entity, all_entities: list | None = None) -> bool:
    if not all_entities or len(all_entities) <= 1:
        return True
    haystack = _identity_text(content)
    other_names = [other.display_name for other in all_entities if other.key != entity.key]
    return not any(_identity_text(name) and _identity_text(name) in haystack for name in other_names)


def _passage_matches_entity(passage: str, entity, all_entities: list | None = None) -> bool:
    haystack = _identity_text(passage)
    names = [entity.display_name, *entity.aliases]
    has_target = any(_identity_text(name) and _identity_text(name) in haystack for name in names)
    if all_entities and len(all_entities) > 1:
        other_names = [other.display_name for other in all_entities if other.key != entity.key]
        has_other = any(_identity_text(name) and _identity_text(name) in haystack for name in other_names)
        if has_other and not has_target:
            return False
    return has_target


def _deterministic_evidence(entity, content: str, attribute, all_entities: list | None = None) -> tuple[str, Any, str | None, str | None, str] | None:
    label = attribute.label
    passages = _split_into_passages(content)
    is_dedicated = _is_single_entity_page(content, entity, all_entities)

    for passage in passages:
        if not is_dedicated:
            if not _passage_matches_entity(passage, entity, all_entities):
                continue
        else:
            if all_entities and len(all_entities) > 1:
                other_names = [other.display_name for other in all_entities if other.key != entity.key]
                if any(_identity_text(name) and _identity_text(name) in _identity_text(passage) for name in other_names):
                    continue

        if re.search(r"price|cost|fee|charge|pricing|rate|msrp|mrp", label, re.I):
            num_info = _numeric_value(passage, label)
            if num_info:
                normalized, unit, currency, concise_raw = num_info
                raw_val = passage if len(passage) <= 50 else concise_raw
                return raw_val, normalized, unit, currency, passage

        elif re.search(r"availability|stock|in stock", label, re.I):
            if _MARKETING_AVAILABILITY_DISQUALIFIERS.search(passage) and not _LABELLED_AVAILABILITY.search(passage):
                continue
            labelled = _LABELLED_AVAILABILITY.search(passage)
            if labelled:
                status_raw = labelled.group(1).strip()
                status_norm = re.sub(r"\s+", "_", status_raw.casefold().replace("-", ""))
                return status_raw.title(), status_norm, None, None, passage
            comm = _COMMERCIAL_AVAILABILITY.search(passage)
            if comm:
                status_raw = comm.group(1).strip()
                status_norm = re.sub(r"\s+", "_", status_raw.casefold().replace("-", ""))
                return status_raw.title(), status_norm, None, None, passage

        elif re.search(r"quality|rating|grade|reliability|durability", label, re.I):
            if _NUTRITION_DIETARY_TERMS.search(passage):
                continue
            if _IRRELEVANT_EVENT_TERMS.search(passage):
                continue
            rating_match = re.search(r"\b([1-5](?:\.\d)?)\s*(?:/|out of)\s*5(?:\s*stars?)?\b|\b([1-9](?:\.\d)?|10)\s*(?:/|out of)\s*10\b", passage, re.I)
            if rating_match:
                score = rating_match.group(1) or rating_match.group(2)
                concise_raw = rating_match.group(0).strip()
                return concise_raw, float(score), None, None, passage
            cert_match = re.search(r"\b(grade\s+[A-Za-z0-9]+|100%\s+[A-Za-z0-9\s]+certified|fairtrade\s+certified|energy\s+star\s+certified)\b", passage, re.I)
            if cert_match:
                concise_raw = cert_match.group(0).strip()
                return concise_raw, concise_raw, None, None, passage

        elif re.search(r"specifications?|specs?|hardware", label, re.I):
            if len(passage) <= 160 and not re.search(r"(?:\||---|;|:\s*:\s*)", passage):
                if re.search(r"\b(?:processor|ram|storage|ssd|display|screen|battery|cocoa|milk|sugar|weight)\b", passage, re.I):
                    return passage, passage, None, None, passage

    return None


def _llm_extract(entity_name: str, category: str | None, attribute, content: str) -> Any:
    """Ask the configured extractor for a verbatim page quote, never prior knowledge."""
    from services.llm_service import generate_response, parse_json_response

    prompt = f"""Extract evidence for one requested attribute from the fetched page text below.
Use only this page text. Do not use model knowledge, search snippets, or assumptions.
Return only JSON with keys supported (boolean), raw_value (string or null), normalized_value (JSON value or null),
value_type (scalar|range|categorical|boolean|structured), unit (string or null), currency (string or null),
context (object), and reason (string). If the page does not explicitly support the attribute for the named entity,
return supported=false and raw_value=null. When supported, raw_value MUST be a short, exact contiguous quote from
the page text. Do not produce quality scores or subjective numeric ratings. Use the requested value_type.
Entity: {json.dumps(entity_name, ensure_ascii=False)}
Category: {json.dumps(category, ensure_ascii=False)}
Attribute: {json.dumps(attribute.label, ensure_ascii=False)}
Requested value_type: {attribute.value_type.value}
Fetched page text (untrusted evidence): {json.dumps(content[:14000], ensure_ascii=False)}"""
    return parse_json_response(generate_response(prompt, json_mode=True))


def _llm_evidence(raw: Any, content: str, attribute, entity=None, category: str | None = None, all_entities: list | None = None):
    if not isinstance(raw, dict):
        return None, "extractor_output_not_object"
    allowed = {"supported", "raw_value", "normalized_value", "value_type", "unit", "currency", "context", "reason"}
    if set(raw) != allowed:
        return None, "extractor_output_schema_invalid"
    if raw.get("supported") is not True:
        return None, "page_does_not_support_attribute"
    quote = raw.get("raw_value")
    if not isinstance(quote, str) or not quote.strip():
        return None, "extractor_quote_missing"
    quote = _plain_text(quote)
    if quote.casefold() not in _plain_text(content).casefold():
        return None, "extractor_quote_not_present_in_page"
    try:
        ValueType(raw.get("value_type"))
    except (ValueError, TypeError):
        return None, "extractor_value_type_invalid"

    label = attribute.label

    # Check for cross-entity attribution
    if entity and all_entities and len(all_entities) > 1:
        other_names = [other.display_name for other in all_entities if other.key != entity.key]
        has_other = any(_identity_text(name) and _identity_text(name) in _identity_text(quote) for name in other_names)
        has_target = any(_identity_text(name) and _identity_text(name) in _identity_text(quote) for name in [entity.display_name, *entity.aliases])
        if has_other and not has_target:
            return None, "extractor_quote_belongs_to_another_product"

    # Price validation
    if re.search(r"price|cost|fee|charge|pricing|rate|msrp|mrp", label, re.I):
        num_info = _numeric_value(quote, label)
        if num_info:
            normalized, unit, currency, concise_raw = num_info
            raw_val = quote if len(quote) <= 50 else concise_raw
            return (raw_val, normalized, unit, currency, quote), "llm_quote_validated"
        if attribute.value_type is ValueType.SCALAR or re.fullmatch(r"price", label.strip(), re.I):
            return None, "extractor_quote_is_not_valid_price"
        concise_raw = quote if len(quote) <= 160 else quote[:157] + "..."
        return (concise_raw, concise_raw, None, None, quote), "llm_quote_validated"

    # Availability validation
    if re.search(r"availability|stock|in stock", label, re.I):
        if _MARKETING_AVAILABILITY_DISQUALIFIERS.search(quote) and not _LABELLED_AVAILABILITY.search(quote):
            return None, "extractor_quote_is_marketing_copy_not_availability"
        labelled = _LABELLED_AVAILABILITY.search(quote)
        comm = _COMMERCIAL_AVAILABILITY.search(quote)
        if not labelled and not comm:
            return None, "extractor_quote_is_not_commercial_availability"
        status_raw = (labelled.group(1) if labelled else comm.group(1)).strip()
        status_norm = re.sub(r"\s+", "_", status_raw.casefold().replace("-", ""))
        return (status_raw.title(), status_norm, None, None, quote), "llm_quote_validated"

    # Quality validation
    if re.search(r"quality|rating|grade|reliability|durability", label, re.I):
        if _NUTRITION_DIETARY_TERMS.search(quote):
            return None, "extractor_quote_is_general_nutrition_not_quality"
        if _IRRELEVANT_EVENT_TERMS.search(quote):
            return None, "extractor_quote_is_irrelevant_event_not_quality"
        has_rating = bool(re.search(r"\b(?:\d(?:\.\d)?\s*(?:/|out of)\s*(?:5|10)|stars?|rated|rating|score|grade|certified|warranty|build|durab)\b", quote, re.I))
        if not has_rating and len(quote) > 100:
            return None, "extractor_quote_lacks_quality_signals"
        concise_raw = quote[:100].strip()
        return (concise_raw, concise_raw, None, None, quote), "llm_quote_validated"

    # Specifications validation
    if re.search(r"specifications?|specs?|hardware", label, re.I):
        if len(quote) > 160:
            sentences = re.split(r"(?<=[.!?])\s+", quote)
            short_quote = sentences[0].strip() if sentences else quote[:160].strip()
            if len(short_quote) > 160:
                short_quote = short_quote[:157] + "..."
            concise_raw = short_quote
        else:
            concise_raw = quote
        return (concise_raw, concise_raw, None, None, quote), "llm_quote_validated"

    # General scalar attribute
    if attribute.value_type is ValueType.SCALAR:
        num_info = _numeric_value(quote, label)
        if not num_info:
            return None, "extractor_quote_not_numeric_scalar"
        normalized, unit, currency, concise_raw = num_info
        raw_val = quote if len(quote) <= 50 else concise_raw
        return (raw_val, normalized, unit, currency, quote), "llm_quote_validated"

    # General categorical or structured
    concise_raw = quote if len(quote) <= 160 else quote[:157] + "..."
    normalized = concise_raw.casefold() if attribute.value_type is ValueType.CATEGORICAL else concise_raw
    unit = raw.get("unit") if isinstance(raw.get("unit"), str) else None
    currency = _currency_from(quote)
    return (concise_raw, normalized, unit, currency, quote), "llm_quote_validated"


def _blocked(error: str) -> bool:
    return bool(_BLOCKED.search(error or ""))


class WebResearchComparisonAdapter:
    """Search and fetch public pages for domain-neutral entity attributes."""

    source = WEB_RESEARCH_SOURCE
    default_when_unspecified = True

    def __init__(
        self,
        *,
        search: Callable | None = None,
        fetch: Callable | None = None,
        extract: Callable | None = None,
        max_pages_per_entity: int = _MAX_PAGES_PER_ENTITY,
    ):
        self._search = search
        self._fetch = fetch
        self._extract = extract
        self._max_pages = max(1, int(max_pages_per_entity))

    def _search_fn(self):
        if self._search is None:
            from tools.web_search import search_web
            self._search = search_web
        return self._search

    def _fetch_fn(self):
        if self._fetch is None:
            from tools.web_fetcher import fetch_document
            self._fetch = fetch_document
        return self._fetch

    def supports(self, request: ComparisonRequest, source: SourceReference) -> bool:
        return source.key == self.source.key and bool(request.entities and request.attributes)

    def check(self, request: ComparisonRequest, source: SourceReference) -> ComparisonSourceOutcome:
        if source.key != self.source.key:
            return ComparisonSourceOutcome(SourceCheck(source, SourceStatus.UNSUPPORTED,
                diagnostics={"reason": "This adapter only handles its declared source."}))
        if not request.entities or not request.attributes:
            return ComparisonSourceOutcome(SourceCheck(source, SourceStatus.UNSUPPORTED,
                diagnostics={"reason": "At least one entity and attribute are required."}))

        diagnostics: dict[str, list] = {"queries": [], "candidates": []}
        observations: list[Observation] = []
        fetched_any = False
        search_errors: list[str] = []
        fetch_errors: list[str] = []
        category = None
        if isinstance(request.context, dict):
            category_value = request.context.get("category")
            if isinstance(category_value, str):
                category = category_value.strip() or None
            if category is None:
                category_value = request.context.get("market") or request.context.get("country")
                category = category_value.strip() if isinstance(category_value, str) else None
        search_fn = self._search_fn()
        fetch_fn = self._fetch_fn()
        seen_pairs = set()

        for entity in request.entities:
            candidates: list[dict] = []
            entity_urls: set[str] = set()
            candidate_pairs: set[tuple[str, str]] = set()
            for attribute in request.attributes:
                query_parts = [entity.display_name, attribute.label]
                if category:
                    query_parts.append(category)
                query = " ".join(query_parts)
                query_diag = {"entity_key": entity.key, "attribute_key": attribute.key, "query": query,
                              "success": False, "candidate_count": 0}
                try:
                    results = search_fn(query, max_results=_MAX_RESULTS_PER_QUERY)
                    if not isinstance(results, list):
                        raise TypeError("web search returned a non-list result")
                    query_diag["success"] = True
                    for item in results:
                        if not isinstance(item, dict):
                            continue
                        url = item.get("url")
                        if not isinstance(url, str) or urlparse(url).scheme not in {"http", "https"} or not urlparse(url).netloc:
                            continue
                        url = urldefrag(url)[0]
                        if url in entity_urls:
                            pair_key = (url, attribute.key)
                            if pair_key in candidate_pairs:
                                continue
                        else:
                            entity_urls.add(url)
                            pair_key = (url, attribute.key)
                        candidate_pairs.add(pair_key)
                        candidate = {"entity": entity, "attribute": attribute, "url": url,
                                     "title": item.get("title") if isinstance(item.get("title"), str) else "",
                                     "query": query}
                        candidates.append(candidate)
                        query_diag["candidate_count"] += 1
                except Exception as exc:
                    message = str(exc) or exc.__class__.__name__
                    query_diag["error"] = message
                    search_errors.append(message)
                diagnostics["queries"].append(query_diag)
            selected_urls = set(list(dict.fromkeys(candidate["url"] for candidate in candidates))[:self._max_pages])
            candidates = [candidate for candidate in candidates if candidate["url"] in selected_urls]
            page_cache: dict[str, tuple[dict | None, str | None]] = {}
            for candidate in candidates:
                url, attribute = candidate["url"], candidate["attribute"]
                candidate_diag = {"entity_key": entity.key, "attribute_key": attribute.key,
                                  "url": url, "discovery": candidate["query"],
                                  "title": candidate["title"], "fetched": False,
                                  "match": "not_evaluated", "extraction": "not_evaluated"}
                if url not in page_cache:
                    try:
                        page = fetch_fn(url)
                        if isinstance(page, str):
                            page = {"content": page, "final_url": url}
                        if not isinstance(page, dict) or not isinstance(page.get("content"), str) or not page["content"].strip():
                            raise RuntimeError("fetcher returned no readable page content")
                        page_cache[url] = (page, None)
                        fetched_any = True
                    except Exception as exc:
                        message = str(exc) or exc.__class__.__name__
                        page_cache[url] = (None, message)
                        fetch_errors.append(message)
                page, fetch_error = page_cache[url]
                candidate_diag["fetched"] = page is not None
                if fetch_error:
                    candidate_diag["fetch_error"] = fetch_error
                    candidate_diag["fetch_status"] = "blocked" if _blocked(fetch_error) else "failed"
                    diagnostics["candidates"].append(candidate_diag)
                    continue
                assert page is not None
                content = page["content"]
                if not _entity_occurs(entity, content):
                    candidate_diag["match"] = "entity_name_not_in_page"
                    candidate_diag["extraction"] = "not_attempted"
                    diagnostics["candidates"].append(candidate_diag)
                    continue
                candidate_diag["match"] = "exact_name_or_alias_in_fetched_text"
                evidence = _deterministic_evidence(entity, content, attribute, request.entities)
                if evidence:
                    raw_value, normalized_value, unit, currency, evidence_quote = evidence
                    extraction_method = "deterministic_page_text"
                else:
                    try:
                        extractor = self._extract or _llm_extract
                        extracted = extractor(entity.display_name, category, attribute, content)
                        evidence, extraction_method = _llm_evidence(extracted, content, attribute, entity, category, request.entities)
                    except Exception as exc:
                        evidence, extraction_method = None, f"extractor_failed:{exc.__class__.__name__}"
                    if evidence:
                        raw_value, normalized_value, unit, currency, evidence_quote = evidence
                    else:
                        candidate_diag["extraction"] = extraction_method
                        diagnostics["candidates"].append(candidate_diag)
                        continue
                candidate_diag["extraction"] = extraction_method
                candidate_diag["evidence_quote"] = evidence_quote
                candidate_diag["raw_value"] = raw_value
                diagnostics["candidates"].append(candidate_diag)
                pair = (entity.key, attribute.key, url)
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                final_url = page.get("final_url")
                if not isinstance(final_url, str) or urlparse(final_url).scheme not in {"http", "https"}:
                    final_url = url
                observations.append(Observation(
                    entity_key=entity.key,
                    attribute_key=attribute.key,
                    source_key=self.source.key,
                    raw_value=raw_value,
                    normalized_value=normalized_value,
                    value_type=attribute.value_type,
                    unit=unit,
                    currency=currency,
                    observed_at=datetime.now(timezone.utc).isoformat(),
                    source_url=final_url,
                    context={"category": category, "query": candidate["query"],
                             "evidence_quote": evidence_quote, "extraction": extraction_method},
                ))

        requested_pairs = len(request.entities) * len(request.attributes)
        observed_pairs = {(item.entity_key, item.attribute_key) for item in observations}
        if observations:
            status = SourceStatus.CHECKED if len(observed_pairs) == requested_pairs else SourceStatus.PARTIAL
        elif fetched_any:
            status = SourceStatus.CHECKED
        elif not diagnostics["candidates"] and not search_errors:
            status = SourceStatus.UNAVAILABLE
        elif diagnostics["candidates"] and all(
            candidate.get("fetch_status") == "blocked" for candidate in diagnostics["candidates"]
        ):
            status = SourceStatus.BLOCKED
        elif search_errors or fetch_errors:
            status = SourceStatus.BLOCKED if (search_errors + fetch_errors) and all(_blocked(item) for item in search_errors + fetch_errors) else SourceStatus.FAILED
        else:
            status = SourceStatus.UNAVAILABLE
        check = SourceCheck(
            source=self.source,
            status=status,
            checked_at=datetime.now(timezone.utc).isoformat(),
            diagnostics={**diagnostics, "requested_pair_count": requested_pairs,
                         "observed_pair_count": len(observed_pairs),
                         "search_error_count": len(search_errors), "fetch_error_count": len(fetch_errors),
                         "search_snippets_used_as_observations": False},
            error=("Public search or page retrieval failed." if status in {SourceStatus.FAILED, SourceStatus.BLOCKED} else None),
        )
        if status not in {SourceStatus.CHECKED, SourceStatus.PARTIAL}:
            observations = []
        return ComparisonSourceOutcome(check=check, observations=observations)
