"""Bounded observe-evaluate-follow-up research loop."""
import re
import uuid
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from agents.research_planner import create_research_plan
from models.evidence import Evidence, classify_evidence_scope, classify_source, detect_conflicts, evaluate_evidence, geographic_relevance, score_evidence_quality
from tools.web_fetcher import fetch_document
from tools.web_search import search_web

MAX_ITERATIONS = 3
MAX_SOURCES = 15

_QUERY_STOPWORDS = {"about", "after", "analysis", "analyze", "before", "best", "credible", "current", "find", "for", "from", "latest", "market", "news", "overview", "recent", "report", "research", "sources", "the", "this", "under", "what", "with"}
_FACTUAL_SIGNAL = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s?%|(?:Rs\.?|INR|₹|\$|€)\s?\d|\b(?:percent|per cent|billion|million|crore|lakh|units|users|"
    r"launched|launches|announced|reported|according to|grew|growth|increased|declined|"
    r"fell|rose|reached|accounts for|priced at|survey(?:ed)?|"
    r"adopt(?:ed|ion)|leads|largest|became|revenue|sales|expects|forecast|plans to|"
    r"introduced|recorded|registered|delivered|shipped|sold|represented|stood at|"
    r"prefer(?:s|red)?|is expected to|entered the market|moving upmarket|shift(?:ing)? to premium|analysts say|buyers increasingly)\b)",
    re.I,
)
_BOILERPLATE_SENTENCE = re.compile(r"(?:sign up|subscribe|cookie settings|accept cookies|follow us|share this|read more|latest news|trending now|most read|advertisement|sponsored content)", re.I)
_EDITORIAL_SENTENCE = re.compile(r"\b(?:worth your|what you value|brands that matter|this (?:article|ranking|report|guide)|\d{4} ranking|ranking breaks down|breaks down the|in this article|our picks?|we recommend|you should|must[- ]buy|top\s+\d+|ultimate guide|everything you need|best .{0,30} to buy|according to our review|our verdict|in our opinion|we believe|great choice|perfect for|choosing among|we weighed|we examined|we ranked|we covered|six pillars|our ranking|the list|shaped the list|criteria (?:for|used)|the ranking)\b", re.I)
_PROMOTIONAL_PHRASE = re.compile(r"\b(?:true engine of growth|undeniable global force|global force|no small task|world[- ]class|game[- ]changer|iconic|revolutionary|unmatched|best)\b", re.I)
_SMARTPHONE_CONTEXT = re.compile(r"\b(?:smartphones?|mobile phones?|handsets?|cell phones?|phones?|devices?|5g)\b", re.I)
_SMARTPHONE_CONTEXT_PROXY = re.compile(r"\b(?:smartphone|phone|handset|device)?\s*(?:shipments?|shipment volumes?|market share|unit volumes?)\b", re.I)
_OTHER_PRODUCT = re.compile(r"\b(?:accessor(?:y|ies)(?: market)?|sunscreen|spf\s*\d|cosmetics?|skincare|beauty products?|laptops?|notebooks?|computers?|pcs?|televisions?|tvs?|appliances?|refrigerators?|washing machines?|air conditioners?|digital cameras?|camera market|tablets?|smartwatches?|wearables?|earbuds?|headphones?|chargers?|phone cases?|power banks?|routers?|game consoles?|printers?|app development|software development services?)\b", re.I)
_GENERIC_WIFI_DEVICE_STAT = re.compile(r"\bwi-?fi\b.{0,80}\bdevices?\b|\bdevices?\b.{0,80}\bwi-?fi\b", re.I)
_PROMOTIONAL_CLAIM = re.compile(r"\b(?:dominates? the affordable tier|powers? (?:indian|india) sales|will keep pushing .{0,70} into more hands|will continue to drive|will keep driving|multi[- ]faceted narrative|narrative, driven|continues? to push|quite powerful option|powerful option for many|undisputed champion|champion in pure value|clear picture of its natural home|strong performance[- ]focused options|quite powerful|respectable for a)\b", re.I)
_CONCRETE_FACT = re.compile(r"(?:\b\d[\d,.]*\s?%(?!\w)|\b\d[\d,.]*\s+(?:percent|per cent|cagr)\b|\b\d[\d,.]*\s+(?:million|billion|crore|lakh|units|shipments|devices|buyers|users)\b|(?:Rs\.?|INR|\u20b9|\$|\u20ac)\s?\d|\b(?:survey|poll|study|research|report)\b.{0,100}\b(?:found|reported|indicated|showed|estimated|measured)\b|\b(?:analysts?|IDC|Counterpoint|Canalys|Omdia)\s+(?:say|said|found|reported|estimate|estimated|project|projected)\b|\b20\d{2}\b.{0,80}\b(?:buyers?|consumers?|users?)\b.{0,60}\b(?:prefer\w*|adopt\w*|shift\w*|chose)\b)", re.I)
_QUESTION_OR_HEADING = re.compile(r"^(?:which|what|how|when|where|why|who|should|can you|read more)\b", re.I)
_INCOMPLETE_END = re.compile(r"(?:\b(?:at|of|and|or|but|with|from|to|for|by|in|on|around|about|between|including|such as|would|could|should|which|that|who|is|are|was|were|has|have)\.?|(?:\u20b9|\u20ac|\$|Rs\.?|INR)\s*|(?:Rs\.?|INR)\s+[\d,]+[,\.]|\.{2,}|…)$", re.I)
_INCOMPLETE_START = re.compile(r"^(?:would|could|should|and|or|but|which|that|while|whereas|to|at|of|from|with)\b")
_EXTRACTION_ARTIFACT = re.compile(r"(?:\ufffd|Ã.|â€|â‚|\|{2,}|_{4,})")


