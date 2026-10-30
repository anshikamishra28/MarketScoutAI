import type { ResearchRun } from "../types/research";

interface Props { run: ResearchRun }

export function RequirementCoverage({ run }: Props) {
  const requirements = run.plan?.information_needed ?? [];
  const details = run.coverage?.requirement_details ?? [];
  const byRequirement = new Map(details.map((detail) => [detail.requirement, detail]));
  const supported = run.coverage?.sufficient?.length ?? 0;
  const partial = run.coverage?.weak?.length ?? 0;
  const unresolved = run.coverage?.unanswered?.length ?? 0;
  return <section className="panel coverage-panel">
    <div className="panel-title"><h3>Research coverage</h3><span>{requirements.length} requirements assessed</span></div>
    <div className="coverage-summary"><div><strong>{supported}</strong><span>Supported</span></div><div><strong>{partial}</strong><span>Partially supported</span></div><div><strong>{unresolved}</strong><span>Unresolved</span></div></div>
    {requirements.length > 0 && <details className="coverage-details"><summary>View each requirement</summary><ul className="coverage-list">
      {requirements.map((requirement, index) => {
        const detail = byRequirement.get(requirement);
        const state = detail?.status ?? "Coverage details unavailable";
        const kind = state === "Supported" ? "supported" : state === "Weak" ? "weak" : state.startsWith("UNRESOLVED") ? "unresolved" : "unknown";
        return <li className="coverage-row" key={`${index}-${requirement}`}><div className="coverage-copy"><span>{requirement}</span><span className={`coverage-badge ${kind}`}>{state}</span></div>
          {detail?.supporting_evidence_count !== undefined && <small>{detail.supporting_evidence_count} supporting item{detail.supporting_evidence_count === 1 ? "" : "s"}</small>}
          {!!detail?.supporting_evidence?.length && <ul className="coverage-snippets">{detail.supporting_evidence.slice(0, 3).map((snippet, snippetIndex) => <li key={`${snippetIndex}-${snippet}`}>{snippet}</li>)}</ul>}
        </li>;
      })}
    </ul></details>}
  </section>;
}
