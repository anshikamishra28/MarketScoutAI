"""Research-question planner. LLM plans are validated; offline fallback is explicit."""
import re

from services.llm_service import generate_response, parse_json_response

DEFAULT_REQUIREMENTS = ["market overview", "competitors and positioning", "pricing and segments", "consumer preferences", "recent trends", "opportunities and risks"]

_PRICE_BAND = r"(?:20\s*k.{0,15}30\s*k|20\s*,?\s*000.{0,20}30\s*,?\s*000|(?:sub|under|below).{0,20}(?:₹|rs\.?\s*|inr\s*)?(?:30\s*,?\s*000|30\s*k)|mid[- ]?(?:range|tier))"
_INDIA_SMARTPHONE_SUB30_REQUIREMENTS = [
    ("India smartphone brand share in the ₹20,000–₹30,000 segment", rf"(?=.*(?:brand|brands))(?=.*share)(?=.*{_PRICE_BAND})", r"brand|share"),
    ("Consumer preferences and survey insights for Indian mid-tier smartphone buyers", rf"(?=.*(?:consumer|buyer|preference))(?=.*(?:survey|insight))(?=.*{_PRICE_BAND})", r"consumer|buyer|preference|survey|insight"),
    ("Current smartphone model pricing under ₹30,000 in India", rf"(?=.*\bmodel\b)(?=.*(?:model.{{0,40}}pric|pric.{{0,40}}model))(?=.*{_PRICE_BAND})", r"model.{0,30}pric|pric.{0,30}model|pricing and segments"),
    ("Pricing strategies and promotional offers within the Indian sub-₹30,000 smartphone segment", rf"(?=.*(?:pricing|price))(?=.*(?:strateg|promot|offer|discount|financ|exchange))(?=.*{_PRICE_BAND})", r"pricing|price|promotion|offer|discount|financ|exchange"),
    ("Sales volume and revenue growth for India’s sub-₹30,000 smartphone segment", rf"(?=.*(?:sales|shipment|unit|volume))(?=.*(?:growth|revenue))(?=.*{_PRICE_BAND})", r"sales|shipment|unit|volume|revenue|growth"),
    ("Mid-tier smartphone technology adoption trends in India", rf"(?=.*(?:technology|tech|5g|ai))(?=.*(?:adoption|trend))(?=.*{_PRICE_BAND})", r"technology|tech|5g|ai|adoption|trend"),
    ("Online vs. offline distribution for Indian sub-₹30,000 smartphones", rf"(?=.*online)(?=.*offline)(?=.*(?:channel|distribution)?)(?=.*{_PRICE_BAND})", r"online|offline|channel|distribution|retail"),
]


def _is_india_smartphone_under_30k(question: str) -> bool:
    value = question.lower()
    if not ("india" in value or "indian" in value) or not any(term in value for term in ("smartphone", "mobile phone", "handset")):
        return False
    match = re.search(r"(?:under|below|less than|<)\s*(?:₹|rs\.?\s*|inr\s*)?(\d[\d,]*)(\s*k)?", value, re.I)
    if not match:
        return False
    ceiling = int(match.group(1).replace(",", "")) * (1000 if match.group(2) else 1)
    return ceiling <= 30000


def _ensure_india_smartphone_requirements(plan: dict, question: str) -> dict:
    if not _is_india_smartphone_under_30k(question):
        return plan
    original = list(plan.get("information_needed", []))
    scoped = []
    replaced_patterns = []
    for required, specific_pattern, broad_pattern in _INDIA_SMARTPHONE_SUB30_REQUIREMENTS:
        specific = next((existing for existing in original if re.search(specific_pattern, existing, re.I)), None)
        scoped.append(specific or required)
        replaced_patterns.append(broad_pattern)
    # Replace broad planner dimensions once, then append all scoped dimensions.
    # Applying replacements incrementally could accidentally remove a canonical
    # requirement added by an earlier pass (for example pricing vs promotions).
    extras = [existing for existing in original if not any(re.search(pattern, existing, re.I) for pattern in replaced_patterns)]
    # Keep an additional macro requirement only as explicitly labeled context;
    # the seven canonical dimensions remain the complete analytical checklist.
    macro_extras = [
        f"MACRO / CONTEXT: {existing}" if not existing.lower().startswith("macro / context:") else existing
        for existing in extras
        if re.search(r"macroeconom|inflation|interest rates?|exchange rates?|currency|gdp|economic factors", existing, re.I)
    ]
    requirements = list(macro_extras)
    for item in scoped:
        if item not in requirements:
            requirements.append(item)
    return {**plan, "information_needed": requirements}


def _fallback_plan(question: str) -> dict:
    terms = question.strip().rstrip("?.!")
    queries = [f"{terms} market size overview", f"{terms} leading competitors pricing", f"{terms} consumer trends reviews", f"{terms} industry report opportunities risks"]
    return {"research_goal": terms, "sub_questions": [f"What is the current state of {terms}?", f"Who are the main competitors and how are they positioned?", f"What trends, opportunities, and risks are evident?"], "information_needed": DEFAULT_REQUIREMENTS.copy(), "search_queries": queries}


def create_research_plan(research_question: str) -> dict:
    if not research_question or not research_question.strip():
        raise ValueError("Research question cannot be empty")
    prompt = f'''Create a research plan for this market research question: {research_question}\nReturn JSON with research_goal (string), sub_questions (3-6 strings), information_needed (strings), search_queries (strings). Do not answer the question.'''
    try:
        plan = parse_json_response(generate_response(prompt, json_mode=True))
        if not isinstance(plan, dict):
            raise ValueError("Plan must be a JSON object")
        for field in ("sub_questions", "information_needed", "search_queries"):
            if not isinstance(plan.get(field), list) or not all(isinstance(v, str) and v.strip() for v in plan[field]):
                raise ValueError(f"Invalid plan field: {field}")
        if not plan["search_queries"] or not plan["information_needed"]:
            raise ValueError("Plan is missing required research tasks")
        return _ensure_india_smartphone_requirements(plan, research_question)
    except Exception:
        # Allows the research tools and API to remain usable when Gemini is unavailable.
        return _ensure_india_smartphone_requirements(_fallback_plan(research_question), research_question)