def _normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.rstrip("/") or "/"
    query = urlencode([(k, v) for k, v in parse_qsl(parsed.query) if not k.lower().startswith("utm_") and k.lower() not in {"gclid", "fbclid", "oc", "ved"}])
    return urlunparse((parsed.scheme.lower(), host, path, "", query, ""))


_FOLLOWUP_STOPWORDS = _QUERY_STOPWORDS | {"highlighting", "split", "between", "platform", "platforms", "information", "requirement", "sales", "data", "distribution", "research", "where", "which", "such", "like", "their", "into", "through", "across", "about", "based", "include", "including"}


def generate_followup_queries(research_question: str, missing_requirements: list[str], max_queries_per_requirement: int = 3) -> list[str]:
    """Turn each uncovered plan requirement into focused, query-shaped searches."""
    now_year = datetime.now(timezone.utc).year
    years = re.findall(r"\b20\d{2}\b", research_question)
    years = list(dict.fromkeys(years)) if years else [str(now_year), str(now_year - 1)]
    anchors = [w for w in re.findall(r"[\w₹$€-]+", research_question.lower()) if len(w) >= 3 and w not in _FOLLOWUP_STOPWORDS]
    anchors = list(dict.fromkeys(anchors))[:6]
    anchor_text = " ".join(anchors)
    queries = []
    for requirement in missing_requirements:
        core = [w for w in re.findall(r"[\w₹$€-]+", requirement.lower()) if len(w) >= 3 and w not in _FOLLOWUP_STOPWORDS]
        core_text = " ".join(dict.fromkeys(core)) or requirement.strip()
        lower = requirement.lower()
        if re.search(r"channel|distribution|online|offline|e-commerce|ecommerce|retail", lower):
            focus = [f"{anchor_text} {core_text} {years[0]} sales data", f"{anchor_text} online vs offline sales share {years[0]}", f"{anchor_text} e-commerce platforms offline retail {years[-1]} channel share"]
        elif re.search(r"price|pricing|cost|afford|segment", lower):
            focus = [f"{anchor_text} {core_text} {years[0]} product prices", f"{anchor_text} price ranges by segment {years[-1]}", f"{anchor_text} pricing market data {years[0]}"]
        elif re.search(r"compet|brand|position|player", lower):
            focus = [f"{anchor_text} {core_text} {years[0]} market share", f"{anchor_text} competitor comparison positioning {years[-1]}", f"{anchor_text} leading companies segment share {years[0]}"]
        elif re.search(r"consumer|customer|buyer|preference|behavior|behaviour", lower):
            focus = [f"{anchor_text} {core_text} {years[0]} survey findings", f"{anchor_text} consumer purchase preferences data {years[-1]}", f"{anchor_text} customer adoption research {years[0]}"]
        elif re.search(r"trend|adoption|launch|growth", lower):
            focus = [f"{anchor_text} {core_text} {years[0]} data", f"{anchor_text} adoption trend evidence {years[-1]}", f"{anchor_text} recent launches growth report {years[0]}"]
        else:
            focus = [f"{anchor_text} {core_text} {years[0]} data", f"{anchor_text} {core_text} evidence {years[-1]}", f"{anchor_text} {core_text} industry research statistics"]
        queries.extend(focus[:max_queries_per_requirement])
    return list(dict.fromkeys(" ".join(q.split()) for q in queries if q.strip()))


_REQUIREMENT_TERMS = {
    "market overview": {"market", "growth", "size", "share", "revenue"},
    "competitors and positioning": {"competitor", "brand", "position", "company", "share"},
    "pricing and segments": {"price", "pricing", "cost", "segment", "budget"},
    "consumer preferences": {"consumer", "customer", "buyer", "preference", "survey"},
    "recent trends": {"trend", "launch", "growth", "adoption", "shift"},
    "opportunities and risks": {"opportunity", "risk", "challenge", "gap"},
}


def _requirement_kind(requirement: str) -> str:
    value = requirement.lower()
    if value.startswith("macro / context:") or re.search(r"macroeconomic|economic factors", value):
        return "macro_context"
    if re.search(r"technology|tech(?:nology)? adoption|5g adoption|ai adoption", value) and re.search(r"adoption|penetration|trend", value):
        return "technology_adoption"
    if re.search(r"sales|shipment|volume|revenue", value) and re.search(r"growth|increase|decline|change", value):
        return "target_sales_growth"
    if re.search(r"offer|exchange|emi|financ|discount|cashback|promotion", value):
        return "offers"
    if re.search(r"brand.{0,30}share|share.{0,30}brand", value):
        return "brand_share"
    if re.search(r"channel|distribution|online|offline|e-commerce|ecommerce|retail", value):
        return "channel"
    if re.search(r"consumer|customer|buyer|preference|behavior|behaviour|survey", value):
        return "consumer"
    if re.search(r"top[- ]selling|best[- ]selling|models under|smartphone models|model prices|current smartphone model pricing|smartphone model pricing|model pricing under", value):
        return "target_models"
    if re.search(r"20\s*,?\s*000.{0,20}30\s*,?\s*000|20\s*k.{0,15}30\s*k|price band|price segment|under.{0,10}30", value):
        return "target_band"
    if re.search(r"price|pricing|cost|model price|price list", value):
        return "pricing"
    if re.search(r"compet|brand|player|position", value):
        return "competition"
    if re.search(r"risk|challenge|opportun", value):
        return "risk"
    if re.search(r"trend|adoption|launch|growth|shipment|market size|share|revenue", value):
        return "market_data"
    if re.search(r"market overview|market size|market growth", value):
        return "market_data"
    return "general"


