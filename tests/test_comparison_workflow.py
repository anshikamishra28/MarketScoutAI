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
from models.comparison_intent import ComparisonIntent, ComparisonIntentState, Provenance
from services.comparison_intent import build_comparison_intent
from services.comparison_workflow import (
    ConfirmationPayload,
    confirm_comparison_intent,
    execute_confirmed_comparison,
    get_clarification_details,
    interpret_comparison_workflow,
)
from tools.comparison_sources import ComparisonSourceOutcome


TEXT = "Compare Alpha Service and Beta Service by monthly cost on Example Source."
SOURCE = SourceReference("example_source", "Example Source", "official")


def provider_output(*, identifiers=True, sources=True):
    ids_a = {"provider_name": "Alpha Service"} if identifiers else {}
    ids_b = {"provider_name": "Beta Service"} if identifiers else {}
    return {
        "entities": [
            {"display_name": "Alpha Service", "evidence": "Alpha Service", "entity_type": None,
             "identifiers": ids_a, "aliases": []},
            {"display_name": "Beta Service", "evidence": "Beta Service", "entity_type": None,
             "identifiers": ids_b, "aliases": []},
        ],
        "attributes": [
            {"label": "monthly cost", "evidence": "monthly cost", "value_type": "scalar",
             "unit": "monthly", "currency": None, "comparison_rule": None},
        ],
        "sources": [{"key": SOURCE.key}] if sources else [],
        "context": {},
        "issues": [],
    }


class FakeProvider:
    def __init__(self, output):
        self.output = output
        self.calls = 0

    def interpret(self, user_request, *, allowed_sources):
        self.calls += 1
        return self.output


class FakeAdapter:
    source = SOURCE

    def __init__(self):
        self.calls = []

    def supports(self, request, source):
        return True

    def check(self, request, source):
        self.calls.append((request, source))
        return ComparisonSourceOutcome(
            SourceCheck(source, "checked"),
            [Observation("alpha_service", "monthly_cost", source.key, "$12/month", 12,
                         value_type="scalar", unit="monthly", currency="USD")],
        )


def ready_intent():
    request = ComparisonRequest(
        "Compare Alpha Service and Beta Service by monthly cost on Example Source.",
        entities=[
            EntityReference("alpha_service", "Alpha Service", identifiers={"provider_name": "Alpha Service"}),
            EntityReference("beta_service", "Beta Service", identifiers={"provider_name": "Beta Service"}),
        ],
        attributes=[AttributeDefinition("monthly_cost", "Monthly cost", "scalar", "monthly", "USD")],
        source_preferences=[SOURCE],
    )
    base = build_comparison_intent(request)
    return ComparisonIntent(request, base.state, base.unresolved, base.provenance)


class ComparisonWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_patch = patch("database.store.DB_PATH", os.path.join(self.temp_dir.name, "workflow.sqlite3"))
        self.db_patch.start()
        store.init_db()

    def tearDown(self):
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def interpret(self, *, identifiers=True, sources=True, structured_sources=None, context=None):
        provider = FakeProvider(provider_output(identifiers=identifiers, sources=sources))
        intent = interpret_comparison_workflow(
            TEXT,
            context=context,
            source_preferences=structured_sources,
            allowed_sources=(SOURCE,),
            provider=provider,
        )
        return intent, provider

    def test_natural_language_needs_clarification_does_not_execute(self):
        intent, _ = self.interpret()
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        adapter = FakeAdapter()
        with patch("services.comparison_workflow.execute_comparison") as execute:
            with self.assertRaisesRegex(ValueError, "not fully resolved"):
                execute_confirmed_comparison(intent, adapters=[adapter])
        execute.assert_not_called()
        self.assertEqual(adapter.calls, [])

    def test_proposed_identity_remains_proposed_before_confirmation(self):
        intent, _ = self.interpret()
        entity = intent.request.entities[0]
        path = f"entities.{entity.key}.identifiers.provider_name"
        self.assertEqual(intent.provenance[path], Provenance.PROPOSED)
        self.assertTrue(any(issue.code == "PROPOSED_IDENTITY_REQUIRES_CONFIRMATION" for issue in intent.unresolved))

    def test_confirmation_changes_only_the_selected_field(self):
        intent, _ = self.interpret()
        entity = intent.request.entities[0]
        path = f"/entities/{entity.key}/identifiers/provider_name"
        confirmed = confirm_comparison_intent(intent, ConfirmationPayload({path: "Alpha Service"}))
        self.assertEqual(confirmed.provenance[f"entities.{entity.key}.identifiers.provider_name"], Provenance.USER_CONFIRMED)
        self.assertEqual(confirmed.provenance[f"entities.{entity.key}.display_name"], Provenance.USER_PROVIDED)
        self.assertEqual(confirmed.provenance["attributes.monthly_cost.label"], Provenance.USER_PROVIDED)
        self.assertEqual(confirmed.provenance["entities.beta_service.identifiers.provider_name"], Provenance.PROPOSED)

    def test_confirmation_requires_an_explicit_payload(self):
        intent, _ = self.interpret()
        with self.assertRaises(TypeError):
            confirm_comparison_intent(intent)
        with self.assertRaisesRegex(ValueError, "ConfirmationPayload"):
            confirm_comparison_intent(intent, None)

    def test_invalid_confirmation_paths_are_rejected(self):
        intent, _ = self.interpret()
        with self.assertRaisesRegex(ValueError, "does not identify"):
            confirm_comparison_intent(intent, ConfirmationPayload({"/entities/unknown/identifiers/model": "x"}))
        with self.assertRaisesRegex(ValueError, "JSON Pointer escape"):
            confirm_comparison_intent(intent, ConfirmationPayload({"/entities/alpha~2/identifiers/x": "x"}))

    def test_confirmation_cannot_add_an_unproposed_field(self):
        intent, _ = self.interpret()
        with self.assertRaisesRegex(ValueError, "does not identify"):
            confirm_comparison_intent(
                intent,
                ConfirmationPayload({"/entities/alpha_service/identifiers/model_number": "invented"}),
            )

    def test_partial_confirmation_stays_unresolved(self):
        intent, _ = self.interpret()
        entity = intent.request.entities[0]
        confirmed = confirm_comparison_intent(
            intent,
            ConfirmationPayload({f"/entities/{entity.key}/identifiers/provider_name": "Alpha Service"}),
        )
        self.assertEqual(confirmed.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertTrue(confirmed.unresolved)

    def test_multiple_proposed_fields_all_require_confirmation(self):
        intent, _ = self.interpret()
        details = get_clarification_details(intent)
        paths = {item["path"] for item in details["confirmations_required"]}
        self.assertIn("/entities/alpha_service/identifiers/provider_name", paths)
        self.assertIn("/entities/beta_service/identifiers/provider_name", paths)
        self.assertIn("/attributes/monthly_cost/value_type", paths)
        self.assertIn("/source_preferences/0/key", paths)

    def test_fully_confirmed_intent_becomes_ready(self):
        intent, _ = self.interpret()
        required = get_clarification_details(intent)["confirmations_required"]
        confirmations = {item["path"]: item["proposed_value"] for item in required}
        confirmed = confirm_comparison_intent(intent, ConfirmationPayload(confirmations))
        self.assertEqual(confirmed.state, ComparisonIntentState.READY)
        self.assertEqual(confirmed.unresolved, [])
        self.assertEqual(confirmed.provenance["entities.alpha_service.identifiers.provider_name"], Provenance.USER_CONFIRMED)
        self.assertEqual(confirmed.provenance["entities.beta_service.identifiers.provider_name"], Provenance.USER_CONFIRMED)
        self.assertEqual(confirmed.provenance["attributes.monthly_cost.value_type"], Provenance.USER_CONFIRMED)
        self.assertEqual(confirmed.provenance["attributes.monthly_cost.unit"], Provenance.USER_CONFIRMED)
        self.assertEqual(confirmed.provenance["sources.example_source.key"], Provenance.USER_CONFIRMED)

    def test_user_provided_source_and_context_provenance_are_preserved(self):
        intent, _ = self.interpret(structured_sources=[SOURCE], context={"audience": "student"})
        self.assertEqual(intent.provenance["sources.example_source.name"], Provenance.USER_PROVIDED)
        self.assertEqual(intent.provenance["context.audience"], Provenance.USER_PROVIDED)
        confirmed = confirm_comparison_intent(
            intent,
            ConfirmationPayload({"/entities/alpha_service/identifiers/provider_name": "Alpha Service"}),
        )
        self.assertEqual(confirmed.provenance["sources.example_source.name"], Provenance.USER_PROVIDED)
        self.assertEqual(confirmed.provenance["context.audience"], Provenance.USER_PROVIDED)

    def test_ready_intent_reaches_existing_execution_service(self):
        adapter = FakeAdapter()
        result = execute_confirmed_comparison(ready_intent(), adapters=[adapter], comparison_id="workflow-live")
        self.assertEqual(result["comparison_id"], "workflow-live")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["source_checks"][0]["status"], "checked")
        self.assertEqual(result["observations"][0]["entity_key"], "alpha_service")
        self.assertEqual(len(adapter.calls), 1)

    def test_execution_lifecycle_and_persistence_are_preserved(self):
        result = execute_confirmed_comparison(ready_intent(), adapters=[FakeAdapter()], comparison_id="lifecycle")
        persisted = store.get_comparison_result("lifecycle")
        self.assertEqual(persisted["status"], result["status"])
        self.assertEqual(persisted["request"], result["request"])
        self.assertEqual(persisted["observations"], result["observations"])
        self.assertEqual(result["analysis"]["attributes"][0]["attribute_key"], "monthly_cost")

    def test_unresolved_intent_cannot_execute_even_with_adapter(self):
        intent, _ = self.interpret()
        adapter = FakeAdapter()
        with self.assertRaises(ValueError):
            execute_confirmed_comparison(intent, adapters=[adapter])
        self.assertEqual(adapter.calls, [])

    def test_execution_guard_rejects_ready_state_with_unconfirmed_proposals(self):
        draft, _ = self.interpret()
        forged_ready = ComparisonIntent(
            request=draft.request,
            state=ComparisonIntentState.READY,
            unresolved=[],
            provenance=draft.provenance,
        )
        with self.assertRaisesRegex(ValueError, "not fully resolved and confirmed"):
            execute_confirmed_comparison(forged_ready, adapters=[FakeAdapter()])

    def test_execution_error_surfaces_without_changing_intent_provenance(self):
        intent = ready_intent()
        before = dict(intent.provenance)
        with patch("services.comparison_workflow.execute_comparison", side_effect=RuntimeError("execution failed")):
            with self.assertRaisesRegex(RuntimeError, "execution failed"):
                execute_confirmed_comparison(intent, adapters=[])
        self.assertEqual(intent.provenance, before)

    def test_confirmation_itself_does_not_call_provider_or_adapter(self):
        intent, provider = self.interpret()
        adapter = FakeAdapter()
        calls_before = provider.calls
        confirmed = confirm_comparison_intent(
            intent,
            ConfirmationPayload({"/entities/alpha_service/identifiers/provider_name": "Alpha Service"}),
        )
        self.assertEqual(provider.calls, calls_before)
        self.assertEqual(adapter.calls, [])
        self.assertEqual(confirmed.state, ComparisonIntentState.NEEDS_CLARIFICATION)

    def test_clarification_details_expose_confirmable_paths(self):
        intent, _ = self.interpret()
        details = get_clarification_details(intent)
        self.assertFalse(details["ready_for_execution"])
        self.assertTrue(any(item["path"].startswith("/entities/") for item in details["confirmations_required"]))
        self.assertTrue(details["unresolved"])

    def test_source_selection_proposal_requires_explicit_confirmation(self):
        intent, _ = self.interpret()
        self.assertEqual(intent.provenance["sources.example_source.key"], Provenance.PROPOSED)
        confirmed = confirm_comparison_intent(
            intent,
            ConfirmationPayload({"/source_preferences/0/key": "example_source"}),
        )
        self.assertEqual(confirmed.provenance["sources.example_source.key"], Provenance.USER_CONFIRMED)
        self.assertEqual(confirmed.state, ComparisonIntentState.NEEDS_CLARIFICATION)

    def test_confirming_fields_does_not_silently_clear_ambiguity(self):
        output = provider_output()
        output["issues"] = [{
            "code": "AMBIGUOUS_ATTRIBUTE",
            "target": "attribute",
            "message": "The requested cost period remains ambiguous.",
            "candidates": ["monthly", "annual"],
            "clarification_question": "Which cost period should be used?",
        }]
        provider = FakeProvider(output)
        intent = interpret_comparison_workflow(TEXT, allowed_sources=(SOURCE,), provider=provider)
        confirmations = {
            item["path"]: item["proposed_value"]
            for item in get_clarification_details(intent)["confirmations_required"]
        }
        confirmed = confirm_comparison_intent(intent, ConfirmationPayload(confirmations))
        self.assertEqual(confirmed.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertIn("AMBIGUOUS_ATTRIBUTE", {issue.code for issue in confirmed.unresolved})

    def test_user_provided_field_cannot_be_reconfirmed_as_proposed(self):
        intent = ready_intent()
        with self.assertRaisesRegex(ValueError, "does not correspond to a proposed field"):
            confirm_comparison_intent(
                intent,
                ConfirmationPayload({"/entities/alpha_service/identifiers/provider_name": "Alpha Service"}),
            )


if __name__ == "__main__":
    unittest.main()
