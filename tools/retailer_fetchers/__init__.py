"""Retailer-specific price page adapters, separate from research extraction."""

from tools.retailer_fetchers.base import RetailerFetchOutcome, RetailerFetcher
from tools.retailer_fetchers.reliance_digital import RelianceDigitalFetcher

__all__ = ["RetailerFetchOutcome", "RetailerFetcher", "RelianceDigitalFetcher"]
