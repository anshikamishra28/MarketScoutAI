import type { ProductDiscoveryDiagnostics, ProductIdentity } from "../types/price-comparison";

interface Props {
  product: ProductIdentity;
  diagnostics: ProductDiscoveryDiagnostics;
}

function outcomeText(outcome: string, product: ProductIdentity): string {
  const label = [product.brand, product.model || product.model_number].filter(Boolean).join(" ") || "Requested product";
  switch (outcome) {
    case "exact_product_found": return `${label} matched an exact product identity.`;
    case "not_found_through_available_public_discovery": return `${label} not found through available public discovery.`;
    case "retailer_or_product_page_unavailable": return `${label}: retailer or product page unavailable.`;
    case "discovery_or_fetch_failed": return `${label}: discovery or page fetch failed.`;
    case "product_page_parse_failed": return `${label}: product page could not be parsed.`;
    case "ambiguous_product_variants": return `${label}: multiple variants matched; identity needs more detail.`;
    case "retailer_adapter_unavailable": return "This retailer does not have an active comparison adapter.";
    default: return `${label}: ${outcome.replaceAll("_", " ")}.`;
  }
}

export function DiscoveryDiagnostics({ product, diagnostics }: Props) {
  const strategies = diagnostics.strategies ?? [];
  const candidates = diagnostics.candidates ?? [];
  const fetched = candidates.filter((candidate) => candidate.fetched).length;
  return (
    <details className="diagnostics">
      <summary><span>{outcomeText(diagnostics.final_outcome, product)}</span><small>{strategies.length} strategies · {candidates.length} candidates · {fetched} fetched</small></summary>
      <div className="diagnostics-body">
        <h5>Discovery strategies</h5>
        {strategies.length ? <ul className="diagnostic-strategies">{strategies.map((strategy, index) => (
          <li key={`${strategy.source}-${index}`}><span className={`diagnostic-state ${strategy.success ? "ok" : "bad"}`}>{strategy.success ? "Completed" : "Failed"}</span>
            <strong>{strategy.source.replaceAll("_", " ")}</strong><span>{strategy.descriptor}</span>
            <small>{strategy.candidate_count} candidate{strategy.candidate_count === 1 ? "" : "s"}{strategy.error ? ` · ${strategy.error}` : ""}</small></li>
        ))}</ul> : <p className="muted">No discovery strategies were recorded.</p>}
        <h5>Candidates</h5>
        {candidates.length ? <ul className="diagnostic-candidates">{candidates.map((candidate) => (
          <li key={candidate.url}>
            <div className="candidate-heading"><span className={`diagnostic-state ${candidate.match === "matched" ? "ok" : candidate.match === "rejected" ? "bad" : ""}`}>{candidate.match}</span>
              <span>{candidate.fetched ? `Fetched${candidate.http_status ? ` · HTTP ${candidate.http_status}` : ""}` : "Not fetched"}</span></div>
            <a href={candidate.url} target="_blank" rel="noreferrer">{candidate.url}</a>
            {candidate.extracted_identity && <p>Page identity: {[candidate.extracted_identity.brand, candidate.extracted_identity.model, candidate.extracted_identity.model_number,
              candidate.extracted_identity.ram, candidate.extracted_identity.storage, candidate.extracted_identity.variant].filter(Boolean).join(" · ")}</p>}
            {candidate.rejection_reason && <p>Reason: {candidate.rejection_reason.replaceAll("_", " ")}</p>}
            {candidate.error && <p className="diagnostic-error">{candidate.error}</p>}
          </li>
        ))}</ul> : <p className="muted">No candidate product pages were found.</p>}
      </div>
    </details>
  );
}
