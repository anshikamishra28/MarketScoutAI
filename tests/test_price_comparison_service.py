import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import requests

from database import store
from models.price_comparison import PriceComparisonRequest, PriceOffer, ProductIdentity, RetailerResult
from tools.retailer_fetchers.base import RetailerFetchOutcome
from tools.retailer_fetchers.reliance_digital import RelianceDigitalFetcher
from services.price_comparison import _offer_matches_adapter_confirmation, _offer_matches_request, execute_price_comparison, start_price_comparison


class FakeFetcher:
    retailer = "Reliance Digital"

    def __init__(self, outcome=None, error=None):
        self.outcome = outcome
        self.error = error

    def fetch(self, target):
        if self.error:
            raise self.error
        return self.outcome


class PriceComparisonServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch("database.store.DB_PATH", os.path.join(self.tmp.name, "comparison.sqlite3"))
        self.db_patch.start()
        store.init_db()
        self.product = ProductIdentity("Samsung", "Galaxy A55", ram="8GB", storage="128GB")
        self.request = PriceComparisonRequest([self.product], ["Reliance Digital"])

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def _start(self):
        return start_price_comparison(self.request)["comparison_id"]

    def test_success_persists_checked_offer_and_decimal(self):
        offer = PriceOffer("Reliance Digital", self.product, Decimal("34999.50"), "https://reliancedigital.in/a55")
        adapter = FakeFetcher(RetailerFetchOutcome(RetailerResult("Reliance Digital", "checked"), [offer]))
        comparison_id = self._start()
        result = execute_price_comparison(comparison_id, {"Reliance Digital": adapter})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["retailer_checks"][0]["status"], "checked")
        self.assertEqual(result["offers"][0]["price"], Decimal("34999.50"))

    def test_structured_diagnostics_persist_with_product_and_retailer_check(self):
        diagnostics = {"strategies": [{"source": "sitemap", "descriptor": "public sitemap", "success": True,
                                       "candidate_count": 1, "error": None}],
                      "candidates": [{"url": "https://reliancedigital.in/product/a55", "discovered_by": ["sitemap"],
                                      "fetched": True, "extracted_identity": self.product.to_dict(), "match": "matched",
                                      "rejection_reason": None}],
                      "exact_product_found": True, "final_outcome": "exact_product_found"}
        adapter = FakeFetcher(RetailerFetchOutcome(RetailerResult("Reliance Digital", "checked", diagnostics=diagnostics)))
        comparison_id = self._start()
        execute_price_comparison(comparison_id, {"Reliance Digital": adapter})
        stored = store.get_price_comparison(comparison_id)["retailer_checks"][0]["diagnostics"]
        self.assertEqual(stored["products"][0]["product"], self.product.to_dict())
        self.assertEqual(stored["products"][0]["discovery"], diagnostics)

    def test_checked_without_offer_completes_cleanly(self):
        comparison_id = self._start()
        result = execute_price_comparison(
            comparison_id,
            {"Reliance Digital": FakeFetcher(RetailerFetchOutcome(RetailerResult("Reliance Digital", "checked")))},
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["offers"], [])

    def test_blocked_unavailable_and_failed_states_are_preserved(self):
        for status in ("blocked", "unavailable", "failed"):
            with self.subTest(status=status):
                comparison_id = self._start()
                outcome = RetailerFetchOutcome(RetailerResult("Reliance Digital", status, message=f"{status} by fixture"))
                result = execute_price_comparison(comparison_id, {"Reliance Digital": FakeFetcher(outcome)})
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["retailer_checks"][0]["status"], status)
                self.assertEqual(result["offers"], [])

    def test_fetch_exception_becomes_failed_retailer_check(self):
        comparison_id = self._start()
        result = execute_price_comparison(comparison_id, {"Reliance Digital": FakeFetcher(error=RuntimeError("fixture error"))})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["retailer_checks"][0]["status"], "failed")
        self.assertEqual(result["offers"], [])

    def test_unimplemented_retailer_is_unavailable_without_offer(self):
        request = PriceComparisonRequest([self.product], ["Amazon India"])
        comparison_id = start_price_comparison(request)["comparison_id"]
        result = execute_price_comparison(comparison_id, {})
        self.assertEqual(result["retailer_checks"][0]["status"], "unavailable")
        self.assertEqual(result["offers"], [])

    def test_snake_case_retailer_key_matches_reliance_adapter(self):
        offer = PriceOffer("Reliance Digital", self.product, 24999, "https://reliancedigital.in/a55")
        adapter = FakeFetcher(RetailerFetchOutcome(RetailerResult("Reliance Digital", "checked"), [offer]))
        request = PriceComparisonRequest([self.product], ["reliance_digital"])
        comparison_id = start_price_comparison(request)["comparison_id"]
        result = execute_price_comparison(comparison_id, {"Reliance Digital": adapter})
        self.assertEqual(result["retailer_checks"][0]["retailer"], "Reliance Digital")
        self.assertEqual(result["retailer_checks"][0]["status"], "checked")
        self.assertEqual(len(result["offers"]), 1)

    def test_service_matches_capacity_spacing_but_rejects_different_values(self):
        api_product = ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="128GB")
        extracted_product = ProductIdentity("OnePlus", "Nord 4", ram="8 GB", storage="128 GB")
        exact_offer = PriceOffer("Reliance Digital", extracted_product, 29999, "https://reliancedigital.in/nord4")
        exact_run = start_price_comparison(PriceComparisonRequest([api_product], ["Reliance Digital"]))["comparison_id"]
        exact_result = execute_price_comparison(
            exact_run,
            {"Reliance Digital": FakeFetcher(RetailerFetchOutcome(RetailerResult("Reliance Digital", "checked"), [exact_offer]))},
        )
        self.assertEqual(len(exact_result["offers"]), 1)
        self.assertEqual(exact_result["input_data"]["products"][0]["ram"], "8GB")
        self.assertEqual(exact_result["input_data"]["products"][0]["storage"], "128GB")

        different_product = ProductIdentity("OnePlus", "Nord 4", ram="12 GB", storage="128 GB")
        different_offer = PriceOffer("Reliance Digital", different_product, 29999, "https://reliancedigital.in/nord4")
        mismatch_run = start_price_comparison(PriceComparisonRequest([api_product], ["Reliance Digital"]))["comparison_id"]
        mismatch_result = execute_price_comparison(
            mismatch_run,
            {"Reliance Digital": FakeFetcher(RetailerFetchOutcome(RetailerResult("Reliance Digital", "checked"), [different_offer]))},
        )
        self.assertEqual(mismatch_result["offers"], [])

    def test_service_accepts_whitespace_normalized_brand_without_relaxing_variant(self):
        requested = ProductIdentity("OnePlus", "Nord 6", ram="8GB", storage="256GB")
        observed = ProductIdentity("One Plus", "Nord 6", ram="8 GB", storage="256 GB")
        offer = PriceOffer("Reliance Digital", observed, Decimal("34999"), "https://reliancedigital.in/nord6")
        comparison_id = start_price_comparison(PriceComparisonRequest([requested], ["Reliance Digital"]))["comparison_id"]
        result = execute_price_comparison(
            comparison_id,
            {"Reliance Digital": FakeFetcher(RetailerFetchOutcome(RetailerResult("Reliance Digital", "checked"), [offer]))},
        )
        self.assertEqual(len(result["offers"]), 1)

        wrong_capacity = ProductIdentity("One Plus", "Nord 6", ram="12GB", storage="256GB")
        rejected = PriceOffer("Reliance Digital", wrong_capacity, Decimal("34999"), "https://reliancedigital.in/nord6")
        other_id = start_price_comparison(PriceComparisonRequest([requested], ["Reliance Digital"]))["comparison_id"]
        rejected_result = execute_price_comparison(
            other_id,
            {"Reliance Digital": FakeFetcher(RetailerFetchOutcome(RetailerResult("Reliance Digital", "checked"), [rejected]))},
        )
        self.assertEqual(rejected_result["offers"], [])

    def test_nord6_live_title_model_is_preserved_and_offer_reaches_persistence(self):
        fixture_path = Path(__file__).parent / "fixtures" / "reliance_digital_nord6_one_plus_brand.html"
        html = fixture_path.read_text(encoding="utf-8")
        url = "https://www.reliancedigital.in/product/oneplus-nord-6-5g-256-gb-8-gb-ram-fresh-mint-mobile-phone-moiium-10047667"

        class FixtureResponse:
            status_code = 200
            encoding = "utf-8"
            apparent_encoding = "utf-8"

            def __init__(self, response_url, text):
                self.url = response_url
                self.text = text

            def raise_for_status(self):
                return None

        def sitemap_failure(*args, **kwargs):
            raise requests.ConnectionError("fixture: use deterministic search candidate")

        adapter = RelianceDigitalFetcher(
            searcher=lambda query, max_results=5: [{"url": url}],
            http_get=lambda requested_url, headers, timeout: FixtureResponse(requested_url, html),
            sitemap_get=sitemap_failure,
        )
        requested = ProductIdentity("OnePlus", "Nord 6", ram="8GB", storage="256GB", variant="Fresh Mint")
        adapter_outcome = adapter.fetch(requested)
        self.assertEqual(len(adapter_outcome.offers), 1)
        offer = adapter_outcome.offers[0]
        self.assertEqual(offer.product.model, "Nord 6 5G")
        self.assertEqual(offer.price, Decimal("46999.00"))
        self.assertFalse(_offer_matches_request(offer.product, requested))
        self.assertTrue(_offer_matches_adapter_confirmation(offer.product, adapter_outcome.check.diagnostics))

        comparison_id = start_price_comparison(PriceComparisonRequest([requested], ["Reliance Digital"]))["comparison_id"]
        result = execute_price_comparison(comparison_id, {"Reliance Digital": FakeFetcher(adapter_outcome)})
        self.assertEqual(result["retailer_checks"][0]["status"], "checked")
        self.assertEqual(len(result["offers"]), 1)
        self.assertEqual(result["offers"][0]["price"], Decimal("46999.00"))
        self.assertEqual(result["offers"][0]["product"]["model"], "Nord 6 5G")


if __name__ == "__main__":
    unittest.main()
