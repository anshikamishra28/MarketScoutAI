import unittest

from models.comparison import SourceReference
from models.comparison_intent import ComparisonIntentState, Provenance
from services.comparison_interpreter import interpret_comparison_request


REQUEST_TEXT = (
    "Compare OnePlus Nord 6 8GB 256GB with OnePlus Nord 4 8GB 128GB "
    "on Reliance Digital by price and storage."
)
RELIANCE = SourceReference(
    "reliance_digital", "Reliance Digital", "retailer", "https://www.reliancedigital.in/"
)


def interpreted_payload(*, entities=None, attributes=None, sources=None, context=None, issues=None):
    return {
        "entities": entities if entities is not None else [
            {
                "display_name": "OnePlus Nord 6",
                "evidence": "OnePlus Nord 6 8GB 256GB",
                "entity_type": None,
                "identifiers": {"brand": "OnePlus", "model": "Nord 6", "ram": "8GB", "storage": "256GB"},
                "aliases": [],
            },
            {
                "display_name": "OnePlus Nord 4",
                "evidence": "OnePlus Nord 4 8GB 128GB",
                "entity_type": None,
                "identifiers": {"brand": "OnePlus", "model": "Nord 4", "ram": "8GB", "storage": "128GB"},
                "aliases": [],
            },
        ],
        "attributes": attributes if attributes is not None else [
            {"label": "price", "evidence": "by price", "value_type": "scalar", "unit": None, "currency": None, "comparison_rule": None},
            {"label": "storage", "evidence": "and storage", "value_type": "scalar", "unit": None, "currency": None, "comparison_rule": None},
        ],
        "sources": sources if sources is not None else [{"key": "reliance_digital"}],
        "context": context if context is not None else {},
        "issues": issues if issues is not None else [],
    }


class FakeProvider:
    def __init__(self, output=None, error=None):
        self.output = output
        self.error = error
        self.calls = []

    def interpret(self, user_request, *, allowed_sources):
        self.calls.append((user_request, list(allowed_sources)))
        if self.error:
            raise self.error
        return self.output

    def check(self, *_args, **_kwargs):
        raise AssertionError("interpretation must never invoke a comparison adapter")