_MEASURE = re.compile(r"\b\d[\d,.]*\s?%(?!\w)|\b\d[\d,.]*\s+(?:percent|per cent|million|billion|crore|lakh|units|shipments|users|buyers)\b|(?:Rs\.?|INR|\u20b9|\$|\u20ac)\s?\d|\b(?:market share|shipment share|revenue share|ASP)\b", re.I)
_BAND_METRIC = re.compile(r"\b(?:shipments?|units?|market share|brand share|shipment share|revenue share|share|growth|declin\w*|YoY|CAGR|market size|sales volume)\b", re.I)
_SURVEY_FINDING = re.compile(r"\b(?:survey|poll|consumer study|buyer study|consumer research)\b.{0,120}\b(?:found|reported|showed|indicated|prefer\w*|willing|expect\w*)\b|\b(?:survey|poll)\b.{0,100}\b(?:%|percent|per cent)\b", re.I)
_SPECULATIVE_MODEL_PRICE = re.compile(r"\b(?:upcoming|forthcoming|rumou?red?|leak(?:ed)?|working on|expected to be priced|could be priced|may be priced|will be priced|plans? to launch|set to debut)\b", re.I)
_ANALYTICAL_EDITORIAL = re.compile(r"\b(?:pretty good|curated list|curated selection|we have curated|we hve curated|list of (?:the )?(?:top|best)|best .{0,35}phones? under|reliable smartphone under|great smartphone under)\b", re.I)
_PRICE_RANGE = re.compile(r"(?:₹|Rs\.?\s*|INR\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k)?\s*(?:-|–|to)\s*(?:₹|Rs\.?\s*|INR\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k)?", re.I)
_SUB30_CONTEXT = re.compile(r"\b(?:sub[- ]?|under|below|less than)\s*(?:₹|Rs\.?\s*|INR\s*)?30\s*,?\s*000\b|\b(?:sub[- ]?|under|below|less than)\s*(?:₹|Rs\.?\s*|INR\s*)?30\s*k\b", re.I)


def _range_values(claim: str) -> list[tuple[int, int]]:
    ranges = []
    for match in _PRICE_RANGE.finditer(claim):
        low = int(match.group(1).replace(",", "")) * (1000 if match.group(2) else 1)
        high = int(match.group(3).replace(",", "")) * (1000 if match.group(4) else 1)
        ranges.append((low, high))
    return ranges


def _requirement_band_matches(claim: str, requirement: str) -> bool:
    """Require the claim's stated band to match the requirement; never widen a sub-band."""
    req = requirement.lower()
    ranges = _range_values(claim)
    exact_20_30_req = bool(re.search(r"20\s*,?\s*000.{0,20}30\s*,?\s*000|20\s*k.{0,15}30\s*k", req))
    if exact_20_30_req:
        return any(low == 20000 and high == 30000 for low, high in ranges)
    if re.search(r"sub.{0,15}30\s*,?\s*000|under.{0,15}30\s*,?\s*000|sub.{0,15}30\s*k|under.{0,15}30\s*k", req):
        if not _SUB30_CONTEXT.search(claim):
            return False
        # A measurement explicitly attached to a narrower band is not a total
        # for the entire under-30K category.
        return not any(high < 30000 for _, high in ranges)
    return False


def _has_mid_tier_claim_context(claim: str) -> bool:
    ranges = _range_values(claim)
    if ranges and all(high < 20000 for _, high in ranges):
        return False
    return bool(re.search(r"\bmid[- ]?(?:tier|range)\b|\bupper[- ]budget\b", claim, re.I)
                or _SUB30_CONTEXT.search(claim)
                or any(low == 20000 and high == 30000 for low, high in ranges))


def _recent_claim(item: dict, claim: str) -> bool:
    current_year = datetime.now(timezone.utc).year
    claim_years = [int(year) for year in re.findall(r"\b20\d{2}\b", claim)]
    if claim_years:
        return max(claim_years) >= current_year - 1
    raw_date = item.get("published_at")
    if not raw_date:
        return False
    try:
        published = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
    except ValueError:
        try:
            published = parsedate_to_datetime(str(raw_date))
        except (TypeError, ValueError, OverflowError):
            return False
    if published.tzinfo is None:
        published = published.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - published).days <= 550


def _is_india_specific(item: dict, research_question: str = "", requirement: str = "") -> bool:
    target_india = bool(re.search(r"\bindia\b|\bindian\b", (research_question + " " + requirement).lower()))
    if not target_india:
        return True
    claim = item.get("evidence_text", "")
    if re.search(r"\bglobal(?:ly)?\b|\bworldwide\b", claim, re.I) and not re.search(r"\bindia\b|\bindian\b", claim, re.I):
        return False
    geography = item.get("geographic_relevance")
    return bool(re.search(r"\bindia\b|\bindian\b", claim, re.I) or (geography is not None and float(geography) >= 0.8))


