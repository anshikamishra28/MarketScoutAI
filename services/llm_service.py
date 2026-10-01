"""Small Gemini adapter with validated structured-output helpers."""
import json
import os
import re
import time
from functools import lru_cache

from dotenv import load_dotenv

load_dotenv()


@lru_cache(maxsize=1)
def _client():
    key = os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    from google import genai
    from google.genai import types
    return genai.Client(api_key=key, http_options=types.HttpOptions(timeout=30_000))


def generate_response(prompt: str, *, json_mode: bool = False, retries: int = 2) -> str:
    client = _client()
    if client is None:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    from google.genai import types
    config = types.GenerateContentConfig(
        response_mime_type="application/json" if json_mode else None,
        # This app does not register Gemini-callable functions; keep the API call text-only.
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    for attempt in range(retries + 1):
        try:
            response = client.models.generate_content(model=model, contents=prompt, config=config)
            text = getattr(response, "text", None)
            if not text or not text.strip():
                raise RuntimeError("Gemini returned an empty response")
            return text.strip()
        except Exception as exc:
            if attempt >= retries or not any(s in str(exc).lower() for s in ("429", "rate", "timeout", "temporar")):
                raise RuntimeError(f"Gemini request failed: {exc}") from exc
            time.sleep(0.5 * (attempt + 1))


def parse_json_response(text: str):
    """Parse JSON including common fenced or prefaced model responses."""
    if not text or not text.strip():
        raise ValueError("LLM returned an empty response")
    candidate = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text.strip(), flags=re.I)
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(candidate[start:end + 1])
            except json.JSONDecodeError:
                pass
        raise ValueError("LLM returned malformed JSON")
