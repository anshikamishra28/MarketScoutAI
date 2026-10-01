"use client";

import { useEffect, useState, type FormEvent } from "react";
import {
  confirmComparisonWorkflow,
  getComparisonWorkflow,
  getComparisonWorkflowSources,
  startComparisonWorkflow,
} from "../lib/api";
import type {
  ComparisonWorkflowResponse,
  JsonValue,
  SourceReference,
} from "../types/comparison";

interface ComparisonWorkflowProps {
  busy: boolean;
  error: string;
  onExecutionStarted: (comparisonId: string, status: string) => void;
}

function displayValue(value: JsonValue): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function maybeJson(value: string): JsonValue {
  try {
    return JSON.parse(value) as JsonValue;
  } catch {
    return value;
  }
}

export function ComparisonWorkflow({ busy, error, onExecutionStarted }: ComparisonWorkflowProps) {
  const [request, setRequest] = useState("");
  const [sources, setSources] = useState<SourceReference[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [session, setSession] = useState<ComparisonWorkflowResponse | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [confirmed, setConfirmed] = useState<Record<string, boolean>>({});
  const [loading, setLoading] = useState(false);
  const [errorText, setErrorText] = useState("");

  useEffect(() => {
    let cancelled = false;
    getComparisonWorkflowSources().then((items) => { if (!cancelled) setSources(items); })
      .catch((reason: unknown) => { if (!cancelled) setErrorText(reason instanceof Error ? reason.message : "Could not load comparison sources."); });
    return () => { cancelled = true; };
  }, []);

  function acceptResponse(result: ComparisonWorkflowResponse) {
    setSession(result);
    if (result.comparison_id) onExecutionStarted(result.comparison_id, result.comparison_status ?? "queued");
    const values: Record<string, string> = {};
    for (const item of result.clarification.confirmations_required) values[item.path] = displayValue(item.proposed_value);
    setDrafts(values);
    setConfirmed({});
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!request.trim()) { setErrorText("Describe the entities and what you want to compare."); return; }
    if (!selected.length) { setErrorText("Select at least one source to check."); return; }
    setLoading(true);
    setErrorText("");
    setSession(null);
    try {
      const preferences = sources.filter((source) => selected.includes(source.key));
      acceptResponse(await startComparisonWorkflow({ user_request: request.trim(), source_preferences: preferences }));
    } catch (reason) {
      setErrorText(reason instanceof Error ? reason.message : "Could not interpret this comparison request.");
    } finally { setLoading(false); }
  }

  async function submitConfirmations() {
    if (!session) return;
    const values: Record<string, JsonValue> = {};
    for (const [path, isConfirmed] of Object.entries(confirmed)) {
      if (isConfirmed) values[path] = maybeJson(drafts[path] ?? "");
    }
    if (!Object.keys(values).length) { setErrorText("Select and confirm at least one proposed value before continuing."); return; }
    setLoading(true);
    setErrorText("");
    try {
      const updated = await confirmComparisonWorkflow(session.workflow_id, { values });
      acceptResponse(await getComparisonWorkflow(updated.workflow_id));
    } catch (reason) {
      setErrorText(reason instanceof Error ? reason.message : "Could not confirm the selected interpretation.");
    } finally { setLoading(false); }
  }

  const intent = session?.intent;
  const entities = intent?.request.entities ?? [];
  const attributes = intent?.request.attributes ?? [];
  const sourcePreferences = intent?.request.source_preferences ?? [];
  const provenance = intent?.provenance ?? {};

  return <section className="workspace comparison-workflow" aria-labelledby="natural-comparison-title">
    <div className="section-head">
      <div><p className="eyebrow">NATURAL-LANGUAGE COMPARISON</p><h2 id="natural-comparison-title">Describe the comparison</h2>
        <p className="muted">Interpretations remain proposals until you explicitly confirm them.</p></div>
    </div>
    <form className="comparison-workflow-form" onSubmit={submit}>
      <label htmlFor="comparison-natural-request">What would you like to compare?</label>
      <textarea id="comparison-natural-request" value={request} onChange={(event) => setRequest(event.target.value)} placeholder="Compare two services by monthly price and contract length" disabled={loading || busy} rows={3} />
      <fieldset className="workflow-source-list"><legend>Select sources</legend>
        {sources.length ? sources.map((source) => <label key={source.key} className="workflow-source-option">
          <input type="checkbox" checked={selected.includes(source.key)} onChange={(event) => setSelected((current) => event.target.checked ? [...current, source.key] : current.filter((key) => key !== source.key))} disabled={loading || busy} />
          <span>{source.name}</span><small>{source.source_type ?? "source"}</small>
        </label>) : <p className="muted">No comparison sources are currently registered.</p>}
      </fieldset>
      {(errorText || error) && <p className="generic-error" role="alert">{errorText || error}</p>}
      <button className="generic-submit" type="submit" disabled={loading || busy || sources.length === 0}>{loading ? "Interpreting..." : "Interpret comparison"}</button>
    </form>

    {session && <div className="workflow-draft" aria-live="polite">
      <div className="workflow-state"><strong>Interpretation: {intent?.state === "ready" ? "Ready" : "Needs clarification"}</strong>
        {session.comparison_id && <span>Execution started · {session.comparison_status}</span>}
      </div>
      <p className="workflow-note">Proposed values are not verified. Confirm only the details you want used.</p>
      {!!entities.length && <section><h3>Entities</h3><ul className="workflow-proposals">{entities.map((entity) => <li key={entity.key}>
        <strong>{entity.display_name}</strong><span className="provenance-tag">{provenance[`entities.${entity.key}.display_name`] ?? "user_provided"}</span>
        {entity.entity_type && <p>Type: {entity.entity_type} <span className="provenance-tag">{provenance[`entities.${entity.key}.entity_type`] ?? "proposed"}</span></p>}
        {Object.entries(entity.identifiers ?? {}).map(([key, value]) => <p key={key}><code>{key}</code>: {displayValue(value as JsonValue)} <span className="provenance-tag">{provenance[`entities.${entity.key}.identifiers.${key}`] ?? "proposed"}</span></p>)}
      </li>)}</ul></section>}
      {!!attributes.length && <section><h3>Requested attributes</h3><ul className="workflow-proposals">{attributes.map((attribute) => <li key={attribute.key}>
        <strong>{attribute.label}</strong><span className="provenance-tag">{provenance[`attributes.${attribute.key}.label`] ?? "proposed"}</span>
        <p>{attribute.value_type}{attribute.unit ? ` · ${attribute.unit}` : ""}{attribute.comparison_rule ? ` · ${attribute.comparison_rule}` : ""}</p>
      </li>)}</ul></section>}
      {!!sourcePreferences.length && <section><h3>Sources</h3><ul className="workflow-proposals">{sourcePreferences.map((source) => <li key={source.key}><strong>{source.name}</strong><span className="provenance-tag">{provenance[`sources.${source.key}.key`] ?? "user_provided"}</span></li>)}</ul></section>}
      {!!session.clarification.unresolved.length && <section className="workflow-issues"><h3>Needs your attention</h3><ul>{session.clarification.unresolved.map((issue, index) => <li key={`${issue.code}-${index}`}>
        <strong>{issue.clarification_question ?? issue.message}</strong><p>{issue.message}</p><small>Target: {issue.target}</small>
        {issue.candidates.length > 0 && <p>Candidates: {issue.candidates.map((candidate) => displayValue(candidate)).join(", ")}</p>}
      </li>)}</ul></section>}
      {!!session.clarification.confirmations_required.length && <section className="workflow-confirmations"><h3>Confirm proposed details</h3>
        {session.clarification.confirmations_required.map((item) => <div className="workflow-confirmation" key={item.path}>
          <label><input type="checkbox" checked={confirmed[item.path] ?? false} onChange={(event) => setConfirmed((current) => ({ ...current, [item.path]: event.target.checked }))} disabled={loading || busy} /> I confirm or correct this proposed value</label>
          <code>{item.path}</code><input aria-label={`Proposed value for ${item.path}`} value={drafts[item.path] ?? ""} onChange={(event) => setDrafts((current) => ({ ...current, [item.path]: event.target.value }))} disabled={loading || busy} />
          <small>Proposed: {displayValue(item.proposed_value)} · Needs confirmation</small>
        </div>)}
        <button type="button" className="generic-submit" onClick={submitConfirmations} disabled={loading || busy}>{loading ? "Updating..." : "Submit confirmations"}</button>
      </section>}
      {session.clarification.ready_for_execution && !session.comparison_id && <p className="workflow-note">The backend marked this intent ready; execution will use the existing comparison service.</p>}
    </div>}
  </section>;
}