def _requirement_supported(item: dict, requirement: str, research_question: str = "") -> bool:
    claim = item.get("evidence_text", "")
    lower = claim.lower()
    if not claim or _ANALYTICAL_EDITORIAL.search(claim) or item.get("direct_support") is False or item.get("category_relevance", 1) < 0.35:
        return False
    if not _CONCRETE_FACT.search(claim) or not _is_india_specific(item, research_question, requirement):
        return False
    kind = _requirement_kind(requirement)
    scope = item.get("evidence_scope") or classify_evidence_scope(
        claim, research_question, float(item.get("category_relevance", 1) or 0),
        float(item.get("geographic_relevance", 0) or 0), item.get("source_title", ""),
    )
    if scope == "OUT_OF_SCOPE":
        return False
    if kind == "macro_context":
        return bool(re.search(r"inflation|interest rates?|exchange rates?|currency|GDP|economic growth|input costs|component costs", claim, re.I) and _MEASURE.search(claim))
    if kind == "target_sales_growth":
        has_sales_metric = bool(re.search(r"sales|shipments?|units?|volume|revenue", lower))
        has_change = bool(re.search(r"growth|grew|increas\w*|declin\w*|fell|rose|contract\w*|change", lower))
        return scope == "TARGET_SEGMENT" and _requirement_band_matches(claim, requirement) and has_sales_metric and has_change and bool(_MEASURE.search(claim))
    if kind == "technology_adoption":
        has_technology = bool(re.search(r"5g|4g|ai\b|artificial intelligence|camera|processor|chipset|display|fast charg|technology", lower))
        has_adoption = bool(re.search(r"adopt\w*|penetrat\w*|accounted for|share|usage|buyers? (?:prefer|choose)|shift(?:ed|ing)? to", lower))
        return scope == "TARGET_SEGMENT" and _has_mid_tier_claim_context(claim) and has_technology and has_adoption and bool(_MEASURE.search(claim))
    question_has_price_ceiling = bool(re.search(r"(?:under|below|less than|<)\s*(?:\u20b9|rs\.?\s*|inr\s*)?\d", research_question, re.I))
    target_requirement = kind in {"brand_share", "target_band", "target_models"} or (question_has_price_ceiling and kind in {"pricing", "channel"}) or bool(
        re.search(r"(?:under|below|sub[- ]?).{0,20}(?:₹|rs\.?\s*|inr\s*)?\s*(?:30\s*,?\s*000|30\s*k)|20\s*k.{0,15}30\s*k|20\s*,?\s*000.{0,20}30\s*,?\s*000|mid[- ]?(?:range|tier)", requirement, re.I)
    )
    if target_requirement and scope != "TARGET_SEGMENT":
        return False
    if kind == "brand_share":
        if re.search(r"\b(?:chipset|processor|soc)\b", lower):
            return False
        explicit_target_band = scope == "TARGET_SEGMENT" and (
            (bool(re.search(r"sub|under|below|less than", lower, re.I)) and bool(re.search(r"30\s*,?\s*000|30\s*k", lower, re.I)))
            or bool(re.search(r"20\s*k\s*(?:-|–|to)\s*30\s*k|20\s*,?\s*000\s*(?:-|–|to)\s*30\s*,?\s*000", lower, re.I))
        )
        has_share = bool(re.search(r"market share|shipment share|brand share|\bshare\b", lower) and re.search(r"\d\s?%|percent|per cent", lower))
        has_brand = bool(re.search(r"\b(?:brands?|Samsung|Apple|Xiaomi|Redmi|Oppo|Vivo|Realme|Poco|OnePlus|Motorola|iQOO|Transsion|Tecno|Infinix|Nothing|Google Pixel)\b", claim, re.I))
        return explicit_target_band and has_share and has_brand and bool(_BAND_METRIC.search(claim))
    if kind == "offers":
        offer_term = bool(re.search(r"exchange bonus|exchange offer|no[- ]cost EMI|EMI|cashback|discount|promotional offer|offer price|instant discount", claim, re.I))
        concrete_terms = bool(re.search(r"\d\s?%|percent|(?:₹|Rs\.?|INR)\s?\d|\d+\s*(?:months?|installments?)", claim, re.I))
        has_price_ceiling = bool(re.search(r"(?:under|below|less than|<)\s*(?:₹|rs\.?\s*|inr\s*)?\d", research_question, re.I))
        return offer_term and concrete_terms and bool(re.search(r"smartphone|mobile phone|handset|\bphone\b", lower)) and (not has_price_ceiling or scope == "TARGET_SEGMENT")
    if kind == "channel":
        has_online = bool(re.search(r"online|e-commerce|ecommerce|\be-?commerce\b", lower))
        has_offline = bool(re.search(r"offline|physical retail|brick[- ]and[- ]mortar|store sales", lower))
        return scope == "TARGET_SEGMENT" and _has_mid_tier_claim_context(claim) and has_online and has_offline and bool(_MEASURE.search(claim)) and bool(re.search(r"smartphone|mobile phone|handset|\bphone\b", lower))
    if kind == "consumer":
        question_has_price_ceiling = bool(re.search(r"(?:under|below|less than|<)\s*(?:\u20b9|rs\.?\s*|inr\s*)?\d", research_question, re.I))
        target_context_ok = not question_has_price_ceiling or (scope == "TARGET_SEGMENT" and _has_mid_tier_claim_context(claim))
        return target_context_ok and bool(_SURVEY_FINDING.search(claim) and re.search(r"consumer|customer|buyer|preference|prefer|purchase|willing", lower))
    if kind == "target_models":
        has_model_fact = bool(re.search(r"\b(?:model|phone|smartphone)\b", lower) and re.search(r"top[- ]selling|best[- ]selling|rank(?:ed|ing)?|sold|sales|priced|price", lower))
        prices = [int(value.replace(",", "")) for value in re.findall(r"(?:Rs\.?|INR|\u20b9)\s?(\d[\d,]*)", claim, re.I)]
        ceiling_match = re.search(r"(?:under|below|less than|<)\s*(?:\u20b9|rs\.?\s*|inr\s*)?(\d[\d,]*)\s*(k)?", research_question, re.I)
        ceiling = int(ceiling_match.group(1).replace(",", "")) * (1000 if ceiling_match and ceiling_match.group(2) else 1) if ceiling_match else None
        has_price = bool(prices and ceiling is not None and any(price <= ceiling for price in prices))
        has_named_model = bool(re.search(r"\b(?:Samsung|Apple|Xiaomi|Redmi|Oppo|Vivo|Realme|Poco|OnePlus|Motorola|iQOO|Transsion|Tecno|Infinix|Nothing|Google Pixel)\s+[A-Z0-9][\w.+-]*", claim))
        return scope == "TARGET_SEGMENT" and float(item.get("segment_relevance", 0) or 0) >= 0.9 and has_model_fact and has_named_model and has_price and _recent_claim(item, claim) and not _SPECULATIVE_MODEL_PRICE.search(claim)
    if kind == "target_band":
        segment_score = float(item.get("segment_relevance", 0) or 0)
        exact_20_30 = bool(re.search(r"20\s*k.{0,15}30\s*k|20\s*,?\s*000.{0,20}30\s*,?\s*000", requirement, re.I))
        exact_sub30 = bool(re.search(r"sub.{0,12}(?:₹|rs\.?\s*|inr\s*)?30\s*,?\s*000|under.{0,12}(?:₹|rs\.?\s*|inr\s*)?30\s*,?\s*000", requirement, re.I))
        claim_has_band = bool(
            (exact_20_30 and re.search(r"20\s*k.{0,15}30\s*k|20\s*,?\s*000.{0,20}30\s*,?\s*000", lower, re.I))
            or (exact_sub30 and re.search(r"(?:sub|under|below).{0,15}(?:₹|rs\.?\s*|inr\s*)?30\s*,?\s*000", lower, re.I))
        )
        return scope == "TARGET_SEGMENT" and segment_score >= 0.9 and claim_has_band and bool(_MEASURE.search(claim) and _BAND_METRIC.search(claim)) and float(item.get("recency_score", 0) or 0) >= 0.66
    if kind == "pricing":
        return bool(re.search(r"smartphone|mobile phone|handset|\bphone\b", lower) and re.search(r"(?:Rs\.?|INR|\u20b9)\s?\d", claim, re.I))
    if kind == "competition":
        return bool(re.search(r"market share|shipments?|rank(?:ed|ing)?|outsold|price|priced|\d\s?%", lower) and _MEASURE.search(claim))
    if kind == "risk":
        return bool(re.search(r"risk|challenge|cost|shortage|opportun|demand", lower) and _MEASURE.search(claim))
    if kind == "market_data":
        return bool(_MEASURE.search(claim) and re.search(r"market|shipments?|share|revenue|growth|declin|sales", lower))
    return bool(_MEASURE.search(claim))


