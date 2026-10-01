from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import re
from urllib.parse import urlparse
from uuid import uuid4


@dataclass
class Evidence:
    claim: str
    source_title: str
    source_url: str
    publisher: str = ""
    evidence_text: str = ""
    published_at: str = ""
    search_query: str = ""
    id: str = field(default_factory=lambda: str(uuid4()))
    research_id: str = ""
    source_id: str = ""
    source_type: str = "unknown"
    content_scope: str = "unknown"
    relevance: float = 0.0
    confidence: float = 0.0
    source_quality_score: float = 0.0
    recency_score: float = 0.0
    geographic_relevance: float = 0.0
    category_relevance: float = 0.0
    segment_relevance: float = 0.0
    evidence_scope: str = "INDIA_MARKET_CONTEXT"
    evidence_scope: str = "INDIA_MARKET_CONTEXT"
    direct_support: bool = False
    quality_score: float = 0.0
    extracted_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self):
        return asdict(self)


def classify_source(url: str, publisher: str = "") -> str:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    name = " ".join((publisher or "").lower().replace("&", "and").split())

    def host_matches(*domains):
        return any(host == domain or host.endswith("." + domain) for domain in domains)

    if host.endswith((".gov", ".gov.in", ".nic.in")) or host_matches("mospi.gov.in", "rbi.org.in", "india.gov.in"):
        return "government"
    official_domains = ("samsung.com", "apple.com", "mi.com", "xiaomi.com", "google.com", "motorola.com", "oneplus.com", "oppo.com", "vivo.com", "realme.com")
    if host_matches(*official_domains):
        return "official"
    industry_hosts = ("counterpointresearch.com", "idc.com", "canalys.com", "omdia.com", "gartner.com")
    industry_names = ("counterpoint research", "international data corporation", "canalys", "omdia", "gartner")
    if host_matches(*industry_hosts) or any(label in name for label in industry_names):
        return "industry_report"
    major_hosts = ("business-standard.com", "reuters.com", "thehindu.com", "economictimes.indiatimes.com", "economictimes.com", "livemint.com", "hindustantimes.com", "indianexpress.com", "cnbctv18.com", "moneycontrol.com", "bloomberg.com", "bbc.com", "bbc.co.uk")
    major_names = ("business standard", "reuters", "the hindu", "economic times", "mint", "hindustan times", "indian express", "cnbc-tv18", "cnbc tv18", "moneycontrol", "bloomberg", "bbc news")
    if host_matches(*major_hosts) or any(label in name for label in major_names):
        return "major_publication"
    specialist_hosts = ("gsmarena.com", "91mobiles.com", "techradar.com", "tomsguide.com")
    specialist_names = ("gsmarena", "91mobiles", "techradar", "tom's guide")
    if host_matches(*specialist_hosts) or any(label in name for label in specialist_names):
        return "specialist_publication"
    return "unknown"


def evaluate_evidence(item: dict) -> dict:
    text = (item.get("content") or "").strip()
    scope = item.get("content_scope", "unknown")
    useful = bool(text) and scope == "source_page" and len(text) >= 80
    quality = classify_source(item.get("final_url") or item.get("url", ""), item.get("publisher", ""))
    confidence = min(0.95, 0.45 + (0.25 if quality in ("government", "official", "industry_report") else 0.15 if quality in ("major_publication", "specialist_publication") else 0) + (0.2 if useful else 0))
    return {"source_type": quality, "relevance": 0.6 if useful else 0.15, "confidence": confidence if useful else 0.1, "usable": useful, "reason": "Fetched article text" if useful else "Content is empty, too short, or is not a source article page"}


