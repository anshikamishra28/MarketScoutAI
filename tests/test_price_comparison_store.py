import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

from database import store
from models.price_comparison import PriceComparisonRequest, PriceOffer, ProductIdentity, RetailerResult


class PriceComparisonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path_patch = patch("database.store.DB_PATH", os.path.join(self.temp_dir.name, "comparison.sqlite3"))
        self.db_path_patch.start()
        store.init_db()
        self.comparison_id = "comparison-test-1"
        self.product = ProductIdentity(
            brand="Example", model="Phone X", model_number="EX-X1", ram="8 GB", storage="256 GB", variant="India",
        )
        self.request = PriceComparisonRequest(products=[self.product], retailers=["Amazon India", "Flipkart"])
        store.create_price_comparison(self.comparison_id, self.request)

    def tearDown(self):
        self.db_path_patch.stop()
        self.temp_dir.cleanup()

    def test_create_and_retrieve_comparison_request_and_lifecycle_fields(self):
        comparison = store.get_price_comparison(self.comparison_id)
        self.assertEqual(comparison["comparison_id"], self.comparison_id)
        self.assertEqual(comparison["status"], "queued")
        self.assertEqual(comparison["input_data"]["retailers"], ["Amazon India", "Flipkart"])
        self.assertEqual(comparison["input_data"]["products"][0]["model_number"], "EX-X1")
        self.assertTrue(comparison["created_at"])
        self.assertTrue(comparison["updated_at"])
        self.assertIsNone(comparison["completed_at"])
        self.assertIsNone(comparison["error"])

        store.update_price_comparison(self.comparison_id, status="completed", error=None)
        completed = store.get_price_comparison(self.comparison_id)
        self.assertEqual(completed["status"], "completed")
        self.assertIsNotNone(completed["completed_at"])

    def test_retailer_status_is_persisted_independently(self):
        store.upsert_price_retailer_check(self.comparison_id, RetailerResult("Amazon India", "blocked", message="Access denied"))
        store.upsert_price_retailer_check(self.comparison_id, RetailerResult("Flipkart", "checked"))
        checks = store.get_price_retailer_checks(self.comparison_id)
        self.assertEqual([(item["retailer"], item["status"]) for item in checks], [("Amazon India", "blocked"), ("Flipkart", "checked")])
        self.assertEqual(checks[0]["message"], "Access denied")
        self.assertTrue(checks[0]["checked_at"])

    def test_price_offer_persists_all_observation_fields(self):
        store.upsert_price_retailer_check(self.comparison_id, RetailerResult("Amazon India", "checked"))
        offer = PriceOffer(
            retailer="Amazon India", product=self.product, price=Decimal("28999.50"), currency="INR",
            seller="Example Seller", discount="10% off shown on page", observed_at="2026-09-30T10:00:00Z",
            source_url="https://amazon.in/example-product",
        )
        store.add_price_observation(self.comparison_id, offer)
        rows = store.get_price_observations(self.comparison_id)
        self.assertEqual(len(rows), 1)
        saved = rows[0]
        self.assertEqual(saved["product"], self.product.to_dict())
        self.assertEqual(saved["retailer"], "Amazon India")
        self.assertEqual(saved["price"], Decimal("28999.50"))
        self.assertEqual(saved["currency"], "INR")
        self.assertEqual(saved["seller"], "Example Seller")
        self.assertEqual(saved["discount"], "10% off shown on page")
        self.assertEqual(saved["observed_at"], "2026-09-30T10:00:00+00:00")
        self.assertEqual(saved["source_url"], "https://amazon.in/example-product")

    def test_decimal_round_trip_does_not_use_float_storage(self):
        store.upsert_price_retailer_check(self.comparison_id, RetailerResult("Croma", "checked"))
        precise_price = Decimal("12345.670089")
        store.add_price_observation(self.comparison_id, PriceOffer("Croma", self.product, precise_price, "https://croma.com/item"))
        self.assertEqual(store.get_price_observations(self.comparison_id)[0]["price"], precise_price)

    def test_multiple_retailers_can_store_offers_for_one_comparison(self):
        for retailer, price, url in (
            ("Amazon India", "28999", "https://amazon.in/item"),
            ("Flipkart", "27999", "https://flipkart.com/item"),
        ):
            store.upsert_price_retailer_check(self.comparison_id, RetailerResult(retailer, "checked"))
            store.add_price_observation(self.comparison_id, PriceOffer(retailer, self.product, price, url))
        result = store.get_price_comparison(self.comparison_id)
        self.assertEqual({offer["retailer"] for offer in result["offers"]}, {"Amazon India", "Flipkart"})
        self.assertEqual(len(result["retailer_checks"]), 2)

    def test_unavailable_retailer_is_recorded_without_a_price(self):
        store.upsert_price_retailer_check(self.comparison_id, RetailerResult("Reliance Digital", "unavailable", message="No accessible listing"))
        result = store.get_price_comparison(self.comparison_id)
        self.assertEqual(result["retailer_checks"][0]["status"], "unavailable")
        self.assertEqual(result["offers"], [])
        with self.assertRaisesRegex(ValueError, "checked retailer result is required"):
            store.add_price_observation(self.comparison_id, PriceOffer("Reliance Digital", self.product, 100, "https://reliancedigital.in/item"))

    def test_comparison_tables_are_separate_from_research_tables(self):
        with store.connect() as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"research_runs", "sources", "evidence", "reports"}.issubset(tables))
        self.assertTrue({"price_comparisons", "price_retailer_checks", "price_observations"}.issubset(tables))
        self.assertIsNone(store.get_run(self.comparison_id))


if __name__ == "__main__":
    unittest.main()
