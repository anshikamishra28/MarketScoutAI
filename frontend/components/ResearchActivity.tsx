import type { ResearchRun } from "../types/research";

interface ResearchActivityProps { run: ResearchRun }

export function ResearchActivity({ run }: ResearchActivityProps) {
  const events = run.activity ?? [];
  const active = run.status === "running" || run.status === "queued";
  return (
    <article className="panel activity">
      <div className="panel-title"><h3>Research activity</h3><span>{run.iterations} iteration{run.iterations === 1 ? "" : "s"}</span></div>
      {events.length ? <ol className="activity-list">
        {events.map((event, index) => <li key={`${index}-${event}`} className={active && index === events.length - 1 ? "current" : "done"}>
          <b>{active && index === events.length - 1 ? <span className="activity-dot" /> : "✓"}</b>
          <span>{event}</span>
          {active && index === events.length - 1 && <small>Latest update</small>}
        </li>)}
      </ol> : <div className="empty-state"><strong>{run.status === "queued" ? "Queued" : "Preparing research"}</strong><span>Activity will appear as the backend records progress.</span></div>}
      {active && <p className="live-caption"><span className="live-dot" /> Waiting for the next status update</p>}
      {run.error && <p className="error">{run.error}</p>}
    </article>
  );
}
