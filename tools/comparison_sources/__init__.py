"""Generic source adapter contracts for domain-neutral comparisons."""

from tools.comparison_sources.base import ComparisonSourceAdapter, ComparisonSourceOutcome
from tools.comparison_sources.reliance_digital import RelianceDigitalComparisonAdapter

__all__ = ["ComparisonSourceAdapter", "ComparisonSourceOutcome", "RelianceDigitalComparisonAdapter"]
