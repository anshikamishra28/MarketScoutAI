import requests
from bs4 import BeautifulSoup


def search_web(query: str, max_results: int = 5) -> list[dict]:
    """
    Search Google News RSS and return structured results.
    """

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
            "User-Agent": "MarketScoutAI/0.1",
        },
        timeout=10,
    )

    response.raise_for_status()

    soup = BeautifulSoup(
        response.content,
        "xml",
    )

    results = []

    for item in soup.find_all("item")[:max_results]:
        title = item.find("title")
        link = item.find("link")
        description = item.find("description")
        pub_date = item.find("pubDate")
        source = item.find("source")

        if not title or not link:
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
                "url": link.get_text(strip=True),
                "raw_link": str(link),
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