def _loosely_related(item: dict, requirement: str) -> bool:
    text = item.get("evidence_text", "").lower()
    kind = _requirement_kind(requirement)
    patterns = {
        "channel": r"online|e-commerce|ecommerce|offline|retail|distribution|channel",
        "consumer": r"consumer|customer|buyer|preference|survey|purchase",
        "target_band": r"20\s*,?\s*000|30\s*,?\s*000|20\s*k|30\s*k|segment|price band",
        "pricing": r"price|pricing|cost|₹|inr|rs\.?",
        "competition": r"brand|compet|player|position|share|rank",
        "risk": r"risk|challenge|cost|shortage|opportun|demand",
        "market_data": r"market|growth|shipment|share|revenue|sales|size",
    }
    return bool(re.search(patterns.get(kind, r"\w+"), text, re.I))


def _requirements_matched(item: dict, requirements: list[str]) -> list[str]:
    return [requirement for requirement in requirements if _requirement_supported(item, requirement)]


def _select_diverse_evidence(candidates: list[dict], requirements: list[str], limit: int = 36) -> list[dict]:
    """Prefer quality and coverage, with modest per-source/publisher redundancy caps."""
    remaining = sorted(candidates, key=lambda item: (item.get("quality_score", 0), item.get("relevance", 0)), reverse=True)
    selected, per_source, per_publisher, covered = [], {}, {}, set()
    seen_claims = set()
    while remaining and len(selected) < limit:
        best_index, best_score = None, -1.0
        for index, item in enumerate(remaining):
            sid = item.get("source_id", "")
            publisher = (item.get("publisher") or urlparse(item.get("source_url", "")).hostname or "unknown").lower()
            publisher = re.sub(r"^www\.|[^a-z0-9]+", "", publisher)
            claim_key = re.sub(r"\W+", " ", item.get("evidence_text", "").lower()).strip()
            if per_source.get(sid, 0) >= 3 or per_publisher.get(publisher, 0) >= 5 or claim_key in seen_claims:
                continue
            matches = _requirements_matched(item, requirements)
            coverage_bonus = sum(0.12 if req not in covered else 0.025 for req in matches)
            score = item.get("quality_score", 0) + coverage_bonus
            if score > best_score:
                best_index, best_score = index, score
        if best_index is None:
            break
        item = remaining.pop(best_index)
        sid = item.get("source_id", "")
        publisher = (item.get("publisher") or urlparse(item.get("source_url", "")).hostname or "unknown").lower()
        publisher = re.sub(r"^www\.|[^a-z0-9]+", "", publisher)
        selected.append(item)
        per_source[sid] = per_source.get(sid, 0) + 1
        per_publisher[publisher] = per_publisher.get(publisher, 0) + 1
        seen_claims.add(re.sub(r"\W+", " ", item.get("evidence_text", "").lower()).strip())
        covered.update(_requirements_matched(item, requirements))
    return selected


