from dataclasses import dataclass


@dataclass
class Evidence:
    """
    Represents a piece of evidence collected during research.
    """

    claim: str
    source_title: str
    source_url: str
    publisher: str
    evidence_text: str
    published_at: str
    search_query: str