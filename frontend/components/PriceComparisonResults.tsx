import { DiscoveryDiagnostics } from "./DiscoveryDiagnostics";
import type { PriceComparisonResult, ProductIdentity, RetailerResult } from "../types/price-comparison";

function identityText(product: ProductIdentity): string {
  return [product.brand, product.model, product.model_number, product.ram, product.storage, product.variant].filter(Boolean).join(" · ");
}

function checkedDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function retailerLabel(result: RetailerResult, offersCount: number): string {
  if (result.status === "blocked") return "Retailer access blocked";
  if (result.status === "unavailable") return "Retailer or listing unavailable";
  if (result.status === "failed") return "Check failed";
  if (offersCount > 0) return "Price observed";
  const outcomes = result.diagnostics?.products.map((item) => item.discovery.final_outcome) ?? [];
  if (outcomes.includes("not_found_through_available_public_discovery")) return "No exact match found";
  if (outcomes.includes("product_page_parse_failed")) return "Product page could not be verified";
  if (outcomes.includes("exact_product_found")) return "Product found; no displayed price";
  return "Checked; no price offer";
}

interface Props { result: PriceComparisonResult }

export function PriceComparisonResults({ result }: Props) {
  return (
    <section className="comparison-results" aria-live="polite">
      <div className="comparison-results-head">
        <div><p className="eyebrow">COMPARISON RESULT</p><h2>Price observations</h2>
          <p className="comparison-id">ID · <code>{result.comparison_id}</code></p></div>
        <span className={`status ${result.status}`}>{result.status}</span>
      </div>
      {result.error && <p className="comparison-error" role="alert">{result.error}</p>}
      <div className="requested-products">
        <h3>Requested product identity</h3>
        {result.products.map((product, index) => <p key={`${product.brand}-${product.model}-${index}`}>{identityText(product)}</p>)}
      </div>
      {result.retailer_checks.length === 0 && <p className="empty-note">No retailer check result was returned.</p>}
      {result.retailer_checks.map((retailer) => {
        const offers = result.offers.filter((offer) => offer.retailer === retailer.retailer);
        return <article className="retailer-result" key={retailer.retailer}>
          <div className="retailer-result-head"><div><h3>{retailer.retailer}</h3><span className={`retailer-state ${retailer.status}`}>{retailerLabel(retailer, offers.length)}</span></div>
            <div className="retailer-checked"><small>Status · {retailer.status}</small><small>Checked · {checkedDate(retailer.checked_at)}</small></div></div>
          {retailer.message && <p className="retailer-message">{retailer.message}</p>}
          {offers.length ? <div className="offer-list">{offers.map((offer, index) => <div className="offer-row" key={`${offer.source_url}-${index}`}>
            <div className="offer-price">{offer.currency} {offer.price}</div>
            <div className="offer-identity"><strong>{identityText(offer.product)}</strong>
              {offer.seller && <span>Seller: {offer.seller}</span>}{offer.discount && <span>Offer: {offer.discount}</span>}
              <span>Observed: {checkedDate(offer.observed_at)}</span></div>
            <a href={offer.source_url} target="_blank" rel="noreferrer">View product page ↗</a>
          </div>)}</div> : <p className="no-offers">No accepted price observation is available for this retailer.</p>}
          {retailer.diagnostics?.products.map((item, index) => <DiscoveryDiagnostics key={`${item.product.brand}-${item.product.model}-${index}`} product={item.product} diagnostics={item.discovery} />)}
        </article>;
      })}
    </section>
  );
}
