import os
import tempfile
import unittest
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
from services.comparison_service import execute_comparison
from tools.comparison_sources import ComparisonSourceOutcome


class FakeAdapter:
    def __init__(self, key, outcome=None, error=None, supported=True):
        self.source = SourceReference(key, key)
        self.outcome = outcome
        self.error = error
        self.supported = supported
        self.checked = []

    def supports(self, request, source):
        return self.supported

    def check(self, request, source):
        self.checked.append((request, source))
        if self.error:
            raise self.error
        return self.outcome


class GenericComparisonServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch("database.store.DB_PATH", os.path.join(self.temp_dir.name, "comparison.sqlite3"))
        self.db_patch.start()
        store.init_db()
        self.request = ComparisonRequest(
            "Compare Netflix and Prime Video by monthly price and free tier.",
            entities=[EntityReference("netflix", "Netflix"), EntityReference("prime", "Prime Video")],
            attributes=[
                AttributeDefinition("monthly_price", "Monthly price", "scalar", "month", "INR"),
                AttributeDefinition("free_tier", "Free tier", "boolean"),
            ],
            source_preferences=[
                SourceReference("provider-a", "Provider A", "official", "https://a.example/"),
            ],
        )

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _checked_outcome(self, source_key="provider-a"):
        return ComparisonSourceOutcome(
            SourceCheck(SourceReference(source_key, "Provider A", "official", "https://a.example/"), "checked"),
            [Observation("netflix", "monthly_price", source_key, "₹649/month", 649,
                         value_type="scalar", unit="month", currency="INR",
                         source_url="https://a.example/plans")],
        )

    def test_creates_run_and_persists_request_entities_and_attributes(self):
        result = execute_comparison(self.request, comparison_id="run-1")
        self.assertEqual(result["comparison_id"], "run-1")
        self.assertEqual(result["status"], "completed")
        self.assertEqual([entity["key"] for entity in result["entities"]], ["netflix", "prime"])
        self.assertEqual([attribute["key"] for attribute in result["attributes"]], ["monthly_price", "free_tier"])
        self.assertEqual(result["request"]["user_request"], self.request.user_request)

    def test_successful_adapter_persists_traceable_observation_without_replacing_raw_value(self):
        adapter = FakeAdapter("provider-a", self._checked_outcome())
        result = execute_comparison(self.request, [adapter], comparison_id="success")
        self.assertEqual(result["source_checks"][0]["status"], "checked")
        observation = result["observations"][0]
        self.assertEqual((observation["entity_key"], observation["attribute_key"], observation["source_key"]),
                         ("netflix", "monthly_price", "provider-a"))
        self.assertEqual(observation["raw_value"], "₹649/month")
        self.assertEqual(observation["normalized_value"], 649)
        self.assertEqual(observation["source_url"], "https://a.example/plans")
        self.assertEqual(result["unresolved"], ["Netflix — Free tier", "Prime Video — Monthly price", "Prime Video — Free tier"])

    def test_missing_adapter_is_unsupported_without_fabricated_observations(self):
        result = execute_comparison(self.request, [], comparison_id="unsupported")
        self.assertEqual(result["source_checks"][0]["status"], "unsupported")
        self.assertEqual(result["source_checks"][0]["diagnostics"]["reason"], "No adapter is registered for this source.")
        self.assertEqual(result["observations"], [])

    def test_adapter_declining_request_is_unsupported(self):
        result = execute_comparison(self.request, [FakeAdapter("provider-a", supported=False)], comparison_id="declined")
        self.assertEqual(result["source_checks"][0]["status"], "unsupported")
        self.assertEqual(result["observations"], [])

    def test_source_failure_is_recorded_and_other_source_can_succeed(self):
        self.request.source_preferences.append(SourceReference("provider-b", "Provider B"))
        failing = FakeAdapter("provider-a", error=RuntimeError("fixture timeout"))
        succeeding = FakeAdapter("provider-b", self._checked_outcome("provider-b"))
        result = execute_comparison(self.request, [failing, succeeding], comparison_id="partial")
        checks = {item["source"]["key"]: item for item in result["source_checks"]}
        self.assertEqual(checks["provider-a"]["status"], "failed")
        self.assertEqual(checks["provider-a"]["error"], "fixture timeout")
        self.assertEqual(checks["provider-b"]["status"], "checked")
        self.assertEqual(len(result["observations"]), 1)
        self.assertTrue(any("fixture timeout" in error for error in result["errors"]))

    def test_unavailable_blocked_and_failed_adapter_states_have_no_observations(self):
        self.request.source_preferences = [
            SourceReference("unavailable", "Unavailable"),
            SourceReference("blocked", "Blocked"),
            SourceReference("failed", "Failed"),
        ]
        adapters = [
            FakeAdapter(key, ComparisonSourceOutcome(SourceCheck(SourceReference(key, key), status), []))
            for key, status in (("unavailable", "unavailable"), ("blocked", "blocked"), ("failed", "failed"))
        ]
        result = execute_comparison(self.request, adapters, comparison_id="states")
        self.assertEqual({check["status"] for check in result["source_checks"]}, {"unavailable", "blocked", "failed"})
        self.assertEqual(result["observations"], [])

    def test_adapter_output_for_unrequested_entity_or_attribute_is_rejected(self):
        invalid = ComparisonSourceOutcome(
            SourceCheck(SourceReference("provider-a", "Provider A"), "checked"),
            [Observation("unknown", "monthly_price", "provider-a", "raw", 1)],
        )
        result = execute_comparison(self.request, [FakeAdapter("provider-a", invalid)], comparison_id="invalid-ref")
        self.assertEqual(result["source_checks"][0]["status"], "failed")
        self.assertIn("unrequested entity", result["source_checks"][0]["error"])
        self.assertEqual(result["observations"], [])

    def test_outcome_contract_rejects_observations_for_non_checked_source(self):
        with self.assertRaisesRegex(ValueError, "only a checked source"):
            ComparisonSourceOutcome(
                SourceCheck(SourceReference("src", "Source"), "blocked"),
                [Observation("netflix", "monthly_price", "src", "649", 649)],
            )

    def test_adapters_are_considered_when_request_has_no_source_preferences(self):
        self.request.source_preferences = []
        adapter = FakeAdapter("provider-a", self._checked_outcome())
        result = execute_comparison(self.request, [adapter], comparison_id="implicit-source")
        self.assertEqual(len(adapter.checked), 1)
        self.assertEqual(result["source_checks"][0]["source"]["key"], "provider-a")

    def test_mapping_request_is_validated_and_accepted(self):
        request_data = self.request.to_dict()
        result = execute_comparison(request_data, [], comparison_id="mapping")
        self.assertEqual(result["request"]["user_request"], self.request.user_request)


if __name__ == "__main__":
    unittest.main()
