import unittest
from unittest.mock import patch

from models.comparison import (
    AttributeDefinition,
    ComparisonRequest,
    ComparisonResult,
    EntityReference,
    Observation,
)
from services.comparison_analysis import analyze_comparison


class ComparisonAnalysisTests(unittest.TestCase):
    def make_result(self, *, rule=None, observations=None, value_type="scalar"):
        request = ComparisonRequest(
            "Compare entities by a generic attribute.",
            entities=[EntityReference("a", "Entity A"), EntityReference("b", "Entity B")],
            attributes=[AttributeDefinition("metric", "Metric", value_type, comparison_rule=rule)],
        )
        return ComparisonResult(
            "analysis-test", "completed", request,
            entities=request.entities,
            attributes=request.attributes,
            observations=observations or [],
            unresolved=["b — Metric"] if not observations else [],
        )

    @staticmethod
    def observation(entity, value, *, source="source-a", normalized=None, value_type="scalar", url=None):
        return Observation(
            entity, "metric", source, str(value), value if normalized is None else normalized,
            value_type=value_type, source_url=url or f"https://example.com/{source}",
            observed_at="2026-10-01T10:00:00Z",
        )

    def test_two_entities_with_complete_scalar_values_are_reported_without_default_ranking(self):
        result = analyze_comparison(self.make_result(observations=[
            self.observation("a", 10, url="https://example.com/a"),
            self.observation("b", 20, source="source-b"),
        ]))
        attribute = result["attributes"][0]
        self.assertEqual(attribute["status"], "complete")
        self.assertEqual([item["comparable_value"] for item in attribute["entities"]], [10, 20])
        self.assertEqual(attribute["ranking"], [])
        self.assertIsNone(attribute["winner_entity_key"])

    def test_missing_entity_observation_is_unresolved_and_never_ranked(self):
        result = analyze_comparison(self.make_result(rule="lower_is_better", observations=[self.observation("a", 10)]))
        attribute = result["attributes"][0]
        self.assertEqual(attribute["status"], "unresolved")
        self.assertEqual(attribute["entities"][1]["status"], "unresolved")
        self.assertEqual(attribute["ranking"], [])
        self.assertIsNone(attribute["winner_entity_key"])

    def test_no_observations_produce_unresolved_entries_for_every_entity(self):
        attribute = analyze_comparison(self.make_result())["attributes"][0]
        self.assertEqual(attribute["status"], "unresolved")
        self.assertTrue(all(item["status"] == "unresolved" for item in attribute["entities"]))

    def test_multiple_observations_for_same_entity_are_preserved_and_conflicts_not_collapsed(self):
        result = analyze_comparison(self.make_result(rule="lower_is_better", observations=[
            self.observation("a", 10, source="source-a"),
            self.observation("a", 11, source="source-b"),
            self.observation("b", 20),
        ]))
        attribute = result["attributes"][0]
        self.assertEqual(attribute["entities"][0]["status"], "conflicting")
        self.assertEqual(len(attribute["entities"][0]["observations"]), 2)
        self.assertEqual(attribute["status"], "unresolved")
        self.assertEqual(attribute["ranking"], [])

    def test_lower_is_better_rule_ranks_only_complete_numeric_scalar_values(self):
        result = analyze_comparison(self.make_result(rule="lower_is_better", observations=[
            self.observation("a", 12), self.observation("b", 7),
        ]))
        attribute = result["attributes"][0]
        self.assertEqual([row["entity_key"] for row in attribute["ranking"]], ["b", "a"])
        self.assertEqual(attribute["winner_entity_key"], "b")

    def test_higher_is_better_rule_ranks_complete_numeric_values(self):
        result = analyze_comparison(self.make_result(rule="higher_is_better", observations=[
            self.observation("a", 12), self.observation("b", 7),
        ]))
        attribute = result["attributes"][0]
        self.assertEqual([row["entity_key"] for row in attribute["ranking"]], ["a", "b"])
        self.assertEqual(attribute["winner_entity_key"], "a")

    def test_no_rule_reports_values_without_ranking(self):
        attribute = analyze_comparison(self.make_result(observations=[
            self.observation("a", 12), self.observation("b", 7),
        ]))["attributes"][0]
        self.assertEqual(attribute["ranking"], [])
        self.assertIsNone(attribute["winner_entity_key"])
        self.assertIn("No comparison_rule", attribute["limitations"][0])

    def test_invalid_and_non_numeric_values_are_not_ranked(self):
        result = self.make_result(rule="lower_is_better", observations=[
            self.observation("a", "not numeric", normalized="not numeric"),
            self.observation("b", 7),
        ])
        attribute = analyze_comparison(result)["attributes"][0]
        self.assertEqual(attribute["status"], "unresolved")
        self.assertEqual(attribute["ranking"], [])

    def test_source_and_observation_traceability_are_preserved(self):
        observation = self.observation("a", 10, source="official", url="https://example.com/facts")
        analysis = analyze_comparison(self.make_result(observations=[observation]))
        saved = analysis["attributes"][0]["entities"][0]["observations"][0]
        self.assertEqual(saved["source_key"], "official")
        self.assertEqual(saved["source_url"], "https://example.com/facts")
        self.assertEqual(saved["raw_value"], "10")
        self.assertEqual(saved["normalized_value"], 10)

    def test_analysis_does_not_access_the_network(self):
        result = self.make_result(observations=[self.observation("a", 1)])
        with patch("requests.get", side_effect=AssertionError("network access is forbidden")):
            analysis = analyze_comparison(result)
        self.assertEqual(analysis["comparison_id"], "analysis-test")

    def test_structured_analysis_is_json_safe_and_result_accepts_existing_text(self):
        result = self.make_result(observations=[self.observation("a", 1)])
        analysis = analyze_comparison(result)
        enriched = ComparisonResult(
            result.comparison_id, result.status, result.request,
            entities=result.entities, attributes=result.attributes, observations=result.observations,
            analysis=analysis,
        )
        self.assertEqual(enriched.to_dict()["analysis"], analysis)
        legacy = ComparisonResult("old", "completed", ComparisonRequest("Old result"), analysis="Summary")
        self.assertEqual(legacy.to_dict()["analysis"], "Summary")


if __name__ == "__main__":
    unittest.main()
