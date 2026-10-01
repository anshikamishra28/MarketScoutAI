import os
import tempfile
import unittest
from unittest.mock import patch

from database import store
from models.comparison import Observation, SourceCheck, SourceReference
from tools.comparison_sources.base import ComparisonSourceOutcome


class StaticComparisonAdapter:
    def __init__(self, observations):
        self.source = SourceReference("fixture", "Fixture source", "test")
        self.observations = observations

    def supports(self, request, source):
        return source.key == self.source.key

    def check(self, request, source):
        return ComparisonSourceOutcome(
            SourceCheck(source, "checked"),
            [Observation(
                entity_key=entity_key,
                attribute_key="metric",
                source_key=source.key,
                raw_value=raw_value,
                normalized_value=value,
                value_type="scalar",
                unit="unit",
                source_url=f"https://example.com/{entity_key}",
            ) for entity_key, raw_value, value in self.observations],
        )


class GenericComparisonApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch("database.store.DB_PATH", os.path.join(self.temp_dir.name, "api.sqlite3"))
        self.db_patch.start()
        store.init_db()
        from fastapi.testclient import TestClient
        from backend.main import app
        self.client = TestClient(app)
        self.payload = {
            "user_request": "Compare Netflix and Prime Video by monthly price.",
            "entities": [
                {"key": "netflix", "display_name": "Netflix", "entity_type": "streaming_service"},
                {"key": "prime", "display_name": "Prime Video"},
            ],
            "attributes": [
                {"key": "monthly_price", "label": "Monthly price", "value_type": "scalar", "currency": "INR"},
            ],
            "source_preferences": [
                {"key": "provider", "name": "Provider website", "source_type": "official", "url": "https://example.com/"},
            ],
        }

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_post_returns_202_queued_and_persists_request(self):
        with patch("backend.main._run_generic_comparison") as background:
            response = self.client.post("/comparisons", json=self.payload)
        self.assertEqual(response.status_code, 202, response.text)
        body = response.json()
        comparison_id = body["comparison_id"]
        self.assertEqual(body["status"], "queued")
        self.assertEqual(body["status_url"], f"/comparisons/{comparison_id}/status")
        background.assert_called_once()
        saved = store.get_comparison_result(comparison_id)
        self.assertEqual(saved["status"], "queued")
        self.assertEqual(saved["request"]["user_request"], self.payload["user_request"])
        self.assertEqual([item["key"] for item in saved["entities"]], ["netflix", "prime"])

    def test_status_returns_generic_lifecycle_fields_only(self):
        with patch("backend.main._run_generic_comparison"):
            started = self.client.post("/comparisons", json=self.payload).json()
        response = self.client.get(started["status_url"])
        self.assertEqual(response.status_code, 200)
        status = response.json()
        self.assertEqual(status["comparison_id"], started["comparison_id"])
        self.assertEqual(status["status"], "queued")
        self.assertTrue(status["created_at"])
        self.assertTrue(status["updated_at"])
        self.assertIsNone(status["error"])
        self.assertNotIn("offers", status)
        self.assertNotIn("retailer_checks", status)
        self.assertNotIn("input_data", status)

    def test_status_exposes_failed_generic_run_error(self):
        with patch("backend.main._run_generic_comparison"):
            started = self.client.post("/comparisons", json=self.payload).json()
        store.update_comparison_run(started["comparison_id"], status="failed", error="adapter registry failure")
        status = self.client.get(started["status_url"]).json()
        self.assertEqual(status["status"], "failed")
        self.assertEqual(status["error"], "adapter registry failure")
        self.assertEqual(status["errors"], ["adapter registry failure"])

    def test_detail_returns_complete_generic_result(self):
        with patch("backend.main._run_generic_comparison"):
            started = self.client.post("/comparisons", json=self.payload).json()
        response = self.client.get(f"/comparisons/{started['comparison_id']}")
        self.assertEqual(response.status_code, 200)
        result = response.json()
        self.assertEqual(result["comparison_id"], started["comparison_id"])
        self.assertEqual(result["request"]["user_request"], self.payload["user_request"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["source_checks"], [])
        self.assertEqual(result["observations"], [])

    def _analysis_payload(self, comparison_rule=None):
        return {
            "user_request": "Compare two generic entities by a numeric metric.",
            "entities": [
                {"key": "entity_a", "display_name": "Entity A"},
                {"key": "entity_b", "display_name": "Entity B"},
            ],
            "attributes": [{
                "key": "metric", "label": "Metric", "value_type": "scalar",
                "unit": "unit", "comparison_rule": comparison_rule,
            }],
            "source_preferences": [{"key": "fixture", "name": "Fixture source", "source_type": "test"}],
        }

    def _run_with_fixture_source(self, payload, observations):
        adapter = StaticComparisonAdapter(observations)
        with patch("backend.main._generic_comparison_adapters", return_value=(adapter,)):
            started = self.client.post("/comparisons", json=payload)
        self.assertEqual(started.status_code, 202, started.text)
        comparison_id = started.json()["comparison_id"]
        response = self.client.get(f"/comparisons/{comparison_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return comparison_id, response.json()

    def test_completed_api_result_contains_persisted_structured_analysis_and_explicit_ranking(self):
        comparison_id, result = self._run_with_fixture_source(
            self._analysis_payload("lower_is_better"),
            [("entity_a", "12 units", 12), ("entity_b", "7 units", 7)],
        )
        for field in (
            "comparison_id", "status", "entities", "attributes", "source_checks",
            "observations", "analysis", "unresolved", "errors",
        ):
            self.assertIn(field, result)
        self.assertEqual(result["status"], "completed")
        self.assertIsInstance(result["analysis"], dict)
        self.assertEqual(len(result["observations"]), 2)
        attribute = result["analysis"]["attributes"][0]
        self.assertEqual(attribute["attribute_key"], "metric")
        self.assertEqual(attribute["status"], "complete")
        self.assertEqual([row["comparable_value"] for row in attribute["entities"]], [12, 7])
        self.assertEqual([row["entity_key"] for row in attribute["ranking"]], ["entity_b", "entity_a"])
        self.assertEqual(attribute["winner_entity_key"], "entity_b")
        saved = store.get_comparison_result(comparison_id)
        self.assertEqual(saved["analysis"], result["analysis"])

    def test_missing_entity_data_remains_unresolved_without_ranking_or_winner(self):
        _, result = self._run_with_fixture_source(
            self._analysis_payload("higher_is_better"),
            [("entity_a", "12 units", 12)],
        )
        attribute = result["analysis"]["attributes"][0]
        self.assertEqual(attribute["status"], "unresolved")
        self.assertEqual(attribute["entities"][1]["status"], "unresolved")
        self.assertEqual(attribute["ranking"], [])
        self.assertIsNone(attribute["winner_entity_key"])

    def test_without_comparison_rule_api_reports_values_without_ranking(self):
        _, result = self._run_with_fixture_source(
            self._analysis_payload(),
            [("entity_a", "12 units", 12), ("entity_b", "7 units", 7)],
        )
        attribute = result["analysis"]["attributes"][0]
        self.assertEqual([row["comparable_value"] for row in attribute["entities"]], [12, 7])
        self.assertEqual(attribute["ranking"], [])
        self.assertIsNone(attribute["winner_entity_key"])

    def test_missing_comparison_returns_404_from_both_get_routes(self):
        self.assertEqual(self.client.get("/comparisons/missing/status").status_code, 404)
        self.assertEqual(self.client.get("/comparisons/missing").status_code, 404)

    def test_unregistered_requested_source_becomes_unsupported_without_observation(self):
        response = self.client.post("/comparisons", json=self.payload)
        self.assertEqual(response.status_code, 202, response.text)
        comparison_id = response.json()["comparison_id"]
        # TestClient runs FastAPI BackgroundTasks before returning the response.
        detail = self.client.get(f"/comparisons/{comparison_id}").json()
        self.assertEqual(detail["status"], "completed")
        self.assertEqual(len(detail["source_checks"]), 1)
        self.assertEqual(detail["source_checks"][0]["status"], "unsupported")
        self.assertEqual(detail["source_checks"][0]["source"]["key"], "provider")
        self.assertEqual(detail["observations"], [])

    def test_invalid_generic_request_uses_422_validation(self):
        response = self.client.post("/comparisons", json={"user_request": "   "})
        self.assertEqual(response.status_code, 422)

    def test_background_task_receives_generic_request_and_explicit_empty_registry(self):
        with patch("backend.main._generic_comparison_adapters", return_value=()) as registry:
            with patch("backend.main.execute_comparison") as execute:
                response = self.client.post("/comparisons", json=self.payload)
        self.assertEqual(response.status_code, 202)
        execute.assert_called_once()
        args, kwargs = execute.call_args
        self.assertEqual(args[0].user_request, self.payload["user_request"])
        self.assertEqual(kwargs["comparison_id"], response.json()["comparison_id"])
        self.assertEqual(kwargs["adapters"], ())
        registry.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
