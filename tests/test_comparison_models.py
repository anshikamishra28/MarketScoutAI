import json
import unittest
from decimal import Decimal

from models.comparison import (
    AttributeDefinition,
    ComparisonRequest,
    ComparisonResult,
    ComparisonStatus,
    EntityReference,
    Observation,
    SourceCheck,
    SourceReference,
    SourceStatus,
    ValueType,
)


class GenericComparisonModelTests(unittest.TestCase):
    def test_request_with_entities_attributes_context_and_sources(self):
        request = ComparisonRequest(
            user_request="Compare streaming plans by monthly price, content library, and screens.",
            entities=[EntityReference("netflix", "Netflix", "streaming_service")],
            attributes=[AttributeDefinition("monthly_price", "Monthly price", "scalar", "month", "INR")],
            context={"region": "IN"},
            source_preferences=[SourceReference("provider_site", "Provider websites", "official")],
        )
        self.assertEqual(request.entities[0].key, "netflix")
        self.assertEqual(request.attributes[0].currency, "INR")
        self.assertEqual(request.to_dict()["user_request"], request.user_request)

    def test_request_allows_entities_and_attributes_to_be_resolved_later(self):
        request = ComparisonRequest("Compare cloud providers for a small startup.")
        self.assertEqual(request.entities, [])
        self.assertEqual(request.attributes, [])
        self.assertIsNone(request.context)

    def test_entity_type_is_optional(self):
        entity = EntityReference("aws", "AWS")
        self.assertIsNone(entity.entity_type)

    def test_entity_accepts_generic_identifiers_and_aliases(self):
        entity = EntityReference(
            "aws", "AWS", identifiers={"website": "https://aws.amazon.com", "provider_code": "aws"},
            aliases=["Amazon Web Services"],
        )
        self.assertEqual(entity.identifiers["provider_code"], "aws")
        self.assertEqual(entity.aliases, ["Amazon Web Services"])

    def test_scalar_attribute_definition(self):
        attribute = AttributeDefinition("compute_cost", "Compute cost", ValueType.SCALAR, "hour", "USD", "lower_is_better")
        self.assertEqual(attribute.value_type, ValueType.SCALAR)
        self.assertEqual(attribute.to_dict()["comparison_rule"], "lower_is_better")

    def test_categorical_boolean_and_structured_attribute_definitions(self):
        self.assertEqual(AttributeDefinition("plan_name", "Plan", "categorical").value_type, ValueType.CATEGORICAL)
        self.assertEqual(AttributeDefinition("free_tier", "Free tier", "boolean").value_type, ValueType.BOOLEAN)
        self.assertEqual(AttributeDefinition("regions", "Supported regions", "structured").value_type, ValueType.STRUCTURED)
        self.assertEqual(AttributeDefinition("price_band", "Price band", "range").value_type, ValueType.RANGE)

    def test_observation_preserves_raw_and_normalized_values(self):
        observation = Observation(
            "netflix", "monthly_price", "provider_site", "₹649/month", Decimal("649"),
            value_type="scalar", unit="month", currency="INR", source_url="https://example.com/plans",
        )
        data = observation.to_dict()
        self.assertEqual(data["raw_value"], "₹649/month")
        self.assertEqual(data["normalized_value"], "649")

    def test_observation_accepts_currency_unit_and_timezone_timestamp(self):
        observation = Observation(
            "aws", "compute_cost", "official_site", "$0.0116 per hour", 0.0116,
            value_type="scalar", unit="hour", currency="usd", observed_at="2026-10-01T10:00:00+05:30",
        )
        self.assertEqual(observation.currency, "USD")
        self.assertEqual(observation.observed_at, "2026-10-01T04:30:00+00:00")

    def test_observation_accepts_categorical_and_structured_values(self):
        categorical = Observation("plan", "availability", "provider", "Available", "available", value_type="categorical")
        structured = Observation(
            "cloud", "supported_regions", "official", ["ap-south-1", "eu-west-1"],
            {"count": 2, "regions": ["ap-south-1", "eu-west-1"]}, value_type="structured",
            context={"as_of": "2026-Q4"},
        )
        self.assertEqual(categorical.normalized_value, "available")
        self.assertEqual(structured.raw_value[0], "ap-south-1")
        self.assertEqual(structured.to_dict()["normalized_value"]["count"], 2)

    def test_source_check_statuses_are_explicit_and_generic(self):
        source = SourceReference("public_site", "Public site", "website", "https://example.com")
        for status in ("pending", "checked", "partial", "unavailable", "blocked", "failed", "unsupported"):
            with self.subTest(status=status):
                check = SourceCheck(source, status)
                self.assertEqual(check.status.value, status)
        self.assertEqual(SourceCheck(source).status, SourceStatus.PENDING)

    def test_comparison_result_serializes_generic_sources_and_observations(self):
        request = ComparisonRequest("Compare Netflix and Prime by monthly price.")
        result = ComparisonResult(
            "cmp-generic-1", ComparisonStatus.COMPLETED, request,
            entities=[EntityReference("netflix", "Netflix"), EntityReference("prime", "Amazon Prime Video")],
            attributes=[AttributeDefinition("monthly_price", "Monthly price", "scalar", "month", "INR")],
            source_checks=[SourceCheck(SourceReference("netflix_site", "Netflix plans"), "checked")],
            observations=[Observation("netflix", "monthly_price", "netflix_site", "₹649/month", Decimal("649"),
                                      "scalar", "month", "INR", source_url="https://example.com/netflix")],
            unresolved=["content_library"], errors=[],
        )
        data = result.to_dict()
        self.assertEqual(data["status"], "completed")
        self.assertEqual(data["observations"][0]["raw_value"], "₹649/month")
        self.assertEqual(data["observations"][0]["normalized_value"], "649")
        self.assertEqual(data["source_checks"][0]["status"], "checked")
        self.assertIn('"entity_type": null', json.dumps(data))

    def test_one_request_can_contain_entities_from_different_domains(self):
        request = ComparisonRequest(
            "Compare these entities.",
            entities=[
                EntityReference("netflix", "Netflix"),
                EntityReference("aws", "AWS"),
                EntityReference("nord6", "OnePlus Nord 6"),
            ],
        )
        self.assertEqual([entity.display_name for entity in request.entities], ["Netflix", "AWS", "OnePlus Nord 6"])
        self.assertFalse(hasattr(request.entities[0], "brand"))
        self.assertFalse(hasattr(request.entities[2], "ram"))

    def test_request_rejects_empty_user_request(self):
        for text in ("", "   ", None):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "user_request"):
                ComparisonRequest(text)


if __name__ == "__main__":
    unittest.main()
