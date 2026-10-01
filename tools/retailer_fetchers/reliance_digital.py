"""Best-effort Reliance Digital product-page adapter.

Search is used only to discover candidate product URLs. Prices are extracted
from a fetched product page's visible price region and checked against its
Product/Offer structured data; search snippets are never used as price input.
"""
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from threading import Lock
from time import monotonic
from typing import Callable
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import requests
from bs4 import BeautifulSoup

from models.price_comparison import PriceOffer, ProductIdentity, RetailerResult, RetailerStatus, normalize_capacity_value
from tools.retailer_fetchers.base import ProductTarget, RetailerFetchOutcome
from tools.web_search import search_web

_PRICE_SELECTORS = (".product-price", ".add-to-card-container__product-price", '[itemprop="price"]')
_DISCOUNT_PATTERN = re.compile(r"(?:\b\d+(?:\.\d+)?\s*%\s*off\b|\bsave\s*(?:₹|â‚¹|Rs\.?\s*|INR\s*)?[\d,]+(?:\.\d{1,2})?)", re.I)
_RUPEE_PRICE_PATTERN = re.compile(r"(?:₹|â‚¹|Rs\.?\s*|INR\s*)([\d,]+(?:\.\d{1,2})?)", re.I)
_AMOUNT_PATTERN = re.compile(r"(?<!\w)([\d,]+(?:\.\d{1,2})?)(?!\w)")
_RAM_PATTERN = re.compile(r"\b(\d+(?:\.\d+)?\s*(?:GB|TB))\s*RAM\b", re.I)
_CAPACITY_PATTERN = re.compile(r"\b\d+(?:\.\d+)?\s*(?:GB|TB)\b", re.I)
_STOP_QUERY_TERMS = {"buy", "price", "prices", "phone", "phones", "mobile", "smartphone", "online", "india", "reliance", "digital"}
_SITEMAP_INDEX_URL = "https://www.reliancedigital.in/sitemap.xml"
_ROBOTS_URL = "https://www.reliancedigital.in/robots.txt"
_SITEMAP_CACHE_TTL_SECONDS = 3600
_SITEMAP_CACHE_LOCK = Lock()
_SITEMAP_CACHE: tuple[float, list[str]] | None = None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _direct_loc(element) -> str | None:
    return next((child.text.strip() for child in element if _local_name(child.tag) == "loc" and child.text), None)


def _sitemap_locations(root, expected_kind: str) -> list[str]:
    if _local_name(root.tag) != expected_kind:
        raise ValueError(f"Expected sitemap {expected_kind}")
    child_kind = "sitemap" if expected_kind == "sitemapindex" else "url"
    return [loc for child in root if _local_name(child.tag) == child_kind if (loc := _direct_loc(child))]