def _evidence_candidates(source: dict, limit: int = 4) -> list[tuple[str, float, float]]:
    """Choose factual, topical source sentences. Scores affect selection only."""
    content = source.get("content", "")
    if not content:
        return []
    topic_context = " ".join((source.get("research_question", ""), source.get("search_query", ""))).lower()
    context = " ".join((topic_context, source.get("title", ""))).lower()
    def normalize_tokens(value):
        terms = set()
        for word in re.findall(r"[a-z0-9]{3,}", value.lower()):
            if word in _QUERY_STOPWORDS:
                continue
            if word.endswith("ies") and len(word) > 5:
                word = word[:-3] + "y"
            elif word.endswith("s") and len(word) > 4 and not word.endswith("ss"):
                word = word[:-1]
            terms.add(word)
        return terms
    query_terms = normalize_tokens(context)
    topic_terms = normalize_tokens(topic_context)
    # Keep queries with at least two topical anchors; one generic word is not enough.
    if len(query_terms) < 2:
        return []
    sentences = []
    for paragraph in re.split(r"\n+", content):
        sentences.extend(re.split(r"(?<=[.!?])\s+(?=[A-Z0-9₹$€])", paragraph.strip()))
    ranked = []
    seen = set()
    for sentence in sentences:
        text = sentence.strip()
        promotional = _PROMOTIONAL_PHRASE.search(text)
        supported_bestseller = bool(re.search(r"\bbest[- ]selling\b", text, re.I) and re.search(r"\d|market share|shipments?|sales|units|according to|report(?:ed)?", text, re.I))
        if len(text) < 55 or len(text) > 1200 or not text.rstrip().endswith((".", "!", "?")) or text.rstrip().endswith("?") or _QUESTION_OR_HEADING.search(text) or _BOILERPLATE_SENTENCE.search(text) or _EDITORIAL_SENTENCE.search(text) or _ANALYTICAL_EDITORIAL.search(text) or (promotional and not supported_bestseller):
            continue
        if re.search(r"\bleading\b", text, re.I) and not re.search(r"\b(?:market share|shipments?|sales|revenue|units|according to|report(?:ed)?|data|ranked|outsold)\b", text, re.I):
            continue
        completeness_text = text.rstrip("!?;:,")
        if completeness_text.endswith(".") and not completeness_text.endswith("..."):
            completeness_text = completeness_text[:-1].rstrip()
        if _INCOMPLETE_END.search(completeness_text) or _INCOMPLETE_START.search(text) or _EXTRACTION_ARTIFACT.search(text):
            continue
        equity_topic = bool(re.search(r"\b(stock|equity|sensex|nifty|indices)\b", topic_context))
        energy_topic = bool(re.search(r"\b(fuel|petrol|diesel|crude|oil|energy)\b", topic_context))
        if not equity_topic and re.search(r"\b(sensex|nifty|bse|nse|stock market|market ticker)\b", text, re.I):
            continue
        if not energy_topic and re.search(r"\b(fuel|petrol|diesel|crude oil) prices?\b", text, re.I):
            continue
        words = normalize_tokens(text)
        overlap = len(words & query_terms)
        # A strong article title/topic match can support a concise factual claim
        # that omits the product name (for example a segment shipment statistic).
        title_terms = normalize_tokens(source.get("title", ""))
        title_topic_match = len(title_terms & topic_terms) >= 2
        if overlap < 2 and not (overlap >= 1 and title_topic_match):
            continue
        if _PROMOTIONAL_CLAIM.search(text):
            continue
        if not _FACTUAL_SIGNAL.search(text) or not _CONCRETE_FACT.search(text):
            continue
        host = (urlparse(source.get("final_url") or source.get("url", "")).hostname or "").lower()
        marketplace = any(site in host for site in ("amazon.", "flipkart."))
        # Marketplace page titles are broad and cannot establish product scope.
        smartphone_research = bool(_SMARTPHONE_CONTEXT.search(topic_context))
        topic_text = text if marketplace else " ".join((text, source.get("title", "")))
        if smartphone_research:
            if _OTHER_PRODUCT.search(text) or not _SMARTPHONE_CONTEXT.search(topic_text):
                continue
            if _GENERIC_WIFI_DEVICE_STAT.search(text) and not re.search(r"smartphones?|mobile phones?|handsets?|cell phones?", text, re.I):
                continue
            # Headline context alone cannot turn generic price/sales copy into
            # phone research; context-only claims need a phone-specific metric.
            if not _SMARTPHONE_CONTEXT.search(text) and (marketplace or not _SMARTPHONE_CONTEXT.search(source.get("title", "") or "") or not _SMARTPHONE_CONTEXT_PROXY.search(text)):
                continue
        elif _OTHER_PRODUCT.search(text):
            continue
        ceiling_match = re.search(r"\b(?:under|below|less than)\s*(?:\u20b9|rs\.?\s*|inr\s*)?(\d[\d,]*)(\s*k)?", topic_context, re.I)
        currency_prices = re.findall(r"(?:\u20b9|rs\.?\s*|inr\s*)(\d[\d,]*)(\s*k)?", text, re.I)
        if ceiling_match and currency_prices:
            ceiling = int(ceiling_match.group(1).replace(",", "")) * (1000 if ceiling_match.group(2) else 1)
            ceiling = ceiling * 1000 if ceiling < 1000 else ceiling
            parsed_prices = [int(value.replace(",", "")) * (1000 if suffix else 1) for value, suffix in currency_prices]
            if any((price * 1000 if price < 1000 else price) > ceiling for price in parsed_prices):
                continue
        geo = geographic_relevance(text, source.get("title", ""), source.get("research_question", ""), content)
        preliminary = score_evidence_quality({"evidence_text": text, "source_title": source.get("title", ""), "source_type": source.get("source_type", "unknown"), "published_at": source.get("published_at", ""), "relevance": 0.5}, source.get("research_question", ""), content)
        if geo < 0.35 or preliminary["category_relevance"] < 0.35:
            continue
        key = re.sub(r"\W+", " ", text.lower()).strip()
        if key in seen:
            continue
        seen.add(key)
        relevance = min(1.0, 0.35 + 0.4 * min(overlap / 4, 1) + 0.25 * geo)
        ranked.append((text, relevance, geo))
    ranked.sort(key=lambda item: item[1], reverse=True)
    return ranked[:limit]


