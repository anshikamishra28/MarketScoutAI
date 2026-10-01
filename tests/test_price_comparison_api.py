import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

from database import store
from models.price_comparison import PriceOffer, ProductIdentity, RetailerResult


class PriceComparisonApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_patch = patch("database.store.DB_PATH", os.path.join(self.tmp.name, "api.sqlite3"))
        self.db_patch.start()
        store.init_db()
        from fastapi.testclient import TestClient
        from backend.main import app
        self.client = TestClient(app)
        self.payload = {
            "products": [{"brand": "Samsung", "model": "Galaxy A55", "ram": "8GB", "storage": "128GB"}],
            "retailers": ["Reliance Digital"],
        }

    def tearDown(self):
        self.db_patch.stop()
        self.tmp.cleanup()

    def test_start_returns_id_and_queued_status(self):
        with patch("backend.main._run_price_comparison"):
            response = self.client.post("/price-comparisons", json=self.payload)
        self.assertEqual(response.status_code, 202)
        body = response.json()
        self.assertEqual(body["status"], "queued")
        self.assertTrue(body["comparison_id"])
        self.assertEqual(body["status_url"], f"/price-comparisons/{body['comparison_id']}/status")

    def test_start_accepts_ram_gb_storage_gb_request_contract(self):
        payload = {
            "products": [{"brand": "OnePlus", "model": "Nord 4", "ram_gb": 8, "storage_gb": 128}],
            "retailers": ["reliance_digital"],
        }
        with patch("backend.main._run_price_comparison"):
            response = self.client.post("/price-comparisons", json=payload)
        self.assertEqual(response.status_code, 202, response.text)
        comparison_id = response.json()["comparison_id"]
        record = store.get_price_comparison(comparison_id)
        self.assertEqual(record["input_data"]["products"][0], {
            "brand": "OnePlus", "model": "Nord 4", "model_number": "",
            "ram": "8GB", "storage": "128GB", "variant": "",
        })

    def test_detail_status_decimal_serialization_and_unknown_id(self):
        with patch("backend.main._run_price_comparison"):
            started = self.client.post("/price-comparisons", json=self.payload).json()
        comparison_id = started["comparison_id"]
        diagnostics = {"products": [{"product": {"brand": "Samsung", "model": "Galaxy A55"},
                                     "discovery": {"strategies": [], "candidates": [], "exact_product_found": False,
                                                   "final_outcome": "not_found_through_available_public_discovery"}}]}
        store.upsert_price_retailer_check(comparison_id, RetailerResult("Reliance Digital", "checked", diagnostics=diagnostics))
        product = ProductIdentity(**self.payload["products"][0])
        store.add_price_observation(comparison_id, PriceOffer("Reliance Digital", product, Decimal("24999.95"), "https://reliancedigital.in/item"))
        detail = self.client.get(f"/price-comparisons/{comparison_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["offers"][0]["price"], "24999.95")
        self.assertEqual(detail.json()["offers"][0]["source_url"], "https://reliancedigital.in/item")
        self.assertEqual(detail.json()["retailer_checks"][0]["status"], "checked")
        self.assertEqual(detail.json()["retailer_checks"][0]["diagnostics"], diagnostics)
        self.assertNotIn("price", str(detail.json()["retailer_checks"][0]["diagnostics"]).lower())
        status = self.client.get(f"/price-comparisons/{comparison_id}/status")
        self.assertEqual(status.status_code, 200)
        self.assertEqual(status.json()["status"], "queued")
        self.assertNotIn("diagnostics", status.json()["retailer_checks"][0])
        self.assertEqual(self.client.get("/price-comparisons/not-found").status_code, 404)
        self.assertEqual(self.client.get("/price-comparisons/not-found/status").status_code, 404)

    def test_invalid_request_returns_422_and_research_routes_unchanged(self):
        self.assertEqual(self.client.post("/price-comparisons", json={"products": [], "retailers": []}).status_code, 422)
        self.assertEqual(self.client.get("/health").json()["status"], "healthy")
        self.assertEqual(self.client.get("/research/missing").status_code, 404)
        with patch("backend.main._run_research"):
            research = self.client.post("/research", json={"question": "Analyze India's smartphone market"})
        self.assertEqual(research.status_code, 202)
        research_id = research.json()["id"]
        self.assertEqual(self.client.get(f"/research/{research_id}/status").status_code, 200)
        self.assertEqual(self.client.get(f"/research/{research_id}/sources").status_code, 200)
        self.assertEqual(self.client.get(f"/research/{research_id}/report").status_code, 404)


if __name__ == "__main__":
    unittest.main()
