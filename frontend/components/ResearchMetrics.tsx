import type { ResearchRun } from "../types/research";

interface ResearchMetricsProps { run: ResearchRun; sourceCount: number; evidenceCount: number }

export function ResearchMetrics({ run, sourceCount, evidenceCount }: ResearchMetricsProps) {
  return <section className="summary-grid" aria-label="Research status summary">
    <div className="summary-card status-card"><span>Status</span><strong className={`status-text ${run.status}`}>{run.status}</strong></div>
    <div className="summary-card"><span>Iterations</span><strong>{run.iterations}<small> / 3</small></strong></div>
    <div className="summary-card"><span>Sources</span><strong>{sourceCount}</strong></div>
    <div className="summary-card"><span>Evidence statements</span><strong>{evidenceCount}</strong></div>
  </section>;
}
