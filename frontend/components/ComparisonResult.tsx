import type { AttributeAnalysis, ComparisonAnalysis, ComparisonResult as ComparisonResultData, JsonValue, Observation } from "../types/comparison";

interface ComparisonResultProps {
  result: ComparisonResultData | null;
  comparisonId?: string;
  status?: string;
  loading?: boolean;
  error?: string;
}

function displayValue(value: JsonValue | undefined): string {
  if (value === undefined) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function structuredAnalysis(value: ComparisonResultData["analysis"]): ComparisonAnalysis | null {
  if (value && typeof value === "object" && "attributes" in value && Array.isArray(value.attributes)) {
    return value as ComparisonAnalysis;
  }
  return null;
}

function attributeForObservation(result: ComparisonResultData, observation: Observation): string {
  return result.attributes.find((attribute) => attribute.key === observation.attribute_key)?.label ?? observation.attribute_key;
}

function entityForObservation(result: ComparisonResultData, observation: Observation): string {
  return result.entities.find((entity) => entity.key === observation.entity_key)?.display_name ?? observation.entity_key;
}

function observationSource(result: ComparisonResultData, observation: Observation): string {
  return result.source_checks.find((check) => check.source.key === observation.source_key)?.source.name ?? observation.source_key;
}

function entityAnalysis(attribute: AttributeAnalysis | undefined, entityKey: string) {
  return attribute?.entities.find((entity) => entity.entity_key === entityKey);
}

function ruleLabel(rule: string | null): string {
  if (rule === "lower_is_better") return "Lower is better";
  if (rule === "higher_is_better") return "Higher is better";
  return rule ?? "No comparison rule";
}

function AnalysisFindings({ analysis }: { analysis: ComparisonAnalysis | null }) {
  if (!analysis) {
    return <p className="generic-empty">Structured analysis is not available for this result.</p>;
  }
  if (!analysis.attributes.length) {
    return <p className="generic-empty">No attribute analysis was returned.</p>;
  }

  return <div className="generic-findings-list">
    {analysis.attributes.map((attribute) => (
      <article className="generic-finding" key={attribute.attribute_key}>
        <div className="generic-finding-heading">
          <div><h4>{attribute.label}</h4><span>{ruleLabel(attribute.comparison_rule)}</span></div>
          <span className={`generic-result-badge ${attribute.status}`}>{attribute.status}</span>
        </div>
        {attribute.ranking.length > 0 && <ol className="generic-ranking">
          {attribute.ranking.map((item) => <li key={item.entity_key}>
            <span>{item.rank}</span><strong>{attribute.entities.find((entity) => entity.entity_key === item.entity_key)?.entity_name ?? item.entity_key}</strong>
            <span>{displayValue(item.value)}</span>
          </li>)}
        </ol>}
        {attribute.winner_entity_key && <p className="generic-winner">Backend analysis selection: {attribute.entities.find((entity) => entity.entity_key === attribute.winner_entity_key)?.entity_name ?? attribute.winner_entity_key}</p>}
        {!attribute.ranking.length && <p className="generic-no-ranking">{attribute.status === "unresolved" ? "No ranking provided; required observation data is incomplete." : "No ranking was provided by the analysis."}</p>}
        <div className="generic-finding-values">
          {attribute.entities.map((entity) => <div className="generic-finding-value" key={entity.entity_key}>
            <div><strong>{entity.entity_name}</strong><span className={`generic-result-badge ${entity.status}`}>{entity.status}</span></div>
            <p>{entity.comparable_value === null ? "No comparable value" : displayValue(entity.comparable_value)}</p>
            {entity.note && <small>{entity.note}</small>}
          </div>)}
        </div>
        {attribute.limitations.map((limitation) => <p className="generic-analysis-limitation" key={limitation}>{limitation}</p>)}
      </article>
    ))}
  </div>;
}

function EntityIdentity({ result }: { result: ComparisonResultData }) {
  if (!result.entities.length) return <p className="generic-empty">No entities were supplied or resolved.</p>;
  return <div className="generic-entity-cards">
    {result.entities.map((entity) => (
      <article className="generic-entity-card" key={entity.key}>
        <h4>{entity.display_name}</h4>
        {entity.entity_type && <span className="generic-entity-type">{entity.entity_type}</span>}
        {Object.keys(entity.identifiers ?? {}).length > 0 ? <dl className="generic-identifier-summary">
          {Object.entries(entity.identifiers ?? {}).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>)}
        </dl> : <p className="generic-no-identifiers">No identifiers supplied.</p>}
      </article>
    ))}
  </div>;
}

