import base64
from urllib.parse import parse_qs, urlparse

import requests
from bs4 import BeautifulSoup


def decode_bing_url(url: str) -> str:
    """
    Convert a Bing tracking URL into the actual destination URL.
    """

    parsed = urlparse(url)
    query = parse_qs(parsed.query)

    encoded_url = query.get("u", [None])[0]

    if not encoded_url:
        return url

    try:
        # Bing prefixes the Base64 value with "a1".
        if encoded_url.startswith("a1"):
            encoded_url = encoded_url[2:]

        padding = "=" * (-len(encoded_url) % 4)

        decoded_url = base64.urlsafe_b64decode(
            encoded_url + padding
        ).decode("utf-8")

        return decoded_url

    except (ValueError, UnicodeDecodeError):
        return url


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web using Bing's public HTML search page.
    """

    response = requests.get(
        "https://www.bing.com/search",
        params={
            "q": query,
        },
        headers={
            "User-Agent": "Mozilla/5.0",
        },
        timeout=10,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.text,
        "html.parser",
    )

    results = []

    for result in soup.select("li.b_algo"):
        link = result.select_one("h2 a")

        if not link:
            continue

        title = link.get_text(
            " ",
            strip=True,
        )

        tracking_url = link.get("href", "")

        actual_url = decode_bing_url(
            tracking_url
        )

        snippet_element = result.select_one(
            ".b_caption p"
        )

        snippet = (
            snippet_element.get_text(
                " ",
                strip=True,
            )
            if snippet_element
            else ""
        )

        results.append(
            {
                "title": title,
                "url": actual_url,
                "snippet": snippet,
                "search_query": query,
            }
        )

        if len(results) >= max_results:
            break

    return results