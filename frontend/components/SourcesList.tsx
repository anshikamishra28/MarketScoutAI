import type { ResearchSource } from "../types/research";

interface Props { sources?: ResearchSource[] | null }

function domainOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "Source"; }
}

export function SourcesList({ sources: suppliedSources }: Props) {
  const sources = suppliedSources ?? [];
  const unique = Array.from(new Map(sources.filter((source) => source.url).map((source) => [source.url, source])).values());
  return <details className="panel disclosure-panel sources-panel concise-secondary">
    <summary className="disclosure-summary"><h3>Sources</h3><span>{unique.length} source{unique.length === 1 ? "" : "s"} used · View sources</span></summary>
    {!unique.length ? <p className="empty-note">No sources were returned.</p> : <div className="source-table-scroll"><table className="source-table">
      <thead><tr><th>Source</th><th>Relevance</th><th>Link</th></tr></thead>
      <tbody>{unique.map((source) => <tr key={source.url}><th scope="row"><strong>{source.title?.trim() || source.publisher?.trim() || domainOf(source.url)}</strong><small>{source.publisher || domainOf(source.url)}</small></th><td>{typeof source.evaluation?.relevance === "number" ? `${Math.round(source.evaluation.relevance * 100)}%` : "Not provided"}</td><td><a href={source.url} target="_blank" rel="noopener noreferrer">View source</a></td></tr>)}</tbody>
    </table></div>}
  </details>;
}
