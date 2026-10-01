from pathlib import Path
import unittest
from decimal import Decimal

import requests

from models.price_comparison import PriceOffer, ProductIdentity, RetailerResult, RetailerStatus
from tools.retailer_fetchers import RelianceDigitalFetcher, RetailerFetchOutcome
from tools.retailer_fetchers import reliance_digital


FIXTURE = Path(__file__).parent / "fixtures" / "reliance_digital_product.html"
NORD4_FIXTURE = Path(__file__).parent / "fixtures" / "reliance_digital_nord4_product.html"
NORD6_FIXTURE = Path(__file__).parent / "fixtures" / "reliance_digital_nord6_one_plus_brand.html"
PRODUCT_URL = "https://www.reliancedigital.in/product/example-nova-5g-742"
NORD4_URL = "https://www.reliancedigital.in/product/oneplus-nord-4-128-gb-8-gb-ram"
ROBOTS_TEXT = "User-agent: *\nDisallow: /*?*\nSitemap: https://www.reliancedigital.in/sitemap.xml\n"


class FixtureResponse:
    def __init__(self, text, url=PRODUCT_URL, status_code=200):
        self.text = text
        self.url = url
        self.status_code = status_code
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"
        self.content = text.encode("utf-8")

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f"HTTP {self.status_code}")
            error.response = self
            raise error


