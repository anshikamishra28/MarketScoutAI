import os
import sqlite3
import tempfile
import unittest
from decimal import Decimal
from unittest.mock import patch

from database import store
from models.comparison import (
    AttributeDefinition,
    ComparisonRequest,
    EntityReference,
    Observation,
    SourceCheck,
    SourceReference,
)
from models.price_comparison import PriceComparisonRequest, PriceOffer, ProductIdentity, RetailerResult


class GenericComparisonStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch("database.store.DB_PATH", os.path.join(self.temp_dir.name, "store.sqlite3"))
        self.db_patch.start()
        store.init_db()
        self.request = ComparisonRequest(
            user_request="Compare streaming services and their monthly costs.",
            entities=[
                EntityReference("netflix", "Netflix", "streaming_service", {"region": "IN"}, ["Netflix India"]),
                EntityReference("prime", "Amazon Prime Video", "streaming_service"),
            ],
            attributes=[
                AttributeDefinition("monthly_price", "Monthly price", "scalar", "month", "INR"),
                AttributeDefinition("content_library", "Content library", "structured"),
            ],
            context={"market": "India", "currency": "INR"},
        )
        self.comparison_id = "generic-1"
        store.create_comparison_run(self.comparison_id, self.request, created_at="2026-10-01T10:00:00Z")

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_create_read_generic_comparison_with_entities_and_attributes(self):
        result = store.get_comparison_result(self.comparison_id)
        self.assertEqual(result["request"]["user_request"], self.request.user_request)
        self.assertEqual([item["key"] for item in result["entities"]], ["netflix", "prime"])
        self.assertEqual(result["entities"][0]["identifiers"], {"region": "IN"})
        self.assertEqual(result["entities"][0]["aliases"], ["Netflix India"])
        self.assertEqual([item["key"] for item in result["attributes"]], ["monthly_price", "content_library"])
        self.assertEqual(result["attributes"][0]["currency"], "INR")
        self.assertEqual(result["created_at"], "2026-10-01T10:00:00+00:00")
        self.assertEqual(result["source_checks"], [])
        self.assertEqual(result["observations"], [])

    def test_all_generic_source_statuses_round_trip(self):
        statuses = ("pending", "checked", "unavailable", "blocked", "failed", "unsupported")
        for status in statuses:
            store.upsert_comparison_source_check(self.comparison_id, SourceCheck(
                SourceReference(f"source-{status}", f"Source {status}", "public", "https://example.com"),
                status=status, checked_at="2026-10-01T11:00:00Z",
                diagnostics={"attempt": 1}, error="unavailable detail" if status == "failed" else None,
            ))
        result = store.get_comparison_result(self.comparison_id)
        self.assertEqual({item["status"] for item in result["source_checks"]}, set(statuses))
        failed = next(item for item in result["source_checks"] if item["status"] == "failed")
        self.assertEqual(failed["error"], "unavailable detail")
        self.assertEqual(failed["diagnostics"], {"attempt": 1})
        self.assertEqual(failed["checked_at"], "2026-10-01T11:00:00+00:00")

    def test_observation_links_entity_attribute_and_source_and_preserves_values(self):
        store.upsert_comparison_source_check(self.comparison_id, SourceCheck(
            SourceReference("official", "Official pricing", "official", "https://example.com/pricing"),
            status="checked", checked_at="2026-10-01T11:30:00Z",
        ))
        observation = Observation(
            "netflix", "monthly_price", "official", "₹649/month", 649,
            value_type="scalar", unit="month", currency="INR",
            observed_at="2026-10-01T11:15:00Z", source_url="https://example.com/plan",
            context={"plan": "Standard", "screens": [2, 3]},
        )
        store.add_comparison_observation(self.comparison_id, observation)
        result = store.get_comparison_result(self.comparison_id)
        saved = result["observations"][0]
        self.assertEqual(saved["entity_key"], "netflix")
        self.assertEqual(saved["attribute_key"], "monthly_price")
        self.assertEqual(saved["source_key"], "official")
        self.assertEqual(saved["raw_value"], "₹649/month")
        self.assertEqual(saved["normalized_value"], 649)
        self.assertIsInstance(saved["normalized_value"], int)
        self.assertEqual(saved["unit"], "month")
        self.assertEqual(saved["currency"], "INR")
        self.assertEqual(saved["observed_at"], "2026-10-01T11:15:00+00:00")
        self.assertEqual(saved["source_url"], "https://example.com/plan")
        self.assertEqual(saved["context"], {"plan": "Standard", "screens": [2, 3]})

    def test_string_boolean_and_structured_normalized_values_round_trip(self):
        store.upsert_comparison_source_check(self.comparison_id, SourceCheck(SourceReference("src", "Source"), "checked"))
        cases = [
            ("content_library", "availability", "Available", "available", "categorical"),
            ("content_library", "free_tier", "Yes", True, "boolean"),
            ("content_library", "catalog", "Top genres: drama, comedy", {"genres": ["drama", "comedy"], "count": 2}, "structured"),
        ]
        # The request's content_library attribute is reused for heterogeneous observed values.
        for attribute_key, entity_key, raw, normalized, value_type in cases:
            # Link observations to an existing request-local entity and attribute.
            store.add_comparison_observation(self.comparison_id, Observation(
                "netflix", attribute_key, "src", raw, normalized, value_type=value_type,
            ))
        observations = store.get_comparison_result(self.comparison_id)["observations"]
        self.assertEqual([item["normalized_value"] for item in observations], ["available", True, {"genres": ["drama", "comedy"], "count": 2}])

    def test_decimal_normalized_value_uses_stage_one_json_safe_representation(self):
        store.upsert_comparison_source_check(self.comparison_id, SourceCheck(SourceReference("src", "Source"), "checked"))
        store.add_comparison_observation(self.comparison_id, Observation(
            "netflix", "monthly_price", "src", "649.2500 INR", Decimal("649.2500"),
            value_type="scalar", currency="INR",
        ))
        value = store.get_comparison_result(self.comparison_id)["observations"][0]["normalized_value"]
        self.assertEqual(value, "649.2500")
        self.assertIsInstance(value, str)

    def test_partial_and_empty_comparison_is_readable(self):
        empty_id = "empty"
        store.create_comparison_run(empty_id, ComparisonRequest("Compare options later."))
        result = store.get_comparison_result(empty_id)
        self.assertEqual(result["entities"], [])
        self.assertEqual(result["attributes"], [])
        self.assertEqual(result["source_checks"], [])
        self.assertEqual(result["observations"], [])
        self.assertIsNone(result["request"]["context"])
        self.assertIsNone(store.get_comparison_result("missing"))

    def test_comparisons_and_request_local_entity_keys_are_isolated(self):
        other_id = "generic-2"
        other = ComparisonRequest("Compare a different service.", entities=[EntityReference("netflix", "Another entity")])
        store.create_comparison_run(other_id, other)
        self.assertEqual(store.get_comparison_result(self.comparison_id)["entities"][0]["display_name"], "Netflix")
        self.assertEqual(store.get_comparison_result(other_id)["entities"][0]["display_name"], "Another entity")
        with self.assertRaises(sqlite3.IntegrityError):
            store.add_comparison_entities(self.comparison_id, [EntityReference("netflix", "Duplicate key")])

    def test_observation_requires_existing_references_in_same_comparison(self):
        with self.assertRaisesRegex(ValueError, "must exist in this comparison"):
            store.add_comparison_observation(self.comparison_id, Observation(
                "missing", "monthly_price", "missing-source", "x", 1,
            ))

    def test_update_persists_result_fields_and_error(self):
        store.update_comparison_run(self.comparison_id, status="completed", error="partial result",
                                    analysis="Summary", unresolved=["channel data"], errors=["source timeout"])
        result = store.get_comparison_result(self.comparison_id)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["analysis"], "Summary")
        self.assertEqual(result["unresolved"], ["channel data"])
        self.assertEqual(result["errors"], ["source timeout", "partial result"])

    def test_structured_analysis_round_trips_without_changing_legacy_text(self):
        analysis = {"schema_version": 1, "attributes": [{"key": "monthly_price", "status": "unresolved"}]}
        store.update_comparison_run(self.comparison_id, analysis=analysis)
        self.assertEqual(store.get_comparison_result(self.comparison_id)["analysis"], analysis)
        store.update_comparison_run(self.comparison_id, analysis='{"legacy":"text payload"}')
        self.assertEqual(store.get_comparison_result(self.comparison_id)["analysis"], '{"legacy":"text payload"}')
        store.update_comparison_run(self.comparison_id, analysis="Legacy summary")
        self.assertEqual(store.get_comparison_result(self.comparison_id)["analysis"], "Legacy summary")

    def test_same_entity_attribute_can_have_observations_from_distinct_sources_and_times(self):
        for key, name, price, time in (
            ("provider-a", "Provider A", 649, "2026-10-01T10:00:00Z"),
            ("provider-b", "Provider B", 699, "2026-10-02T10:00:00Z"),
        ):
            store.upsert_comparison_source_check(self.comparison_id, SourceCheck(
                SourceReference(key, name), status="checked", checked_at=time,
            ))
            store.add_comparison_observation(self.comparison_id, Observation(
                "netflix", "monthly_price", key, f"₹{price}/month", price,
                value_type="scalar", unit="month", currency="INR", observed_at=time,
            ))
        observations = store.get_comparison_result(self.comparison_id)["observations"]
        self.assertEqual([item["source_key"] for item in observations], ["provider-a", "provider-b"])
        self.assertEqual([item["normalized_value"] for item in observations], [649, 699])
        self.assertEqual([item["observed_at"] for item in observations], [
            "2026-10-01T10:00:00+00:00", "2026-10-02T10:00:00+00:00",
        ])

    def test_generic_initialization_preserves_real_legacy_comparison_path(self):
        legacy_id = "legacy-safety"
        product = ProductIdentity(brand="OnePlus", model="Nord 6", ram="8GB", storage="256GB", variant="Fresh Mint")
        request = PriceComparisonRequest(products=[product], retailers=["Reliance Digital"])
        store.create_price_comparison(legacy_id, request)
        store.upsert_price_retailer_check(legacy_id, RetailerResult("Reliance Digital", "checked"))
        store.add_price_observation(legacy_id, PriceOffer(
            "Reliance Digital", product, "46999.00", "https://reliancedigital.in/product/example",
            currency="INR", seller="Reliance Digital", discount="10% off",
            observed_at="2026-10-01T09:00:00Z",
        ))
        before = store.get_price_comparison(legacy_id)

        # Re-run the actual initializer with new generic tables present, then use both stores.
        store.init_db()
        store.create_comparison_run("new-generic", ComparisonRequest("Compare services."))
        after = store.get_price_comparison(legacy_id)
        self.assertEqual(after, before)
        self.assertEqual(after["offers"][0]["price"], before["offers"][0]["price"])
        self.assertEqual(after["offers"][0]["product"], before["offers"][0]["product"])


if __name__ == "__main__":
    unittest.main()
