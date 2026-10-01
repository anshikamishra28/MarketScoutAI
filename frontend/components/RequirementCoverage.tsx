import type { ResearchRun } from "../types/research";

interface Props { run: ResearchRun }

export function RequirementCoverage({ run }: Props) {
  const requirements = run.plan?.information_needed ?? [];
  const details = run.coverage?.requirement_details ?? [];
  const detailsByRequirement = new Map(details.map((detail) => [detail.requirement, detail]));
  return <article className="panel coverage-panel">
    <div className="panel-title"><h3>Requirement coverage</h3><span>{requirements.length} planned requirements</span></div>
    {!requirements.length ? <div className="empty-state"><strong>Coverage is not available yet</strong><span>The API has not returned the research requirements.</span></div> : <ul className="coverage-list">
      {requirements.map((requirement, index) => {
        const detail = detailsByRequirement.get(requirement);
        const state = detail?.status ?? "Coverage details unavailable";
        const kind = state === "Supported" ? "supported" : state === "Weak" ? "weak" : state.startsWith("UNRESOLVED") ? "unresolved" : "unknown";
        const evidence = detail?.supporting_evidence ?? [];
        return <li className="coverage-row" key={`${index}-${requirement}`}>
          <div className="coverage-copy"><span className="requirement-index">{String(index + 1).padStart(2, "0")}</span><span>{requirement}</span></div>
          <span className={`coverage-badge ${kind}`}>{state}</span>
          {detail?.supporting_evidence_count !== undefined && <p className="coverage-count">{detail.supporting_evidence_count} supporting evidence item{detail.supporting_evidence_count === 1 ? "" : "s"}</p>}
          {evidence.length > 0 && <ul className="coverage-snippets">{evidence.map((snippet, snippetIndex) => <li key={`${snippetIndex}-${snippet}`}>{snippet}</li>)}</ul>}
          {!evidence.length && detail && detail.supporting_evidence_count === 0 && <p className="coverage-empty">No retained evidence directly supports this requirement.</p>}
        </li>;
      })}
    </ul>}
  </article>;
}
