import type { ResearchSource } from "../types/research";

interface Props { sources: ResearchSource[] }

export function SourcesList({ sources }: Props) {
  return <article className="panel sources-panel">
    <div className="panel-title"><h3>Sources</h3><span>{sources.length} discovered</span></div>
    {!sources.length ? <div className="empty-state"><strong>No sources returned</strong><span>Discovered and evaluated source pages will appear here.</span></div> : <div className="source-list">
      {sources.map((source) => <article className="source-card" key={source.id}>
        <div className="source-card-heading"><div><h4>{source.title || source.url}</h4><span>{source.publisher || domainOf(source.url)} · {source.source_type || source.evaluation?.source_type || "Type unavailable"}</span></div>
          <span className={`usable-badge ${source.evaluation?.usable ? "usable" : "not-usable"}`}>{source.evaluation?.usable === undefined ? "Not evaluated" : source.evaluation.usable ? "Usable" : "Not usable"}</span>
        </div>
        {source.evaluation?.reason && <p className="source-reason">{source.evaluation.reason}</p>}
        {source.fetch_error && <p className="source-error">Fetch issue: {source.fetch_error}</p>}
        <div className="source-meta"><span>Confidence {score(source.evaluation?.confidence)}</span><span>Relevance {score(source.evaluation?.relevance)}</span><span>{source.published_at || "Publication date unavailable"}</span></div>
        {source.url && <a className="source-link" href={source.url} target="_blank" rel="noopener noreferrer">Open source ↗</a>}
      </article>)}
    </div>}
  </article>;
}

function score(value: number | undefined): string { return typeof value === "number" ? `${Math.round(value * 100)}%` : "—"; }
function domainOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "Publisher unavailable"; }
}
