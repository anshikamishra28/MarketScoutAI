import os
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from googlenewsdecoder import gnewsdecoder

from tools.web_search_direct import search_direct


def _decode_google_news_url(url: str) -> str:
    """Convert a Google News wrapper URL into the original article URL."""
    if "news.google.com" not in url:
        return url

    try:
        result = gnewsdecoder(url)

        if result.get("success") and result.get("decoded_url"):
            return result["decoded_url"]

    except Exception:
        pass

    return ""


def _search_bing(query: str, max_results: int) -> list[dict]:
    response = requests.get(
        "https://www.bing.com/search",
        params={"q": query, "count": max_results},
        headers={
            "User-Agent": "Mozilla/5.0 (compatible; MarketScoutAI/1.0)"
        },
        timeout=12,
    )
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    results = []

    for row in soup.select("li.b_algo"):
        anchor = row.select_one("h2 a[href]")

        if not anchor:
            continue

        url = anchor.get("href", "")
        host = (urlparse(url).hostname or "").lower()

        if not url.startswith("http") or host.endswith("bing.com"):
            continue

        snippet = row.select_one(".b_caption p")

        results.append(
            {
                "title": anchor.get_text(" ", strip=True),
                "url": url,
                "publisher": host.removeprefix("www."),
                "snippet": (
                    snippet.get_text(" ", strip=True)
                    if snippet
                    else ""
                ),
                "published_at": "",
                "search_query": query,
            }
        )

        if len(results) >= max_results:
            break

    return results


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web and return direct article URLs.

    Search order:
    1. Configured SearXNG instance
    2. Bing
    3. Direct Google search
    4. Google News RSS with URL decoding
    """

    # 1. SearXNG
    searx_url = os.getenv("SEARX_URL", "").strip()

    if searx_url:
        try:
            response = requests.get(
                urljoin(searx_url.rstrip("/") + "/", "search"),
                params={
                    "q": query,
                    "format": "json",
                },
                headers={
                    "User-Agent": "MarketScoutAI/1.0"
                },
                timeout=12,
            )

            response.raise_for_status()

            rows = response.json().get("results", [])

            direct = [
                {
                    "title": row.get("title", ""),
                    "url": row.get("url", ""),
                    "publisher": row.get("pretty_url", ""),
                    "snippet": row.get("content", ""),
                    "published_at": row.get("publishedDate", "") or "",
                    "search_query": query,
                }
                for row in rows
                if row.get("url", "").startswith("http")
            ]

            if direct:
                return direct[:max_results]

        except (requests.RequestException, ValueError, TypeError):
            pass

    # 2. Bing
    try:
        direct = _search_bing(query, max_results)

        if direct:
            return direct

    except requests.RequestException:
        pass

    # 3. Direct Google search
    try:
        direct = search_direct(
            query,
            max_results=max_results,
        )

        if direct:
            return direct[:max_results]

    except requests.RequestException:
        pass

    # 4. Google News RSS
    url = "https://news.google.com/rss/search"

    response = requests.get(
        url,
        params={
            "q": query,
            "hl": "en-IN",
            "gl": "IN",
            "ceid": "IN:en",
        },
        headers={
            "User-Agent": "MarketScoutAI/1.0",
        },
        timeout=10,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.content,
        "xml",
    )

    results = []

    for item in soup.find_all("item"):

        if len(results) >= max_results:
            break

        title = item.find("title")
        link = item.find("link")
        description = item.find("description")
        pub_date = item.find("pubDate")
        source = item.find("source")

        if not title or not link:
            continue

        google_news_url = link.get_text(strip=True)

        # Decode Google News wrapper into real publisher URL.
        decoded_url = _decode_google_news_url(
            google_news_url
        )

        # If decoding failed, don't send a Google News
        # wrapper downstream as if it were an article.
        if not decoded_url:
            continue

        publisher = ""
        publisher_url = ""

        if source:
            publisher = source.get_text(strip=True)
            publisher_url = source.get("url", "")

        snippet = ""

        if description:
            description_html = description.get_text(
                strip=True
            )

            snippet = BeautifulSoup(
                description_html,
                "html.parser",
            ).get_text(
                " ",
                strip=True,
            )

        results.append(
            {
                "title": title.get_text(strip=True),
                "url": decoded_url,
                "google_news_url": google_news_url,
                "publisher": publisher,
                "publisher_url": publisher_url,
                "snippet": snippet,
                "published_at": (
                    pub_date.get_text(strip=True)
                    if pub_date
                    else ""
                ),
                "search_query": query,
            }
        )

    return results