function AttributeMatrix({ result, analysis }: { result: ComparisonResultData; analysis: ComparisonAnalysis | null }) {
  if (!result.attributes.length) return <p className="generic-empty">No comparison attributes were supplied.</p>;
  return <div className="generic-table-scroll"><table className="generic-comparison-table">
    <thead><tr><th scope="col">Attribute</th>{result.entities.map((entity) => <th scope="col" key={entity.key}>{entity.display_name}</th>)}</tr></thead>
    <tbody>{result.attributes.map((attribute) => {
      const analyzed = analysis?.attributes.find((item) => item.attribute_key === attribute.key);
      return <tr key={attribute.key}>
        <th scope="row">{attribute.label}<small>{attribute.value_type}{attribute.unit ? ` - ${attribute.unit}` : ""}{attribute.currency ? ` - ${attribute.currency}` : ""}</small></th>
        {result.entities.map((entity) => {
          const observations = result.observations.filter((item) => item.entity_key === entity.key && item.attribute_key === attribute.key);
          const analysisEntry = entityAnalysis(analyzed, entity.key);
          return <td key={entity.key}>
            {observations.length ? <div className="generic-matrix-values">
              {observations.map((observation, index) => <div key={`${observation.source_key}-${observation.observed_at}-${index}`}>
                <strong>{displayValue(observation.raw_value)}</strong>
                {observation.unit && <small>{observation.unit}</small>}
                {observation.currency && <small>{observation.currency}</small>}
              </div>)}
              {analysisEntry?.status === "conflicting" && <span className="generic-result-badge conflicting">Conflicting observations</span>}
            </div> : <span className="generic-no-observation">No verified observation available.</span>}
          </td>;
        })}
      </tr>;
    })}</tbody>
  </table></div>;
}

function UnresolvedSection({ result, analysis }: { result: ComparisonResultData; analysis: ComparisonAnalysis | null }) {
  const details: string[] = [...result.unresolved];
  for (const attribute of analysis?.attributes ?? []) {
    for (const entity of attribute.entities) {
      if (entity.status === "unresolved" || entity.status === "conflicting") {
        const detail = `${entity.entity_name} - ${attribute.label}: ${entity.note ?? (entity.status === "conflicting" ? "Source observations conflict; no value was selected." : "No verified observation available.")}`;
        details.push(detail);
      }
    }
  }
  for (const item of analysis?.unresolved_information ?? []) details.push(item);
  const uniqueDetails = [...new Set(details)];

  return uniqueDetails.length ? <ul className="generic-unresolved-list">
    {uniqueDetails.map((item) => <li key={item}>{item}</li>)}
  </ul> : <p className="generic-empty">No unresolved information was reported.</p>;
}

function EvidenceList({ result }: { result: ComparisonResultData }) {
  if (!result.observations.length) return <p className="generic-empty">No verified observations were returned.</p>;
  return <div className="generic-evidence-list">
    {result.observations.map((observation, index) => {
      const identity = `${observation.entity_key}-${observation.attribute_key}-${observation.source_key}-${observation.observed_at}-${index}`;
      return <article className="generic-evidence-item" key={identity}>
        <div className="generic-evidence-topline"><span>{entityForObservation(result, observation)}</span><span>{attributeForObservation(result, observation)}</span></div>
        <p className="generic-evidence-value">{displayValue(observation.raw_value)}</p>
        {observation.normalized_value !== undefined && observation.normalized_value !== null && <p className="generic-evidence-normalized">Normalized value: {displayValue(observation.normalized_value)}</p>}
        <div className="generic-evidence-meta">
          <span>Source: {observationSource(result, observation)} <small>({observation.source_key})</small></span>
          {observation.observed_at && <span>Observed: {observation.observed_at}</span>}
          {observation.source_url && <a href={observation.source_url} target="_blank" rel="noreferrer">Open source</a>}
        </div>
        {observation.context && Object.keys(observation.context).length > 0 && <details className="generic-evidence-context">
          <summary>Additional source context</summary>
          <dl>{Object.entries(observation.context).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{displayValue(value)}</dd></div>)}</dl>
        </details>}
      </article>;
    })}
  </div>;
}

