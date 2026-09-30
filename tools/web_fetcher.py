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
                "User-Agent": "Mozilla/5.0"
            },
        )

        response.raise_for_status()

        response.encoding = response.apparent_encoding
        return extract_content(response.text)

    except requests.RequestException as error:
        raise RuntimeError(
            f"Failed to fetch webpage: {error}"
        ) from error