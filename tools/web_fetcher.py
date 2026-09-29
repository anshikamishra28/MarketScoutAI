import requests
from bs4 import BeautifulSoup


def resolve_url(url: str) -> str:
    """
    Resolve a redirect URL to the final webpage URL.
    """

    response = requests.get(
        url,
        headers={
            "User-Agent": "MarketScoutAI/0.1"
        },
        timeout=10,
        allow_redirects=True,
    )

    response.raise_for_status()

    return response.url


def fetch_page(url: str) -> str:
    """
    Fetch a webpage and return its readable text.
    """

    try:
        final_url = resolve_url(url)

        response = requests.get(
            final_url,
            timeout=10,
            headers={
                "User-Agent": "MarketScoutAI/0.1"
            },
        )

        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        for element in soup(["script", "style", "noscript"]):
            element.decompose()

        text = soup.get_text(separator=" ", strip=True)

        return text

    except requests.RequestException as error:
        raise RuntimeError(
            f"Failed to fetch webpage: {error}"
        ) from error