function SourceChecks({ result }: { result: ComparisonResultData }) {
  if (!result.source_checks.length) return <p className="generic-empty">No source checks were returned.</p>;
  return <ul className="generic-source-checks">
    {result.source_checks.map((check) => <li className="generic-source-check" key={check.source.key}>
      <div className="generic-source-check-main">
        <div><strong>{check.source.name}</strong><span>{check.source.source_type ?? "Source"}</span></div>
        <span className={`generic-source-status ${check.status}`}>{check.status}</span>
      </div>
      {check.source.url && <a href={check.source.url} target="_blank" rel="noreferrer">{check.source.url}</a>}
      {check.checked_at && <small>Checked: {check.checked_at}</small>}
      {check.error && <p className="generic-source-error">{check.error}</p>}
      {check.diagnostics?.reason && <p className="generic-source-diagnostic">{String(check.diagnostics.reason)}</p>}
      {Array.isArray(check.diagnostics?.entities) && <details className="generic-source-debug">
        <summary>Per-entity check details</summary>
        <ul>{check.diagnostics.entities.filter((item): item is { [key: string]: JsonValue } => !!item && typeof item === "object" && !Array.isArray(item)).map((item, index) => <li key={`${String(item.entity_key ?? index)}-${index}`}>
          <strong>{String(item.entity_name ?? item.entity_key ?? "Entity")}</strong>
          <span>{String(item.status ?? "unknown")}</span>
          {typeof item.message === "string" && item.message && <small>{item.message}</small>}
        </li>)}</ul>
      </details>}
    </li>)}
  </ul>;
}

export function ComparisonResult({ result, comparisonId, status, loading = false, error = "" }: ComparisonResultProps) {
  if (!result && !comparisonId && !loading && !error) return null;
  const analysis = result ? structuredAnalysis(result.analysis) : null;
  const displayStatus = result?.status ?? status ?? "queued";
  const checkedSources = result?.source_checks.filter((check) => check.status === "checked" || check.status === "partial").length ?? 0;

  return (
    <section className="generic-result" aria-live="polite" aria-labelledby="generic-result-title">
      <header className="generic-result-heading">
        <div><p className="eyebrow">COMPARISON RESULT</p><h2 id="generic-result-title">Comparison findings</h2>
          {(result?.comparison_id ?? comparisonId) && <p className="generic-result-id">ID - {result?.comparison_id ?? comparisonId}</p>}
        </div>
        <span className={`generic-status ${displayStatus}`}>{displayStatus}</span>
      </header>
      {loading && <p className="generic-muted">Comparison is in progress.</p>}
      {error && <p className="generic-error" role="alert">{error}</p>}
      {result?.errors.map((item, index) => <p className="generic-error" key={`${item}-${index}`}>{item}</p>)}

      {result && <>
        <section className="generic-result-section generic-summary-section" aria-label="Comparison summary">
          <h3>Summary</h3>
          <dl className="generic-summary-grid">
            <div><dt>Status</dt><dd className={`generic-summary-status ${result.status}`}>{result.status}</dd></div>
            <div><dt>Entities</dt><dd>{result.entities.length}</dd></div>
            <div><dt>Attributes</dt><dd>{result.attributes.length}</dd></div>
            <div><dt>Observations</dt><dd>{result.observations.length}</dd></div>
            <div><dt>Unresolved pairs</dt><dd>{result.unresolved.length}</dd></div>
            <div><dt>Checked / partial sources</dt><dd>{checkedSources}</dd></div>
          </dl>
        </section>

        <section className="generic-result-section">
          <h3>Key findings</h3>
          <AnalysisFindings analysis={analysis} />
        </section>

        <section className="generic-result-section">
          <h3>Entity comparison</h3>
          <EntityIdentity result={result} />
          <AttributeMatrix result={result} analysis={analysis} />
        </section>

        <section className="generic-result-section generic-unresolved-section">
          <h3>Unresolved information</h3>
          <p className="generic-section-intro">These items have no verified observation available or could not be reconciled.</p>
          <UnresolvedSection result={result} analysis={analysis} />
        </section>

        <section className="generic-result-section">
          <h3>Evidence and sources</h3>
          <h4 className="generic-subsection-title">Observations</h4>
          <EvidenceList result={result} />
          <h4 className="generic-subsection-title">Source checks</h4>
          <SourceChecks result={result} />
        </section>
        <p className="generic-analysis-availability">{analysis ? "Structured analysis is available from the backend." : result.analysis ? "An analysis result is present in an older or unrecognized format." : "Structured analysis is not available for this result."}</p>
      </>}
    </section>
  );
}