def _extract_evidence(source: dict, research_id: str) -> list[dict]:
    """Create evidence records from exact article sentences only."""
    if source.get("content_scope") != "source_page" or not source.get("evaluation", {}).get("usable"):
        return []
    results = []
    base_confidence = float(source["evaluation"].get("confidence", 0.1))
    for text, relevance, _geo in _evidence_candidates(source):
        quality = score_evidence_quality({"evidence_text": text, "source_title": source.get("title", ""), "source_type": source.get("source_type", "unknown"), "published_at": source.get("published_at", ""), "relevance": relevance}, source.get("research_question", ""), source.get("content", ""))
        if not quality["direct_support"] or quality["geographic_relevance"] < 0.35 or quality["category_relevance"] < 0.35:
            continue
        results.append(Evidence(claim=text, evidence_text=text, source_id=source["id"], research_id=research_id,
                     source_title=source.get("title", ""), source_url=source.get("final_url") or source.get("url", ""),
                     publisher=source.get("publisher", ""), published_at=source.get("published_at", ""),
                     search_query=source.get("search_query", ""), source_type=source.get("source_type", "unknown"),
                     content_scope=source.get("content_scope", "unknown"), relevance=relevance,
                     confidence=round(min(0.95, 0.35 * base_confidence + 0.65 * quality["quality_score"]), 3),
                     source_quality_score=quality["source_quality_score"], recency_score=quality["recency_score"],
                     geographic_relevance=quality["geographic_relevance"], direct_support=quality["direct_support"],
                     category_relevance=quality["category_relevance"], segment_relevance=quality["segment_relevance"],
                     evidence_scope=quality["evidence_scope"],
                     quality_score=quality["quality_score"]).to_dict())
    return results


def _missing_information(requirements: list[str], evidence: list[dict], research_question: str = "") -> list[str]:
    coverage = _evaluate_coverage(requirements, evidence, research_question)
    return coverage["weak"] + coverage["unanswered"]


def _evaluate_coverage(requirements: list[str], evidence: list[dict], research_question: str = "") -> dict:
    sufficient, weak, unanswered = [], [], []
    for requirement in requirements:
        if any(_requirement_supported(item, requirement, research_question) for item in evidence):
            sufficient.append(requirement)
        elif any(_loosely_related(item, requirement) for item in evidence):
            weak.append(requirement)
        else:
            unanswered.append(requirement)
    return {"sufficient": sufficient, "weak": weak, "unanswered": unanswered}


def _report(question, plan, evidence, missing, conflicts, coverage=None):
    summary = f"Collected {len(evidence)} traceable evidence statements from {len({e['source_id'] for e in evidence})} source pages over the research process."
    if not evidence: summary += " No article-level evidence was collected; search snippets are leads only and cannot substantiate market conclusions."
    lines = ["# Market research report", "", f"**Research question:** {question}", "", "## Executive summary", "", summary, ""]
    scope_names = ("TARGET_SEGMENT", "INDIA_MARKET_CONTEXT", "GLOBAL_CONTEXT", "OUT_OF_SCOPE")
    lines += ["## Evidence scope", "", "Evidence is classified by the claim itself; only TARGET_SEGMENT evidence can satisfy direct price-segment requirements.", ""]
    scoped = {name: [] for name in scope_names}
    for item in evidence:
        scope = item.get("evidence_scope") or classify_evidence_scope(
            item.get("evidence_text", item.get("claim", "")), question,
            float(item.get("category_relevance", 1) or 0),
            float(item.get("geographic_relevance", 0) or 0), item.get("source_title", ""),
        )
        scoped.setdefault(scope, []).append(item)
    for scope in scope_names:
        lines.append(f"### {scope}")
        lines.append("")
        if scoped.get(scope):
            for item in scoped[scope]:
                lines.append(f"- [{scope}] {item['claim']} ([{item['source_title'] or item['publisher'] or 'Source'}]({item['source_url']}))")
        else:
            lines.append("No retained evidence.")
        lines.append("")
    sections = {
        "Market overview": ("market", "growth", "size", "share"),
        "Competitors and positioning": ("competitor", "brand", "position", "company", "player"),
        "Segments and pricing": ("price", "pricing", "segment", "cost", "budget"),
        "Consumer preferences": ("consumer", "customer", "buyer", "preference", "survey", "review"),
        "Trends and emerging competitors": ("trend", "launch", "emerging", "growth", "adoption"),
        "Opportunities and risks": ("opportunity", "risk", "challenge", "gap", "demand"),
    }
    for title, keys in sections.items():
        lines += [f"## {title}", ""]
        matched = [e for e in evidence if any(k in e["claim"].lower() for k in keys)]
        if matched:
            for item in matched[:6]:
                scope = item.get("evidence_scope") or classify_evidence_scope(
                    item.get("evidence_text", item.get("claim", "")), question,
                    float(item.get("category_relevance", 1) or 0),
                    float(item.get("geographic_relevance", 0) or 0), item.get("source_title", ""),
                )
                lines.append(f"- [{scope}] {item['claim']} ([{item['source_title'] or item['publisher'] or 'Source'}]({item['source_url']}), confidence {item['confidence']:.2f})")
        else:
            lines.append("No usable article evidence found for this area in this run.")
        lines.append("")
    lines += ["", "## Research coverage", "", "**Information requirements:** " + (", ".join(plan.get("information_needed", [])) or "None specified"), "", "**Unresolved / insufficient evidence:** " + (", ".join(missing) if missing else "None identified by evidence-level checks."), "", "Only retained TARGET_SEGMENT evidence can satisfy direct target-segment requirements. Search results, query matches, broad market context, and related claims alone do not satisfy a requirement.", "", "## Conflicts", ""]
    if coverage:
        lines.insert(lines.index("## Conflicts"), "**Supported requirements:** " + (", ".join(coverage["sufficient"]) or "None") + "\n\n**Unresolved / insufficient evidence:** " + (", ".join(coverage["weak"] + coverage["unanswered"]) or "None") + "\n\n")
    support_lines = ["### Requirement-by-requirement support", ""]
    for requirement in plan.get("information_needed", []):
        supporters = [item for item in evidence if _requirement_supported(item, requirement, question)]
        if supporters:
            support_lines.append(f"- **SUPPORTED — {requirement}:** " + " | ".join(item["evidence_text"] for item in supporters[:3]))
        else:
            support_lines.append(f"- **UNRESOLVED / INSUFFICIENT EVIDENCE — {requirement}.**")
    support_lines.append("")
    lines.insert(lines.index("## Conflicts"), "\n".join(support_lines))
    lines.append("\n".join(f"- {c['message']} Claims: {c['claims'][0]} / {c['claims'][1]}" for c in conflicts) if conflicts else "No numeric conflicts detected by the basic heuristic.")
    lines += ["", "## Methodology and limitations", "", f"The system searched up to {MAX_SOURCES} unique URLs over {MAX_ITERATIONS} iterations, fetched accessible HTML pages, and retained only verbatim article sentences as evidence. Source ratings and gap/conflict checks are heuristic. Missing information: " + (", ".join(missing) if missing else "none flagged") + "."]
    return "\n".join(lines)


