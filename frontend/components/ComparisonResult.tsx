import type { ComparisonAnalysis, ComparisonResult as ResultData, JsonValue, Observation } from "../types/comparison";

interface Props { result: ResultData | null; comparisonId?: string; status?: string; loading?: boolean; error?: string }
function valueText(value: JsonValue | undefined): string { return value === undefined || value === null ? "" : typeof value === "string" ? value : JSON.stringify(value); }
function analysisOf(value: ResultData["analysis"]): ComparisonAnalysis | null {
  return value && typeof value === "object" && "attributes" in value && Array.isArray(value.attributes) ? value as ComparisonAnalysis : null;
}
function sourceName(result: ResultData, observation: Observation): string {
  return result.source_checks.find((check) => check.source.key === observation.source_key)?.source.name ?? "Source";
}
function checkedRetailer(result: ResultData, sourceKey: string): boolean {
  return result.source_checks.some((check) => check.source.key === sourceKey && check.source.source_type === "retailer" && (check.status === "checked" || check.status === "partial"));
}
function validSourceUrl(value: string | null | undefined): value is string {
  return typeof value === "string" && /^https?:\/\//i.test(value);
}

export function ComparisonResult({ result, comparisonId, status, loading = false, error = "" }: Props) {
  if (!result && !comparisonId && !loading && !error) return null;
  const analysis = result ? analysisOf(result.analysis) : null;
  const phase = result?.status ?? status ?? "queued";
  const phaseLabel = phase === "queued" || phase === "running" ? "Comparing products..." : phase;
  const priceAttribute = result?.attributes.find((item) => item.key.toLowerCase() === "price" || item.label.toLowerCase() === "price");
  const availabilityAttribute = result?.attributes.find((item) => item.key.toLowerCase() === "availability" || item.label.toLowerCase() === "availability");
  const purchaseRows = result?.observations.filter((item) => priceAttribute && item.attribute_key === priceAttribute.key && validSourceUrl(item.source_url) && checkedRetailer(result, item.source_key)) ?? [];
  const sourceLinks = result ? Array.from(new Map(result.observations.filter((item) => validSourceUrl(item.source_url)).map((item) => [`${item.source_key}|${item.source_url}`, item])).values()) : [];

  return <section className="generic-result" aria-live="polite" aria-labelledby="comparison-result-title">
    <header className="generic-result-heading"><div><p className="eyebrow">YOUR COMPARISON</p><h2 id="comparison-result-title">Comparison</h2></div><span className={`generic-status ${phase}`}>{phaseLabel}</span></header>
    {loading && <p className="generic-muted">Comparing products...</p>}
    {(error || result?.status === "failed" || !!result?.errors.length) && <p className="generic-error" role="alert">We couldn't complete this comparison. Please try again.</p>}
    {result && <>
      <section className="comparison-summary"><h3>Summary</h3>{analysis?.attributes.length ? <ul>{analysis.attributes.map((attribute) => {
        const observed = attribute.entities.filter((entity) => entity.status === "observed").length;
        const complete = observed === result.entities.length && result.entities.length > 0;
        return <li key={attribute.attribute_key}><strong>{attribute.label}:</strong> {complete ? `Information verified for all ${observed} products.` : `Information verified for ${observed} of ${result.entities.length} products.`}</li>;
      })}</ul> : <p>Verified information is shown in the table below.</p>}</section>
      <section className="comparison-table-section"><h3>Product comparison</h3>{result.entities.length && result.attributes.length ? <div className="generic-table-scroll"><table className="generic-comparison-table"><thead><tr><th scope="col">Attribute</th>{result.entities.map((entity) => <th scope="col" key={entity.key}>{entity.display_name}</th>)}</tr></thead><tbody>{result.attributes.map((attribute) => <tr key={attribute.key}><th scope="row">{attribute.label}{attribute.unit && <small>{attribute.unit}</small>}</th>{result.entities.map((entity) => {
        const values = result.observations.filter((observation) => observation.entity_key === entity.key && observation.attribute_key === attribute.key);
        const attrAnalysis = analysis?.attributes.find((a) => a.attribute_key === attribute.key);
        const entityAnalysis = attrAnalysis?.entities.find((e) => e.entity_key === entity.key);
        const isVerified = entityAnalysis ? entityAnalysis.status === "observed" : values.length > 0;
        return <td key={entity.key}>{isVerified && values.length ? <div className="comparison-observed-values">{values.map((item, index) => <strong key={`${item.source_key}-${item.observed_at}-${index}`}>{valueText(item.raw_value)}</strong>)}</div> : <span className="generic-no-observation">Not verified</span>}</td>;
      })}</tr>)}</tbody></table></div> : <p>No comparison details were returned.</p>}</section>
      {result.status === "completed" && <section className="where-to-buy"><h3>Where to Buy</h3>{purchaseRows.length ? <div className="generic-table-scroll"><table className="generic-comparison-table"><thead><tr><th>Product</th><th>Store</th><th>Price</th><th>Availability</th><th>Link</th></tr></thead><tbody>{purchaseRows.map((item, index) => { const availability = availabilityAttribute && result.observations.find((candidate) => candidate.entity_key === item.entity_key && candidate.attribute_key === availabilityAttribute.key && candidate.source_key === item.source_key); const availAttr = analysis?.attributes.find((a) => a.attribute_key === availabilityAttribute?.key); const availEntity = availAttr?.entities.find((e) => e.entity_key === item.entity_key); const isAvailVerified = availEntity ? availEntity.status === "observed" : !!availability; return <tr key={`${item.entity_key}-${item.source_key}-${index}`}><th>{result.entities.find((entity) => entity.key === item.entity_key)?.display_name ?? "Product"}</th><td>{sourceName(result, item)}</td><td>{valueText(item.raw_value)}</td><td>{isAvailVerified && availability ? valueText(availability.raw_value) : "Not verified"}</td><td><a href={item.source_url!} target="_blank" rel="noreferrer">Buy</a></td></tr>; })}</tbody></table></div> : <p>Shopping links aren’t available for this comparison yet.</p>}</section>}
      {!!sourceLinks.length && <details className="comparison-source-details"><summary>View sources ({sourceLinks.length})</summary><ul>{sourceLinks.map((item, index) => <li key={`${item.source_key}-${item.source_url}-${index}`}><span>{result.entities.find((entity) => entity.key === item.entity_key)?.display_name ?? "Product"} · {result.attributes.find((attribute) => attribute.key === item.attribute_key)?.label ?? "Detail"} · {sourceName(result, item)}</span><a href={item.source_url ?? "#"} target="_blank" rel="noreferrer">Open source</a></li>)}</ul></details>}
    </>}
  </section>;
}
