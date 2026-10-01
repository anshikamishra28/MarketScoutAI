import os
import json
import re
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

from agents.research_executor import MAX_ITERATIONS, MAX_SOURCES, _BAND_METRIC, _CONCRETE_FACT, _evaluate_coverage, _evidence_candidates, _extract_evidence, _is_india_specific, _missing_information, _report, _requirement_kind, _requirement_supported, _select_diverse_evidence, execute_research, generate_followup_queries
from models.evidence import classify_evidence_scope, classify_source, detect_conflicts, evaluate_evidence, geographic_relevance, score_evidence_quality, segment_relevance
from services.llm_service import parse_json_response
from tools.content_extractor import extract_content
from tools.web_fetcher import fetch_page
from tools.web_search import search_web
from agents.research_planner import create_research_plan
from services.llm_service import generate_response


class ResearchUnitTests(unittest.TestCase):
    def test_structured_json_parsing(self):
        self.assertEqual(parse_json_response('```json\n{"ok": true}\n```'), {"ok": True})
        with self.assertRaises(ValueError): parse_json_response("not json")
        with self.assertRaises(ValueError): parse_json_response("")

    def test_planner_validates_and_falls_back_on_bad_model_json(self):
        plan = {"research_goal": "x", "sub_questions": ["a", "b", "c"], "information_needed": ["pricing"], "search_queries": ["market pricing"]}
        with patch("agents.research_planner.generate_response", return_value='{"research_goal":"x","sub_questions":["a"],"information_needed":["pricing"],"search_queries":["market pricing"]}'):
            self.assertEqual(create_research_plan("Research this market")["search_queries"], ["market pricing"])
        with patch("agents.research_planner.generate_response", return_value="{oops"):
            self.assertGreaterEqual(len(create_research_plan("Research this market")["search_queries"]), 3)

    def test_india_under_30k_plan_always_has_all_seven_required_dimensions(self):
        plan = {
            "research_goal": "India smartphones under 30000", "sub_questions": ["Market"],
            "information_needed": [
                "Market share data for smartphone brands in the Rs 20000 to Rs 30000 price bracket in India",
                "Analyst reports on macroeconomic factors influencing mid-range smartphone purchases in India",
                "Consumer survey insights regarding must-have features in mid-range smartphones",
                "Pricing strategies and promotional tactics of leading players",
                "Sales volume and revenue growth statistics for the sub-Rs 30000 category",
                "Analyst reports on upcoming technology adoption trends in the Indian mid-tier mobile market",
                "Analyst reports on online vs offline channel distribution for mobile phones in India",
            ],
            "search_queries": ["India smartphone under 30000 market"],
        }
        with patch("agents.research_planner.generate_response", return_value=json.dumps(plan)):
            requirements = create_research_plan("Analyze the Indian smartphone market under \u20b930000.")["information_needed"]
        self.assertTrue(any(("brand share" in r.lower() or "market share" in r.lower()) and re.search(r"20\s*,?\s*000", r) and re.search(r"30\s*,?\s*000", r) for r in requirements))
        self.assertTrue(any("survey" in r.lower() and "consumer" in r.lower() for r in requirements))
        self.assertTrue(any("current smartphone model pricing under" in r.lower() for r in requirements))
        self.assertTrue(any("promotional offers within" in r.lower() for r in requirements))
        self.assertTrue(any("sales volume and revenue growth" in r.lower() for r in requirements))
        self.assertTrue(any("technology adoption trends" in r.lower() for r in requirements))
        self.assertTrue(any("online vs. offline distribution" in r.lower() and ("under" in r.lower() or "sub-" in r.lower()) for r in requirements))
        self.assertFalse(any("Analyst reports on online vs offline channel distribution" == r for r in requirements))
        self.assertTrue(any(r.startswith("MACRO / CONTEXT:") and "macroeconomic" in r.lower() for r in requirements))

    def test_gemini_request_disables_unused_function_calling(self):
        class Models:
            def generate_content(self, **kwargs):
                self.kwargs = kwargs
                return type("Response", (), {"text": "ready"})()
        class Client:
            models = Models()
        client = Client()
        with patch("services.llm_service._client", return_value=client):
            self.assertEqual(generate_response("Say ready"), "ready")
        self.assertTrue(client.models.kwargs["config"].automatic_function_calling.disable)

    def test_evaluation_rejects_homepages_and_empty_pages(self):
        self.assertFalse(evaluate_evidence({"url": "https://example.com", "content": "A" * 200, "content_scope": "publisher_homepage"})["usable"])
        self.assertFalse(evaluate_evidence({"url": "https://example.com/article", "content": "", "content_scope": "source_page"})["usable"])
        self.assertTrue(evaluate_evidence({"url": "https://reuters.com/article", "content": "Market " + "evidence " * 30, "content_scope": "source_page"})["usable"])
        failed = {"id": "s-failed", "url": "https://reuters.com/article", "content": "", "content_scope": "search_result", "evaluation": evaluate_evidence({"url": "https://reuters.com/article", "content": "", "content_scope": "search_result"})}
        self.assertFalse(failed["evaluation"]["usable"])
        self.assertEqual(_extract_evidence(failed, "r1"), [])

    def test_conflict_detector_flags_different_numbers(self):
        rows = [{"id": "1", "claim": "market share grew 20% in India"}, {"id": "2", "claim": "market share grew 30% in India"}]
        self.assertEqual(len(detect_conflicts(rows)), 1)

    def test_html_extraction_prefers_clean_article_and_removes_page_noise(self):
        html = """<html><body>
        <header><nav><a>Home</a><a>Markets</a><a>Latest news</a></nav></header>
        <main><article class="article-body"><header><h1>India smartphone market report</h1></header>
        <p>The Indian smartphone market grew 12% to 40 million units in 2025.</p>
        <h2>Pricing and products</h2><p>Samsung launched the Galaxy A56 in March 2025 at ₹41,999.</p>
        <p>Subscribe to our newsletter for daily updates.</p>
        <div class="related-news"><p>Latest news: fuel prices increased across the country.</p></div>
        <aside class="sidebar"><p>Sensex and Nifty ended lower after trading.</p></aside>
        <p>The Indian smartphone market grew 12% to 40 million units in 2025.</p>
        </article><div class="stock-market-widget">Nifty market ticker</div></main>
        <footer>About us Contact privacy policy</footer></body></html>"""
        result = extract_content(html)
        self.assertIn("India smartphone market report", result)
        self.assertIn("40 million units in 2025", result)
        self.assertIn("₹41,999", result)
        self.assertNotIn("Home", result)
        self.assertNotIn("Subscribe", result)
        self.assertNotIn("fuel prices", result)
        self.assertNotIn("Sensex", result)
        self.assertNotIn("About us", result)
        self.assertEqual(result.count("grew 12%"), 1)

    def test_html_extraction_handles_malformed_and_empty_pages(self):
        self.assertIn("Readable text", extract_content("<html><body><article><p>Readable text</body>"))
        self.assertEqual(extract_content("<script>hidden()</script><nav>menu</nav>"), "")

    def test_failed_fetch_is_reported(self):
        with patch("tools.web_fetcher.resolve_url", side_effect=RuntimeError("offline")):
            with self.assertRaises(RuntimeError): fetch_page("https://example.invalid/page")

    def test_google_news_wrapper_redirects_to_decoded_article_content(self):
        class Response:
            url = "https://www.reuters.com/world/india/smartphone-report"
            headers = {"content-type": "text/html; charset=utf-8"}
            text = "<article><h1>India smartphone report</h1><p>The smartphone market grew 12% in 2025.</p></article>"
            apparent_encoding = "utf-8"
            def raise_for_status(self): pass
        with patch("tools.web_fetcher.resolve_url", return_value=Response.url), patch("tools.web_fetcher.requests.get", return_value=Response()):
            from tools.web_fetcher import fetch_document
            result = fetch_document("https://news.google.com/rss/articles/example")
        self.assertEqual(result["final_url"], Response.url)
        self.assertIn("grew 12%", result["content"])

    def test_fetch_http_error_is_reported(self):
        import requests
        with patch("tools.web_fetcher.resolve_url", return_value="https://example.com/page"), patch("tools.web_fetcher.requests.get", side_effect=requests.Timeout("timeout")):
            with self.assertRaisesRegex(RuntimeError, "Failed to fetch"):
                fetch_page("https://example.com/page")

    def test_search_empty_result_fallback(self):
        with patch.dict(os.environ, {"SEARX_URL": ""}), patch("tools.web_search.search_direct", return_value=[]), patch("tools.web_search._search_bing", return_value=[]), patch("tools.web_search.requests.get") as get:
            get.return_value.content = b"<rss><channel></channel></rss>"
            get.return_value.raise_for_status.return_value = None
            self.assertEqual(search_web("no results"), [])

    def test_search_prefers_direct_bing_article_urls(self):
        html = '<ol><li class="b_algo"><h2><a href="https://reuters.com/markets/article">Market article</a></h2><div class="b_caption"><p>Current market information</p></div></li></ol>'
        with patch.dict(os.environ, {"SEARX_URL": ""}), patch("tools.web_search.requests.get") as get, patch("tools.web_search.search_direct") as google:
            get.return_value.text = html
            get.return_value.raise_for_status.return_value = None
            result = search_web("market research", max_results=3)
        self.assertEqual(result[0]["url"], "https://reuters.com/markets/article")
        google.assert_not_called()

    def test_evidence_extraction_is_verbatim_and_scope_checked(self):
        content = """India smartphone market share and pricing
The Indian smartphone market grew 12% to 40 million units in 2025, according to the industry tracker.
Samsung launched a new smartphone in India in March 2025, with the Galaxy model priced at ₹41,999.
The smartphone market in India includes many companies and consumers today.
Subscribe for daily news about India's markets and consumer products.
Sensex and Nifty market values fell 2% during trading in India."""
        source = {"id": "s1", "title": "India smartphone market share and pricing", "url": "https://example.com/a", "content": content, "search_query": "Indian smartphone market under 30000", "research_question": "Analyze the Indian smartphone market under 30000", "content_scope": "source_page", "evaluation": {"usable": True, "relevance": .8, "confidence": .7}, "source_type": "major_publication"}
        result = _extract_evidence(source, "r1")
        claims = [item["claim"] for item in result]
        # The article also contains a Rs 41,999 phone claim, outside this study's target ceiling.
        self.assertEqual(len(claims), 1)
        self.assertTrue(all(claim in content for claim in claims))
        self.assertTrue(all(item["evidence_text"] == item["claim"] for item in result))
        self.assertIn("12% to 40 million units", claims[0])
        self.assertNotIn("Subscribe", " ".join(claims))
        self.assertNotIn("Sensex", " ".join(claims))
        self.assertTrue(all(item["source_id"] == "s1" and item["search_query"] == source["search_query"] for item in result))
        for field in ("source_title", "source_url", "publisher", "published_at", "source_type", "content_scope", "relevance", "confidence"):
            self.assertIn(field, result[0])
        source["content_scope"] = "search_result"
        self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_noisy_or_nonfactual_text_is_not_selected_as_evidence(self):
        source = {"id": "s1", "title": "Indian smartphone market report", "content": "Subscribe now. Latest news and trending stories. The smartphone market in India includes many companies and consumers today. The Indian smartphone market remains popular with several choices in 2026.", "search_query": "Indian smartphone market", "research_question": "Indian smartphone market", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
        self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_editorial_opinion_and_article_descriptions_are_rejected(self):
        editorial = [
            "The mobile phone brands in India worth your rupees in 2026 come down to what you value.",
            "This 2026 ranking breaks down the ten brands that matter most to Indian shoppers.",
            "This article discusses the smartphone market in India and what readers should know.",
            "We recommend this smartphone because it is the best choice for Indian consumers.",
        ]
        for sentence in editorial:
            source = {"id": "s1", "title": "India smartphone market ranking", "content": sentence, "search_query": "Indian smartphone market", "research_question": "Analyze the Indian smartphone market", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(sentence=sentence): self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_ranking_methodology_introductions_and_questions_are_rejected(self):
        examples = [
            "Choosing among the best mobile phone brands in India in 2026 is no small task in the world's second-largest smartphone market.",
            "We weighed market share and shipments in India, value in rupees, after-sales and service reach online and offline, software support, camera and battery performance, and resale value.",
            "Six pillars shaped the list: market share and shipments in India; value in rupees against rivals; after-sales reach, online and offline; software support and update length.",
            "Which price range is expected to remain most preferred in the mobile phone accessories market?",
        ]
        for sentence in examples:
            source = {"id": "s1", "title": "India smartphone brands ranking", "content": sentence, "search_query": "India smartphone market brands", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(sentence=sentence): self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_claim_date_overrides_recent_publication_for_current_market(self):
        published = "2026-06-15"
        old = "By the fourth quarter of 2017, Xiaomi became the leading smartphone brand in India by shipments."
        current = "India smartphone shipments declined 10% year-on-year in the second quarter of 2026, according to the tracker."
        common = {"source_title": "India smartphone shipment report", "source_type": "major_publication", "published_at": published, "relevance": .9}
        old_score = score_evidence_quality({**common, "evidence_text": old}, "Analyze the Indian smartphone market", old)
        current_score = score_evidence_quality({**common, "evidence_text": current}, "Analyze the Indian smartphone market", current)
        self.assertLess(old_score["recency_score"], current_score["recency_score"])
        self.assertLess(old_score["quality_score"], current_score["quality_score"])

    def test_category_and_target_price_band_relevance_affect_evidence(self):
        question = "Analyze the Indian smartphone market under Rs 30000"
        accessory = "India is projected to record the fastest mobile phone accessories market growth at 8.2% CAGR through 2036."
        accessory_source = {"id": "a", "title": "India Mobile Phone Accessories Market Forecast", "content": accessory, "search_query": "India smartphone market", "research_question": question, "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
        self.assertEqual(_extract_evidence(accessory_source, "r1"), [])
        narrow_title = "Best camera phones under Rs 50000"
        narrow_claim = "The smartphone in this price range features a 50 megapixel camera and optical stabilization."
        wide = score_evidence_quality({"evidence_text": narrow_claim, "source_title": "Indian smartphone market under Rs 30000", "source_type": "specialist_publication", "relevance": .8}, question, narrow_claim)
        adjacent = score_evidence_quality({"evidence_text": narrow_claim, "source_title": narrow_title, "source_type": "specialist_publication", "relevance": .8}, question, narrow_claim)
        self.assertLess(adjacent["segment_relevance"], wide["segment_relevance"])
        self.assertLess(adjacent["quality_score"], wide["quality_score"])

    def test_current_subsegment_and_qualitative_market_evidence_survive(self):
        statements = [
            "The report noted that shipments in the mass-market segment (sub-INR 15,000) plunged 45% year-on-year in the second quarter of 2026.",
            "Analysts say India's smartphone market is moving upmarket as buyers increasingly choose higher specification devices.",
        ]
        for statement in statements:
            source = {"id": "s1", "title": "India smartphone market segments", "content": statement, "search_query": "India smartphone market trends segments", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "source_type": "industry_report", "published_at": "2026-07-01", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(statement=statement):
                evidence = _extract_evidence(source, "r1")
                self.assertTrue(evidence)
                self.assertEqual(evidence[0]["evidence_text"], statement)

    def test_quality_score_controls_selection_order(self):
        high = {"id": "high", "source_id": "s-high", "publisher": "Industry", "source_url": "https://industry.example", "evidence_text": "India smartphone shipments grew 10% in 2026.", "quality_score": .91, "relevance": .5}
        low = {"id": "low", "source_id": "s-low", "publisher": "Unknown", "source_url": "https://unknown.example", "evidence_text": "India smartphone shipments grew 10% in 2026 from a weak source.", "quality_score": .25, "relevance": 1.0}
        self.assertEqual(_select_diverse_evidence([low, high], [], limit=1), [high])

    def test_editorial_superlatives_and_headings_are_rejected(self):
        rejected = [
            "India's smartphone industry has become the true engine of growth for an undeniable global force in the digital economy.",
            "Choosing a smartphone is no small task for consumers seeking the best device in a crowded market.",
            "Our leading smartphone brand delivers unmatched innovation and an exceptional experience for Indian buyers.",
            "Top Factors Driving Growth in the India Smartphone Industry",
            "Smartphone Market Segment Overview",
        ]
        for statement in rejected:
            source = {"id": "s1", "title": "India smartphone industry", "content": statement, "search_query": "India smartphone market trends", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(statement=statement): self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_vague_market_introductions_launches_and_praise_fail_factual_gate(self):
        rejected = [
            "The growth of the India smartphone industry is a multi-faceted narrative, driven equally by technological shifts, economic factors, and aggressive competitive strategies.",
            "In recent times, several brands have launched phones that support demanding games within an affordable range.",
            "Poco continues to push performance-heavy smartphones in the Rs 30000 segment, and the X7 Pro is a quite powerful option for many.",
            "Globally, both devices hover around the $300 mark, making the iQOO an undisputed champion in pure value.",
        ]
        for statement in rejected:
            source = {"id": "s1", "title": "India smartphone market and phones under Rs 30000", "content": statement, "search_query": "India smartphone market segment analysis", "research_question": "Analyze the Indian smartphone market under Rs 30000.", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(statement=statement): self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_concrete_market_measurements_prices_and_survey_findings_are_retained(self):
        statements = [
            "India smartphone shipments declined 10% year-on-year in Q2 2026, according to IDC.",
            "The Indian smartphone market reached 24% share for Brand X in Q2 2026, according to Counterpoint.",
            "The Nova smartphone launched in India at Rs 24999 in June 2026.",
            "A survey of Indian smartphone buyers found that 62% preferred longer battery life and faster charging.",
        ]
        for statement in statements:
            source = {"id": "s1", "title": "India smartphone market research", "content": statement, "search_query": "India smartphone market price survey shipment data", "research_question": "Analyze the Indian smartphone market under Rs 30000.", "content_scope": "source_page", "source_type": "industry_report", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(statement=statement): self.assertTrue(_extract_evidence(source, "r1"))

    def test_direct_under_30k_evidence_and_context_are_scored_differently(self):
        question = "Analyze the Indian smartphone market under Rs 30000"
        direct = score_evidence_quality({"evidence_text": "Smartphones priced between Rs 20000 and Rs 30000 captured 24% of Indian shipments in 2026.", "source_title": "India smartphone segments", "source_type": "industry_report", "relevance": .9}, question, "Smartphones priced between Rs 20000 and Rs 30000 captured 24% of Indian shipments in 2026.")
        context = score_evidence_quality({"evidence_text": "India's smartphone shipments declined 10% year-on-year in the second quarter of 2026, according to the tracker.", "source_title": "India smartphone market trends", "source_type": "major_publication", "relevance": .9}, question, "India's smartphone shipments declined 10% year-on-year in the second quarter of 2026, according to the tracker.")
        low_budget = score_evidence_quality({"evidence_text": "Smartphones in the Rs 6000 to Rs 8000 segment gained 12% of Indian shipments.", "source_title": "India smartphone prices", "source_type": "specialist_publication", "relevance": .9}, question, "Smartphones in the Rs 6000 to Rs 8000 segment gained 12% of Indian shipments.")
        self.assertGreater(direct["segment_relevance"], context["segment_relevance"])
        self.assertGreater(context["segment_relevance"], low_budget["segment_relevance"])
        self.assertGreater(direct["quality_score"], context["quality_score"])

    def test_source_quality_levels_and_publisher_fallback_affect_score(self):
        evidence = "India smartphone shipments grew 10% in 2026, according to published market data."
        base = {"evidence_text": evidence, "source_title": "India smartphone market", "published_at": "2026-06-01", "relevance": .9}
        quality = lambda item: score_evidence_quality(item, "Analyze the Indian smartphone market", evidence)
        government = quality({**base, "source_type": "government"})
        industry = quality({**base, "source_type": "industry_report"})
        major = quality({**base, "source_type": "major_publication"})
        specialist = quality({**base, "source_type": "specialist_publication"})
        unknown = quality({**base, "source_type": "unknown"})
        named_major = quality({**base, "source_type": "unknown", "publisher": "Reuters"})
        self.assertGreater(government["source_quality_score"], industry["source_quality_score"])
        self.assertGreater(industry["source_quality_score"], major["source_quality_score"])
        self.assertGreater(major["source_quality_score"], specialist["source_quality_score"])
        self.assertGreater(specialist["source_quality_score"], unknown["source_quality_score"])
        self.assertGreater(named_major["quality_score"], unknown["quality_score"])

    def test_specialist_fact_is_retained_but_specialist_promotion_is_rejected(self):
        facts = "The smartphone maker launched its X30 model in India in April 2026 at a starting price of Rs 24999."
        promotion = "The X30 is the best smartphone and an undeniable global force for every Indian buyer."
        source = {"id": "s1", "title": "Smartphone launches in India", "content": facts, "search_query": "India smartphone launches prices", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "source_type": "specialist_publication", "evaluation": {"usable": True, "confidence": .8}}
        self.assertEqual([row["evidence_text"] for row in _extract_evidence(source, "r1")], [facts])
        source["content"] = promotion
        self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_attributed_leading_shipment_claim_remains_usable(self):
        fact = "Samsung was the leading smartphone brand in India by shipments with a 21% share in 2026, according to the industry tracker."
        source = {"id": "s1", "title": "India smartphone shipment shares", "content": fact, "search_query": "India smartphone shipments share", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "source_type": "industry_report", "evaluation": {"usable": True, "confidence": .8}}
        self.assertEqual([row["evidence_text"] for row in _extract_evidence(source, "r1")], [fact])

    def test_smartphone_hard_gate_rejects_unrelated_products_and_marketplace_prices(self):
        examples = [
            ("Beauty of Joseon Relief Sun SPF50+ PA++++ sunscreen (50ml) is available for Rs 1048.", "https://www.amazon.in/deals"),
            ("This laptop is available for Rs 124990 after a 54% discount.", "https://www.amazon.in/deals"),
            ("The television is available for Rs 41490 with GST savings.", "https://www.amazon.in/deals"),
            ("The smartphone model is available for Rs 41490 with GST savings.", "https://www.amazon.in/deals"),
            ("The smartphone model is available for Rs 124990 after a 54% discount.", "https://www.amazon.in/deals"),
            ("Enjoy 54% off with GST savings and get it for Rs 124990.", "https://www.amazon.in/deals"),
            ("Enjoy 52% off with GST savings and get this for Rs 41490.", "https://www.amazon.in/deals"),
            ("The skincare product is available for Rs 1048 and sales increased 20% this week.", "https://www.amazon.in/deals"),
        ]
        for statement, url in examples:
            source = {"id": "amazon", "title": "Smartphone deals and offers", "url": url, "content": statement, "search_query": "India smartphone under Rs 30000", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(statement=statement): self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_target_smartphone_price_and_market_statements_pass_hard_gate(self):
        statements = [
            "The smartphone is priced between Rs 20000 and Rs 30000 in India and was launched in 2026.",
            "India smartphone shipments declined 10% year-on-year in the second quarter of 2026, according to the industry tracker.",
            "India smartphone market share reached 24% in the mid-range segment in 2026, according to the report.",
        ]
        for statement in statements:
            source = {"id": "s1", "title": "India smartphone market segment report", "url": "https://reuters.com/technology/india", "content": statement, "search_query": "India smartphone market under Rs 30000", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "source_type": "major_publication", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(statement=statement): self.assertTrue(_extract_evidence(source, "r1"))

    def test_vague_editorial_and_predictive_market_claims_fail_hard_gate(self):
        statements = [
            "Redmi dominates the affordable tier that powers Indian sales.",
            "Made-in-India manufacturing, easy EMIs and aggressive festive-season sales will keep pushing better phones into more hands.",
        ]
        for statement in statements:
            source = {"id": "s1", "title": "India smartphone brands and market outlook", "content": statement, "search_query": "India smartphone market sales trends", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(statement=statement): self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_mixed_marketplace_page_only_retains_smartphone_evidence(self):
        phone = "The smartphone model is priced at " + chr(0x20b9) + "24999 in India after the latest launch."
        source = {"id": "amazon", "title": "Smartphone deals", "url": "https://www.amazon.in/deals", "content": "\n\n".join([
            phone,
            "Beauty of Joseon Relief Sun SPF50+ PA++++ sunscreen (50ml) is available for Rs 1048.",
            "This laptop is available for Rs 124990 after a 54% discount.",
            "The television is available for Rs 41490 with GST savings.",
        ]), "search_query": "India smartphone under Rs 30000", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
        self.assertEqual([item["evidence_text"] for item in _extract_evidence(source, "r1")], [phone])

    def test_generic_market_price_sales_sentence_without_phone_context_is_rejected(self):
        statement = "The Indian market price and sales increased by 20% during the latest seasonal promotion."
        source = {"id": "s1", "title": "India smartphone market report", "url": "https://example.com/article", "content": statement, "search_query": "India smartphone market price sales", "research_question": "Analyze the Indian smartphone market under Rs 30000", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
        self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_generic_wifi_device_forecast_is_not_smartphone_market_evidence(self):
        source = {
            "title": "What Factors Are Driving the Rapid Growth of India's Smartphone Industry?",
            "research_question": "Analyze the Indian smartphone market under Rs 30000.",
            "search_query": "consumer preferences features Indian smartphone market mid-range",
            "content": "According to Wi-Fi Alliance, the official industry certification body, 4.1 billion Wi-Fi devices are forecast to ship in 2024, contributing to 45.9 billion cumulative Wi-Fi shipments over the technology's 25-year lifetime.\nIndia smartphone shipments grew 8% to 30 million units in 2025.",
            "url": "https://www.imarcgroup.com/insight/top-factors-driving-growth-india-smartphone-industry",
            "final_url": "https://www.imarcgroup.com/insight/top-factors-driving-growth-india-smartphone-industry",
        }
        candidates = _evidence_candidates(source)
        texts = [row[0] for row in candidates]
        self.assertFalse(any("Wi-Fi" in text for text in texts))
        self.assertTrue(any("smartphone shipments grew 8%" in text for text in texts))

    def test_qualitative_factual_evidence_is_accepted(self):
        statement = "A survey of Indian smartphone buyers found that customers increasingly prefer longer software support and repair availability."
        source = {"id": "s1", "title": "Indian smartphone buyers and preferences", "content": statement, "search_query": "Indian smartphone consumer preferences", "research_question": "Analyze Indian smartphone consumer preferences", "content_scope": "source_page", "source_type": "major_publication", "published_at": "2026-03-01", "evaluation": {"usable": True, "confidence": .8}}
        evidence = _extract_evidence(source, "r1")
        self.assertEqual([item["evidence_text"] for item in evidence], [statement])

    def test_sentence_starting_with_year_context_is_not_mistaken_for_a_fragment(self):
        statement = "In 2025, Indian smartphone buyers increasingly preferred brands with longer software support."
        source = {"id": "s1", "title": "Indian smartphone buyer preferences", "content": statement, "search_query": "Indian smartphone preferences", "research_question": "Analyze the Indian smartphone market", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
        self.assertTrue(_extract_evidence(source, "r1"))

    def test_incomplete_and_artifact_sentences_are_rejected(self):
        incomplete = [
            "The company would now require pricing it in India at around Rs.",
            "The smartphone model was released in India and",
            "Samsung launched a smartphone in India at",
            "The smartphone price in India reached INR 29,",
            "The smartphone replacement rate reached 20% in India \ufffd this quarter.",
        ]
        for sentence in incomplete:
            source = {"id": "s1", "title": "India smartphone pricing", "content": sentence, "search_query": "Indian smartphone market pricing", "research_question": "Indian smartphone market pricing", "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
            with self.subTest(sentence=sentence): self.assertEqual(_extract_evidence(source, "r1"), [])

    def test_recency_and_source_type_change_quality_without_rejecting_unknown(self):
        base = {"evidence_text": "India smartphone sales grew 10% in the market.", "source_title": "India smartphone market", "relevance": .9}
        old = score_evidence_quality({**base, "source_type": "unknown", "published_at": "2023-05-01"}, "Analyze Indian smartphone market", base["evidence_text"])
        recent = score_evidence_quality({**base, "source_type": "unknown", "published_at": "2026-05-01"}, "Analyze Indian smartphone market", base["evidence_text"])
        major = score_evidence_quality({**base, "source_type": "major_publication", "published_at": "2026-05-01"}, "Analyze Indian smartphone market", base["evidence_text"])
        self.assertLess(old["recency_score"], recent["recency_score"])
        self.assertLess(recent["source_quality_score"], major["source_quality_score"])
        self.assertGreater(old["quality_score"], 0)
        self.assertTrue(recent["direct_support"])
        historical_old = score_evidence_quality({**base, "source_type": "major_publication", "published_at": "2023-06-01"}, "Analyze the 2025 Indian smartphone market", base["evidence_text"])
        historical_target = score_evidence_quality({**base, "source_type": "major_publication", "published_at": "2025-06-01"}, "Analyze the 2025 Indian smartphone market", base["evidence_text"])
        self.assertLess(historical_old["recency_score"], historical_target["recency_score"])

    def test_geographic_relevance_reduces_us_only_market_claim(self):
        question = "Analyze the Indian smartphone market under 30000"
        self.assertLess(geographic_relevance("US smartphone market share reached 20% in 2025.", "US smartphone market share", question), .35)
        self.assertGreaterEqual(geographic_relevance("Global smartphone adoption grew across emerging markets in 2025.", "Global smartphone adoption", question), .35)

    def test_followups_target_missing_requirement_generically(self):
        queries = generate_followup_queries("Analyze the Indian smartphone market under 30000", ["channel distribution, highlighting the split between e-commerce platforms Amazon Flipkart and offline retail"])
        joined = " ".join(queries).lower()
        self.assertGreaterEqual(len(queries), 3)
        for term in ("indian", "smartphone", "online", "offline", "e-commerce", "amazon", "flipkart", str(datetime.now().year)):
            self.assertIn(term, joined)
        generic = generate_followup_queries("Analyze the Canadian electric bicycle market", ["consumer preferences"])
        self.assertTrue(any("canadian electric bicycle" in query and "consumer" in query for query in generic))

    def test_evidence_selection_limits_redundancy_and_keeps_other_sources(self):
        items = []
        for index in range(8):
            publisher = "Same Publisher" if index < 6 else f"Independent {index}"
            items.append({"id": str(index), "source_id": f"s{index // 2}", "publisher": publisher, "source_url": f"https://source{index}.example/article", "evidence_text": f"India smartphone market recorded a distinct factual change of {index} percent in the year 2026.", "search_query": "Indian smartphone market", "quality_score": .9 if index < 6 else .7, "relevance": .8})
        selected = _select_diverse_evidence(items, ["market overview"])
        self.assertLessEqual(sum(item["publisher"] == "Same Publisher" for item in selected), 5)
        self.assertGreaterEqual(sum(item["publisher"].startswith("Independent") for item in selected), 2)

    def test_source_classification_for_research_publishers(self):
        major = [
            ("https://www.business-standard.com/article", "Business Standard"),
            ("https://www.reuters.com/world/india", "Reuters"),
            ("https://www.thehindu.com/business", "The Hindu"),
            ("https://economictimes.indiatimes.com/tech", "Economic Times"),
            ("https://www.livemint.com/technology", "Mint"),
            ("https://www.hindustantimes.com/business", "Hindustan Times"),
            ("https://indianexpress.com/section/business", "Indian Express"),
            ("https://www.cnbctv18.com/technology", "CNBC-TV18"),
            ("https://www.moneycontrol.com/news/business", "Moneycontrol"),
        ]
        for url, publisher in major:
            with self.subTest(publisher=publisher): self.assertEqual(classify_source(url, publisher), "major_publication")
        for url, publisher in [("https://www.gsmarena.com/", "GSMArena"), ("https://www.91mobiles.com/", "91mobiles")]:
            with self.subTest(publisher=publisher): self.assertEqual(classify_source(url, publisher), "specialist_publication")
        for url, publisher in [("https://counterpointresearch.com/", "Counterpoint Research"), ("https://www.idc.com/", "IDC"), ("https://canalys.com/", "Canalys"), ("https://omdia.tech.informa.com/", "Omdia")]:
            with self.subTest(publisher=publisher): self.assertEqual(classify_source(url, publisher), "industry_report")
        self.assertEqual(classify_source("https://unknown-example.net", "Independent Blog"), "unknown")

    def test_missing_information_detection(self):
        requirement = "market overview"
        self.assertEqual(_missing_information([requirement], []), [requirement])
        factual = {"evidence_text": "India smartphone market size reached 153 million units in 2025.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1}
        self.assertEqual(_missing_information([requirement], [factual], "Analyze the Indian smartphone market"), [])

    def test_coverage_requires_local_requirement_specific_evidence(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        consumer = "Consumer preferences for smartphone features"
        channel = "India-specific online versus offline smartphone distribution"
        band = "Market size, growth rate, and shipment data for the Rs 20000 to Rs 30000 price band in India"
        global_item = {"evidence_text": "Global smartphone shipments grew 12% in 2026.", "direct_support": True, "geographic_relevance": .62, "category_relevance": 1, "segment_relevance": .54, "recency_score": .98}
        low_band = {"evidence_text": "India smartphone shipments in the Rs 6000 to Rs 8000 segment increased 12% in 2026.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .22, "recency_score": .98}
        self.assertNotIn(consumer, _evaluate_coverage([consumer], [global_item], q)["sufficient"])
        self.assertNotIn(channel, _evaluate_coverage([channel], [global_item], q)["sufficient"])
        self.assertNotIn(band, _evaluate_coverage([band], [low_band], q)["sufficient"])
        for requirement in (consumer, channel, band):
            with self.subTest(requirement=requirement):
                missing = _missing_information([requirement], [global_item if requirement != band else low_band], q)
                self.assertEqual(missing, [requirement])

    def test_specific_evidence_satisfies_consumer_channel_and_target_band_requirements(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        items = [
            {"evidence_text": "A survey of Indian Rs 20000 to Rs 30000 smartphone buyers found 62% prefer longer battery life in 2026.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98},
            {"evidence_text": "In India's Rs 20000 to Rs 30000 smartphone segment, online sales held 38% share while offline retail accounted for 62% in 2025.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .84},
            {"evidence_text": "India smartphone shipments in the Rs 20000 to Rs 30000 segment grew 12% to 8 million units in 2025.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .84},
        ]
        requirements = ["Consumer preferences and survey evidence", "Online vs offline distribution for Indian sub-Rs 30000 smartphones", "Market size, growth, and shipment data for the Rs 20000 to Rs 30000 price band in India"]
        result = _evaluate_coverage(requirements, items, q)
        self.assertEqual(result["sufficient"], requirements)
        self.assertEqual(result["weak"], [])
        self.assertEqual(result["unanswered"], [])

    def test_model_pricing_requirement_rejects_rumors_and_accepts_current_target_price(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        requirement = "Current smartphone model pricing under Rs 30,000 in India"
        rumor = {"evidence_text": "Samsung is working on a Galaxy A57 smartphone expected to be priced at Rs 28,999 in India in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        current = {"evidence_text": "Samsung Galaxy A56 smartphone was priced at Rs 28,999 in India in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        self.assertNotIn(requirement, _evaluate_coverage([requirement], [rumor], q)["sufficient"])
        self.assertIn(requirement, _evaluate_coverage([requirement], [current], q)["sufficient"])

    def test_missing_current_pricing_and_channel_requirements_are_reported_unresolved(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        pricing = "Current smartphone model pricing under Rs 30,000 in India"
        channel = "Online vs offline distribution for Indian sub-Rs 30,000 smartphones"
        plan = {"information_needed": [pricing, channel]}
        coverage = _evaluate_coverage(plan["information_needed"], [], q)
        report = _report(q, plan, [], coverage["weak"] + coverage["unanswered"], [], coverage)
        for requirement in (pricing, channel):
            with self.subTest(requirement=requirement):
                self.assertIn(requirement, coverage["unanswered"])
                self.assertIn(f"UNRESOLVED / INSUFFICIENT EVIDENCE — {requirement}", report)

    def test_price_above_ceiling_is_out_of_scope_and_cannot_cover_target_requirements(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        claim = "Qualcomm led the premium smartphone segment above Rs 30,000, capturing 51% shipment share in India in 2026."
        scope = classify_evidence_scope(claim, q)
        self.assertEqual(scope, "OUT_OF_SCOPE")
        self.assertEqual(segment_relevance(claim, "", q), .05)
        item = {"evidence_text": claim, "evidence_scope": scope, "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .05, "recency_score": .98}
        requirements = ["India smartphone brand share in the Rs 20,000 to Rs 30,000 segment", "Current smartphone model pricing under Rs 30,000 in India", "Sales volume and revenue growth for India's sub-Rs 30,000 smartphone segment"]
        self.assertEqual(_evaluate_coverage(requirements, [item], q)["sufficient"], [])

    def test_broad_india_market_context_does_not_satisfy_direct_target_requirements(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        broad = {"evidence_text": "India smartphone shipments grew 12% to 48 million units in 2026.", "evidence_scope": "INDIA_MARKET_CONTEXT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .54, "recency_score": .98}
        requirements = ["India smartphone brand share in the Rs 20,000 to Rs 30,000 segment", "Sales volume and revenue growth for India's sub-Rs 30,000 smartphone segment"]
        result = _evaluate_coverage(requirements, [broad], q)
        self.assertEqual(result["sufficient"], [])
        self.assertEqual(set(_missing_information(requirements, [broad], q)), set(requirements))

    def test_10k_to_15k_target_scope_does_not_satisfy_sales_or_technology_requirements(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        claim = "India's mid-range smartphone shipments in the Rs 10,000 to Rs 15,000 segment increased 20% in 2026."
        scope = classify_evidence_scope(claim, q)
        self.assertEqual(scope, "TARGET_SEGMENT")
        evidence = {"evidence_text": claim, "evidence_scope": scope, "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .76, "recency_score": .98}
        sales = "Sales volume and revenue growth for India's sub-Rs 30,000 smartphone segment"
        technology = "Mid-tier smartphone technology adoption trends in India"
        self.assertNotIn(sales, _evaluate_coverage([sales], [evidence], q)["sufficient"])
        self.assertNotIn(technology, _evaluate_coverage([technology], [evidence], q)["sufficient"])

    def test_target_sales_requires_broad_sub30_band_and_measured_change(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        requirement = "Sales volume and revenue growth for India's sub-Rs 30,000 smartphone segment"
        overall = {"evidence_text": "India smartphone shipments grew 12% to 48 million units in 2026.", "evidence_scope": "INDIA_MARKET_CONTEXT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .54, "recency_score": .98}
        valid = {"evidence_text": "India smartphone shipments under Rs 30,000 grew 12% to 8 million units in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        self.assertNotIn(requirement, _evaluate_coverage([requirement], [overall], q)["sufficient"])
        self.assertIn(requirement, _evaluate_coverage([requirement], [valid], q)["sufficient"])

    def test_mid_tier_technology_requires_technology_adoption_signal(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        requirement = "Mid-tier smartphone technology adoption trends in India"
        shipment_only = {"evidence_text": "India mid-tier smartphone shipments grew 12% to 8 million units in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        valid = {"evidence_text": "5G smartphones in India's Rs 20,000 to Rs 30,000 segment accounted for 42% of shipments in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        self.assertNotIn(requirement, _evaluate_coverage([requirement], [shipment_only], q)["sufficient"])
        self.assertIn(requirement, _evaluate_coverage([requirement], [valid], q)["sufficient"])

    def test_brand_price_and_promotion_requirements_need_their_own_facts(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        brand = "India smartphone brand share in the Rs 20,000 to Rs 30,000 segment"
        pricing = "Current smartphone model pricing under Rs 30,000 in India"
        offers = "Pricing strategies and promotional offers within the Indian sub-Rs 30,000 smartphone segment"
        brand_only = {"evidence_text": "Samsung competed in India's Rs 20,000 to Rs 30,000 smartphone segment in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        generic_price = {"evidence_text": "Smartphone prices in India changed during 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        generic_promo = {"evidence_text": "Brands competed aggressively on price in India's smartphone market in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        self.assertNotIn(brand, _evaluate_coverage([brand], [brand_only], q)["sufficient"])
        self.assertNotIn(pricing, _evaluate_coverage([pricing], [generic_price], q)["sufficient"])
        self.assertNotIn(offers, _evaluate_coverage([offers], [generic_promo], q)["sufficient"])

    def test_editorial_product_lists_cannot_support_analysis_requirements(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        requirement = "Sales volume and revenue growth for India's sub-Rs 30,000 smartphone segment"
        editorial = "Overall, it is a pretty good smartphone under Rs 30,000 in the 2026 sale."
        curated = "Curated list of top smartphones under Rs 30,000 for July 2026 includes five models."
        source = {"id": "s-editorial", "title": "Best smartphones under Rs 30000 India", "url": "https://example.com/article", "final_url": "https://example.com/article", "content": editorial + "\n" + curated, "search_query": "India smartphone market under 30000", "research_question": q, "content_scope": "source_page", "evaluation": {"usable": True, "confidence": .8}}
        retained = _extract_evidence(source, "r1")
        self.assertEqual(retained, [])
        for text in (editorial, curated):
            item = {"evidence_text": text, "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
            self.assertNotIn(requirement, _evaluate_coverage([requirement], [item], q)["sufficient"])

    def test_macro_context_is_labeled_and_cannot_substitute_for_analysis_dimensions(self):
        q = "Analyze the Indian smartphone market under Rs 30000."
        plan = {"information_needed": ["MACRO / CONTEXT: Analyst reports on macroeconomic factors influencing smartphone purchases in India"]}
        macro_requirement = plan["information_needed"][0]
        market_item = {"evidence_text": "India's mid-range smartphone shipments in the Rs 10,000 to Rs 15,000 segment increased 20% in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .76, "recency_score": .98}
        self.assertTrue(macro_requirement.startswith("MACRO / CONTEXT:"))
        self.assertNotIn(macro_requirement, _evaluate_coverage([macro_requirement], [market_item], q)["sufficient"])

    def test_scope_labels_out_of_band_context_global_and_direct_target(self):
        q = "Analyze the Indian smartphone market under ₹30000."
        premium = "Qualcomm led the premium smartphone segment (>INR 30,000), with 51% share in India."
        shipments = "India smartphone shipments reached 48 million units in 2025."
        unit_count = "India smartphone shipments exceeded 30,000 units in the first month of 2026."
        global_claim = "Global smartphone shipments grew 8% in 2025."
        target_claim = "Samsung held 24% share in India's smartphone market under ₹30,000 in 2026."
        self.assertEqual(classify_evidence_scope(premium, q), "OUT_OF_SCOPE")
        self.assertEqual(segment_relevance(premium, "", q), .05)
        self.assertEqual(classify_evidence_scope(shipments, q), "INDIA_MARKET_CONTEXT")
        self.assertEqual(classify_evidence_scope(unit_count, q), "INDIA_MARKET_CONTEXT")
        self.assertGreater(segment_relevance(unit_count, "", q), .05)
        self.assertEqual(classify_evidence_scope(global_claim, q), "GLOBAL_CONTEXT")
        self.assertEqual(classify_evidence_scope(target_claim, q), "TARGET_SEGMENT")

    def test_out_of_band_and_chipset_or_overall_share_cannot_cover_target_brand_share(self):
        q = "Analyze the Indian smartphone market under ₹30000."
        requirement = "Brand share in India's sub-₹30,000 smartphone segment"
        claims = [
            "Qualcomm led the premium smartphone segment (>INR 30,000), with 51% shipment share in India.",
            "Samsung held 24% of India's overall smartphone market share in 2026.",
            "MediaTek led India’s smartphone chipset market with a 49% shipment share in 2026.",
        ]
        for claim in claims:
            item = {"evidence_text": claim, "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
            with self.subTest(claim=claim):
                self.assertNotIn(requirement, _evaluate_coverage([requirement], [item], q)["sufficient"])
        direct = {"evidence_text": "Samsung held 24% share of India's smartphone brands in the sub-₹30,000 segment in 2026.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        self.assertEqual(classify_evidence_scope(direct["evidence_text"], q), "TARGET_SEGMENT")
        self.assertEqual(_requirement_kind(requirement), "brand_share")
        self.assertTrue(_CONCRETE_FACT.search(direct["evidence_text"]))
        self.assertTrue(_is_india_specific(direct, q, requirement))
        self.assertTrue(_BAND_METRIC.search(direct["evidence_text"]))
        self.assertNotRegex(direct["evidence_text"], r"\b(?:chipset|processor|soc)\b")
        self.assertRegex(direct["evidence_text"], r"\b(?:brands?|Samsung|Apple|Xiaomi|Redmi|Oppo|Vivo|Realme|Poco|OnePlus|Motorola|iQOO|Transsion|Tecno|Infinix|Nothing|Google Pixel)\b")
        self.assertTrue(_requirement_supported(direct, requirement, q))
        self.assertEqual(_evaluate_coverage([requirement], [direct], q)["sufficient"], [requirement])

    def test_competitor_activity_needs_documented_offer_terms(self):
        q = "Analyze the Indian smartphone market under ₹30000."
        requirement = "Competitor offers, exchange bonuses, and financing"
        general = {"evidence_text": "Smartphone brands compete aggressively for Indian buyers in 2026.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .54, "recency_score": .98}
        actual = {"evidence_text": "Samsung offered an ₹2,000 exchange bonus and no-cost EMI for six months on its Galaxy A55 smartphone priced at ₹28,999 in India in 2026.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        self.assertNotIn(requirement, _evaluate_coverage([requirement], [general], q)["sufficient"])
        self.assertEqual(_evaluate_coverage([requirement], [actual], q)["sufficient"], [requirement])

    def test_target_requirements_stay_unresolved_without_target_segment_evidence(self):
        q = "Analyze the Indian smartphone market under ₹30000."
        requirements = ["Brand share in India's sub-₹30,000 segment", "Competitor offers, exchange bonuses, and financing"]
        context = [
            {"evidence_text": "India smartphone shipments reached 48 million units in 2025.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .54},
            {"evidence_text": "Samsung held 20% share of India's overall smartphone market in 2025.", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .54},
        ]
        result = _evaluate_coverage(requirements, context, q)
        self.assertEqual(result["sufficient"], [])
        self.assertEqual(set(_missing_information(requirements, context, q)), set(requirements))

    def test_only_target_scope_satisfies_explicit_target_segment_requirement(self):
        q = "Analyze the Indian smartphone market under ₹30000."
        requirement = "Shipment share in the ₹20,000 to ₹30,000 smartphone segment in India"
        pricing_requirement = "Pricing and segments"
        contextual = {"evidence_text": "India's smartphone shipments grew 12% in 2026.", "evidence_scope": "INDIA_MARKET_CONTEXT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        global_item = {"evidence_text": "Global smartphone shipments grew 12% in 2026.", "evidence_scope": "GLOBAL_CONTEXT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        out_of_scope = {"evidence_text": "Premium smartphones above ₹30,000 gained 12% shipment share in India in 2026.", "evidence_scope": "OUT_OF_SCOPE", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        target = {"evidence_text": "India smartphone shipments in the ₹20,000 to ₹30,000 segment grew 12% to 8 million units in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        for item in (contextual, global_item, out_of_scope):
            with self.subTest(scope=item["evidence_scope"]): self.assertNotIn(requirement, _evaluate_coverage([requirement], [item], q)["sufficient"])
        self.assertNotIn(pricing_requirement, _evaluate_coverage([pricing_requirement], [contextual], q)["sufficient"])
        self.assertEqual(_evaluate_coverage([requirement], [target], q)["sufficient"], [requirement])
        price = {"evidence_text": "Samsung Galaxy A55 smartphone was priced at ₹28,999 in India in 2026.", "evidence_scope": "TARGET_SEGMENT", "direct_support": True, "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "recency_score": .98}
        self.assertEqual(_requirement_kind(pricing_requirement), "pricing")
        self.assertTrue(_CONCRETE_FACT.search(price["evidence_text"]))
        self.assertTrue(_is_india_specific(price, q, pricing_requirement))
        self.assertRegex(price["evidence_text"], r"(?:Rs\.?|INR|\u20b9)\s?\d")
        self.assertRegex(price["evidence_text"].lower(), r"smartphone|mobile phone|handset|\bphone\b")
        self.assertTrue(_requirement_supported(price, pricing_requirement, q))
        self.assertEqual(_evaluate_coverage([pricing_requirement], [price], q)["sufficient"], [pricing_requirement])

    def test_run_iteration_count_matches_started_activity_iterations(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("database.store.DB_PATH", os.path.join(directory, "iteration.sqlite3")):
                from database import store
                store.init_db()
                run_id = "single-iteration-source-cap"
                question = "Analyze the Indian smartphone market under ₹30000."
                store.create_run(run_id, question)
                plan = {"research_goal": "market", "sub_questions": ["share"], "information_needed": ["market overview"], "search_queries": ["q"]}
                results = [{"url": f"https://example.com/{i}", "title": f"Source {i}"} for i in range(MAX_SOURCES)]
                with patch("agents.research_executor.create_research_plan", return_value=plan), \
                     patch("agents.research_executor.search_web", return_value=results), \
                     patch("agents.research_executor.fetch_document", side_effect=RuntimeError("offline")):
                    result = execute_research(question, research_id=run_id)
                stored_run = store.get_run(run_id)
                starts = [event for event in stored_run["activity"] if event == "Research iteration started"]
                numbered = [event for event in stored_run["activity"] if re.match(r"Iteration \d+: searching", event)]
                self.assertEqual(result["iterations"], 1)
                self.assertEqual(stored_run["iterations"], 1)
                self.assertEqual(len(starts), stored_run["iterations"])
                self.assertEqual(len(numbered), stored_run["iterations"])
                self.assertNotIn("Follow-up research generated", stored_run["activity"])

    def test_legacy_sqlite_evidence_is_backfilled_with_correct_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("database.store.DB_PATH", os.path.join(directory, "legacy.sqlite3")):
                from database import store
                store.init_db()
                with store.connect() as db:
                    db.execute("ALTER TABLE evidence DROP COLUMN evidence_scope")
                run_id = "legacy-scope"
                question = "Analyze the Indian smartphone market under Rs 30000."
                store.create_run(run_id, question)
                source_id = store.add_source(run_id, {"url": "https://example.com", "title": "India smartphone premium segment"})
                with store.connect() as db:
                    db.execute("""INSERT INTO evidence(id,research_id,source_id,claim,evidence_text,source_url,source_title,publisher,published_at,source_type,content_scope,relevance,confidence,extracted_at,source_quality_score,recency_score,geographic_relevance,direct_support,quality_score,category_relevance,segment_relevance)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", ("e1", run_id, source_id, "Premium share", "Qualcomm led the premium smartphone segment (>INR 30,000), with 51% share in India.", "https://example.com", "India smartphone premium segment", "Example", "2026-01-01", "unknown", "source_page", .8, .8, "2026-01-01", .28, .98, 1, 1, .8, 1, .88))
                store.init_db()
                evidence = store.get_evidence(run_id)[0]
                self.assertEqual(evidence["evidence_scope"], "OUT_OF_SCOPE")
                self.assertEqual(evidence["segment_relevance"], .05)

    def test_search_result_or_source_without_evidence_does_not_cover_requirements(self):
        plan = {"research_goal": "x", "sub_questions": ["x"], "information_needed": ["consumer preferences", "India-specific online-vs-offline channel distribution"], "search_queries": ["q"]}
        def search(query, max_results=4):
            if query == "q": return [{"url": "https://example.com/article", "title": "India smartphone market"}]
            return []
        article = "India smartphone market has many brands and buyers. This page provides a general introduction without measurements or research findings."
        with patch("agents.research_executor.create_research_plan", return_value=plan), patch("agents.research_executor.search_web", side_effect=search), patch("agents.research_executor.fetch_document", return_value={"content": article, "final_url": "https://example.com/article", "content_type": "text/html"}):
            result = execute_research("Analyze the Indian smartphone market")
        self.assertTrue(result["sources"])
        self.assertEqual(result["evidence"], [])
        self.assertEqual(set(result["missing_information"]), set(plan["information_needed"]))
        self.assertIn("Follow-up research generated", result["activity"])

    def test_unresolved_requirements_are_explicit_in_final_report(self):
        missing = ["consumer preferences", "India-specific online-vs-offline channel distribution", "direct current Rs 20000 to Rs 30000 shipment data"]
        report = _report("Analyze the Indian smartphone market under Rs 30000", {"information_needed": missing}, [], missing, [], {"sufficient": [], "weak": [], "unanswered": missing})
        for requirement in missing:
            with self.subTest(requirement=requirement): self.assertIn(requirement, report)
        self.assertIn("UNRESOLVED / INSUFFICIENT EVIDENCE", report)
        self.assertIn("Only retained TARGET_SEGMENT evidence can satisfy direct target-segment requirements", report)

    def test_report_labels_target_and_context_findings_separately(self):
        context = {"claim": "India smartphone shipments reached 48 million units in 2025.", "evidence_text": "India smartphone shipments reached 48 million units in 2025.", "source_id": "s1", "source_title": "India Market Report", "source_url": "https://example.com/report", "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .54, "confidence": .8}
        target = {"claim": "Samsung held 24% share in India's smartphone market under Rs 30000 in 2026.", "evidence_text": "Samsung held 24% share in India's smartphone market under Rs 30000 in 2026.", "source_id": "s2", "source_title": "Segment Report", "source_url": "https://example.com/segment", "geographic_relevance": 1, "category_relevance": 1, "segment_relevance": .98, "confidence": .8}
        report = _report("Analyze the Indian smartphone market under Rs 30000", {"information_needed": []}, [context, target], [], [])
        self.assertIn("### TARGET_SEGMENT", report)
        self.assertIn("### INDIA_MARKET_CONTEXT", report)
        self.assertIn("[INDIA_MARKET_CONTEXT] India smartphone shipments", report)
        self.assertIn("[TARGET_SEGMENT] Samsung held", report)

    def test_empty_search_results_stop_without_fabricated_evidence(self):
        with patch("agents.research_executor.create_research_plan", return_value={"research_goal": "x", "sub_questions": ["x"], "information_needed": ["market overview"], "search_queries": ["empty search"]}), \
             patch("agents.research_executor.search_web", return_value=[]):
            result = execute_research("Research a sample market")
        self.assertEqual(result["sources"], [])
        self.assertEqual(result["evidence"], [])
        self.assertTrue(result["missing_information"])
        self.assertIn("No article-level evidence", result["report"])

    def test_research_loop_deduplicates_and_obeys_budgets(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("database.store.DB_PATH", os.path.join(directory, "test.sqlite3")):
                from database import store
                store.init_db()
                run_id = "offline-test"
                store.create_run(run_id, "Analyze the sample market in India")
                plan = {"research_goal": "sample market", "sub_questions": ["who sells"], "information_needed": ["market overview"], "search_queries": ["sample market data", "sample market data"]}
                with patch("agents.research_executor.create_research_plan", return_value=plan), \
                     patch("agents.research_executor.search_web", return_value=[{"url": "https://example.com/a", "title": "Market report", "publisher": "Example"}, {"url": "https://example.com/a", "title": "Duplicate"}]), \
                     patch("agents.research_executor.fetch_document", return_value={"content": "The sample market grew 18% across India during 2025, according to the industry report. The sample market reached 4 million users in India during 2025, according to the industry report.", "final_url": "https://example.com/a", "content_type": "text/html"}):
                    result = execute_research("Analyze the sample market in India", research_id=run_id)
                self.assertLessEqual(result["iterations"], MAX_ITERATIONS)
                self.assertLessEqual(len(result["sources"]), MAX_SOURCES)
                self.assertEqual(len(result["sources"]), 1)
                self.assertTrue(result["report"])
                self.assertEqual(store.get_run(run_id)["status"], "completed")
                stored = store.get_evidence(run_id)
                self.assertEqual(len(stored), len(result["evidence"]))
                self.assertTrue(stored)
                self.assertTrue(all(row["evidence_scope"] in {"TARGET_SEGMENT", "INDIA_MARKET_CONTEXT", "GLOBAL_CONTEXT", "OUT_OF_SCOPE"} for row in stored))
                self.assertTrue(all(row["direct_support"] and row["quality_score"] > 0 and row["geographic_relevance"] > 0 and row["category_relevance"] > 0 and row["segment_relevance"] > 0 for row in stored))

    def test_research_source_budget_caps_at_fifteen(self):
        plan = {"research_goal": "x", "sub_questions": ["x"], "information_needed": ["market overview"], "search_queries": ["q1", "q2", "q3", "q4"]}
        def results(query, max_results=5):
            return [{"url": f"https://example.com/{query}/{i}", "title": "source"} for i in range(max_results)]
        with patch("agents.research_executor.create_research_plan", return_value=plan), patch("agents.research_executor.search_web", side_effect=results), patch("agents.research_executor.fetch_document", side_effect=RuntimeError("offline")):
            result = execute_research("Research sample market")
        self.assertEqual(len(result["sources"]), MAX_SOURCES)


if __name__ == "__main__": unittest.main()
