"""Generic source adapter contracts for domain-neutral comparisons."""

from tools.comparison_sources.base import ComparisonSourceAdapter, ComparisonSourceOutcome
from tools.comparison_sources.reliance_digital import RelianceDigitalComparisonAdapter
from tools.comparison_sources.web_research import WEB_RESEARCH_SOURCE, WebResearchComparisonAdapter

__all__ = [
    "ComparisonSourceAdapter",
    "ComparisonSourceOutcome",
    "RelianceDigitalComparisonAdapter",
    "WEB_RESEARCH_SOURCE",
    "WebResearchComparisonAdapter",
]
