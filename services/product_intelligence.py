"""Domain-independent product intelligence, variant discovery, unit pricing, and executive verdict generation."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import re
from typing import Any
from urllib.parse import quote_plus, urlparse

from models.comparison import AttributeDefinition, ValueType


# ---------------------------------------------------------------------------
# Quantity & Variant Extraction
# ---------------------------------------------------------------------------

_MASS_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(kg|kilograms?|kilo|g\b|gm\b|grams?)\b",
    re.I,
)

_VOLUME_PATTERN = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*(l\b|litres?|liters?|ml\b|millilitres?|milliliters?)\b",
    re.I,
)

_PACK_COUNT_PATTERN = re.compile(
    r"\b(?:pack\s*of\s*(\d+)|(\d+)[- ]pack|(\d+)\s*(?:units?|pieces?|pcs?|bars?|bottles?|cans?|pouches?|tablets?|capsules?))\b",
    re.I,
)

_TECH_CONFIG_PATTERN = re.compile(
    r"\b(\d+\s*(?:GB|TB))\s*(?:RAM|memory|unified\s*memory|SSD|storage|ROM)?\b",
    re.I,
)

_CHIP_PROCESSOR_PATTERN = re.compile(
    r"\b(M[1-4](?:\s*Pro|\s*Max|\s*Ultra)?|Intel\s*Core\s*(?:Ultra\s*[579]|i[3579])(?:-\w+)?|AMD\s*Ryzen\s*[3579](?:\s*\w+)?|Snapdragon\s*X\s*(?:Elite|Plus))\b",
    re.I,
)

_NON_PRICE_SPEC_UNITS = re.compile(
    r"(?:\b|\d)\s*(?:Gbps|Gb/s|Mbps|Mb/s|GHz|MHz|kHz|GB|TB|MB|KB|inches?|inch|\"|Hz|Wh|kWh|mAh|V|W|kW|mW|mm|cm|fps|nits|cores?|threads?|MP\b|megapixels?|px\b|ppi|dpi|rpm|dB|dBA)",
    re.I,
)


@dataclass
class ParsedQuantity:
    quantity: Decimal
    unit: str
    measure_type: str  # "mass", "volume", "count", "config"
    standard_amount: Decimal
    standard_unit: str  # "g", "ml", "unit"
    display: str


def parse_pack_or_variant(text: str | None) -> ParsedQuantity | None:
    """Extract verifiable mass, volume, or pack count from a product or offer description.

    Returns None if text is empty, ambiguous, or lacks a verifiable quantity.
    Hardware measurements (e.g. 16GB, 10Gbps) are never parsed as mass or volume.
    """
    if not isinstance(text, str) or not text.strip():
        return None

    cleaned = text.strip()

    # 1. Mass check (g / kg)
    # Ensure it's not a hardware unit (e.g. 16GB)
    mass_match = _MASS_PATTERN.search(cleaned)
    if mass_match:
        val_str = mass_match.group(1)
        unit_str = mass_match.group(2).lower()
        # Verify not followed by Gbps or B (e.g. 16GB)
        end_pos = mass_match.end()
        remainder = cleaned[end_pos:end_pos + 4]
        if not re.match(r"^[a-zA-Z]", remainder):
            try:
                num = Decimal(val_str)
                if num > 0:
                    if unit_str in {"kg", "kilogram", "kilograms", "kilo"}:
                        standard_g = num * Decimal("1000")
                        display = f"{num:g} kg"
                    else:
                        standard_g = num
                        display = f"{num:g} g"
                    return ParsedQuantity(
                        quantity=num,
                        unit=unit_str,
                        measure_type="mass",
                        standard_amount=standard_g,
                        standard_unit="g",
                        display=display,
                    )
            except (InvalidOperation, ValueError):
                pass

    # 2. Volume check (ml / l)
    volume_match = _VOLUME_PATTERN.search(cleaned)
    if volume_match:
        val_str = volume_match.group(1)
        unit_str = volume_match.group(2).lower()
        try:
            num = Decimal(val_str)
            if num > 0:
                if unit_str in {"l", "litre", "litres", "liter", "liters"}:
                    standard_ml = num * Decimal("1000")
                    display = f"{num:g} L"
                else:
                    standard_ml = num
                    display = f"{num:g} ml"
                return ParsedQuantity(
                    quantity=num,
                    unit=unit_str,
                    measure_type="volume",
                    standard_amount=standard_ml,
                    standard_unit="ml",
                    display=display,
                )
        except (InvalidOperation, ValueError):
            pass

    # 3. Multipack count check
    count_match = _PACK_COUNT_PATTERN.search(cleaned)
    if count_match:
        count_str = count_match.group(1) or count_match.group(2) or count_match.group(3)
        if count_str:
            try:
                count_num = Decimal(count_str)
                if count_num > 1:
                    return ParsedQuantity(
                        quantity=count_num,
                        unit="units",
                        measure_type="count",
                        standard_amount=count_num,
                        standard_unit="unit",
                        display=f"{int(count_num)} pack",
                    )
            except (InvalidOperation, ValueError):
                pass

    return None


# ---------------------------------------------------------------------------
# Unit Price Calculation
# ---------------------------------------------------------------------------

_CURRENCY_SYMBOLS: dict[str, str] = {
    "INR": "₹",
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "JPY": "¥",
}


def currency_symbol(code: str | None) -> str:
    if not code:
        return ""
    return _CURRENCY_SYMBOLS.get(code.upper(), f"{code.upper()} ")


def calculate_unit_price(
    price: Decimal | int | float | str | None,
    quantity_or_text: ParsedQuantity | str | None,
    currency: str | None = None,
) -> dict[str, Any] | None:
    """Calculate normalized unit price when both price and quantity are verified and compatible.

    - Mass: price per 100 g
    - Volume: price per litre (1000 ml)
    - Count: price per unit (for multipacks)

    Returns None if:
    - Price is invalid, non-positive, or missing
    - Quantity is invalid, ambiguous, or missing
    - Incompatible units are provided
    """
    if price is None:
        return None

    try:
        price_num = Decimal(str(price))
    except (InvalidOperation, ValueError):
        return None

    if price_num <= Decimal("0") or not price_num.is_finite():
        return None

    if isinstance(quantity_or_text, str):
        parsed = parse_pack_or_variant(quantity_or_text)
    elif isinstance(quantity_or_text, ParsedQuantity):
        parsed = quantity_or_text
    else:
        return None

    if not parsed or parsed.standard_amount <= Decimal("0"):
        return None

    sym = currency_symbol(currency)
    curr_suffix = f" {currency.upper()}" if currency and not sym else ""

    if parsed.measure_type == "mass":
        # Price per 100 grams
        # unit_price = (price / standard_amount_in_g) * 100
        unit_val = (price_num / parsed.standard_amount) * Decimal("100")
        rounded = unit_val.quantize(Decimal("0.01"))
        display = f"{sym}{rounded:f}{curr_suffix} / 100g"
        return {
            "unit_price": float(rounded),
            "display": display,
            "measure": "100g",
            "base_type": "mass",
            "pack_size": parsed.display,
            "currency": currency,
        }

    if parsed.measure_type == "volume":
        # Price per 1 Litre (1000 ml)
        # unit_price = (price / standard_amount_in_ml) * 1000
        unit_val = (price_num / parsed.standard_amount) * Decimal("1000")
        rounded = unit_val.quantize(Decimal("0.01"))
        display = f"{sym}{rounded:f}{curr_suffix} / L"
        return {
            "unit_price": float(rounded),
            "display": display,
            "measure": "1L",
            "base_type": "volume",
            "pack_size": parsed.display,
            "currency": currency,
        }

    if parsed.measure_type == "count":
        # Price per unit
        unit_val = price_num / parsed.standard_amount
        rounded = unit_val.quantize(Decimal("0.01"))
        display = f"{sym}{rounded:f}{curr_suffix} / unit"
        return {
            "unit_price": float(rounded),
            "display": display,
            "measure": "unit",
            "base_type": "count",
            "pack_size": parsed.display,
            "currency": currency,
        }

    return None


# ---------------------------------------------------------------------------
# Retailer Recognition & Trustworthy Link Generation
# ---------------------------------------------------------------------------

_KNOWN_RETAILERS: list[tuple[re.Pattern, str, bool]] = [
    (re.compile(r"amazon\.(?:in|com|co\.uk)", re.I), "Amazon India", True),
    (re.compile(r"flipkart\.com", re.I), "Flipkart", True),
    (re.compile(r"blinkit\.com", re.I), "Blinkit", True),
    (re.compile(r"zepto(?:now)?\.(?:com|co\.in)", re.I), "Zepto", True),
    (re.compile(r"reliancedigital\.in", re.I), "Reliance Digital", True),
    (re.compile(r"croma\.com", re.I), "Croma", True),
    (re.compile(r"tatacliq\.com", re.I), "Tata CLiQ", True),
    (re.compile(r"nykaa\.com", re.I), "Nykaa", True),
    (re.compile(r"myntra\.com", re.I), "Myntra", True),
    (re.compile(r"bigbasket\.com", re.I), "BigBasket", True),
    (re.compile(r"walmart\.com", re.I), "Walmart", True),
    (re.compile(r"target\.com", re.I), "Target", True),
    (re.compile(r"bestbuy\.com", re.I), "Best Buy", True),
]

_DIRECT_PRODUCT_URL_PATTERNS = re.compile(
    r"(?:/dp/|/gp/product/|/p/|/prn/|/product/|/item/|/pd/|\.html|\.htm|\?pid=|\?sku=)",
    re.I,
)


def identify_retailer(url: str | None) -> tuple[str, bool]:
    """Identify retailer name and whether URL points to a specific product page."""
    if not isinstance(url, str) or not url.strip():
        return "Source", False

    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()

    retailer_name = "Retailer"
    matched_known = False
    for pattern, name, _ in _KNOWN_RETAILERS:
        if pattern.search(netloc):
            retailer_name = name
            matched_known = True
            break

    if not matched_known:
        # Fallback to domain name
        clean_host = re.sub(r"^www\.", "", netloc)
        parts = clean_host.split(".")
        retailer_name = parts[0].capitalize() if parts else "Source"

    is_direct_product = bool(_DIRECT_PRODUCT_URL_PATTERNS.search(parsed.path + "?" + parsed.query))
    return retailer_name, is_direct_product


def generate_safe_retailer_search_links(
    product_name: str,
    category: str | None = None,
) -> list[dict[str, Any]]:
    """Generate safe, transparent fallback search links for major marketplaces.

    These are explicitly labelled as search fallbacks, never verified listings.
    """
    if not isinstance(product_name, str) or not product_name.strip():
        return []

    query = product_name.strip()
    encoded = quote_plus(query)

    search_options = [
        {
            "retailer": "Amazon India",
            "url": f"https://www.amazon.in/s?k={encoded}",
            "type": "search_fallback",
            "is_verified_product_url": False,
            "label": f"Search on Amazon India",
            "note": "Prices, stock, and delivery vary by seller and location",
        },
        {
            "retailer": "Flipkart",
            "url": f"https://www.flipkart.com/search?q={encoded}",
            "type": "search_fallback",
            "is_verified_product_url": False,
            "label": f"Search on Flipkart",
            "note": "Prices, stock, and delivery vary by seller and location",
        },
    ]

    # For food / grocery, add Blinkit option
    if category and re.search(r"food|grocery|groceries|snack|chocolate|sweet|dairy|beverage", category, re.I):
        search_options.append({
            "retailer": "Blinkit",
            "url": f"https://blinkit.com/s/?q={encoded}",
            "type": "search_fallback",
            "is_verified_product_url": False,
            "label": f"Search on Blinkit",
            "note": "Delivery and stock depend on current pincode",
        })

    return search_options


# ---------------------------------------------------------------------------
# Category-Aware Attributes
# ---------------------------------------------------------------------------

def get_category_attributes(category: str | None) -> list[AttributeDefinition]:
    """Provide category-appropriate comparison criteria dynamically."""
    cat = (category or "").lower().strip()

    if re.search(r"food|grocery|groceries|snack|chocolate|sweet|dairy|beverage", cat):
        return [
            AttributeDefinition("price", "Price", ValueType.SCALAR, comparison_rule="lower_is_better"),
            AttributeDefinition("pack_size", "Pack Size / Weight", ValueType.STRUCTURED),
            AttributeDefinition("flavour", "Flavour / Variety", ValueType.CATEGORICAL),
            AttributeDefinition("ingredients", "Ingredients & Dietary", ValueType.STRUCTURED),
            AttributeDefinition("availability", "Availability", ValueType.CATEGORICAL),
        ]

    if re.search(r"laptop|computer|pc|phone|smartphone|tablet|electronics", cat):
        return [
            AttributeDefinition("price", "Price", ValueType.SCALAR, comparison_rule="lower_is_better"),
            AttributeDefinition("processor", "Processor & Chipset", ValueType.STRUCTURED),
            AttributeDefinition("ram_storage", "RAM & Storage", ValueType.STRUCTURED),
            AttributeDefinition("display", "Display", ValueType.STRUCTURED),
            AttributeDefinition("battery_life", "Battery Life", ValueType.STRUCTURED),
            AttributeDefinition("availability", "Availability", ValueType.CATEGORICAL),
        ]

    if re.search(r"skin|beauty|cosmetic|care|hair", cat):
        return [
            AttributeDefinition("price", "Price", ValueType.SCALAR, comparison_rule="lower_is_better"),
            AttributeDefinition("product_size", "Product Size / Volume", ValueType.STRUCTURED),
            AttributeDefinition("skin_type", "Target Skin Type & Use", ValueType.STRUCTURED),
            AttributeDefinition("ingredients", "Key Ingredients", ValueType.STRUCTURED),
            AttributeDefinition("availability", "Availability", ValueType.CATEGORICAL),
        ]

    if re.search(r"cloth|apparel|footwear|shoe|wear|fashion", cat):
        return [
            AttributeDefinition("price", "Price", ValueType.SCALAR, comparison_rule="lower_is_better"),
            AttributeDefinition("material", "Material & Fabric", ValueType.STRUCTURED),
            AttributeDefinition("sizes_fit", "Sizes & Fit", ValueType.STRUCTURED),
            AttributeDefinition("colors", "Color Options", ValueType.CATEGORICAL),
            AttributeDefinition("availability", "Availability", ValueType.CATEGORICAL),
        ]

    # Default general domain
    return [
        AttributeDefinition("price", "Price", ValueType.SCALAR, comparison_rule="lower_is_better"),
        AttributeDefinition("features", "Key Features & Specs", ValueType.STRUCTURED),
        AttributeDefinition("quality", "Quality & Rating", ValueType.STRUCTURED),
        AttributeDefinition("availability", "Availability", ValueType.CATEGORICAL),
    ]


# ---------------------------------------------------------------------------
# Executive Verdict Generation
# ---------------------------------------------------------------------------

@dataclass
class ExecutiveVerdict:
    recommendation_type: str  # "winner", "tie", "inconclusive"
    winner_entity_key: str | None
    winner_name: str | None
    headline: str
    summary: str
    reasons: list[str] = field(default_factory=list)
    key_findings: list[str] = field(default_factory=list)
    evidence_strength: str = "insufficient"  # "high", "moderate", "low", "insufficient"

    def to_dict(self) -> dict[str, Any]:
        return {
            "recommendation_type": self.recommendation_type,
            "winner_entity_key": self.winner_entity_key,
            "winner_name": self.winner_name,
            "headline": self.headline,
            "summary": self.summary,
            "reasons": self.reasons,
            "key_findings": self.key_findings,
            "evidence_strength": self.evidence_strength,
        }


def generate_executive_verdict(
    entities: list[dict[str, Any]],
    attributes: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    attribute_analyses: list[dict[str, Any]],
    category: str | None = None,
) -> dict[str, Any]:
    """Generate a transparent, evidence-grounded recommendation or inconclusive explanation."""
    if len(entities) < 2:
        return ExecutiveVerdict(
            recommendation_type="inconclusive",
            winner_entity_key=None,
            winner_name=None,
            headline="At least two entities are required to generate a comparison verdict",
            summary="A comparative verdict requires at least two entities with verifiable data.",
            reasons=["Fewer than two entities provided."],
            evidence_strength="insufficient",
        ).to_dict()

    # Index observations by (entity_key, attribute_key)
    obs_by_pair: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for obs in observations:
        pair = (obs.get("entity_key"), obs.get("attribute_key"))
        if pair[0] and pair[1]:
            obs_by_pair.setdefault(pair, []).append(obs)

    # Check price verification
    def _item_key(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("attribute_key") or "")
        return str(getattr(item, "attribute_key", ""))

    def _item_label(item: Any) -> str:
        if isinstance(item, dict):
            return str(item.get("label") or "")
        return str(getattr(item, "label", ""))

    price_analysis = next(
        (a for a in attribute_analyses if _item_key(a) == "price" or "price" in _item_label(a).lower()),
        None,
    )

    entity_prices: dict[str, Decimal] = {}
    entity_unit_prices: dict[str, dict[str, Any]] = {}
    price_unverified_entities: list[str] = []

    for ent in entities:
        ekey = ent.get("key", "")
        ename = ent.get("display_name", ekey)
        # Find price observation
        p_obs = obs_by_pair.get((ekey, "price"), [])
        if not p_obs:
            # check any attribute with price in key
            for (k, attr_k), items in obs_by_pair.items():
                if k == ekey and "price" in attr_k.lower():
                    p_obs = items
                    break

        usable_p = [item for item in p_obs if item.get("normalized_value") is not None]
        if usable_p:
            try:
                num = Decimal(str(usable_p[0]["normalized_value"]))
                entity_prices[ekey] = num
                # Check if unit price is calculable
                curr = usable_p[0].get("currency")
                raw_txt = str(usable_p[0].get("raw_value") or "")
                ctx = usable_p[0].get("context") or {}
                quote = str(ctx.get("evidence_quote") or raw_txt)

                # Look for pack size / variant in context, raw_val, or quote
                up = calculate_unit_price(num, quote, curr) or calculate_unit_price(num, raw_txt, curr)
                if up:
                    entity_unit_prices[ekey] = up
            except (InvalidOperation, ValueError):
                price_unverified_entities.append(ename)
        else:
            price_unverified_entities.append(ename)

    # Rule 1: Key prices unverified -> INCONCLUSIVE
    if len(price_unverified_entities) > 0:
        missing_names = ", ".join(price_unverified_entities)
        return ExecutiveVerdict(
            recommendation_type="inconclusive",
            winner_entity_key=None,
            winner_name=None,
            headline="A decisive recommendation cannot yet be confirmed",
            summary=f"Independent price verification is incomplete for {missing_names}. To prevent misleading advice, a definitive winner cannot be declared without verified price data.",
            reasons=[
                f"Unverified pricing for: {missing_names}",
                "Product variant sizes could not be reconciled into comparable units",
                "Shopping links and live prices remain subject to seller availability",
            ],
            key_findings=[
                f"Pricing information for {missing_names} was not confirmed by accessible sources.",
                "Review the evidence ledger below for verified claims and search links.",
            ],
            evidence_strength="insufficient" if len(price_unverified_entities) == len(entities) else "low",
        ).to_dict()

    # Rule 2: Both have verified unit prices -> Compare Unit Prices!
    if len(entity_unit_prices) >= 2:
        # Check if they share the same measure (e.g. 100g, 1L, unit)
        measures = {up["measure"] for up in entity_unit_prices.values()}
        if len(measures) == 1:
            sorted_units = sorted(entity_unit_prices.items(), key=lambda pair: pair[1]["unit_price"])
            best_key, best_up = sorted_units[0]
            second_key, second_up = sorted_units[1]
            best_ent = next((e for e in entities if e["key"] == best_key), {})
            second_ent = next((e for e in entities if e["key"] == second_key), {})
            best_name = best_ent.get("display_name", best_key)
            second_name = second_ent.get("display_name", second_key)

            diff = second_up["unit_price"] - best_up["unit_price"]
            if diff > 0.01:
                return ExecutiveVerdict(
                    recommendation_type="winner",
                    winner_entity_key=best_key,
                    winner_name=best_name,
                    headline=f"{best_name} delivers superior verified unit value",
                    summary=f"Based on verified pack sizes and pricing, {best_name} offers a lower price per {best_up['measure']} ({best_up['display']}) compared to {second_name} ({second_up['display']}).",
                    reasons=[
                        f"Better value for money: {best_up['display']} vs {second_up['display']}",
                        f"Verified pack size: {best_up.get('pack_size', 'standard')} vs {second_up.get('pack_size', 'standard')}",
                        "Pricing independently verified from retailer evidence",
                    ],
                    key_findings=[
                        f"{best_name} verified unit price: {best_up['display']}.",
                        f"{second_name} verified unit price: {second_up['display']}.",
                        f"Value advantage: {diff:.2f} per {best_up['measure']}.",
                    ],
                    evidence_strength="high",
                ).to_dict()
            else:
                return ExecutiveVerdict(
                    recommendation_type="tie",
                    winner_entity_key=None,
                    winner_name=None,
                    headline=f"{best_name} and {second_name} offer identical unit pricing",
                    summary=f"Both products offer comparable unit pricing ({best_up['display']}). Selection should be made based on flavour or brand preference.",
                    reasons=[
                        f"Equivalent unit pricing: {best_up['display']}",
                        "Comparable pack quantities verified",
                    ],
                    key_findings=[
                        f"Both options share identical verified unit price: {best_up['display']}.",
                    ],
                    evidence_strength="high",
                ).to_dict()

    # Rule 3: Direct verified prices available without unit price normalization
    if len(entity_prices) >= 2:
        sorted_prices = sorted(entity_prices.items(), key=lambda pair: pair[1])
        cheapest_key, cheapest_price = sorted_prices[0]
        pricier_key, pricier_price = sorted_prices[1]
        cheapest_ent = next((e for e in entities if e["key"] == cheapest_key), {})
        pricier_ent = next((e for e in entities if e["key"] == pricier_key), {})
        c_name = cheapest_ent.get("display_name", cheapest_key)
        p_name = pricier_ent.get("display_name", pricier_key)

        sym = currency_symbol(None)
        return ExecutiveVerdict(
            recommendation_type="winner",
            winner_entity_key=cheapest_key,
            winner_name=c_name,
            headline=f"{c_name} offers the lowest verified entry price",
            summary=f"Among verified offers, {c_name} was observed at {cheapest_price} versus {pricier_price} for {p_name}. Compare configurations to ensure matching specifications.",
            reasons=[
                f"Lower observed starting price: {cheapest_price} vs {pricier_price}",
                "Pricing supported by fetched retailer evidence",
            ],
            key_findings=[
                f"{c_name} observed price: {cheapest_price}.",
                f"{p_name} observed price: {pricier_price}.",
            ],
            evidence_strength="moderate",
        ).to_dict()

    return ExecutiveVerdict(
        recommendation_type="inconclusive",
        winner_entity_key=None,
        winner_name=None,
        headline="Insufficient verified data for an executive conclusion",
        summary="Additional verifiable evidence is required to establish a reliable winner.",
        reasons=["Lack of verified comparative observations across both entities."],
        evidence_strength="insufficient",
    ).to_dict()