def _slug_tokens(value: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", value.casefold())


def _has_sequence(tokens: list[str], wanted: list[str]) -> bool:
    if not wanted or len(wanted) > len(tokens):
        return False
    return any(tokens[index:index + len(wanted)] == wanted for index in range(len(tokens) - len(wanted) + 1))


def _brand_in_slug(tokens: list[str], brand: str) -> bool:
    brand_tokens = _slug_tokens(brand)
    compact_brand = "".join(brand_tokens)
    if _has_sequence(tokens, brand_tokens):
        return True
    # Retailer slugs commonly collapse a spaced brand, e.g. "One Plus" to
    # "oneplus". Accept that brand spelling while retaining token boundaries.
    return any("".join(tokens[index:index + size]) == compact_brand for size in (1, 2, 3) for index in range(len(tokens) - size + 1))


def _sitemap_candidate_score(url: str, target: ProductIdentity) -> int:
    tokens = _slug_tokens(urlparse(url).path.rsplit("/", 1)[-1])
    score = 0
    for capacity in (target.ram, target.storage):
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(GB|TB)\s*", capacity, re.I)
        if match and _has_sequence(tokens, [match.group(1).casefold(), match.group(2).casefold()]):
            score += 1
    return score


def _select_sitemap_candidates(urls: list[str], target: ProductIdentity, limit: int) -> list[str]:
    if target.model:
        identity_terms = _slug_tokens(target.model)
    else:
        identity_terms = _slug_tokens(target.model_number)
    selected = []
    seen = set()
    for url in urls:
        parsed = urlparse(url)
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        tokens = _slug_tokens(parsed.path.rsplit("/", 1)[-1])
        if (
            parsed.scheme not in {"http", "https"}
            or host != "reliancedigital.in"
            or parsed.query
            or not parsed.path.startswith("/product/")
            or not _brand_in_slug(tokens, target.brand)
            or not _has_sequence(tokens, identity_terms)
        ):
            continue
        normalized_url = parsed._replace(fragment="").geturl()
        if normalized_url not in seen:
            selected.append(normalized_url)
            seen.add(normalized_url)
    selected.sort(key=lambda url: _sitemap_candidate_score(url, target), reverse=True)
    return selected[:limit]


def _walk_json(value):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_json(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_json(nested)


def _product_schema(soup: BeautifulSoup) -> dict | None:
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            parsed = json.loads(script.string or script.get_text())
        except (json.JSONDecodeError, TypeError):
            continue
        for item in _walk_json(parsed):
            product_type = item.get("@type", [])
            types = [product_type] if isinstance(product_type, str) else product_type
            if any(str(value).lower() == "product" for value in types):
                return item
    return None


def _brand_name(value) -> str:
    if isinstance(value, dict):
        return str(value.get("name", "")).strip()
    return str(value or "").strip()


def _identity_from_schema(product: dict) -> ProductIdentity | None:
    name = re.sub(r"\s+", " ", str(product.get("name", ""))).strip()
    brand = _brand_name(product.get("brand"))
    if not name or not brand:
        return None
    model = _strip_brand_prefix(name, brand)
    model = re.split(r"\s*,\s*", model, maxsplit=1)[0].strip()
    model = re.split(r"\s+\d+(?:\.\d+)?\s*(?:GB|TB)\b", model, maxsplit=1, flags=re.I)[0].strip()
    model = re.sub(r"\s+(?:mobile phone|smartphone|mobile)$", "", model, flags=re.I).strip()
    model_number = str(product.get("mpn") or product.get("model") or "").strip()

    ram_match = _RAM_PATTERN.search(name)
    ram = re.sub(r"\s+", " ", ram_match.group(1)).upper() if ram_match else ""
    storage = ""
    for capacity in _CAPACITY_PATTERN.finditer(name):
        if ram_match and capacity.start() == ram_match.start(1):
            continue
        storage = re.sub(r"\s+", " ", capacity.group(0)).upper()
        break

    variant = ""
    for segment in name.split(","):
        cleaned = segment.strip()
        if not cleaned or _RAM_PATTERN.search(cleaned) or _CAPACITY_PATTERN.search(cleaned):
            continue
        if re.search(r"\b(?:mobile phone|smartphone|mobile)\b", cleaned, re.I):
            continue
        if _strip_brand_prefix(cleaned, brand) != cleaned or cleaned.casefold() == model.casefold():
            continue
        variant = cleaned
    try:
        return ProductIdentity(brand=brand, model=model, model_number=model_number, ram=ram, storage=storage, variant=variant)
    except ValueError:
        return None


def _money(value) -> Decimal | None:
    if value is None:
        return None
    cleaned = str(value).replace(",", "").strip()
    try:
        amount = Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() and amount > 0 else None


def _product_root(soup: BeautifulSoup):
    return soup.select_one(".product-right-container") or soup.select_one(".product-description-container") or soup.select_one("main") or soup


def _visible_price_text(soup: BeautifulSoup) -> tuple[str, set[Decimal]]:
    root = _product_root(soup)
    texts = []
    for selector in _PRICE_SELECTORS:
        for node in root.select(selector):
            text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
            if text:
                texts.append(text)
    combined = " | ".join(dict.fromkeys(texts))
    amounts = set()
    for value in _RUPEE_PRICE_PATTERN.findall(combined):
        parsed = _money(value)
        if parsed is not None:
            amounts.add(parsed)
    return combined, amounts


def _offer_data(product: dict, soup: BeautifulSoup) -> tuple[Decimal | None, str | None, str | None]:
    root = _product_root(soup)
    visible_text, visible_amounts = _visible_price_text(soup)
    offers = product.get("offers", [])
    offers = offers if isinstance(offers, list) else [offers]
    for offer in offers:
        if not isinstance(offer, dict) or str(offer.get("priceCurrency", "")).upper() != "INR":
            continue
        structured_price = _money(offer.get("price"))
        # Structured data alone is not considered an observed/displayed price.
        if structured_price is None or structured_price not in visible_amounts:
            continue
        seller = _brand_name(offer.get("seller")) or None
        break
    else:
        # Permit a visible rupee-denominated price where the page's Product
        # schema omits Offer, but only when one unambiguous amount is shown.
        if len(visible_amounts) != 1:
            return None, None, None
        structured_price = next(iter(visible_amounts))
        seller = None

    if seller is None:
        seller_node = root.select_one('[itemprop="seller"], .seller-name')
        if seller_node:
            seller = re.sub(r"\s+", " ", seller_node.get_text(" ", strip=True)).strip() or None
    discount = None
    discount_nodes = root.select('[class*="discount"], [class*="saving"], [class*="offer"]')
    for node in discount_nodes:
        node_text = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if _DISCOUNT_PATTERN.search(node_text):
            discount = node_text
            break
    return structured_price, seller, discount


def _normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def _normalize_brand(value: str) -> str:
    """Ignore casing and whitespace only; extended or prefix brands stay distinct."""
    return "".join(value.casefold().split())


def _strip_brand_prefix(name: str, brand: str) -> str:
    """Strip a leading brand whose spelling differs only by whitespace/case."""
    wanted = _normalize_brand(brand)
    if not wanted:
        return name
    matched = 0
    for index, char in enumerate(name):
        if char.isspace():
            continue
        if char.casefold() != wanted[matched:matched + 1]:
            return name
        matched += 1
        if matched == len(wanted):
            return name[index + 1:].lstrip(" -,:|")
    return name


def _matches(target: ProductTarget, identity: ProductIdentity, page_name: str) -> bool:
    candidate_name = _normalize(page_name)
    if isinstance(target, ProductIdentity):
        if _normalize_brand(target.brand) != _normalize_brand(identity.brand):
            return False
        if target.model and _normalize(target.model) not in candidate_name:
            return False
        if target.model_number and _normalize(target.model_number) != _normalize(identity.model_number):
            return False
        for field, requested, observed in (
            ("ram", target.ram, identity.ram),
            ("storage", target.storage, identity.storage),
            ("variant", target.variant, identity.variant),
        ):
            if not requested:
                continue
            if field in {"ram", "storage"}:
                requested_capacity = normalize_capacity_value(requested)
                observed_capacity = normalize_capacity_value(observed)
                if requested_capacity is not None or observed_capacity is not None:
                    if requested_capacity != observed_capacity:
                        return False
                    continue
            if _normalize(requested) != _normalize(observed):
                return False
        return bool(target.model or (target.model_number and identity.model_number))
    requested_terms = [term for term in _normalize(target).split() if term not in _STOP_QUERY_TERMS]
    return bool(requested_terms) and all(term in candidate_name for term in requested_terms)


def _match_rejection_reason(target: ProductTarget, identity: ProductIdentity, page_name: str) -> str | None:
    """Explain the existing strict matcher without changing its acceptance rules."""
    if not isinstance(target, ProductIdentity):
        return None if _matches(target, identity, page_name) else "model_mismatch"
    if _normalize_brand(target.brand) != _normalize_brand(identity.brand):
        return "brand_mismatch"
    if target.model and _normalize(target.model) not in _normalize(page_name):
        return "model_mismatch"
    if target.model_number and _normalize(target.model_number) != _normalize(identity.model_number):
        return "model_number_mismatch"
    for field, requested, observed in (("ram", target.ram, identity.ram), ("storage", target.storage, identity.storage), ("variant", target.variant, identity.variant)):
        if not requested:
            continue
        if field in {"ram", "storage"}:
            requested_capacity = normalize_capacity_value(requested)
            observed_capacity = normalize_capacity_value(observed)
            if requested_capacity is not None or observed_capacity is not None:
                if requested_capacity != observed_capacity:
                    return f"{field}_mismatch"
                continue
        if _normalize(requested) != _normalize(observed):
            return f"{field}_mismatch"
    if not (target.model or (target.model_number and identity.model_number)):
        return "model_mismatch"
    return None


def _signature(identity: ProductIdentity) -> tuple[str, ...]:
    return tuple(_normalize(getattr(identity, key)) for key in ("brand", "model", "model_number", "ram", "storage", "variant"))


class RelianceDigitalFetcher:
    """Fetch Reliance Digital product detail pages discovered from URL-only search results."""

    retailer = "Reliance Digital"

    def __init__(
        self,
        searcher: Callable = search_web,
        http_get: Callable = requests.get,
        timeout: int = 12,
        max_candidates: int = 5,
        sitemap_get: Callable = requests.get,
    ):
        self.searcher = searcher
        self.http_get = http_get
        self.timeout = timeout
        self.max_candidates = max_candidates
        self.sitemap_get = sitemap_get

    def _check(self, status: RetailerStatus, message: str, source_url: str | None = None, diagnostics=None) -> RetailerFetchOutcome:
        return RetailerFetchOutcome(RetailerResult(self.retailer, status, message=message, source_url=source_url, diagnostics=diagnostics), [])

    def _queries(self, target: ProductTarget) -> list[str]:
        if isinstance(target, ProductIdentity):
            identity_parts = [target.brand, target.model, target.model_number, target.variant]
            model = " ".join(part.strip() for part in identity_parts if part.strip())
            specs = [part.strip() for part in (target.ram, target.storage) if part.strip()]
            full = " ".join(part for part in (model, *specs) if part)
            query_terms = []
            if model and specs:
                quoted_model = f'"{target.brand} {target.model}"'.strip()
                ram = re.sub(r"\s*GB$", " GB RAM", target.ram, flags=re.I)
                storage = re.sub(r"\s*GB$", " GB", target.storage, flags=re.I)
                exact_specs = " ".join(f'"{part}"' for part in (ram, storage) if part.strip())
                query_terms.append(f'site:reliancedigital.in/product {quoted_model} {exact_specs}')
            if full:
                query_terms.append(f"site:reliancedigital.in/product {full}")
            if model:
                query_terms.append(f'site:reliancedigital.in "{target.brand} {target.model}"')
        else:
            query_terms = [f"site:reliancedigital.in/product {target.strip()}"] if isinstance(target, str) and target.strip() else []
        queries = list(dict.fromkeys(query_terms))
        if not queries:
            raise ValueError("product identity or query target is required")
        return queries

    def _query(self, target: ProductTarget) -> str:
        """Backward-compatible access to the most specific discovery query."""
        return self._queries(target)[0]

    def _load_public_product_sitemap_urls(self) -> list[str]:
        """Read only Reliance Digital's robots-listed public product sitemaps."""
        global _SITEMAP_CACHE
        with _SITEMAP_CACHE_LOCK:
            now = monotonic()
            if _SITEMAP_CACHE is not None and now - _SITEMAP_CACHE[0] < _SITEMAP_CACHE_TTL_SECONDS:
                return list(_SITEMAP_CACHE[1])

            headers = {"User-Agent": "MarketScoutAI/1.0"}

            def get_public_text(url: str):
                response = self.sitemap_get(url, headers=headers, timeout=self.timeout)
                response.raise_for_status()
                return response

            robots_response = get_public_text(_ROBOTS_URL)
            robots = RobotFileParser()
            robots.parse(robots_response.text.splitlines())
            sitemap_urls = [
                line.split(":", 1)[1].strip()
                for line in robots_response.text.splitlines()
                if line.strip().casefold().startswith("sitemap:")
            ]
            index_url = next((url for url in sitemap_urls if url == _SITEMAP_INDEX_URL), None)
            if not index_url or not robots.can_fetch(headers["User-Agent"], index_url):
                raise ValueError("robots.txt does not publish an accessible Reliance Digital sitemap index")

            index_response = get_public_text(index_url)
            index_root = ElementTree.fromstring(index_response.content)
            product_sitemaps = []
            for url in _sitemap_locations(index_root, "sitemapindex"):
                parsed = urlparse(url)
                if (
                    parsed.scheme == "https"
                    and parsed.hostname == "www.reliancedigital.in"
                    and parsed.path.startswith("/sitemap/products/")
                    and parsed.path.endswith(".xml")
                    and not parsed.query
                    and robots.can_fetch(headers["User-Agent"], url)
                ):
                    product_sitemaps.append(url)
            if not product_sitemaps:
                raise ValueError("No robots-allowed Reliance Digital product sitemaps were listed")

            product_urls = []
            sitemap_failures = []
            for sitemap_url in product_sitemaps:
                try:
                    response = get_public_text(sitemap_url)
                    root = ElementTree.fromstring(response.content)
                    for url in _sitemap_locations(root, "urlset"):
                        parsed = urlparse(url)
                        if (
                            parsed.scheme == "https"
                            and parsed.hostname == "www.reliancedigital.in"
                            and parsed.path.startswith("/product/")
                            and not parsed.query
                            and robots.can_fetch(headers["User-Agent"], url)
                        ):
                            product_urls.append(url)
                except Exception as exc:
                    sitemap_failures.append(f"{sitemap_url}: {exc}")
            if not product_urls and sitemap_failures:
                raise RuntimeError("Could not read Reliance Digital product sitemaps: " + "; ".join(sitemap_failures))

            # Deduplicate the cached catalog while preserving sitemap order.
            product_urls = list(dict.fromkeys(product_urls))
            _SITEMAP_CACHE = (monotonic(), product_urls)
            return list(product_urls)

    def fetch(self, target: ProductTarget) -> RetailerFetchOutcome:
        sitemap_error = None
        strategies = []
        candidate_map = {}
        try:
            sitemap_urls = self._load_public_product_sitemap_urls()
            urls = _select_sitemap_candidates(sitemap_urls, target, self.max_candidates) if isinstance(target, ProductIdentity) else []
            strategies.append({"source": "sitemap", "descriptor": _SITEMAP_INDEX_URL, "success": True, "candidate_count": len(urls), "error": None})
            for url in urls:
                candidate_map[url] = {"url": url, "discovered_by": ["sitemap"], "fetched": False, "http_status": None,
                                      "extracted_identity": None, "match": "not_evaluated", "rejection_reason": None, "error": None}
        except Exception as exc:
            sitemap_error = str(exc)
            urls = []
            strategies.append({"source": "sitemap", "descriptor": _SITEMAP_INDEX_URL, "success": False, "candidate_count": 0, "error": sitemap_error})

        if not urls:
            queries = self._queries(target)
            result_sets = []
            search_errors = []
            query_results = []
            for query in queries:
                try:
                    found = self.searcher(query, max_results=self.max_candidates) or []
                    result_sets.append(found)
                    query_results.append((query, found))
                    valid_count = sum(1 for item in found if self._valid_product_url(item.get("url", "")))
                    strategies.append({"source": "targeted_search", "descriptor": query, "success": True, "candidate_count": valid_count, "error": None})
                except Exception as exc:
                    search_errors.append(str(exc))
                    strategies.append({"source": "targeted_search", "descriptor": query, "success": False, "candidate_count": 0, "error": str(exc)})

            # Preserve existing interleaving and URL deduplication behavior.
            search_results = []
            for rank in range(self.max_candidates):
                for result_set in result_sets:
                    if rank < len(result_set):
                        search_results.append(result_set[rank])
            urls = []
            for result in search_results:
                url = str(result.get("url", "")).strip()
                if self._valid_product_url(url) and url not in urls:
                    urls.append(url)
            for query, found in query_results:
                for result in found:
                    url = str(result.get("url", "")).strip()
                    if self._valid_product_url(url) and url in urls:
                        item = candidate_map.setdefault(url, {"url": url, "discovered_by": ["targeted_search"], "discovery_descriptors": [], "fetched": False, "http_status": None,
                                      "extracted_identity": None, "match": "not_evaluated", "rejection_reason": None, "error": None})
                        if query not in item["discovery_descriptors"]:
                            item["discovery_descriptors"].append(query)

        def diagnostic(final_outcome, exact=False):
            return {"strategies": strategies, "candidates": list(candidate_map.values()), "exact_product_found": exact,
                    "final_outcome": final_outcome}

        if not urls:
            all_search_failed = bool(search_errors) and not result_sets
            detail = f"Product URL discovery failed: {'; '.join(search_errors)}" if all_search_failed else None
            if sitemap_error and detail:
                detail = f"Public sitemap discovery failed: {sitemap_error}; {detail}"
            if detail:
                return self._check(RetailerStatus.FAILED, detail, diagnostics=diagnostic("discovery_or_fetch_failed"))
            message = "No matching product URL was found in the public sitemap or targeted search results."
            if sitemap_error:
                message = f"Public sitemap discovery failed; targeted search returned no matching product page: {sitemap_error}"
            return self._check(RetailerStatus.UNAVAILABLE, message, diagnostics=diagnostic("not_found_through_available_public_discovery"))

        offers = []
        parsed_pages = []
        identity_checked = False
        checked_source_url = None
        failures: list[tuple[RetailerStatus, str, str]] = []
        for url in urls[:self.max_candidates]:
            candidate_diag = candidate_map[url]
            try:
                response = self.http_get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=self.timeout)
                candidate_diag["fetched"] = True
                candidate_diag["http_status"] = getattr(response, "status_code", None)
                response.raise_for_status()
                final_url = getattr(response, "url", url) or url
                final_host = (urlparse(final_url).hostname or "").lower().removeprefix("www.")
                if final_host != "reliancedigital.in" or not urlparse(final_url).path.startswith("/product/"):
                    candidate_diag.update({"match": "rejected", "rejection_reason": "fetch_failure", "error": "Product page redirected outside the retailer product site."})
                    failures.append((RetailerStatus.BLOCKED, "Product page redirected outside the retailer product site.", final_url))
                    continue
                response.encoding = getattr(response, "apparent_encoding", None) or getattr(response, "encoding", None) or "utf-8"
                soup = BeautifulSoup(response.text, "html.parser")
                product_data = _product_schema(soup)
                if not product_data:
                    candidate_diag.update({"match": "rejected", "rejection_reason": "page_parsing_failure", "error": "Product identity markup was not available on the page."})
                    failures.append((RetailerStatus.FAILED, "Product identity markup was not available on the page.", final_url))
                    continue
                identity = _identity_from_schema(product_data)
                if not identity:
                    candidate_diag.update({"match": "rejected", "rejection_reason": "page_parsing_failure", "error": "Could not verify the product identity on the page."})
                    failures.append((RetailerStatus.FAILED, "Could not verify the product identity on the page.", final_url))
                    continue
                candidate_diag["extracted_identity"] = identity.to_dict()
                identity_checked = True
                checked_source_url = final_url
                page_name = str(product_data.get("name", ""))
                reason = _match_rejection_reason(target, identity, page_name)
                if reason:
                    candidate_diag.update({"match": "rejected", "rejection_reason": reason})
                    continue
                candidate_diag.update({"match": "matched", "rejection_reason": None})
                price, seller, discount = _offer_data(product_data, soup)
                parsed_pages.append((identity, final_url, price, seller, discount))
            except requests.HTTPError as exc:
                response = exc.response
                code = getattr(response, "status_code", None)
                candidate_diag.update({"http_status": code, "match": "rejected", "rejection_reason": "fetch_failure", "error": f"HTTP {code or 'error'}"})
                status = RetailerStatus.BLOCKED if code in {401, 403, 407, 429, 503} else RetailerStatus.UNAVAILABLE if code in {404, 410} else RetailerStatus.FAILED
                failures.append((status, f"Retailer product page returned HTTP {code or 'error'}.", url))
            except requests.RequestException as exc:
                candidate_diag.update({"match": "rejected", "rejection_reason": "fetch_failure", "error": str(exc)})
                failures.append((RetailerStatus.FAILED, f"Could not fetch retailer product page: {exc}", url))
            except Exception as exc:
                candidate_diag.update({"match": "rejected", "rejection_reason": "page_parsing_failure", "error": str(exc)})
                failures.append((RetailerStatus.FAILED, f"Could not parse retailer product page: {exc}", url))

        distinct = {_signature(item[0]) for item in parsed_pages}
        if len(distinct) > 1:
            return self._check(RetailerStatus.CHECKED, "Multiple product variants matched; specify RAM, storage, or variant to disambiguate.", diagnostics=diagnostic("ambiguous_product_variants", True))
        for identity, source_url, price, seller, discount in parsed_pages:
            if price is not None:
                offers.append(PriceOffer(self.retailer, identity, price, source_url, currency="INR", seller=seller,
                                         discount=discount, observed_at=datetime.now(timezone.utc).isoformat()))
        if offers:
            return RetailerFetchOutcome(RetailerResult(self.retailer, RetailerStatus.CHECKED, source_url=offers[0].source_url,
                                                       diagnostics=diagnostic("exact_product_found", True)), offers)
        if parsed_pages:
            return self._check(RetailerStatus.CHECKED, "Exact product found, but no displayed price was available.", parsed_pages[0][1], diagnostic("exact_product_found", True))
        if failures and not identity_checked:
            statuses = {item[0] for item in failures}
            status = RetailerStatus.BLOCKED if statuses == {RetailerStatus.BLOCKED} else RetailerStatus.UNAVAILABLE if statuses == {RetailerStatus.UNAVAILABLE} else RetailerStatus.FAILED
            if statuses <= {RetailerStatus.BLOCKED, RetailerStatus.UNAVAILABLE} and RetailerStatus.BLOCKED in statuses:
                status = RetailerStatus.BLOCKED
            final = "retailer_or_product_page_unavailable" if status is RetailerStatus.UNAVAILABLE else "discovery_or_fetch_failed"
            if any(candidate.get("rejection_reason") == "page_parsing_failure" for candidate in candidate_map.values()):
                final = "product_page_parse_failed"
            return self._check(status, failures[0][1], failures[0][2], diagnostic(final))
        if identity_checked:
            return self._check(RetailerStatus.CHECKED, "No exact product identity match was found.", checked_source_url, diagnostic("not_found_through_available_public_discovery"))
        return self._check(RetailerStatus.CHECKED, "No exact product identity match was found.", diagnostics=diagnostic("not_found_through_available_public_discovery"))

    @staticmethod
    def _valid_product_url(url: str) -> bool:
        parsed = urlparse(str(url).strip())
        host = (parsed.hostname or "").lower().removeprefix("www.")
        return parsed.scheme in {"http", "https"} and host == "reliancedigital.in" and parsed.path.startswith("/product/")
