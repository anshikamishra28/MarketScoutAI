import requests

from tools.content_extractor import extract_content


def resolve_url(url: str) -> str:
    """
    Resolve a URL to the final webpage URL.
    """

    response = requests.get(
        url,
        headers={
            "User-Agent": "Mozilla/5.0"
        },
        timeout=10,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response.url


def fetch_document(url: str) -> dict:
    """
    Fetch a webpage and return its readable text.
    """

    try:
        final_url = resolve_url(url)

        response = requests.get(
            final_url,
            timeout=10,
            headers={
                "User-Agent": "Mozilla/5.0"
            },
        )

        response.raise_for_status()

        content_type = response.headers.get("content-type", "").lower()
        if content_type and not any(kind in content_type for kind in ("text/html", "application/xhtml+xml")):
            raise RuntimeError(f"Unsupported content type: {content_type}")

        response.encoding = response.apparent_encoding
        content = extract_content(response.text)
        if not content:
            raise RuntimeError("Fetched page contains no readable text")
        return {"content": content, "final_url": response.url, "content_type": content_type}

    except (requests.RequestException, RuntimeError) as error:
        raise RuntimeError(
            f"Failed to fetch webpage: {error}"
        ) from error


def fetch_page(url: str) -> str:
    """Backward compatible text-only fetch helper."""
    return fetch_document(url)["content"]
