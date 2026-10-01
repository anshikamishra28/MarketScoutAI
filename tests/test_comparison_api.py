import os
import tempfile
import unittest
from unittest.mock import patch

from database import store


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
