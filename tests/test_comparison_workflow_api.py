import os
import tempfile
import unittest
from unittest.mock import patch

from database import store
from models.comparison import Observation, SourceCheck, SourceReference
from tools.comparison_sources.base import ComparisonSourceOutcome


SOURCE = SourceReference("fixture", "Fixture source", "test", "https://example.com/")


class FakeProvider:
    def __init__(self, *, invent_identifier=False, fail=False):
        self.invent_identifier = invent_identifier
        self.fail = fail
        self.calls = []

    def interpret(self, user_request, *, allowed_sources):
        self.calls.append((user_request, allowed_sources))
        if self.fail:
            raise RuntimeError("provider unavailable")
        identifier = "invented-42" if self.invent_identifier else "Alpha"
        return {
            "entities": [
                {"display_name": "Alpha", "evidence": "Alpha", "entity_type": None, "identifiers": {"name": identifier}, "aliases": []},
                {"display_name": "Beta", "evidence": "Beta", "entity_type": None, "identifiers": {"name": "Beta"}, "aliases": []},
            ],
            "attributes": [{"label": "price", "evidence": "price", "value_type": "scalar", "unit": None, "currency": None, "comparison_rule": None}],
            "sources": [], "context": {}, "issues": [],
        }


class FakeAdapter:
    source = SOURCE

    def supports(self, request, source):
        return source.key == self.source.key

    def check(self, request, source):
        return ComparisonSourceOutcome(
            SourceCheck(source, "checked"),
            [Observation(entity.key, request.attributes[0].key, source.key, entity.display_name,
                         normalized_value=index + 1, value_type="scalar", source_url="https://example.com/value")
             for index, entity in enumerate(request.entities)],
        )


class ComparisonWorkflowApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch("database.store.DB_PATH", os.path.join(self.temp_dir.name, "workflow.sqlite3"))
        self.db_patch.start()
        store.init_db()
        import backend.main as main
        self.main = main
        with main._comparison_workflows_lock:
            main._comparison_workflows.clear()
        from fastapi.testclient import TestClient
        self.client = TestClient(main.app)

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def _start(self, provider=None, *, include_source=True):
        provider = provider or FakeProvider()
        patchers = [
            patch("backend.main._comparison_interpretation_provider", return_value=provider),
            patch("backend.main._generic_comparison_adapters", return_value=(FakeAdapter(),)),
        ]
        with patchers[0], patchers[1]:
            response = self.client.post("/comparison-workflows", json={
                "user_request": "Compare Alpha and Beta by price",
                "source_preferences": [SOURCE.to_dict()] if include_source else [],
            })
        self.assertEqual(response.status_code, 202, response.text)
        return response.json(), provider

    def test_natural_language_request_reaches_interpreter_and_returns_clarification(self):
        body, provider = self._start()
        self.assertEqual(len(provider.calls), 1)
        self.assertEqual(provider.calls[0][0], "Compare Alpha and Beta by price")
        self.assertEqual(body["intent"]["state"], "needs_clarification")
        self.assertTrue(body["clarification"]["unresolved"])
        self.assertIsNone(body["comparison_id"])

    def test_proposed_identity_is_not_executable_and_provenance_is_proposed(self):
        body, _ = self._start()
        intent = body["intent"]
        self.assertEqual(intent["provenance"]["entities.alpha.identifiers.name"], "proposed")
        self.assertIn("PROPOSED_IDENTITY_REQUIRES_CONFIRMATION", [issue["code"] for issue in intent["unresolved"]])
        self.assertIsNone(body["comparison_id"])

    def test_confirmation_changes_only_selected_provenance_and_partial_remains_clarification(self):
        body, _ = self._start()
        workflow_id = body["workflow_id"]
        first = "/entities/alpha/identifiers/name"
        response = self.client.post(f"/comparison-workflows/{workflow_id}/confirm", json={"values": {first: "Alpha"}})
        self.assertEqual(response.status_code, 202, response.text)
        intent = response.json()["intent"]
        self.assertEqual(intent["provenance"]["entities.alpha.identifiers.name"], "user_confirmed")
        self.assertEqual(intent["provenance"]["entities.beta.identifiers.name"], "proposed")
        self.assertEqual(intent["state"], "needs_clarification")
        self.assertIsNone(response.json()["comparison_id"])

    def test_all_confirmations_execute_through_existing_service_and_return_result_shape(self):
        body, _ = self._start()
        values = {item["path"]: item["proposed_value"] for item in body["clarification"]["confirmations_required"]}
        with patch("backend.main._generic_comparison_adapters", return_value=(FakeAdapter(),)):
            confirmed = self.client.post(f"/comparison-workflows/{body['workflow_id']}/confirm", json={"values": values})
        self.assertEqual(confirmed.status_code, 202, confirmed.text)
        result_id = confirmed.json()["comparison_id"]
        self.assertIsNotNone(result_id)
        result = self.client.get(f"/comparisons/{result_id}").json()
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["observations"]), 2)
        self.assertIn("analysis", result)
        self.assertEqual(confirmed.json()["intent"]["state"], "ready")

    def test_confirmation_route_does_not_execute_before_explicit_confirmation(self):
        provider = FakeProvider()
        with patch("backend.main._comparison_interpretation_provider", return_value=provider), \
             patch("backend.main._generic_comparison_adapters", return_value=(FakeAdapter(),)), \
             patch("backend.main.start_generic_comparison", wraps=self.main.start_generic_comparison) as start_run:
            body = self.client.post("/comparison-workflows", json={
                "user_request": "Compare Alpha and Beta by price",
                "source_preferences": [SOURCE.to_dict()],
            }).json()
            self.assertIsNone(body["comparison_id"])
            start_run.assert_not_called()

    def test_provider_failure_is_structured_and_does_not_leak_credentials(self):
        body, _ = self._start(FakeProvider(fail=True))
        encoded = str(body)
        self.assertEqual(body["intent"]["state"], "needs_clarification")
        self.assertIn("INTERPRETATION_UNAVAILABLE", encoded)
        self.assertNotIn("GEMINI_API_KEY", encoded)
        self.assertNotIn("provider unavailable", encoded)
        self.assertIsNone(body["comparison_id"])

    def test_no_source_is_not_selected_implicitly(self):
        body, _ = self._start(include_source=False)
        self.assertEqual(body["intent"]["request"]["source_preferences"], [])
        self.assertIn("SOURCE_SELECTION_REQUIRED", [item["code"] for item in body["intent"]["unresolved"]])
        self.assertIsNone(body["comparison_id"])

    def test_identifier_not_supported_by_request_is_rejected_without_invention(self):
        body, _ = self._start(FakeProvider(invent_identifier=True))
        self.assertEqual(body["intent"]["request"]["entities"], [])
        self.assertIn("INTERPRETATION_INVALID", [item["code"] for item in body["intent"]["unresolved"]])
        self.assertIsNone(body["comparison_id"])

    def test_workflow_detail_and_unknown_id(self):
        body, _ = self._start()
        detail = self.client.get(f"/comparison-workflows/{body['workflow_id']}")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["workflow_id"], body["workflow_id"])
        self.assertEqual(self.client.get("/comparison-workflows/missing").status_code, 404)


if __name__ == "__main__":
    unittest.main()