class ComparisonInterpreterTests(unittest.TestCase):
    def interpret(self, output=None, *, text=REQUEST_TEXT, allowed=(RELIANCE,), **kwargs):
        provider = FakeProvider(output if output is not None else interpreted_payload())
        intent = interpret_comparison_request(text, allowed_sources=allowed, provider=provider, **kwargs)
        return intent, provider

    def test_extracts_two_clearly_stated_entities(self):
        intent, _ = self.interpret()
        self.assertEqual([entity.display_name for entity in intent.request.entities], ["OnePlus Nord 6", "OnePlus Nord 4"])
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        issues = [item for item in intent.unresolved if item.code == "PROPOSED_IDENTITY_REQUIRES_CONFIRMATION"]
        self.assertEqual(len(issues), 2)
        self.assertEqual({item.target for item in issues}, {"identifier"})

    def test_proposed_identity_provenance_is_not_user_provided(self):
        intent, _ = self.interpret()
        entity = intent.request.entities[0]
        path = f"entities.{entity.key}.identifiers.model"
        self.assertEqual(intent.provenance[path], Provenance.PROPOSED)
        self.assertNotEqual(intent.provenance[path], Provenance.USER_PROVIDED)
        self.assertIn("PROPOSED_IDENTITY_REQUIRES_CONFIRMATION", {item.code for item in intent.unresolved})

    def test_extracts_only_explicit_attributes(self):
        intent, _ = self.interpret()
        self.assertEqual([attribute.label for attribute in intent.request.attributes], ["price", "storage"])
        self.assertEqual([attribute.key for attribute in intent.request.attributes], ["price", "storage"])

    def test_explicit_known_source_is_preserved(self):
        intent, provider = self.interpret()
        self.assertEqual([source.to_dict() for source in intent.request.source_preferences], [RELIANCE.to_dict()])
        self.assertEqual(provider.calls[0][1], [RELIANCE])

    def test_structured_source_preference_remains_user_provided(self):
        intent, _ = self.interpret(
            interpreted_payload(sources=[]),
            source_preferences=[RELIANCE],
        )
        self.assertEqual([source.to_dict() for source in intent.request.source_preferences], [RELIANCE.to_dict()])
        for field in ("key", "name", "source_type", "url"):
            self.assertEqual(intent.provenance[f"sources.{RELIANCE.key}.{field}"], Provenance.USER_PROVIDED)

    def test_each_entity_with_proposed_identity_gets_its_own_issue(self):
        intent, _ = self.interpret()
        issues = [item for item in intent.unresolved if item.code == "PROPOSED_IDENTITY_REQUIRES_CONFIRMATION"]
        self.assertEqual(len(issues), len(intent.request.entities))
        for entity in intent.request.entities:
            self.assertTrue(any(entity.display_name in issue.message for issue in issues))
            self.assertTrue(any(entity.display_name in issue.clarification_question for issue in issues))

    def test_missing_entities_produces_clarification(self):
        intent, _ = self.interpret(interpreted_payload(entities=[]))
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertIn("ENTITIES_REQUIRED", {issue.code for issue in intent.unresolved})

    def test_missing_attributes_produces_clarification(self):
        intent, _ = self.interpret(interpreted_payload(attributes=[]))
        self.assertIn("ATTRIBUTES_REQUIRED", {issue.code for issue in intent.unresolved})

    def test_missing_source_never_defaults_to_reliance(self):
        intent, _ = self.interpret(interpreted_payload(sources=[]))
        self.assertEqual(intent.request.source_preferences, [])
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertIn("SOURCE_SELECTION_REQUIRED", {issue.code for issue in intent.unresolved})

    def test_display_names_do_not_create_identifiers(self):
        payload = interpreted_payload()
        for entity in payload["entities"]:
            entity["identifiers"] = {}
        intent, _ = self.interpret(payload)
        self.assertEqual([entity.identifiers for entity in intent.request.entities], [{}, {}])
        self.assertIn("ENTITY_IDENTITY_UNRESOLVED", {issue.code for issue in intent.unresolved})

    def test_explicit_identifier_text_is_preserved_as_a_proposal(self):
        intent, _ = self.interpret()
        entity = intent.request.entities[0]
        self.assertEqual(entity.identifiers, {"brand": "OnePlus", "model": "Nord 6", "ram": "8GB", "storage": "256GB"})
        self.assertEqual(intent.provenance[f"entities.{entity.key}.identifiers.brand"], Provenance.PROPOSED)

    def test_missing_model_number_is_not_fabricated(self):
        intent, _ = self.interpret()
        self.assertNotIn("model_number", intent.request.entities[0].identifiers)

    def test_interpretation_ambiguity_is_preserved(self):
        issue = {"code": "AMBIGUOUS_ENTITY", "target": "entity", "message": "The name has multiple interpretations.",
                 "candidates": ["Option A", "Option B"], "clarification_question": "Which entity do you mean?"}
        intent, _ = self.interpret(interpreted_payload(issues=[issue]))
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertEqual(intent.unresolved[0].code, "AMBIGUOUS_ENTITY")
        self.assertEqual(intent.unresolved[0].candidates, ["Option A", "Option B"])

    def test_ambiguous_attribute_is_preserved(self):
        issue = {"code": "AMBIGUOUS_ATTRIBUTE", "target": "attribute", "message": "The requested metric is unclear.",
                 "candidates": ["monthly price", "annual price"], "clarification_question": "Which billing period?"}
        intent, _ = self.interpret(interpreted_payload(issues=[issue]))
        self.assertIn("AMBIGUOUS_ATTRIBUTE", {item.code for item in intent.unresolved})

    def test_unknown_source_is_not_made_executable(self):
        intent, _ = self.interpret(interpreted_payload(sources=[{"key": "unknown_marketplace"}]))
        self.assertEqual(intent.request.source_preferences, [])
        self.assertIn("SOURCE_NOT_ALLOWED", {issue.code for issue in intent.unresolved})

    def test_malformed_provider_output_is_rejected_safely(self):
        intent, _ = self.interpret({"entities": []})
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertIn("INTERPRETATION_INVALID", {issue.code for issue in intent.unresolved})
        self.assertEqual(intent.request.entities, [])

    def test_provider_failure_returns_structured_intent(self):
        provider = FakeProvider(error=TimeoutError("private SDK details"))
        intent = interpret_comparison_request(REQUEST_TEXT, provider=provider)
        self.assertEqual(intent.state, ComparisonIntentState.NEEDS_CLARIFICATION)
        self.assertIn("INTERPRETATION_UNAVAILABLE", {issue.code for issue in intent.unresolved})
        self.assertNotIn("private SDK details", " ".join(issue.message for issue in intent.unresolved))

    def test_proposed_and_user_provided_provenance_are_distinguished(self):
        intent, _ = self.interpret()
        first = intent.request.entities[0]
        self.assertEqual(intent.provenance[f"entities.{first.key}.display_name"], Provenance.USER_PROVIDED)
        self.assertEqual(intent.provenance[f"entities.{first.key}.key"], Provenance.PROPOSED)
        self.assertEqual(intent.provenance[f"sources.{RELIANCE.key}.name"], Provenance.USER_PROVIDED)
        self.assertEqual(intent.provenance[f"sources.{RELIANCE.key}.url"], Provenance.PROPOSED)

    def test_provider_cannot_add_identifiers_not_present_in_entity_evidence(self):
        payload = interpreted_payload()
        payload["entities"][0]["identifiers"]["model_number"] = "ABC-999"
        intent, _ = self.interpret(payload)
        self.assertEqual(intent.request.entities, [])
        self.assertIn("INTERPRETATION_INVALID", {issue.code for issue in intent.unresolved})

    def test_no_adapter_network_or_observation_execution_occurs(self):
        intent, provider = self.interpret()
        self.assertEqual(len(provider.calls), 1)
        self.assertFalse(hasattr(intent, "observations"))

    def test_user_context_is_preserved_and_interpreted_context_is_proposed(self):
        payload = interpreted_payload(context={"market": "India"})
        intent, _ = self.interpret(payload, text=REQUEST_TEXT + " Compare in India.", context={"audience": "student"})
        self.assertEqual(intent.request.context, {"market": "India", "audience": "student"})
        self.assertEqual(intent.provenance["context.audience"], Provenance.USER_PROVIDED)
        self.assertEqual(intent.provenance["context.market"], Provenance.PROPOSED)

    def test_intent_contains_no_observations_or_analysis(self):
        intent, _ = self.interpret()
        self.assertFalse(hasattr(intent, "observations"))
        self.assertFalse(hasattr(intent, "analysis"))


if __name__ == "__main__":
    unittest.main()