def _published_datetime(value: str):
    if not value:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            match = re.search(r"\b(20\d{2})\b", value)
            if not match:
                return None
            parsed = datetime(int(match.group(1)), 6, 30, tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


_REGIONS = {
    "india": (r"\bindia\b|\bindian\b",),
    "united states": (r"\bunited states\b|\bu\.?s\.?a?\b|\bamerican\b",),
    "united kingdom": (r"\bunited kingdom\b|\buk\b|\bbritain\b|\bbritish\b",),
    "china": (r"\bchina\b|\bchinese\b",),
    "europe": (r"\beurope\b|\beuropean\b",),
    "japan": (r"\bjapan\b|\bjapanese\b",),
    "indonesia": (r"\bindonesia\b|\bindonesian\b",),
    "canada": (r"\bcanada\b|\bcanadian\b",),
    "australia": (r"\baustralia\b|\baustralian\b",),
    "south korea": (r"\bsouth korea\b|\bsouth korean\b",),
    "brazil": (r"\bbrazil\b|\bbrazilian\b",),
    "mexico": (r"\bmexico\b|\bmexican\b",),
    "vietnam": (r"\bvietnam\b|\bvietnamese\b",),
    "southeast asia": (r"\bsoutheast asia\b|\basean\b",),
    "middle east": (r"\bmiddle east\b|\bgulf countries\b",),
    "africa": (r"\bafrica\b|\bafrican\b",),
    "north america": (r"\bnorth america\b",),
    "asia pacific": (r"\basia pacific\b|\bapac\b",),
    "global": (r"\bglobal\b|\bworldwide\b|\binternational\b",),
}


def geographic_relevance(text: str, title: str, research_question: str, source_content: str = "") -> float:
    question = research_question.lower()
    targets = [name for name, patterns in _REGIONS.items() if any(re.search(p, question, re.I) for p in patterns)]
    if not targets or "global" in targets:
        return 0.9
    claim, title_text, whole_source = text.lower(), title.lower(), source_content.lower()
    for target in targets:
        pattern = _REGIONS[target][0]
        if re.search(pattern, claim, re.I):
            return 1.0
    if re.search(r"\b(global|worldwide|international)\b", claim, re.I):
        if re.search(r"\b(trend|adoption|launch|supply|risk|demand|growth|shipment)\w*\b", claim, re.I):
            return 0.68
    other_regions = [pattern for name, patterns in _REGIONS.items() if name not in targets and name != "global" for pattern in patterns]
    if any(re.search(pattern, claim, re.I) for pattern in other_regions):
        return 0.12
    if any(re.search(pattern, title_text, re.I) for pattern in other_regions):
        return 0.12
    if any(re.search(pattern, title_text, re.I) for target in targets for pattern in _REGIONS[target]):
        return 0.82
    if any(re.search(pattern, whole_source, re.I) for target in targets for pattern in _REGIONS[target]):
        return 0.62
    return 0.12


def category_relevance(text: str, title: str, research_question: str) -> float:
    """Down-rank claims about a neighboring product market, including scope exclusions."""
    q, body = research_question.lower(), (text + " " + title).lower()
    families = {
        "smartphone": r"\b(?:smartphones?|mobile phones?|handsets?)\b",
        "accessories": r"\b(?:accessories|cases|chargers|earbuds|power banks)\b",
        "tablet": r"\btablets?\b", "laptop": r"\b(?:laptops?|notebooks?)\b",
        "wearable": r"\b(?:wearables?|smartwatches?)\b", "feature phone": r"\bfeature phones?\b",
        "automobile": r"\b(?:cars?|automobiles?|passenger vehicles?)\b",
    }
    targets = [key for key, pattern in families.items() if re.search(pattern, q)]
    if not targets:
        return 0.75
    # Detect explicit category names first; smartphone accessories are a separate market.
    explicit = [key for key, pattern in families.items() if re.search(pattern, body)]
    if re.search(r"\b(?:scope excludes?|excluding|does not include|not covered)\b", text, re.I):
        if any(key in targets and key in explicit for key in targets):
            return 0.05
    if "smartphone" in targets and "accessories" in explicit and re.search(r"accessor(?:y|ies)\s+market|market\s+for\s+accessor", body):
        return 0.05
    if explicit and not set(explicit).intersection(targets):
        return 0.18
    if set(explicit).intersection(targets):
        return 1.0
    return 0.68


def segment_relevance(text: str, title: str, research_question: str) -> float:
    """Score direct target-band evidence separately from broad market context."""
    q, body = research_question.lower(), (text + " " + title).lower()
    ceiling_match = re.search(r"(?:under|below|less than|<)\s*(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*)(\s*k)?", q)
    if not ceiling_match:
        return 0.75
    ceiling = int(ceiling_match.group(1).replace(",", "")) * (1000 if ceiling_match.group(2) else 1)
    if ceiling < 1000:
        ceiling *= 1000
    # A claim explicitly about prices above the question's ceiling can never
    # be target-segment evidence, even if it also contains relevant phone terms.
    out_of_band = re.search(
        r"(?:>|above|over|more than|greater than|exceed(?:s|ing)?|premium\s*\()\s*(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k)?",
        body,
        re.I,
    )
    explicit_price_context = bool(re.search(r"(?:₹|\brs\.?\s*|\binr\b|price|priced|price band|price segment|premium\s+segment)", body, re.I))
    if out_of_band and (re.search(r"₹|\brs\.?\s*|\binr\b", out_of_band.group(0), re.I) or explicit_price_context):
        value = float(out_of_band.group(1).replace(",", "")) * (1000 if out_of_band.group(2) else 1)
        if value < 1000:
            value *= 1000
        if value >= ceiling:
            return 0.05
    range_match = re.search(
        r"(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k)?\s*(?:-|–|to)\s*(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*(?:\.\d+)?)\s*(k)?",
        body,
        re.I,
    )
    if range_match:
        high = float(range_match.group(3).replace(",", "")) * (1000 if range_match.group(4) else 1)
        if high < 1000:
            high *= 1000
        if high > ceiling and re.search(r"₹|\brs\.?\s*|\binr\b|\bprice|\bbudget|\bpremium\b", body, re.I):
            low = float(range_match.group(1).replace(",", "")) * (1000 if range_match.group(2) else 1)
            if low < 1000:
                low *= 1000
            if low >= ceiling:
                return 0.05
    # Explicit target ceiling or range is direct evidence. Do not mistake any
    # cheaper budget band for equivalent coverage of the whole under-ceiling market.
    ceiling_text = f"{ceiling:,}"
    ceiling_k = ceiling // 1000 if ceiling >= 1000 and ceiling % 1000 == 0 else None
    ceiling_forms = [str(ceiling), re.escape(ceiling_text)]
    if ceiling_k is not None:
        ceiling_forms.append(rf"{ceiling_k}\s*k")
    ceiling_expr = rf"(?:{'|'.join(ceiling_forms)})"
    if re.search(rf"\b(?:sub[- ]|under|below|less than)\s*(?:₹|rs\.?\s*|inr\s*)?{ceiling_expr}(?:\s*k)?\b", body):
        return 0.98
    direct_range = re.search(r"(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*)(\s*k)?\s*(?:-|–|to|and)\s*(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*)(\s*k)?", body)
    if direct_range and (re.search(r"₹|\brs\.?\s*|\binr\b|\b\d\s*k\b|\b(?:price|priced|budget|rupee|range)\b", body)):
        low = int(direct_range.group(1).replace(",", "")) * (1000 if direct_range.group(2) else 1)
        high = int(direct_range.group(3).replace(",", "")) * (1000 if direct_range.group(4) else 1)
        low = low * 1000 if low < 1000 else low
        high = high * 1000 if high < 1000 else high
        if low <= ceiling and high >= ceiling * 0.65:
            return 0.98
        if high <= 10000:
            return 0.22
        if high < ceiling * 0.65:
            return 0.42
    if re.search(r"\b(?:20\s*k\s*(?:-|–|to)\s*30\s*k|20,?000\s*(?:-|–|to)\s*30,?000)\b", body):
        return 0.98
    if re.search(r"\b(?:mid[- ]?range|upper[- ]budget)\b", body):
        return 0.76
    price_matches = re.finditer(r"(?:under|below|less than|<|₹|rs\.?\s*|inr\s*)(\d[\d,]*)(\s*k)?", body)
    values = [int(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1) for m in price_matches]
    values = [v * 1000 if v < 1000 else v for v in values]
    if values:
        price = min(values)
        if price > ceiling:
            return 0.05
        if price <= 10000:
            return 0.22
        if price < ceiling * 0.65:
            return 0.48
        return 0.98
    # General smartphone-market data is useful context, but is not segment coverage.
    return 0.54


def classify_evidence_scope(evidence_text: str, research_question: str, category_score: float = 1.0,
                            geographic_score: float = 1.0, source_title: str = "") -> str:
    """Classify evidence as target segment, market context, global context, or out of scope."""
    text = evidence_text or ""
    combined = f"{text} {source_title}"
    if category_score < 0.35:
        return "OUT_OF_SCOPE"
    ceiling_match = re.search(r"(?:under|below|less than|<)\s*(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*)(\s*k)?", research_question, re.I)
    if ceiling_match:
        ceiling = int(ceiling_match.group(1).replace(",", "")) * (1000 if ceiling_match.group(2) else 1)
        if ceiling < 1000:
            ceiling *= 1000
        if segment_relevance(text, "", research_question) <= 0.05:
            return "OUT_OF_SCOPE"
        if re.search(r"\b(?:global(?:ly)?|worldwide|international market)\b", text, re.I) and not re.search(r"\b(?:india|indian)\b", text, re.I):
            return "GLOBAL_CONTEXT"
        target_ceiling = re.search(
            rf"\b(?:sub[- ]|under|below|less than)\s*(?:₹|rs\.?\s*|inr\s*)?(?:{ceiling:,}|{ceiling}|{ceiling // 1000}\s*k)\b",
            text,
            re.I,
        )
        target_range = re.search(
            r"(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*)\s*(?:-|–|to)\s*(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*)",
            text,
            re.I,
        )
        concrete_midrange = bool(re.search(r"\bmid[- ]?range\b", text, re.I) and re.search(r"%|percent|shipments?|units?|market share|₹|\bINR\b|\bRs\.?\s*\d", text, re.I))
        range_in_target = False
        if target_range and re.search(r"₹|\brs\.?\s*|\binr\b|\bprice|\bbudget|\bsegment|\brange\b", text, re.I):
            low, high = [int(target_range.group(i).replace(",", "")) for i in (1, 2)]
            low = low * 1000 if low < 1000 else low
            high = high * 1000 if high < 1000 else high
            range_in_target = low < ceiling and high >= ceiling * 0.65 and high <= ceiling
        price_values = [int(m.group(1).replace(",", "")) * (1000 if m.group(2) else 1) for m in re.finditer(r"(?:₹|rs\.?\s*|inr\s*)(\d[\d,]*)(\s*k)?", text, re.I)]
        target_price = any(ceiling * 0.65 <= (v * 1000 if v < 1000 else v) <= ceiling for v in price_values)
        if target_ceiling or range_in_target or target_price or concrete_midrange:
            return "TARGET_SEGMENT"
    if re.search(r"\b(?:global(?:ly)?|worldwide|international market)\b", text, re.I) and not re.search(r"\b(?:india|indian)\b", text, re.I):
        return "GLOBAL_CONTEXT"
    if geographic_score >= 0.8 or re.search(r"\b(?:india|indian)\b", text, re.I):
        return "INDIA_MARKET_CONTEXT"
    return "OUT_OF_SCOPE"


def score_evidence_quality(item: dict, research_question: str, source_content: str = "") -> dict:
    """Return transparent heuristic signals; these are not third-party credibility facts."""
    source_type = item.get("source_type", "unknown")
    if source_type == "unknown":
        source_type = classify_source(item.get("source_url", ""), item.get("publisher", ""))
    source_score = {"government": 0.99, "industry_report": 0.94, "official": 0.90, "major_publication": 0.84, "specialist_publication": 0.72, "review": 0.58, "unknown": 0.28}.get(source_type, 0.28)
    published = _published_datetime(item.get("published_at", ""))
    requested_years = [int(year) for year in re.findall(r"\b20\d{2}\b", research_question)]
    historical_request = bool(re.search(r"\bhistorical\b|\bhistory of\b|\bpast years\b", research_question, re.I))
    if published is None:
        recency = 0.5
    elif requested_years:
        distance = min(abs(published.year - year) for year in requested_years)
        recency = 0.98 if distance == 0 else 0.84 if distance == 1 else 0.66 if distance <= 3 else 0.48 if distance <= 5 else 0.3
    elif historical_request:
        recency = 0.82
    else:
        age_days = (datetime.now(timezone.utc) - published).days
        if age_days < -30:
            recency = 0.35
        else:
            age_years = max(0.0, age_days / 365.25)
            recency = 0.98 if age_years <= 1 else 0.84 if age_years <= 2 else 0.66 if age_years <= 3 else 0.48 if age_years <= 5 else 0.3
    evidence_text = item.get("evidence_text", "")
    # Publication dates do not make an explicitly historical claim current.
    claim_years = [int(year) for year in re.findall(r"\b20\d{2}\b", evidence_text)]
    if claim_years and not historical_request:
        target_year = min(requested_years) if requested_years else datetime.now(timezone.utc).year
        distance = min(abs(year - target_year) for year in claim_years)
        claim_recency = 0.98 if distance == 0 else 0.84 if distance == 1 else 0.66 if distance <= 3 else 0.48 if distance <= 5 else 0.25
        recency = min(recency, claim_recency)
    direct = bool(evidence_text and source_content and evidence_text in source_content)
    geo = geographic_relevance(evidence_text, item.get("source_title", ""), research_question, source_content)
    category = category_relevance(evidence_text, item.get("source_title", ""), research_question)
    segment = segment_relevance(evidence_text, item.get("source_title", ""), research_question)
    scope = classify_evidence_scope(evidence_text, research_question, category, geo, item.get("source_title", ""))
    if scope == "OUT_OF_SCOPE" and segment <= 0.05:
        segment = 0.05
    relevance = max(0.0, min(1.0, float(item.get("relevance", 0.0))))
    score = (0.24 * source_score) + (0.20 * recency) + (0.16 * relevance) + (0.14 * geo) + (0.10 * float(direct)) + (0.08 * category) + (0.08 * segment)
    return {"source_quality_score": round(source_score, 3), "recency_score": round(recency, 3), "geographic_relevance": round(geo, 3), "category_relevance": round(category, 3), "segment_relevance": round(segment, 3), "evidence_scope": scope, "direct_support": direct, "quality_score": round(score, 3)}


def detect_conflicts(evidence: list[dict]) -> list[dict]:
    """Flag strongly overlapping market-topic claims with incompatible numeric values."""
    import re
    conflicts = []
    for i, left in enumerate(evidence):
        lt = left.get("claim", "")
        ln = set(re.findall(r"\d+(?:\.\d+)?%?", lt))
        if not ln: continue
        for right in evidence[i + 1:]:
            rt = right.get("claim", "")
            rn = set(re.findall(r"\d+(?:\.\d+)?%?", rt))
            lw = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", lt)}
            rw = {w.lower() for w in re.findall(r"[a-zA-Z]{4,}", rt)}
            if ln and rn and ln.isdisjoint(rn) and len(lw & rw) >= 2:
                conflicts.append({"claims": [lt, rt], "evidence_ids": [left.get("id"), right.get("id")], "message": "Overlapping claims report different numeric values; compare date, region, segment, source type, and context."})
    return conflicts
