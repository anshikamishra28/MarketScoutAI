"""Contract for sources that provide generic comparison observations."""
from dataclasses import dataclass, field
from typing import Protocol

from models.comparison import ComparisonRequest, Observation, SourceCheck, SourceReference, SourceStatus


@dataclass
class ComparisonSourceOutcome:
    """One source-check result and the observations it explicitly supports."""

    check: SourceCheck
    observations: list[Observation] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.check, SourceCheck):
            raise ValueError("check must be a SourceCheck")
        if not isinstance(self.observations, list) or not all(
            isinstance(item, Observation) for item in self.observations
        ):
            raise ValueError("observations must be a list of Observation values")
        if self.check.status is not SourceStatus.CHECKED and self.observations:
            raise ValueError("only a checked source result may contain observations")
        if any(item.source_key != self.check.source.key for item in self.observations):
            raise ValueError("observation source_key must match the source check")


class ComparisonSourceAdapter(Protocol):
    """A source-specific boundary; generic orchestration knows no source domain."""

    source: SourceReference

    def supports(self, request: ComparisonRequest, source: SourceReference) -> bool:
        """Return whether this adapter can check the given source/request pair."""
        ...

    def check(self, request: ComparisonRequest, source: SourceReference) -> ComparisonSourceOutcome:
        """Return a source state and observations grounded in that source."""
        ...
