import type { ResearchEvidence } from "../types/research";

interface EvidenceLedgerProps { evidence: ResearchEvidence[] }

function percent(value: number | undefined): string { return typeof value === "number" ? `${Math.round(value * 100)}%` : "Not provided"; }
function scopeName(item: ResearchEvidence): string {
  return item.evidence_scope || item.content_scope || "UNCLASSIFIED";
}

export function EvidenceLedger({ evidence }: EvidenceLedgerProps) {
  return <article className="panel evidence-panel">
    <div className="panel-title"><h3>Evidence ledger</h3><span>{evidence.length} retained statements</span></div>
    {!evidence.length ? <div className="empty-state"><strong>No evidence statements</strong><span>Retained evidence will be listed here when available.</span></div> : <div className="evidence-list">
      {evidence.map((item) => {
        const scope = scopeName(item);
        const outOfScope = scope.toUpperCase() === "OUT_OF_SCOPE";
        return <article className={`evidence-card ${outOfScope ? "out-of-scope" : ""}`} key={item.id}>
          <div className="evidence-topline"><span className={`scope-badge ${outOfScope ? "scope-out" : ""}`}>{scope}</span>{outOfScope && <span className="scope-warning">Not target evidence</span>}</div>
          <p className="evidence-claim">{item.claim || item.evidence_text || "Evidence text unavailable"}</p>
          {item.evidence_text && item.claim !== item.evidence_text && <details><summary>Verbatim source text</summary><p>{item.evidence_text}</p></details>}
          <div className="evidence-source"><div><strong>{item.source_title || "Untitled source"}</strong><span>{item.publisher || "Publisher not provided"} · {item.source_type || "Source type not provided"}</span></div>
            {item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer">Open source ↗</a>}
          </div>
          <dl className="evidence-meta">
            <div><dt>Segment relevance</dt><dd>{percent(item.segment_relevance)}</dd></div>
            <div><dt>Quality</dt><dd>{percent(item.quality_score)}</dd></div>
            <div><dt>Confidence</dt><dd>{percent(item.confidence)}</dd></div>
            <div><dt>Published</dt><dd>{item.published_at || "Date unavailable"}</dd></div>
          </dl>
        </article>;
      })}
    </div>}
  </article>;
}