class RetailerFetcherTests(unittest.TestCase):
    def setUp(self):
        reliance_digital._SITEMAP_CACHE = None
        self.html = FIXTURE.read_text(encoding="utf-8")
        self.target = ProductIdentity(
            brand="Example", model="Nova 5G", model_number="EX-NOVA5G-IN",
            ram="8 GB", storage="256 GB", variant="Ocean Blue",
        )

    @staticmethod
    def unavailable_sitemap(url, headers, timeout):
        raise requests.ConnectionError("fixture: sitemap unavailable")

    def make_fetcher(self, html=None, status_code=200, search_results=None, fetch_error=None):
        results = search_results if search_results is not None else [{
            "url": PRODUCT_URL,
            # Deliberately false: snippets are not price observations.
            "snippet": "Example Nova 5G for ₹1 only",
        }]

        def searcher(query, max_results=5):
            self.assertIn("site:reliancedigital.in/product", query)
            return results

        def http_get(url, headers, timeout):
            if fetch_error:
                raise fetch_error
            return FixtureResponse(self.html if html is None else html, url=url, status_code=status_code)

        return RelianceDigitalFetcher(searcher=searcher, http_get=http_get, sitemap_get=self.unavailable_sitemap)

    def test_successful_extraction_has_decimal_price_and_exact_variant_identity(self):
        result = self.make_fetcher().fetch(self.target)
        self.assertEqual(result.check.status, RetailerStatus.CHECKED)
        self.assertEqual(len(result.offers), 1, result.check.message)
        offer = result.offers[0]
        self.assertEqual(offer.price, Decimal("27499.00"))
        self.assertEqual(offer.currency, "INR")
        self.assertEqual(offer.product.brand, "Example")
        self.assertEqual(offer.product.model, "Nova 5G")
        self.assertEqual(offer.product.model_number, "EX-NOVA5G-IN")
        self.assertEqual(offer.product.ram, "8 GB")
        self.assertEqual(offer.product.storage, "256 GB")
        self.assertEqual(offer.product.variant, "Ocean Blue")
        self.assertEqual(offer.source_url, PRODUCT_URL)
        self.assertTrue(offer.observed_at)

    def test_explicit_seller_and_discount_are_preserved(self):
        offer = self.make_fetcher().fetch(self.target).offers[0]
        self.assertEqual(offer.seller, "Reliance Retail")
        self.assertEqual(offer.discount, "Save ₹2,500 · 8% Off")

    def test_missing_optional_seller_and_discount_remain_empty(self):
        html = self.html.replace('<div class="offer-message">Save ₹2,500 · 8% Off</div>', "")
        html = html.replace('<div class="seller-name">Sold by Reliance Retail</div>', "")
        html = html.replace(',\n      "seller": {"@type": "Organization", "name": "Reliance Retail"}', "")
        offer = self.make_fetcher(html=html).fetch(self.target).offers[0]
        self.assertIsNone(offer.seller)
        self.assertIsNone(offer.discount)

    def test_missing_displayed_price_returns_checked_without_offer(self):
        html = self.html.replace('<div class="product-price">₹27,499.00</div>', '<div class="product-price">Price unavailable</div>')
        result = self.make_fetcher(html=html).fetch(self.target)
        self.assertEqual(result.check.status, RetailerStatus.CHECKED)
        self.assertIn("no displayed price", result.check.message.lower())
        self.assertEqual(result.offers, [])

    def test_blocked_and_failed_pages_return_status_without_prices(self):
        blocked = self.make_fetcher(status_code=403).fetch(self.target)
        self.assertEqual(blocked.check.status, RetailerStatus.BLOCKED)
        self.assertEqual(blocked.offers, [])

        failed = self.make_fetcher(fetch_error=requests.Timeout("timeout")).fetch(self.target)
        self.assertEqual(failed.check.status, RetailerStatus.FAILED)
        self.assertEqual(failed.offers, [])

    def test_missing_listing_is_unavailable(self):
        result = self.make_fetcher(search_results=[]).fetch(self.target)
        self.assertEqual(result.check.status, RetailerStatus.UNAVAILABLE)
        self.assertEqual(result.offers, [])

    def test_public_sitemap_selects_exact_model_and_deduplicates_product_urls(self):
        sitemap_url = "https://www.reliancedigital.in/sitemap/products/1/page.sitemap.xml"
        index = f"""<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <sitemap><loc>{sitemap_url}</loc></sitemap></sitemapindex>"""
        product_map = f"""<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>{NORD4_URL}</loc></url>
          <url><loc>{NORD4_URL}</loc></url>
          <url><loc>https://www.reliancedigital.in/product/oneplus-nord-6-128-gb-8-gb-ram</loc></url>
          <url><loc>https://www.reliancedigital.in/product/oneplus-nord-buds-4-earbuds</loc></url>
        </urlset>"""
        sitemap_calls = []
        page_calls = []

        def sitemap_get(url, headers, timeout):
            sitemap_calls.append(url)
            if url.endswith("robots.txt"):
                return FixtureResponse(ROBOTS_TEXT, url=url)
            if url == "https://www.reliancedigital.in/sitemap.xml":
                return FixtureResponse(index, url=url)
            return FixtureResponse(product_map, url=url)

        html = NORD4_FIXTURE.read_text(encoding="utf-8")

        def http_get(url, headers, timeout):
            page_calls.append(url)
            return FixtureResponse(html, url=url)

        fetcher = RelianceDigitalFetcher(
            searcher=lambda query, max_results=5: self.fail("search should not run when sitemap has exact-model candidates"),
            http_get=http_get,
            sitemap_get=sitemap_get,
        )
        result = fetcher.fetch(ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="128GB"))

        self.assertEqual(page_calls, [NORD4_URL], result.check.message)
        self.assertEqual(sitemap_calls, [
            "https://www.reliancedigital.in/robots.txt",
            "https://www.reliancedigital.in/sitemap.xml",
            sitemap_url,
        ])
        self.assertEqual(result.check.status, RetailerStatus.CHECKED)
        self.assertEqual(len(result.offers), 1)
        diag = result.check.diagnostics
        self.assertEqual(diag["strategies"][0]["source"], "sitemap")
        self.assertTrue(diag["strategies"][0]["success"])
        self.assertEqual(diag["candidates"][0]["discovered_by"], ["sitemap"])
        self.assertEqual(diag["candidates"][0]["match"], "matched")
        self.assertTrue(diag["exact_product_found"])
        self.assertEqual(diag["final_outcome"], "exact_product_found")
        self.assertNotIn("price", str(diag).lower())

    def test_sitemap_token_overlap_does_not_select_different_products(self):
        sitemap_url = "https://www.reliancedigital.in/sitemap/products/1/page.sitemap.xml"
        index = f"<sitemapindex><sitemap><loc>{sitemap_url}</loc></sitemap></sitemapindex>"
        product_map = """<urlset>
          <url><loc>https://www.reliancedigital.in/product/oneplus-nord-6-128-gb</loc></url>
          <url><loc>https://www.reliancedigital.in/product/oneplus-nord-ce6-128-gb</loc></url>
          <url><loc>https://www.reliancedigital.in/product/oneplus-nord-buds-4</loc></url>
          <url><loc>https://www.reliancedigital.in/product/samsung-phone-8-gb-128-gb</loc></url>
        </urlset>"""
        def sitemap_get(url, headers, timeout):
            if url.endswith("robots.txt"):
                return FixtureResponse(ROBOTS_TEXT, url=url)
            return FixtureResponse(index if url == "https://www.reliancedigital.in/sitemap.xml" else product_map, url=url)

        searched = []
        fetched = []

        def searcher(query, max_results=5):
            searched.append(query)
            return []

        def http_get(url, headers, timeout):
            fetched.append(url)
            raise AssertionError("overlapping but different products must not be selected")

        result = RelianceDigitalFetcher(searcher=searcher, http_get=http_get, sitemap_get=sitemap_get).fetch(
            ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="128GB")
        )
        self.assertEqual(fetched, [])
        self.assertGreater(len(searched), 0)  # targeted web search is the fallback on a sitemap miss
        self.assertEqual(result.check.status, RetailerStatus.UNAVAILABLE)
        self.assertEqual(result.offers, [])

    def test_sitemap_failure_uses_existing_targeted_web_search_fallback(self):
        search_calls = []

        def sitemap_get(url, headers, timeout):
            if url.endswith("robots.txt"):
                return FixtureResponse(ROBOTS_TEXT, url=url)
            raise requests.Timeout("fixture sitemap timeout")

        def searcher(query, max_results=5):
            search_calls.append(query)
            return [{"url": NORD4_URL, "snippet": "snippet price is ignored"}]

        html = NORD4_FIXTURE.read_text(encoding="utf-8")
        fetcher = RelianceDigitalFetcher(
            searcher=searcher,
            http_get=lambda url, headers, timeout: FixtureResponse(html, url=url),
            sitemap_get=sitemap_get,
        )
        result = fetcher.fetch(ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="128GB"))

        self.assertGreater(len(search_calls), 0)
        self.assertEqual(result.check.status, RetailerStatus.CHECKED)
        self.assertEqual(len(result.offers), 1)
        self.assertEqual(result.offers[0].price, Decimal("29999.00"))
        diag = result.check.diagnostics
        self.assertFalse(diag["strategies"][0]["success"])
        self.assertTrue(any(item["source"] == "targeted_search" and item["success"] for item in diag["strategies"]))
        self.assertEqual(diag["candidates"][0]["discovered_by"], ["targeted_search"])
        self.assertEqual(diag["candidates"][0]["match"], "matched")

    def test_diagnostics_record_model_and_capacity_rejection_reasons(self):
        url = "https://www.reliancedigital.in/product/example-nova-5g-742"
        fetcher = self.make_fetcher()
        model_result = fetcher.fetch(ProductIdentity("Example", "Nova 6", ram="8 GB", storage="256 GB"))
        self.assertEqual(model_result.check.diagnostics["candidates"][0]["rejection_reason"], "model_mismatch")
        ram_result = fetcher.fetch(ProductIdentity("Example", "Nova 5G", ram="12 GB", storage="256 GB"))
        self.assertEqual(ram_result.check.diagnostics["candidates"][0]["rejection_reason"], "ram_mismatch")
        storage_result = fetcher.fetch(ProductIdentity("Example", "Nova 5G", ram="8 GB", storage="128 GB"))
        self.assertEqual(storage_result.check.diagnostics["candidates"][0]["rejection_reason"], "storage_mismatch")

    def test_diagnostics_distinguish_total_discovery_failure(self):
        def failed_search(query, max_results=5):
            raise requests.Timeout("fixture search timeout")

        result = RelianceDigitalFetcher(searcher=failed_search, sitemap_get=self.unavailable_sitemap).fetch(
            ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="128GB")
        )
        self.assertEqual(result.check.diagnostics["final_outcome"], "discovery_or_fetch_failed")
        self.assertTrue(all(not strategy["success"] for strategy in result.check.diagnostics["strategies"]))
        self.assertEqual(result.check.diagnostics["candidates"], [])

    def test_targeted_fallback_query_finds_exact_listing_and_deduplicates_urls(self):
        exact_url = "https://www.reliancedigital.in/product/oneplus-nord-4-128gb-8gb"
        exact_html = '''<html><head><script type="application/ld+json">
        {"@type":"Product","name":"OnePlus Nord 4 128 GB, 8 GB RAM, Mercurial Silver",
         "brand":{"name":"OnePlus"},"offers":{"priceCurrency":"INR","price":"29999",
         "seller":{"name":"Reliance Retail"}}}
        </script></head><body><main><div class="product-price">Rs. 29,999</div></main></body></html>'''
        queries = []
        fetched = []

        def searcher(query, max_results=5):
            queries.append(query)
            if len(queries) == 1:
                return [{"url": PRODUCT_URL, "snippet": "Wrong Example product"}]
            if len(queries) == 2:
                return [{"url": exact_url}, {"url": exact_url}]
            return [{"url": exact_url}]

        def http_get(url, headers, timeout):
            fetched.append(url)
            html = exact_html if url == exact_url else self.html
            return FixtureResponse(html, url=url)

        result = RelianceDigitalFetcher(searcher=searcher, http_get=http_get, sitemap_get=self.unavailable_sitemap).fetch(
            ProductIdentity("OnePlus", "Nord 4", ram="8 GB", storage="128 GB")
        )

        self.assertGreaterEqual(len(queries), 2)
        self.assertIn('"OnePlus Nord 4"', queries[0])
        self.assertIn('"8 GB RAM"', queries[0])
        self.assertIn('"128 GB"', queries[0])
        self.assertEqual(fetched.count(exact_url), 1)
        self.assertEqual(result.check.status, RetailerStatus.CHECKED)
        self.assertEqual(len(result.offers), 1, result.check.message)
        self.assertEqual(result.offers[0].product.model, "Nord 4")
        self.assertEqual(result.offers[0].product.ram, "8 GB")
        self.assertEqual(result.offers[0].product.storage, "128 GB")
        self.assertEqual(result.offers[0].price, Decimal("29999"))

    def test_api_capacity_format_matches_nord4_fixture_and_reads_unicode_rupee(self):
        url = "https://www.reliancedigital.in/product/oneplus-nord-4-128-gb-8-gb-ram"
        html = NORD4_FIXTURE.read_text(encoding="utf-8")
        fetcher = RelianceDigitalFetcher(
            searcher=lambda query, max_results=5: [{"url": url}],
            http_get=lambda requested_url, headers, timeout: FixtureResponse(html, url=requested_url),
            sitemap_get=self.unavailable_sitemap,
        )
        result = fetcher.fetch(ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="128GB"))

        self.assertEqual(result.check.status, RetailerStatus.CHECKED)
        self.assertEqual(len(result.offers), 1, result.check.message)
        offer = result.offers[0]
        self.assertEqual(offer.product.ram, "8 GB")
        self.assertEqual(offer.product.storage, "128 GB")
        self.assertEqual(offer.price, Decimal("29999.00"))

    def test_brand_match_ignores_only_case_and_whitespace(self):
        html = NORD6_FIXTURE.read_text(encoding="utf-8")
        url = "https://www.reliancedigital.in/product/oneplus-nord-6-8gb-256gb"

        def run(brand):
            fetcher = RelianceDigitalFetcher(
                searcher=lambda query, max_results=5: [{"url": url}],
                http_get=lambda requested_url, headers, timeout: FixtureResponse(html, url=requested_url),
                sitemap_get=self.unavailable_sitemap,
            )
            return fetcher.fetch(ProductIdentity(brand, "Nord 6", ram="8GB", storage="256GB"))

        for brand in ("OnePlus", "ONE PLUS", "  one   plus  "):
            with self.subTest(brand=brand):
                result = run(brand)
                self.assertEqual(len(result.offers), 1, result.check.diagnostics)
                self.assertEqual(result.offers[0].product.brand, "One Plus")

    def test_unrelated_and_extended_brand_names_do_not_match(self):
        html = NORD6_FIXTURE.read_text(encoding="utf-8")
        url = "https://www.reliancedigital.in/product/oneplus-nord-6-8gb-256gb"
        for brand in ("Samsung", "OnePlus Nord", "Samsung Galaxy"):
            with self.subTest(brand=brand):
                fetcher = RelianceDigitalFetcher(
                    searcher=lambda query, max_results=5: [{"url": url}],
                    http_get=lambda requested_url, headers, timeout: FixtureResponse(html, url=requested_url),
                    sitemap_get=self.unavailable_sitemap,
                )
                result = fetcher.fetch(ProductIdentity(brand, "Nord 6", ram="8GB", storage="256GB"))
                self.assertEqual(result.offers, [])
                self.assertEqual(result.check.diagnostics["candidates"][0]["rejection_reason"], "brand_mismatch")

    def test_nord6_one_plus_brand_variant_matches_and_wrong_ram_is_rejected(self):
        html = NORD6_FIXTURE.read_text(encoding="utf-8")
        url = "https://www.reliancedigital.in/product/oneplus-nord-6-8gb-256gb"

        def fetch(ram):
            adapter = RelianceDigitalFetcher(
                searcher=lambda query, max_results=5: [{"url": url}],
                http_get=lambda requested_url, headers, timeout: FixtureResponse(html, url=requested_url),
                sitemap_get=self.unavailable_sitemap,
            )
            return adapter.fetch(ProductIdentity("OnePlus", "Nord 6", ram=ram, storage="256 GB"))

        matching = fetch("8 GB")
        self.assertEqual(len(matching.offers), 1, matching.check.diagnostics)
        self.assertEqual(matching.offers[0].product.model, "Nord 6 5G")
        self.assertEqual(matching.offers[0].product.brand, "One Plus")
        self.assertEqual(matching.offers[0].price, Decimal("46999.00"))
        mismatch = fetch("12GB")
        self.assertEqual(mismatch.offers, [])
        self.assertEqual(mismatch.check.diagnostics["candidates"][0]["rejection_reason"], "ram_mismatch")

    def test_different_ram_or_storage_does_not_match_nord4_fixture(self):
        url = "https://www.reliancedigital.in/product/oneplus-nord-4-128-gb-8-gb-ram"
        html = NORD4_FIXTURE.read_text(encoding="utf-8")
        fetcher = RelianceDigitalFetcher(
            searcher=lambda query, max_results=5: [{"url": url}],
            http_get=lambda requested_url, headers, timeout: FixtureResponse(html, url=requested_url),
            sitemap_get=self.unavailable_sitemap,
        )
        for product in (
            ProductIdentity("OnePlus", "Nord 4", ram="12GB", storage="128GB"),
            ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="256GB"),
        ):
            with self.subTest(ram=product.ram, storage=product.storage):
                result = fetcher.fetch(product)
                self.assertEqual(result.check.status, RetailerStatus.CHECKED)
                self.assertEqual(result.offers, [])

    def test_legacy_mojibake_rupee_price_representation_remains_supported(self):
        html = NORD4_FIXTURE.read_text(encoding="utf-8").replace("₹29,999.00", "â‚¹29,999.00")
        url = "https://www.reliancedigital.in/product/oneplus-nord-4-128-gb-8-gb-ram"
        fetcher = RelianceDigitalFetcher(
            searcher=lambda query, max_results=5: [{"url": url}],
            http_get=lambda requested_url, headers, timeout: FixtureResponse(html, url=requested_url),
            sitemap_get=self.unavailable_sitemap,
        )
        result = fetcher.fetch(ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="128GB"))
        self.assertEqual(len(result.offers), 1)
        self.assertEqual(result.offers[0].price, Decimal("29999.00"))

    def test_discovery_continues_when_one_search_strategy_raises(self):
        calls = []

        def searcher(query, max_results=5):
            calls.append(query)
            if len(calls) == 1:
                raise requests.Timeout("first strategy timed out")
            return []

        result = RelianceDigitalFetcher(searcher=searcher, sitemap_get=self.unavailable_sitemap).fetch(
            ProductIdentity("OnePlus", "Nord 4", ram="8GB", storage="128GB")
        )
        self.assertGreater(len(calls), 1)
        self.assertEqual(result.check.status, RetailerStatus.UNAVAILABLE)
        self.assertEqual(result.offers, [])

    def test_mismatched_and_ambiguous_products_are_not_matched(self):
        mismatch = ProductIdentity(brand="Other", model="Nova 5G")
        no_match = self.make_fetcher().fetch(mismatch)
        self.assertEqual(no_match.check.status, RetailerStatus.CHECKED)
        self.assertEqual(no_match.offers, [])

        green_html = self.html.replace("Ocean Blue", "Forest Green")
        results = [{"url": PRODUCT_URL, "snippet": "₹1"}, {"url": "https://www.reliancedigital.in/product/other-variant", "snippet": "₹2"}]
        broad_target = ProductIdentity(brand="Example", model="Nova 5G")
        def searcher(query, max_results=5):
            return results

        def http_get(url, headers, timeout):
            page = self.html if url == PRODUCT_URL else green_html
            return FixtureResponse(page, url=url)

        ambiguous = RelianceDigitalFetcher(searcher=searcher, http_get=http_get, sitemap_get=self.unavailable_sitemap).fetch(broad_target)
        self.assertEqual(ambiguous.check.status, RetailerStatus.CHECKED)
        self.assertIn("Multiple product variants", ambiguous.check.message)
        self.assertEqual(ambiguous.offers, [])

    def test_non_success_retailer_result_cannot_carry_an_offer(self):
        offer = PriceOffer("Reliance Digital", self.target, 27499, PRODUCT_URL)
        with self.assertRaisesRegex(ValueError, "only a checked retailer"):
            RetailerFetchOutcome(RetailerResult("Reliance Digital", "blocked"), [offer])

if __name__ == "__main__":
    unittest.main()