def execute_research(research_question: str, research_id: str | None = None, on_update=None) -> dict:
    rid = research_id or str(uuid.uuid4())
    from database import store
    persist_run = bool(research_id and store.get_run(rid))
    activity = []
    def emit(event, **extra):
        activity.append(event)
        if persist_run:
            fields = {"activity": activity}
            if event != "Report completed": fields["status"] = "running"
            if "iteration" in extra: fields["iterations"] = extra["iteration"]
            if "plan" in extra: fields["plan"] = extra["plan"]
            if "missing" in extra: fields["missing"] = extra["missing"]
            store.update_run(rid, **fields)
        if on_update: on_update(event, extra)
    try:
        plan = create_research_plan(research_question)
        emit("Research plan created", plan=plan)
        sources, evidence, evidence_pool, seen_urls, seen_queries = [], [], [], set(), set()
        tasks = list(plan["search_queries"])
        coverage = _evaluate_coverage(plan["information_needed"], evidence, research_question)
        missing = list(plan["information_needed"])
        actual_iterations = 0
        for iteration in range(1, MAX_ITERATIONS + 1):
            if not tasks or len(sources) >= MAX_SOURCES: break
            actual_iterations = iteration
            current = tasks[:MAX_SOURCES - len(sources)]
            tasks = []
            emit("Research iteration started", iteration=iteration, queries=current)
            activity.append(f"Iteration {iteration}: searching {len(current)} queries")
            for query in current:
                qkey = query.casefold().strip()
                if not qkey or qkey in seen_queries: continue
                seen_queries.add(qkey)
                try:
                    results = search_web(query, max_results=min(4, MAX_SOURCES - len(sources))) or []
                except Exception:
                    results = []
                for result in results:
                    url = result.get("url", "").strip()
                    normalized_url = _normalize_url(url) if url else ""
                    if not normalized_url or normalized_url in seen_urls or len(sources) >= MAX_SOURCES: continue
                    seen_urls.add(normalized_url)
                    source = {**result, "id": str(uuid.uuid4()), "search_query": query, "research_question": research_question, "content_scope": "search_result", "content": "", "source_type": classify_source(url, result.get("publisher", ""))}
                    try:
                        fetched = fetch_document(url)
                        source.update(fetched)
                        final = urlparse(fetched.get("final_url", ""))
                        is_wrapper = final.hostname in {"news.google.com", "www.google.com", "google.com"}
                        is_homepage = final.path in {"", "/"} and final.query == ""
                        source["content_scope"] = "publisher_homepage" if is_homepage else "source_page" if fetched.get("content") and len(fetched["content"]) >= 80 and not is_wrapper else "unknown"
                    except Exception as exc:
                        source["fetch_error"] = str(exc)
                    source["evaluation"] = evaluate_evidence(source)
                    source["source_type"] = source["evaluation"]["source_type"]
                    if persist_run:
                        source["id"] = store.add_source(rid, source)
                    sources.append(source)
                    evidence_pool.extend(_extract_evidence(source, rid))
            evidence = _select_diverse_evidence(evidence_pool, plan.get("information_needed", []))
            activity.append(f"Iteration {iteration}: {len(sources)} unique sources, {len(evidence)} evidence statements")
            emit("Evidence extracted and evaluated", iteration=iteration, sources=len(sources), evidence=len(evidence))
            coverage = _evaluate_coverage(plan.get("information_needed", []), evidence, research_question)
            missing = coverage["weak"] + coverage["unanswered"]
            emit("Missing information evaluated", missing=missing)
            if not missing:
                activity.append("Evidence coverage threshold reached")
                break
            if iteration < MAX_ITERATIONS and len(sources) < MAX_SOURCES:
                tasks = generate_followup_queries(research_question, missing)
                activity.append(f"Follow-up research generated for {len(tasks)} gaps")
                emit("Follow-up research generated", queries=tasks)
        # Evidence is inserted once; source IDs were assigned by SQLite above.
        conflicts = detect_conflicts(evidence)
        report = _report(research_question, plan, evidence, missing, conflicts, coverage)
        emit("Market analysis generated")
        emit("Report completed")
        if persist_run:
            for item in evidence: store.add_evidence(rid, item)
            store.update_run(rid, status="completed", iterations=actual_iterations, plan=plan, activity=activity, missing=missing, coverage=coverage, conflicts=conflicts)
            store.save_report(rid, report)
        if on_update: on_update("Report completed", {"report": report})
        return {"research_id": rid, "research_question": research_question, "plan": plan, "sources": sources, "evidence": evidence, "missing_information": missing, "coverage": coverage, "conflicts": conflicts, "iterations": actual_iterations, "report": report, "activity": activity}
    except Exception as exc:
        if persist_run: store.update_run(rid, status="failed", error=str(exc))
        raise
