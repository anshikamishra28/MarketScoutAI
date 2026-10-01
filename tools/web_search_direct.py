import requests
from bs4 import BeautifulSoup
from urllib.parse import parse_qs, urlparse


def search_direct(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web and return direct result URLs.
    """

    url = "https://www.google.com/search"

    response = requests.get(
        url,
        params={
            "q": query,
            "num": max_results,
        },
        headers={
            "User-Agent": "Mozilla/5.0",
        },
        timeout=10,
    )

    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")

    results = []

    for link in soup.select("a"):
        href = link.get("href", "")

        parsed = urlparse(href)
        actual_url = parse_qs(parsed.query).get("q", [""])[0] if parsed.path == "/url" else href

        if actual_url.startswith("http") and "google." not in urlparse(actual_url).hostname and "news.google.com" not in actual_url:
            results.append({
                "title": link.get_text(" ", strip=True) or actual_url,
                "url": actual_url,
                "publisher": urlparse(actual_url).hostname or "",
                "snippet": "",
                "published_at": "",
                "search_query": query,
            })

        if len(results) >= max_results:
            break

    return results
