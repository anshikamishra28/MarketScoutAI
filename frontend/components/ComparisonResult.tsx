import type { ComparisonAnalysis, ComparisonResult as ComparisonResultData, JsonValue } from "../types/comparison";

interface ComparisonResultProps {
  result: ComparisonResultData | null;
  comparisonId?: string;
  status?: string;
  loading?: boolean;
  error?: string;
}

function displayValue(value: JsonValue | undefined): string {
  if (value === undefined) return "Not available";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function structuredAnalysis(value: ComparisonResultData["analysis"]): ComparisonAnalysis | null {
  if (value && typeof value === "object" && "attributes" in value && Array.isArray(value.attributes)) {
    return value as ComparisonAnalysis;
  }
  return null;
}

export function ComparisonResult({ result, comparisonId, status, loading = false, error = "" }: ComparisonResultProps) {
  if (!result && !comparisonId && !loading && !error) return null;
  const analysis = result ? structuredAnalysis(result.analysis) : null;
  const displayStatus = result?.status ?? status ?? "queued";

  return (
    <section className="generic-result" aria-live="polite" aria-labelledby="generic-result-title">
      <div className="generic-result-heading">
        <div>
          <p className="eyebrow">COMPARISON RESULT</p>
          <h2 id="generic-result-title">Comparison progress and findings</h2>
          {(result?.comparison_id ?? comparisonId) && <p className="generic-result-id">ID - {result?.comparison_id ?? comparisonId}</p>}
        </div>
        <span className={`generic-status ${displayStatus}`}>{displayStatus}</span>
      </div>

      {loading && <p className="generic-muted">Starting comparison...</p>}
      {error && <p className="generic-error" role="alert">{error}</p>}
      {result?.errors.map((item, index) => <p className="generic-error" key={`${item}-${index}`}>{item}</p>)}

      {result && <>
        <div className="generic-result-section">
          <h3>Entities</h3>
          {result.entities.length ? <ul className="generic-chip-list">{result.entities.map((entity) => <li className="generic-entity-result" key={entity.key}>
            <strong>{entity.display_name}</strong>
            {Object.entries(entity.identifiers ?? {}).length > 0 && <dl className="generic-identifier-summary">
              {Object.entries(entity.identifiers ?? {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>)}
            </dl>}
          </li>)}</ul> : <p className="generic-muted">No entities were resolved or supplied.</p>}
        </div>

        <div className="generic-result-section">
          <h3>Requested attributes and observations</h3>
          {!result.attributes.length && <p className="generic-muted">No attributes were supplied.</p>}
          {result.attributes.map((attribute) => {
            const analyzed = analysis?.attributes.find((item) => item.attribute_key === attribute.key);
            return (
              <article className="generic-attribute-result" key={attribute.key}>
                <div className="generic-attribute-heading">
                  <h4>{attribute.label}</h4>
                  <span>{analyzed?.status ?? "analysis pending"}</span>
                </div>
                <ul className="generic-observation-list">
                  {result.entities.map((entity) => {
                    const observations = result.observations.filter((item) => item.entity_key === entity.key && item.attribute_key === attribute.key);
                    return <li key={entity.key}>
                      <strong>{entity.display_name}</strong>
                      {observations.length ? observations.map((observation, index) => {
                        const sourceName = result.source_checks.find((check) => check.source.key === observation.source_key)?.source.name ?? observation.source_key;
                        return <div className="generic-observed-value" key={`${observation.source_key}-${observation.observed_at}-${index}`}>
                          <span>{displayValue(observation.raw_value)}</span>
                          {observation.normalized_value !== null && observation.normalized_value !== undefined && <small>Normalized: {displayValue(observation.normalized_value)}</small>}
                          <small>Source: {sourceName}{observation.unit ? ` - ${observation.unit}` : ""}{observation.currency ? ` - ${observation.currency}` : ""}</small>
                          {observation.source_url && <a href={observation.source_url} target="_blank" rel="noreferrer">View source</a>}
                        </div>;
                      }) : <span className="generic-unresolved">Unresolved / no observation</span>}
                    </li>;
                  })}
                </ul>
                {analyzed?.winner_entity_key && <p className="generic-analysis-note">Selected by comparison rule: {result.entities.find((entity) => entity.key === analyzed.winner_entity_key)?.display_name ?? analyzed.winner_entity_key}</p>}
                {analyzed?.limitations.map((limitation) => <p className="generic-analysis-note" key={limitation}>{limitation}</p>)}
              </article>
            );
          })}
        </div>

        <div className="generic-result-section">
          <h3>Unresolved information</h3>
          {result.unresolved.length || analysis?.unresolved_information.length ? <ul className="generic-unresolved-list">
            {[...new Set([...result.unresolved, ...(analysis?.unresolved_information ?? [])])].map((item) => <li key={item}>{item}</li>)}
          </ul> : <p className="generic-muted">No unresolved information was reported.</p>}
        </div>

        <div className="generic-result-section">
          <h3>Sources checked</h3>
          {result.source_checks.length ? <ul className="generic-source-checks">{result.source_checks.map((check) => <li key={check.source.key}>
            <span>{check.source.name}</span><strong className={`source-state ${check.status}`}>{check.status}</strong>{check.error && <small>{check.error}</small>}
          </li>)}</ul> : <p className="generic-muted">No source checks were returned.</p>}
        </div>

        <p className="generic-analysis-availability">{analysis ? "Structured deterministic analysis is available." : result.analysis ? "An analysis result is present in an older or unrecognized format." : "Analysis is not available yet."}</p>
      </>}
    </section>
  );
}
