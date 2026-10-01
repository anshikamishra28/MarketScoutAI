"""Shared interface and result container for price retailer adapters."""
from dataclasses import dataclass, field
from typing import Protocol, TypeAlias

from models.price_comparison import PriceOffer, ProductIdentity, RetailerResult, RetailerStatus

ProductTarget: TypeAlias = ProductIdentity | str


@dataclass
class RetailerFetchOutcome:
    check: RetailerResult
    offers: list[PriceOffer] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.check.status is not RetailerStatus.CHECKED and self.offers:
            raise ValueError("only a checked retailer result may contain price observations")
        if any(offer.retailer != self.check.retailer for offer in self.offers):
            raise ValueError("offer retailer must match the retailer check")


class RetailerFetcher(Protocol):
    retailer: str

    def fetch(self, target: ProductTarget) -> RetailerFetchOutcome:
        """Check a retailer for the target; never parse prices from search snippets."""
        ...
