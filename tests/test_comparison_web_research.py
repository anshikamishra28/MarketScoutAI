import os
import tempfile
import unittest
from unittest.mock import patch

from database import store
from models.comparison import (
    AttributeDefinition,
    ComparisonRequest,
    EntityReference,
    SourceReference,
    SourceStatus,
)
from services.comparison_service import execute_comparison
from services.comparison_workflow import build_structured_comparison_intent
from tools.comparison_sources import WEB_RESEARCH_SOURCE, WebResearchComparisonAdapter


def _llm_result(raw_value, *, supported=True, value_type="structured"):
    return {
        "supported": supported,
        "raw_value": raw_value if supported else None,
        "normalized_value": {"invented": "ignored"},
        "value_type": value_type,
        "unit": None,
        "currency": None,
        "context": {},
        "reason": "fixture",
    }


class WebResearchComparisonAdapterTests(unittest.TestCase):
    def request(self, names=("Acme Cloud",), attributes=("Monthly cost",), category="software"):
        return ComparisonRequest(
            "Compare entities based on requested attributes.",
            entities=[EntityReference(name.casefold().replace(" ", "_"), name) for name in names],
            attributes=[AttributeDefinition(label.casefold().replace(" ", "_"), label, "structured") for label in attributes],
            context={"category": category},
            source_preferences=[WEB_RESEARCH_SOURCE],
        )

    def adapter(self, *, pages, results=None, search_error=None, extract=None):
        queries = []
        def search(query, max_results):
            queries.append(query)
            if search_error:
                raise search_error
            return (results or {}).get(query, [{"url": url, "title": "discovery only", "snippet": "₹999"} for url in pages])
        def fetch(url):
            value = pages[url]
            if isinstance(value, Exception):
                raise value
            return value
        adapter = WebResearchComparisonAdapter(search=search, fetch=fetch, extract=extract)
        return adapter, queries

    def test_source_contract_is_generic_and_stable(self):
        adapter = WebResearchComparisonAdapter(search=lambda *_args, **_kwargs: [], fetch=lambda _url: "")
        self.assertEqual(adapter.source, WEB_RESEARCH_SOURCE)
        self.assertEqual(adapter.source.key, "web_research")
        self.assertEqual(adapter.source.source_type, "web")
        self.assertTrue(adapter.default_when_unspecified)

    def test_fetched_price_evidence_creates_traceable_observation(self):
        url = "https://example.test/acme-cost"
        adapter, _ = self.adapter(pages={url: {"content": "Acme Cloud pricing\nMonthly cost: $12.50 per month", "final_url": url}})
        result = adapter.check(self.request(), WEB_RESEARCH_SOURCE)
        self.assertEqual(result.check.status, SourceStatus.CHECKED)
        self.assertEqual(len(result.observations), 1)
        observation = result.observations[0]
        self.assertEqual(observation.raw_value, "Monthly cost: $12.50 per month")
        self.assertEqual(observation.normalized_value, 12.5)
        self.assertEqual(observation.currency, "USD")
        self.assertEqual(observation.source_key, "web_research")
        self.assertEqual(observation.source_url, url)
        self.assertTrue(observation.observed_at)
        self.assertEqual(observation.context["evidence_quote"], observation.raw_value)

    def test_search_snippet_is_not_used_when_page_fetch_fails(self):
        url = "https://example.test/not-fetched"
        adapter, _ = self.adapter(pages={url: RuntimeError("connection refused")})
        result = adapter.check(self.request(), WEB_RESEARCH_SOURCE)
        self.assertEqual(result.observations, [])
        self.assertEqual(result.check.status, SourceStatus.FAILED)
        self.assertEqual(result.check.diagnostics["search_snippets_used_as_observations"], False)

    def test_fetch_failure_has_no_observation(self):
        url = "https://example.test/failure"
        adapter, _ = self.adapter(pages={url: RuntimeError("network timeout")})
        result = adapter.check(self.request(), WEB_RESEARCH_SOURCE)
        self.assertEqual(result.observations, [])
        self.assertEqual(result.check.status, SourceStatus.FAILED)

    def test_irrelevant_fetched_page_is_rejected(self):
        url = "https://example.test/unrelated"
        adapter, _ = self.adapter(pages={url: {"content": "Another Cloud monthly cost: $2/month", "final_url": url}})
        result = adapter.check(self.request(), WEB_RESEARCH_SOURCE)
        self.assertEqual(result.observations, [])
        self.assertEqual(result.check.status, SourceStatus.CHECKED)
        self.assertEqual(result.check.diagnostics["candidates"][0]["match"], "entity_name_not_in_page")

    def test_partial_result_keeps_success_and_missing_entity_unresolved(self):
        urls = {"a": "https://example.test/a", "b": "https://example.test/b"}
        results = {"Alpha monthly cost software": [{"url": urls["a"]}], "Beta monthly cost software": [{"url": urls["b"]}]}
        adapter, _ = self.adapter(
            pages={urls["a"]: {"content": "Alpha pricing\nMonthly cost: $10/month", "final_url": urls["a"]},
                   urls["b"]: {"content": "Beta Cloud has several plans but no listed cost", "final_url": urls["b"]}},
            results=results,
            extract=lambda entity, _category, _attribute, content: _llm_result(
                "Monthly cost is not stated" if "Monthly cost is not stated" in content else None,
                supported=False,
            ),
        )
        request = self.request(names=("Alpha", "Beta"))
        result = adapter.check(request, WEB_RESEARCH_SOURCE)
        self.assertEqual(result.check.status, SourceStatus.PARTIAL)
        self.assertEqual([item.entity_key for item in result.observations], ["alpha"])
        self.assertEqual(result.check.diagnostics["observed_pair_count"], 1)

    def test_empty_search_is_unavailable(self):
        adapter = WebResearchComparisonAdapter(search=lambda *_args, **_kwargs: [], fetch=lambda _url: "")
        result = adapter.check(self.request(), WEB_RESEARCH_SOURCE)
        self.assertEqual(result.check.status, SourceStatus.UNAVAILABLE)
        self.assertEqual(result.observations, [])

    def test_blocked_fetch_is_blocked_without_observations(self):
        url = "https://example.test/blocked"
        adapter, _ = self.adapter(pages={url: RuntimeError("403 Forbidden")})
        result = adapter.check(self.request(), WEB_RESEARCH_SOURCE)
        self.assertEqual(result.check.status, SourceStatus.BLOCKED)
        self.assertEqual(result.observations, [])

    def test_missing_attribute_remains_unverified_without_fake_values(self):
        url = "https://example.test/no-feature"
        adapter, _ = self.adapter(
            pages={url: {"content": "Acme Cloud official home page", "final_url": url}},
            extract=lambda *_args: _llm_result("invented feature", value_type="structured"),
        )
        result = adapter.check(self.request(attributes=("Free tier",)), WEB_RESEARCH_SOURCE)
        self.assertEqual(result.observations, [])
        self.assertEqual(result.check.diagnostics["candidates"][0]["extraction"], "extractor_quote_not_present_in_page")

    def test_arbitrary_domain_category_and_multiple_attributes_are_query_driven(self):
        url_cost, url_regions = "https://example.test/cost", "https://example.test/regions"
        results = {
            "Northstar Compute monthly cost cloud hosting": [{"url": url_cost}],
            "Northstar Compute supported regions cloud hosting": [{"url": url_regions}],
        }
        pages = {
            url_cost: {"content": "Northstar Compute pricing details", "final_url": url_cost},
            url_regions: {"content": "Northstar Compute operates in 14 regions", "final_url": url_regions},
        }
        def extract(_entity, _category, attribute, content):
            quote = "Northstar Compute operates in 14 regions" if "operates" in content else "Northstar Compute pricing details"
            return _llm_result(quote, value_type=attribute.value_type.value)
        adapter, queries = self.adapter(pages=pages, results=results, extract=extract)
        result = adapter.check(self.request(names=("Northstar Compute",), attributes=("Monthly cost", "Supported regions"), category="cloud hosting"), WEB_RESEARCH_SOURCE)
        self.assertIn("Northstar Compute", queries[0])
        self.assertIn("cloud hosting", queries[0])
        self.assertEqual({item.attribute_key for item in result.observations}, {"monthly_cost", "supported_regions"})
        self.assertEqual(result.check.status, SourceStatus.CHECKED)

    def test_llm_normalized_payload_cannot_replace_quoted_source_value(self):
        url = "https://example.test/quote"
        adapter, _ = self.adapter(
            pages={url: {"content": "Acme Cloud free tier includes limited compute", "final_url": url}},
            extract=lambda *_args: _llm_result("free tier includes limited compute"),
        )
        result = adapter.check(self.request(attributes=("Free tier",)), WEB_RESEARCH_SOURCE)
        self.assertEqual(len(result.observations), 1)
        self.assertEqual(result.observations[0].normalized_value, result.observations[0].raw_value)
        self.assertNotEqual(result.observations[0].normalized_value, {"invented": "ignored"})

    def test_system_source_is_added_and_display_names_are_sufficient_with_category(self):
        request = self.request(names=("Northstar Compute", "Southwind Cloud"))
        request.source_preferences = []
        intent = build_structured_comparison_intent(request, default_source=WEB_RESEARCH_SOURCE)
        self.assertEqual(intent.state.value, "ready")
        self.assertEqual([source.key for source in intent.request.source_preferences], ["web_research"])
        self.assertEqual(intent.provenance["sources.web_research.key"].value, "system_provided")
        self.assertFalse(intent.unresolved)

    def test_default_source_selection_does_not_select_nondefault_retailer_adapters(self):
        class NonDefaultAdapter:
            source = SourceReference("retailer_fixture", "Retailer fixture", "retailer")

            def supports(self, _request, _source):
                return True

            def check(self, _request, source):
                raise AssertionError("non-default source must not be selected implicitly")

        temp_dir = tempfile.TemporaryDirectory()
        try:
            with patch("database.store.DB_PATH", os.path.join(temp_dir.name, "default-source.sqlite3")):
                store.init_db()
                request = self.request()
                request.source_preferences = []
                web = WebResearchComparisonAdapter(search=lambda *_args, **_kwargs: [], fetch=lambda _url: "")
                result = execute_comparison(request, adapters=[web, NonDefaultAdapter()])
                self.assertEqual([check["source"]["key"] for check in result["source_checks"]], ["web_research"])
                self.assertEqual(result["source_checks"][0]["status"], "unavailable")
                self.assertEqual(result["observations"], [])
        finally:
            temp_dir.cleanup()

    def test_explicit_source_preferences_are_not_replaced_or_supplemented(self):
        chosen = SourceReference("chosen", "Chosen source", "official")
        request = self.request()
        request.source_preferences = [chosen]
        intent = build_structured_comparison_intent(request, default_source=WEB_RESEARCH_SOURCE)
        self.assertEqual([source.key for source in intent.request.source_preferences], ["chosen"])
        self.assertEqual(intent.provenance["sources.chosen.key"].value, "user_provided")

    def test_name_only_identity_still_requires_category_context(self):
        request = self.request(category="")
        request.source_preferences = []
        request.context = {}
        intent = build_structured_comparison_intent(request, default_source=WEB_RESEARCH_SOURCE)
        self.assertEqual(intent.state.value, "needs_clarification")
        self.assertIn("ENTITY_IDENTITY_UNRESOLVED", {issue.code for issue in intent.unresolved})

    def test_partial_observation_persists_and_analysis_marks_missing_pair_unresolved(self):
        temp_dir = tempfile.TemporaryDirectory()
        try:
            with patch("database.store.DB_PATH", os.path.join(temp_dir.name, "web-compare.sqlite3")):
                store.init_db()
                urls = {"alpha": "https://example.test/alpha", "beta": "https://example.test/beta"}
                results = {"Alpha Monthly cost software": [{"url": urls["alpha"]}], "Beta Monthly cost software": [{"url": urls["beta"]}]}
                adapter, _ = self.adapter(
                    pages={urls["alpha"]: {"content": "Alpha price\nMonthly cost: $8/month", "final_url": urls["alpha"]},
                           urls["beta"]: {"content": "Beta official plans; price not listed", "final_url": urls["beta"]}},
                    results=results,
                    extract=lambda *_args: _llm_result(None, supported=False),
                )
                request = self.request(names=("Alpha", "Beta"))
                result = execute_comparison(request, adapters=[adapter])
                self.assertEqual(result["status"], "completed")
                self.assertEqual(len(result["observations"]), 1)
                self.assertIn("Beta", " ".join(result["unresolved"]))
                self.assertEqual(result["analysis"]["attributes"][0]["status"], "unresolved")
        finally:
            temp_dir.cleanup()

    def test_workflow_api_automatically_executes_with_web_source_and_returns_result(self):
        temp_dir = tempfile.TemporaryDirectory()
        try:
            with patch("database.store.DB_PATH", os.path.join(temp_dir.name, "web-workflow.sqlite3")):
                store.init_db()
                import backend.main as main
                from fastapi.testclient import TestClient

                pages = {
                    "https://example.test/kitkat": {
                        "content": "Kit Kat chocolate\nPrice: ₹40", "final_url": "https://example.test/kitkat",
                    },
                    "https://example.test/dairymilk": {
                        "content": "Dairy Milk chocolate\nPrice: ₹45", "final_url": "https://example.test/dairymilk",
                    },
                }

                def search(query, max_results):
                    del max_results
                    return [{"url": "https://example.test/kitkat" if "Kit Kat" in query else "https://example.test/dairymilk",
                             "title": "search discovery only", "snippet": "not evidence"}]

                adapter = WebResearchComparisonAdapter(
                    search=search,
                    fetch=lambda url: pages[url],
                    extract=lambda *_args: _llm_result(None, supported=False),
                )
                with patch("backend.main._generic_comparison_adapters", return_value=(adapter,)):
                    client = TestClient(main.app)
                    response = client.post("/comparison-workflows", json={
                        "user_request": "Compare Kit Kat and Dairy Milk in the chocolate category by Price and Quality.",
                        "context": {"category": "chocolate"},
                        "source_preferences": [],
                        "entities": [
                            {"key": "kit_kat", "display_name": "Kit Kat", "identifiers": {}, "aliases": []},
                            {"key": "dairy_milk", "display_name": "Dairy Milk", "identifiers": {}, "aliases": []},
                        ],
                        "attributes": [
                            {"key": "price", "label": "Price", "value_type": "scalar", "currency": "INR"},
                            {"key": "quality", "label": "Quality", "value_type": "structured"},
                        ],
                    })
                    self.assertEqual(response.status_code, 202, response.text)
                    workflow = response.json()
                    self.assertEqual(workflow["intent"]["state"], "ready")
                    self.assertEqual(workflow["intent"]["provenance"]["sources.web_research.key"], "system_provided")
                    self.assertIsNotNone(workflow["comparison_id"])
                    result_response = client.get(f"/comparisons/{workflow['comparison_id']}")
                    self.assertEqual(result_response.status_code, 200, result_response.text)
                    result = result_response.json()
                    self.assertEqual(result["status"], "completed")
                    self.assertEqual([entity["display_name"] for entity in result["entities"]], ["Kit Kat", "Dairy Milk"])
                    self.assertEqual([item["key"] for item in result["attributes"]], ["price", "quality"])
                    self.assertEqual(result["source_checks"][0]["source"]["key"], "web_research")
                    self.assertEqual(result["source_checks"][0]["status"], "partial")
                    self.assertEqual(len(result["observations"]), 2)
                    self.assertEqual({item["normalized_value"] for item in result["observations"]}, {40, 45})
                    self.assertTrue(all(item["source_url"].startswith("https://example.test/") for item in result["observations"]))
                    self.assertEqual(result["analysis"]["attributes"][1]["status"], "unresolved")
                    self.assertEqual(len(result["unresolved"]), 2)
        finally:
            temp_dir.cleanup()

    def test_unrelated_attribute_text_like_connectivity_speed_is_rejected(self):
        url = "https://example.test/specs"
        adapter, _ = self.adapter(pages={
            url: {"content": "Model Pro connectivity details\nTwo, 10Gbps USB-C ports with Thunderbolt support.", "final_url": url}
        })
        request = ComparisonRequest(
            "Compare Model Pro by price.",
            entities=[EntityReference("model_pro", "Model Pro")],
            attributes=[AttributeDefinition("price", "Price", "scalar")],
        )
        result = adapter.check(request, WEB_RESEARCH_SOURCE)
        self.assertEqual(result.observations, [])
        self.assertEqual(result.check.status, SourceStatus.CHECKED)

    def test_wrong_entity_evidence_on_shared_page_is_rejected(self):
        url = "https://example.test/comparison"
        content = "Shared review: Alpha Widget is priced at $99. Beta Widget pricing is completely unannounced."
        adapter, _ = self.adapter(
            pages={url: {"content": content, "final_url": url}},
            results={
                "Alpha Widget Price gadgets": [{"url": url}],
                "Beta Widget Price gadgets": [{"url": url}],
            },
        )
        request = ComparisonRequest(
            "Compare Alpha Widget and Beta Widget by price.",
            entities=[EntityReference("alpha", "Alpha Widget"), EntityReference("beta", "Beta Widget")],
            attributes=[AttributeDefinition("price", "Price", "scalar")],
            context={"category": "gadgets"},
        )
        result = adapter.check(request, WEB_RESEARCH_SOURCE)
        beta_obs = [obs for obs in result.observations if obs.entity_key == "beta"]
        self.assertEqual(beta_obs, [])

    def test_non_numeric_price_article_excerpt_is_rejected(self):
        url = "https://example.test/market-news"
        content = "Product X market report: Management commented on rising cocoa and logistics costs without giving an MSRP."
        adapter, _ = self.adapter(
            pages={url: {"content": content, "final_url": url}},
            extract=lambda *_args: _llm_result("rising cocoa and logistics costs", value_type="scalar"),
        )
        request = ComparisonRequest(
            "Check price for Product X.",
            entities=[EntityReference("prod_x", "Product X")],
            attributes=[AttributeDefinition("price", "Price", "scalar")],
        )
        result = adapter.check(request, WEB_RESEARCH_SOURCE)
        self.assertEqual(result.observations, [])

    def test_valid_explicitly_supported_numeric_price_extracted_with_concise_raw(self):
        url = "https://example.test/item-offer"
        long_sentence = "The current retail price for Item One has been established at $24.99 across all official retail outlets nationwide."
        adapter, _ = self.adapter(pages={
            url: {"content": f"Item One Store\n{long_sentence}", "final_url": url}
        })
        request = ComparisonRequest(
            "Check price for Item One.",
            entities=[EntityReference("item_one", "Item One")],
            attributes=[AttributeDefinition("price", "Price", "scalar")],
        )
        result = adapter.check(request, WEB_RESEARCH_SOURCE)
        self.assertEqual(len(result.observations), 1)
        obs = result.observations[0]
        self.assertEqual(obs.raw_value, "$24.99")
        self.assertEqual(obs.normalized_value, 24.99)
        self.assertEqual(obs.currency, "USD")
        self.assertEqual(obs.context["evidence_quote"], long_sentence)

    def test_unsupported_quality_general_nutrition_text_is_rejected(self):
        url = "https://example.test/health-facts"
        content = "NutriBar health guide: Milk has 18 of 22 essential nutrients including calcium and vitamin D."
        adapter, _ = self.adapter(
            pages={url: {"content": content, "final_url": url}},
            extract=lambda *_args: _llm_result("18 of 22 essential nutrients including calcium", value_type="structured"),
        )
        request = ComparisonRequest(
            "Compare NutriBar quality.",
            entities=[EntityReference("nutri_bar", "NutriBar")],
            attributes=[AttributeDefinition("quality", "Quality", "structured")],
        )
        result = adapter.check(request, WEB_RESEARCH_SOURCE)
        self.assertEqual(result.observations, [])

    def test_unsupported_availability_marketing_copy_is_rejected(self):
        url = "https://example.test/news"
        content = "TechDevice 2026 models are now available in India: Price, specs and buyer guide."
        adapter, _ = self.adapter(pages={
            url: {"content": content, "final_url": url}
        })
        request = ComparisonRequest(
            "Compare TechDevice availability.",
            entities=[EntityReference("tech_dev", "TechDevice")],
            attributes=[AttributeDefinition("availability", "Availability", "categorical")],
        )
        result = adapter.check(request, WEB_RESEARCH_SOURCE)
        self.assertEqual(result.observations, [])

    def test_commercial_stock_status_is_accepted_as_availability(self):
        url = "https://example.test/product-stock"
        content = "Gizmo Pro Official Store\nStock: In Stock"
        adapter, _ = self.adapter(pages={
            url: {"content": content, "final_url": url}
        })
        request = ComparisonRequest(
            "Compare Gizmo Pro availability.",
            entities=[EntityReference("gizmo_pro", "Gizmo Pro")],
            attributes=[AttributeDefinition("availability", "Availability", "categorical")],
        )
        result = adapter.check(request, WEB_RESEARCH_SOURCE)
        self.assertEqual(len(result.observations), 1)
        obs = result.observations[0]
        self.assertEqual(obs.raw_value, "In Stock")
        self.assertEqual(obs.normalized_value, "in_stock")

    def test_verification_counts_agree_with_accepted_observations(self):
        temp_dir = tempfile.TemporaryDirectory()
        try:
            with patch("database.store.DB_PATH", os.path.join(temp_dir.name, "counts-sync.sqlite3")):
                store.init_db()
                url_alpha = "https://example.test/alpha"
                url_beta = "https://example.test/beta"
                pages = {
                    url_alpha: {"content": "Alpha Device\nPrice: $100\nStock: In Stock", "final_url": url_alpha},
                    url_beta: {"content": "Beta Device connectivity: Two 10Gbps ports.\nModels are now available in stores: specs and more.", "final_url": url_beta},
                }
                adapter = WebResearchComparisonAdapter(
                    search=lambda query, max_results: [{"url": url_alpha if "Alpha" in query else url_beta}],
                    fetch=lambda url: pages[url],
                )
                request = ComparisonRequest(
                    "Compare Alpha and Beta Devices by price and availability.",
                    entities=[EntityReference("alpha", "Alpha Device"), EntityReference("beta", "Beta Device")],
                    attributes=[
                        AttributeDefinition("price", "Price", "scalar"),
                        AttributeDefinition("availability", "Availability", "categorical"),
                    ],
                )
                result = execute_comparison(request, adapters=[adapter])
                # Only Alpha has verified price and availability; Beta's connectivity and marketing text were rejected
                self.assertEqual(len(result["observations"]), 2)
                self.assertTrue(all(obs["entity_key"] == "alpha" for obs in result["observations"]))
                price_analysis = result["analysis"]["attributes"][0]
                avail_analysis = result["analysis"]["attributes"][1]
                # In analysis, Alpha is observed, Beta is unresolved
                alpha_price = next(e for e in price_analysis["entities"] if e["entity_key"] == "alpha")
                beta_price = next(e for e in price_analysis["entities"] if e["entity_key"] == "beta")
                self.assertEqual(alpha_price["status"], "observed")
                self.assertEqual(beta_price["status"], "unresolved")
                self.assertIn("Beta Device — Price", result["analysis"]["unresolved_information"])
                self.assertIn("Beta Device — Availability", result["analysis"]["unresolved_information"])
        finally:
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
