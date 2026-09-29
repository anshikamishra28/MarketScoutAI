import requests


def search_wikipedia(query: str, max_results: int = 5) -> list[dict]:
    """
    Search Wikipedia using its public API.
    """

    response = requests.get(
        "https://en.wikipedia.org/w/api.php",
        params={
            "action": "query",
            "list": "search",
            "srsearch": query,
            "format": "json",
            "srlimit": max_results,
        },
        headers={
            "User-Agent": "MarketScoutAI/0.1"
        },
        timeout=10,
    )

    response.raise_for_status()

    data = response.json()

    results = []

    for item in data.get("query", {}).get("search", []):
        results.append(
            {
                "title": item["title"],
                "snippet": item["snippet"],
                "url": (
                    "https://en.wikipedia.org/wiki/"
                    + item["title"].replace(" ", "_")
                ),
            }
        )

    return results