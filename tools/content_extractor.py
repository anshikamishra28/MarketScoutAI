from bs4 import BeautifulSoup


def extract_content(html: str) -> str:
    """
    Extract readable text from raw HTML.
    """

    soup = BeautifulSoup(html, "html.parser")

    # Remove elements that do not contain useful article content.
    for element in soup(
        ["script", "style", "noscript", "header", "footer", "nav"]
    ):
        element.decompose()

    text = soup.get_text(
        separator=" ",
        strip=True
    )

    return text