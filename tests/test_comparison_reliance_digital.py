import os
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

from database import store
from models.comparison import (
    AttributeDefinition,
    ComparisonRequest,
    EntityReference,
    SourceReference,
    SourceStatus,
)
from models.price_comparison import PriceOffer, ProductIdentity, RetailerResult, RetailerStatus
from tools.comparison_sources import RelianceDigitalComparisonAdapter
from tools.retailer_fetchers.base import RetailerFetchOutcome


class FakeRelianceFetcher:
    def __init__(self, outcomes=None):
        self.outcomes = outcomes or {}
        self.targets = []

    def fetch(self, target):
        self.targets.append(target)
        return self.outcomes[target.model]


class RelianceDigitalComparisonAdapterTests(unittest.TestCase):
    def setUp(self):
        self.product = ProductIdentity(
            brand="OnePlus", model="Nord 6", ram="8GB", storage="256GB", variant="Fresh Mint",
        )
        self.source = SourceReference("reliance_digital", "Reliance Digital", "retailer")
        self.entity = EntityReference(
            "nord6", "OnePlus Nord 6", "smartphone",
            {"brand": "OnePlus", "model": "Nord 6", "ram": "8GB", "storage": "256GB", "variant": "Fresh Mint"},
        )

    def _offer(self, product=None, model="Nord 6"):
        product = product or self.product
        return PriceOffer(
            retailer="Reliance Digital", product=product, price=Decimal("46999.00"),
            currency="INR", seller="Reliance Digital", discount="5% off",
            observed_at="2026-10-01T10:00:00Z",
            source_url=f"https://www.reliancedigital.in/product/{model.casefold().replace(' ', '-')}",
        )

    def _fetch_outcome(self, status="checked", offer=True, diagnostics=None, model="Nord 6"):
        product = self.product if model == "Nord 6" else ProductIdentity(brand="OnePlus", model=model, storage="256GB")
        check = RetailerResult(
            "Reliance Digital", status, message="checked page" if status == "checked" else f"{status} page",
            source_url="https://www.reliancedigital.in/product/example",
            diagnostics=diagnostics or {"strategies": [{"source": "sitemap", "candidate_count": 1}],
                                        "final_outcome": "exact_product_found"},
        )
        offers = [self._offer(product, model)] if offer and status == "checked" else []
        return RetailerFetchOutcome(check, offers)

    def _request(self, entities=None, attributes=None):
        return ComparisonRequest(
            "Compare products by price and storage.",
            entities=entities or [self.entity],
            attributes=attributes or [AttributeDefinition("price", "Price", "scalar", currency="INR")],
        )

    def test_source_metadata_is_stable_and_generic(self):
        adapter = RelianceDigitalComparisonAdapter(FakeRelianceFetcher())
        self.assertEqual(adapter.source.key, "reliance_digital")
        self.assertEqual(adapter.source.name, "Reliance Digital")
        self.assertEqual(adapter.source.source_type, "retailer")
        self.assertEqual(adapter.source.url, "https://www.reliancedigital.in/")

    def test_entity_identifiers_convert_to_canonical_product_identity(self):
        fetcher = FakeRelianceFetcher({"Nord 6": self._fetch_outcome()})
        adapter = RelianceDigitalComparisonAdapter(fetcher)
        self.assertTrue(adapter.supports(self._request(), self.source))
        adapter.check(self._request(), self.source)
        self.assertEqual(fetcher.targets, [self.product])

    def test_missing_identity_is_explicitly_unsupported_without_display_name_guessing(self):
        entity = EntityReference("unknown", "OnePlus Nord 6", "smartphone", {})
        request = self._request(entities=[entity])
        adapter = RelianceDigitalComparisonAdapter(FakeRelianceFetcher())
        self.assertFalse(adapter.supports(request, self.source))
        result = adapter.check(request, self.source)
        self.assertEqual(result.check.status, SourceStatus.UNSUPPORTED)
        self.assertEqual(result.observations, [])
        self.assertEqual(result.check.diagnostics["entities"][0]["entity_key"], "unknown")
        self.assertIn("brand", result.check.diagnostics["entities"][0]["identity_error"])

    def test_exact_fetcher_offer_becomes_generic_price_observation(self):
        adapter = RelianceDigitalComparisonAdapter(FakeRelianceFetcher({"Nord 6": self._fetch_outcome()}))
        result = adapter.check(self._request(), self.source)
        self.assertEqual(result.check.status, SourceStatus.CHECKED)
        self.assertEqual(len(result.observations), 1)
        observation = result.observations[0]
        self.assertEqual(observation.entity_key, "nord6")
        self.assertEqual(observation.attribute_key, "price")
        self.assertEqual(observation.source_key, "reliance_digital")
        self.assertEqual(observation.raw_value, "46999.00")
        self.assertEqual(observation.normalized_value, 46999)
        self.assertIsInstance(observation.normalized_value, int)
        self.assertEqual(observation.currency, "INR")
        self.assertEqual(observation.observed_at, "2026-10-01T10:00:00+00:00")
        self.assertEqual(observation.source_url, "https://www.reliancedigital.in/product/nord-6")
        self.assertEqual(observation.context["seller"], "Reliance Digital")
        self.assertEqual(observation.context["discount"], "5% off")

    def test_storage_observation_only_when_requested_and_available(self):
        attrs = [
            AttributeDefinition("price", "Price", "scalar", currency="INR"),
            AttributeDefinition("storage", "Storage", "scalar", unit="GB"),
        ]
        adapter = RelianceDigitalComparisonAdapter(FakeRelianceFetcher({"Nord 6": self._fetch_outcome()}))
        result = adapter.check(self._request(attributes=attrs), self.source)
        storage = next(item for item in result.observations if item.attribute_key == "storage")
        self.assertEqual(storage.raw_value, "256GB")
        self.assertEqual(storage.normalized_value, 256)
        self.assertEqual(storage.unit, "GB")

        only_price = adapter.check(self._request(), self.source)
        self.assertEqual([item.attribute_key for item in only_price.observations], ["price"])

    def test_storage_with_unmatched_unit_is_not_emitted(self):
        attrs = [AttributeDefinition("storage", "Storage", "scalar", unit="TB")]
        adapter = RelianceDigitalComparisonAdapter(FakeRelianceFetcher({"Nord 6": self._fetch_outcome()}))
        result = adapter.check(self._request(attributes=attrs), self.source)
        self.assertEqual(result.observations, [])

    def test_retailer_statuses_map_to_generic_statuses(self):
        for retailer_status, generic_status in (
            (RetailerStatus.UNAVAILABLE, SourceStatus.UNAVAILABLE),
            (RetailerStatus.BLOCKED, SourceStatus.BLOCKED),
            (RetailerStatus.FAILED, SourceStatus.FAILED),
        ):
            adapter = RelianceDigitalComparisonAdapter(FakeRelianceFetcher({
                "Nord 6": self._fetch_outcome(retailer_status.value, offer=False),
            }))
            result = adapter.check(self._request(), self.source)
            self.assertEqual(result.check.status, generic_status)
            self.assertEqual(result.observations, [])

    def test_checked_ambiguous_or_no_offer_result_creates_no_observation(self):
        diagnostics = {"final_outcome": "ambiguous_product_variants", "exact_product_found": True}
        adapter = RelianceDigitalComparisonAdapter(FakeRelianceFetcher({
            "Nord 6": self._fetch_outcome("checked", offer=False, diagnostics=diagnostics),
        }))
        result = adapter.check(self._request(), self.source)
        self.assertEqual(result.check.status, SourceStatus.CHECKED)
        self.assertEqual(result.observations, [])
        self.assertEqual(result.check.diagnostics["entities"][0]["diagnostics"]["final_outcome"], "ambiguous_product_variants")

    def test_each_entity_keeps_its_own_key_and_matched_offer(self):
        second_product = ProductIdentity(brand="OnePlus", model="Nord CE6", storage="256GB")
        first_entity = self.entity
        second_entity = EntityReference("nord_ce6", "OnePlus Nord CE6", identifiers={
            "brand": "OnePlus", "model": "Nord CE6", "storage": "256GB",
        })
        fetcher = FakeRelianceFetcher({
            "Nord 6": self._fetch_outcome(),
            "Nord CE6": self._fetch_outcome(model="Nord CE6"),
        })
        adapter = RelianceDigitalComparisonAdapter(fetcher)
        result = adapter.check(self._request(entities=[first_entity, second_entity]), self.source)
        self.assertEqual(result.check.status, SourceStatus.CHECKED)
        self.assertEqual([item.entity_key for item in result.observations], ["nord6", "nord_ce6"])

    def test_mixed_checked_and_nonchecked_entities_produce_partial_with_success_observations(self):
        for other_status in ("unavailable", "blocked", "failed"):
            with self.subTest(other_status=other_status):
                fetcher = FakeRelianceFetcher({
                    "Nord 6": self._fetch_outcome(),
                    "Nord CE6": self._fetch_outcome(other_status, offer=False, model="Nord CE6"),
                })
                second = EntityReference("nord_ce6", "OnePlus Nord CE6", identifiers={
                    "brand": "OnePlus", "model": "Nord CE6",
                })
                result = RelianceDigitalComparisonAdapter(fetcher).check(
                    self._request(entities=[self.entity, second]), self.source,
                )
                self.assertEqual(result.check.status, SourceStatus.PARTIAL)
                self.assertEqual([item["status"] for item in result.check.diagnostics["entities"]],
                                 ["checked", other_status])
                self.assertEqual([item.entity_key for item in result.observations], ["nord6"])

    def test_mixed_checked_and_unsupported_entity_produces_partial(self):
        unsupported = EntityReference("unknown", "Some unparseable entity", identifiers={})
        result = RelianceDigitalComparisonAdapter(FakeRelianceFetcher({
            "Nord 6": self._fetch_outcome(),
        })).check(self._request(entities=[self.entity, unsupported]), self.source)
        self.assertEqual(result.check.status, SourceStatus.PARTIAL)
        self.assertEqual([item["status"] for item in result.check.diagnostics["entities"]], ["checked", "unsupported"])
        self.assertEqual([item.entity_key for item in result.observations], ["nord6"])

    def test_all_nonchecked_entities_never_aggregate_to_partial(self):
        for statuses, expected in (
            (("unavailable", "unavailable"), SourceStatus.UNAVAILABLE),
            (("blocked", "blocked"), SourceStatus.BLOCKED),
            (("failed", "failed"), SourceStatus.FAILED),
            (("unsupported", "unsupported"), SourceStatus.UNSUPPORTED),
        ):
            with self.subTest(statuses=statuses):
                entities = [
                    EntityReference(f"entity-{index}", f"Entity {index}", identifiers={
                        "brand": "Brand", "model": f"Model {index}",
                    }) for index in range(2)
                ]
                outcomes = {}
                for index, status in enumerate(statuses):
                    model = f"Model {index}"
                    if status == "unsupported":
                        entities[index] = EntityReference(f"entity-{index}", f"Entity {index}", identifiers={})
                    else:
                        outcomes[model] = self._fetch_outcome(status, offer=False, model=model)
                result = RelianceDigitalComparisonAdapter(FakeRelianceFetcher(outcomes)).check(
                    self._request(entities=entities), self.source,
                )
                self.assertEqual(result.check.status, expected)
                self.assertNotEqual(result.check.status, SourceStatus.PARTIAL)
                self.assertEqual(result.observations, [])

    def test_registered_generic_api_uses_adapter_and_persists_observation(self):
        temp_dir = tempfile.TemporaryDirectory()
        db_patch = patch("database.store.DB_PATH", os.path.join(temp_dir.name, "api.sqlite3"))
        db_patch.start()
        try:
            store.init_db()
            from fastapi.testclient import TestClient
            from backend.main import app

            fetcher = FakeRelianceFetcher({"Nord 6": self._fetch_outcome()})
            adapter = RelianceDigitalComparisonAdapter(fetcher)
            payload = {
                "user_request": "Compare OnePlus Nord 6 by price.",
                "entities": [{"key": "nord6", "display_name": "OnePlus Nord 6", "identifiers": self.entity.identifiers}],
                "attributes": [{"key": "price", "label": "Price", "value_type": "scalar", "currency": "INR"}],
                "source_preferences": [{"key": "reliance_digital", "name": "Reliance Digital", "source_type": "retailer"}],
            }
            client = TestClient(app)
            with patch("backend.main.RelianceDigitalComparisonAdapter", return_value=adapter):
                response = client.post("/comparisons", json=payload)
            self.assertEqual(response.status_code, 202, response.text)
            detail = client.get(f"/comparisons/{response.json()['comparison_id']}").json()
            self.assertEqual(detail["source_checks"][0]["status"], "checked")
            self.assertEqual(detail["observations"][0]["attribute_key"], "price")
            self.assertEqual(detail["observations"][0]["entity_key"], "nord6")
        finally:
            db_patch.stop()
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
