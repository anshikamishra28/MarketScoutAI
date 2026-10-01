"""Extract readable article text from HTML without flattening site chrome into it."""
import re
from bs4 import BeautifulSoup, Tag

_NOISE = re.compile(
    r"(?:^|[-_\s])(?:advert|advertisement|ad-slot|ad-container|promo|promotion|"
    r"social|share|sharing|subscribe|newsletter|cookie|consent|breadcrumb|"
    r"related|recommended|trending|popular|latest|most-read|most-viewed|sidebar|widget|"
    r"ticker|market-data|stock-widget|stock-market|news-widget|top-stories|top-news|"
    r"more-stories|editors-pick|you-may-like|navigation|navbar|menu|footer)(?:$|[-_\s])",
    re.I,
)
_NOISE_TEXT = re.compile(
    r"^(?:advertisement|sponsored content|read more|related (?:articles|news)|"
    r"latest (?:news|articles)|most read|trending now|share this (?:article|story)|"
    r"follow us(?: on .*)?|subscribe(?: now)?|accept (?:all )?cookies|"
    r"manage (?:your )?preferences|sign up for our newsletter)\b",
    re.I,
)
_ARTICLE_HINT = re.compile(r"article|story|post|entry|body|content|main", re.I)


def _is_noise(node: Tag) -> bool:
    if node.name in {"script", "style", "noscript", "nav", "aside", "footer", "form", "button", "svg", "iframe", "template"}:
        return True
    role = (node.get("role") or "").lower()
    if role in {"navigation", "complementary", "contentinfo", "search"}:
        return True
    values = " ".join(str(node.get(key, "")) for key in ("id", "class", "aria-label", "data-testid"))
    if _NOISE.search(values):
        return True
    if node.name == "header" and not node.find_parent("article"):
        return True
    return False


def _candidate_score(node: Tag) -> int:
    text_len = len(node.get_text(" ", strip=True))
    paragraphs = len(node.find_all("p"))
    headings = len(node.find_all(["h1", "h2", "h3"]))
    identity = " ".join([str(node.get("id", "")), " ".join(node.get("class", []))])
    semantic = 1000 if node.name == "article" else 500 if node.name == "main" or node.get("role") == "main" else 200 if _ARTICLE_HINT.search(identity) else 0
    # Penalize enormous generic roots: article-like regions should beat the page body.
    return semantic + min(text_len, 20000) + paragraphs * 100 + headings * 30


def _best_region(soup: BeautifulSoup) -> Tag:
    candidates = soup.select("article, main, [role='main'], [itemprop~='articleBody'], [class*='article'], [class*='story'], [id*='article'], [id*='content']")
    return max(candidates, key=_candidate_score) if candidates else soup.body or soup


def _text_blocks(root: Tag) -> list[str]:
    blocks = []
    for node in root.find_all(["h1", "h2", "h3", "h4", "p", "blockquote", "li", "tr", "td"]):
        if node.name == "td" and node.find_parent("tr"):
            continue
        if node.find(["p", "h1", "h2", "h3", "h4"]):
            continue
        value = re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()
        if len(value) < 3 or _NOISE_TEXT.match(value):
            continue
        blocks.append(value)
    return blocks


def extract_content(html: str) -> str:
    """Return article-oriented text while retaining headings and factual paragraphs.

    Semantic article/main regions are preferred. On less structured pages, the
    body is used after removing common site chrome and widget containers.
    """
    if not html or not html.strip():
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for node in list(soup.find_all(True)):
        if node.parent is not None and _is_noise(node):
            node.decompose()
    root = _best_region(soup)
    blocks = _text_blocks(root)
    if not blocks:
        # Fallback for pages whose article is rendered without semantic blocks.
        text = re.sub(r"\s+", " ", root.get_text(" ", strip=True)).strip()
        return "" if _NOISE_TEXT.match(text) else text
    deduped, seen = [], set()
    for block in blocks:
        key = re.sub(r"\W+", " ", block.lower()).strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(block)
    return "\n\n".join(deduped)
