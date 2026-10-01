import json
import unittest
from decimal import Decimal

from models.price_comparison import (
    ComparisonStatus,
    PriceComparisonRequest,
    PriceComparisonResult,
    PriceOffer,
    ProductIdentity,
    RetailerResult,
    RetailerStatus,
)


class PriceComparisonModelTests(unittest.TestCase):
    def setUp(self):
        self.product = ProductIdentity(
            brand="  Example ", model="Model X", model_number="EX-123",
            ram="8 GB", storage="256 GB", variant="India, Graphite",
        )

    def test_product_requires_brand_and_model_identity(self):
        with self.assertRaisesRegex(ValueError, "brand is required"):
            ProductIdentity(brand="", model="Model X")
        with self.assertRaisesRegex(ValueError, "model or model_number"):
            ProductIdentity(brand="Example")

    def test_request_coerces_product_mappings_and_strips_empty_retailers(self):
        request = PriceComparisonRequest(
            products=[{"brand": "Example", "model": "Model X", "storage": "256 GB"}],
            retailers=[" Amazon India ", "", "Flipkart"],
        )
        self.assertIsInstance(request.products[0], ProductIdentity)
        self.assertEqual(request.retailers, ["Amazon India", "Flipkart"])
        self.assertEqual(request.to_dict()["products"][0]["storage"], "256 GB")

    def test_request_requires_products_and_retailers(self):
        with self.assertRaisesRegex(ValueError, "at least one valid product"):
            PriceComparisonRequest(products=[], retailers=["Amazon India"])
        with self.assertRaisesRegex(ValueError, "at least one retailer"):
            PriceComparisonRequest(products=[self.product], retailers=[" "])

    def test_retailer_status_is_limited_to_declared_states(self):
        for status in ("checked", "unavailable", "blocked", "failed"):
            with self.subTest(status=status):
                result = RetailerResult("Amazon India", status, checked_at="2026-09-30T10:00:00+05:30")
                self.assertEqual(result.status.value, status)
                self.assertEqual(result.to_dict()["status"], status)
        with self.assertRaisesRegex(ValueError, "status must be"):
            RetailerResult("Amazon India", "priced")

    def test_offer_validates_price_currency_timestamp_and_source_url(self):
        offer = PriceOffer(
            retailer="Example Store", product=self.product, price=Decimal("28999.50"),
            currency="inr", seller="Store seller", discount="10% off as displayed",
            observed_at="2026-09-30T10:00:00+05:30", source_url="https://shop.example/product",
        )
        self.assertEqual(offer.price, Decimal("28999.50"))
        self.assertEqual(offer.currency, "INR")
        self.assertEqual(offer.to_dict()["price"], "28999.50")
        self.assertEqual(offer.to_dict()["product"]["model_number"], "EX-123")
        self.assertEqual(offer.to_dict()["discount"], "10% off as displayed")
        for bad_price in (0, -1, "NaN", "not a price"):
            with self.subTest(price=bad_price), self.assertRaises(ValueError):
                PriceOffer("Example Store", self.product, bad_price, "https://shop.example/p")
        with self.assertRaisesRegex(ValueError, "currency"):
            PriceOffer("Example Store", self.product, 100, "https://shop.example/p", currency="rupees")
        with self.assertRaisesRegex(ValueError, "ISO 8601"):
            PriceOffer("Example Store", self.product, 100, "https://shop.example/p", observed_at="yesterday")
        with self.assertRaisesRegex(ValueError, r"HTTP\(S\)"):
            PriceOffer("Example Store", self.product, 100, "javascript:alert(1)")

    def test_comparison_result_serializes_nested_models_and_unavailable_retailer(self):
        result = PriceComparisonResult(
            comparison_id="cmp-1", status=ComparisonStatus.COMPLETED,
            products=[self.product],
            retailers=[RetailerResult("Amazon India", RetailerStatus.BLOCKED, message="Page access was blocked")],
            offers=[PriceOffer("Flipkart", self.product, "27999", "https://shop.example/item", seller="Example seller")],
            created_at="2026-09-30T10:00:00Z", updated_at="2026-09-30T10:01:00Z",
        )
        data = result.to_dict()
        encoded = json.dumps(data)
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["retailers"][0]["status"], "blocked")
        self.assertEqual(data["offers"][0]["price"], "27999")
        self.assertIn('"source_url": "https://shop.example/item"', encoded)
        self.assertEqual(RetailerStatus.UNAVAILABLE.value, "unavailable")

    def test_timestamp_requires_timezone(self):
        with self.assertRaisesRegex(ValueError, "include a timezone"):
            RetailerResult("Croma", "unavailable", checked_at="2026-09-30T10:00:00")


if __name__ == "__main__":
    unittest.main()
