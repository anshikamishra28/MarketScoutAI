import unittest

from models.comparison import AttributeDefinition, ComparisonRequest, EntityReference, SourceReference
from models.comparison_intent import ComparisonIntentState, InterpretationIssue, Provenance
from services.comparison_intent import build_comparison_intent


def ready_request():
    return ComparisonRequest(
        user_request="Compare two services by monthly cost.",
        entities=[
            EntityReference("service_a", "Service A", identifiers={"provider": "A"}),
            EntityReference("service_b", "Service B", identifiers={"provider": "B"}),
        ],
        attributes=[AttributeDefinition("monthly_cost", "Monthly cost", "scalar", "month", "USD")],
        source_preferences=[SourceReference("official", "Official sources", "website")],
    )


class ComparisonIntentTests(unittest.TestCase):
    def test_valid_explicit_request_is_ready(self):
        intent = build_comparison_intent(ready_request())
        self.assertEqual(intent.state, ComparisonIntentState.READY)
        self.assertEqual(intent.unresolved, [])

    def test_missing_entities_needs_clarification(self):
        request = ready_request()
        request.entities = []
        intent = build_comparison_intent(request)
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertIn("ENTITIES_REQUIRED", {issue.code for issue in intent.unresolved})

    def test_missing_attributes_needs_clarification(self):
        request = ready_request()
        request.attributes = []
        intent = build_comparison_intent(request)
        self.assertIn("ATTRIBUTES_REQUIRED", {issue.code for issue in intent.unresolved})

    def test_missing_source_preferences_needs_clarification(self):
        request = ready_request()
        request.source_preferences = []
        intent = build_comparison_intent(request)
        self.assertIn("SOURCE_SELECTION_REQUIRED", {issue.code for issue in intent.unresolved})

    def test_display_name_does_not_create_identifiers(self):
        request = ready_request()
        request.entities[0] = EntityReference("service_a", "Some Product")
        before = request.to_dict()
        intent = build_comparison_intent(request)
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertEqual(intent.request.entities[0].identifiers, {})
        self.assertEqual(request.to_dict(), before)
        self.assertIn("ENTITY_IDENTITY_UNRESOLVED", {issue.code for issue in intent.unresolved})

    def test_explicit_identifiers_are_preserved_exactly(self):
        request = ready_request()
        supplied = {"provider_code": " A-01 ", "region": ["north", "west"]}
        request.entities[0].identifiers = supplied.copy()
        intent = build_comparison_intent(request)
        self.assertEqual(intent.request.entities[0].identifiers, supplied)

    def test_explicit_source_preferences_are_preserved(self):
        request = ready_request()
        before = [source.to_dict() for source in request.source_preferences]
        intent = build_comparison_intent(request)
        self.assertEqual([source.to_dict() for source in intent.request.source_preferences], before)

    def test_multiple_unresolved_issues_coexist(self):
        intent = build_comparison_intent(ComparisonRequest("Compare these."))
        codes = {issue.code for issue in intent.unresolved}
        self.assertTrue({"ENTITIES_REQUIRED", "ATTRIBUTES_REQUIRED", "SOURCE_SELECTION_REQUIRED"}.issubset(codes))

    def test_issue_has_generic_clarification_question(self):
        intent = build_comparison_intent(ComparisonRequest("Compare these."))
        issue = next(item for item in intent.unresolved if item.code == "SOURCE_SELECTION_REQUIRED")
        self.assertEqual(issue.target, "source")
        self.assertTrue(issue.clarification_question)

    def test_service_has_no_adapter_network_or_llm_dependencies(self):
        import services.comparison_intent as service

        self.assertFalse(hasattr(service, "requests"))
        self.assertFalse(hasattr(service, "RelianceDigitalFetcher"))
        self.assertFalse(hasattr(service, "generate_response"))
        self.assertEqual(build_comparison_intent(ready_request()).state, ComparisonIntentState.READY)

    def test_supplied_values_are_user_provided(self):
        intent = build_comparison_intent(ready_request())
        self.assertEqual(intent.provenance["user_request"], Provenance.USER_PROVIDED)
        self.assertEqual(intent.provenance["entities.service_a.identifiers.provider"], Provenance.USER_PROVIDED)
        self.assertEqual(intent.provenance["sources.official.name"], Provenance.USER_PROVIDED)
        self.assertNotIn(Provenance.PROPOSED, intent.provenance.values())

    def test_intent_serialization_is_json_safe(self):
        import json

        serialized = json.loads(json.dumps(build_comparison_intent(ready_request()).to_dict()))
        self.assertEqual(serialized["state"], "ready")
        self.assertEqual(serialized["provenance"]["user_request"], "user_provided")

    def test_interpretation_issue_serializes_candidates(self):
        issue = InterpretationIssue("AMBIGUOUS_ENTITY", "entity", "More than one match.", ["A", {"key": "b"}], "Which one?")
        self.assertEqual(issue.to_dict()["candidates"], ["A", {"key": "b"}])


if __name__ == "__main__":
    unittest.main()
