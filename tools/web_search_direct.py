import requests
from bs4 import BeautifulSoup


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

        if not href.startswith("/url?q="):
            continue

        actual_url = href.split("/url?q=", 1)[1].split("&", 1)[0]

        if actual_url.startswith("http"):
            results.append({
                "title": link.get_text(" ", strip=True),
                "url": actual_url,
                "search_query": query,
            })

        if len(results) >= max_results:
            break

    return results