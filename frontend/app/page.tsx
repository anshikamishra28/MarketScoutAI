"use client";

import { useEffect, useState, type FormEvent } from "react";
import { EvidenceLedger } from "../components/EvidenceLedger";
import { RequirementCoverage } from "../components/RequirementCoverage";
import { ResearchActivity } from "../components/ResearchActivity";
import { ResearchMetrics } from "../components/ResearchMetrics";
import { ResearchPrompt } from "../components/ResearchPrompt";
import { ResearchReport } from "../components/ResearchReport";
import { SourcesList } from "../components/SourcesList";
import { PriceComparisonPanel } from "../components/PriceComparisonPanel";
import { getResearchDetails, getResearchReport, getResearchSources, getResearchStatus, startResearch } from "../lib/api";
import type { ResearchRun, ResearchSource } from "../types/research";

const terminal = (status: string) => status === "completed" || status === "failed";

export default function Home() {
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [report, setReport] = useState("");
  const [error, setError] = useState("");
  const [pollingError, setPollingError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingFinalData, setLoadingFinalData] = useState(false);

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (question.trim().length < 8) {
      setError("Enter a research question with at least 8 characters.");
      return;
    }
    setError("");
    setPollingError("");
    setReport("");
    setSources([]);
    setBusy(true);
    setRun(null);
    try {
      const data = await startResearch({ question: question.trim() });
      setRun({ id: data.id, status: data.status, iterations: 0, activity: [], question: question.trim() });
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : "Could not reach the API");
      setBusy(false);
    }
  }

  useEffect(() => {
    if (!run?.id || terminal(run.status)) {
      if (run && terminal(run.status)) setBusy(false);
      return;
    }
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let previousStatus: string | undefined;
    const poll = async () => {
      try {
        const status = await getResearchStatus(run.id);
        if (cancelled) return;
        setPollingError("");
        setRun((current) => current ? {
          ...current,
          status: status.status,
          iterations: status.iterations,
          updated_at: status.updated_at,
          activity: status.activity,
          error: status.error,
        } : current);
        const statusChanged = status.status !== previousStatus;
        previousStatus = status.status;
        if (statusChanged && !terminal(status.status)) {
          const details = await getResearchDetails(run.id).catch(() => null);
          if (!cancelled && details) {
            setRun((current) => current ? { ...details, status: status.status, iterations: status.iterations, activity: status.activity, error: status.error, question: current.question } : current);
          }
        }
        if (terminal(status.status)) {
          setLoadingFinalData(true);
          const [detailsResult, sourcesResult] = await Promise.allSettled([
            getResearchDetails(run.id), getResearchSources(run.id),
          ]);
          if (cancelled) return;
          if (detailsResult.status === "fulfilled") {
            setRun((current) => ({ ...detailsResult.value, question: current?.question ?? question }));
          }
          if (sourcesResult.status === "fulfilled") {
            setSources(sourcesResult.value.sources ?? []);
            if (detailsResult.status !== "fulfilled") {
              setRun((current) => current ? { ...current, evidence: sourcesResult.value.evidence ?? [] } : current);
            }
          }
          if (status.status === "completed") {
            let finalReport = await getResearchReport(run.id).catch(() => null);
            if (!finalReport) {
              await new Promise((resolve) => setTimeout(resolve, 900));
              if (!cancelled) finalReport = await getResearchReport(run.id).catch(() => null);
            }
            if (!cancelled && finalReport) setReport(finalReport.content);
          }
          if (!cancelled) {
            setLoadingFinalData(false);
            setBusy(false);
          }
          return;
        }
      } catch {
        if (!cancelled) setPollingError("Connection issue. Retrying research status…");
      }
      if (!cancelled) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [run?.id]);

  const evidence = run?.evidence ?? [];
  const sourceCount = run?.sources_count ?? sources.length;

  return (
    <main className="shell">
      <header className="dashboard-header">
        <a className="brand" href="#"><span className="mark">M</span> MarketScout<span>AI</span></a>
        <div className="header-caption"><span className="badge"><i /> Autonomous Market Intelligence</span></div>
      </header>

      <ResearchPrompt question={question} busy={busy} error={error} onQuestionChange={setQuestion} onSubmit={start} />

      <PriceComparisonPanel />

      {run && <section className="workspace" aria-live="polite">
        <div className="section-head">
          <div className="run-heading">
            <p className="eyebrow">RESEARCH RUN</p>
            <h2>{run.question ?? question}</h2>
            <code className="run-id">ID · {run.id}</code>
          </div>
          <span className={`status ${run.status}`}>{run.status}</span>
        </div>
        {pollingError && <p className="network-banner">{pollingError}</p>}

        <ResearchMetrics run={run} sourceCount={sourceCount} evidenceCount={evidence.length} />

        <div className="columns">
          <ResearchActivity run={run} />
          <RequirementCoverage run={run} />
        </div>

        <EvidenceLedger evidence={evidence} />
        <SourcesList sources={sources} />
        {run.status === "completed" && report ? <ResearchReport content={report} /> : run.status === "completed" ? (
          <article className="panel report"><div className="panel-title"><h3>Final market intelligence report</h3></div>
            <p className="muted">{loadingFinalData ? "Loading the completed report…" : "The report is not ready from the API yet."}</p>
          </article>
        ) : null}
        {run.status === "failed" && <article className="panel failure"><h3>Research failed</h3><p>{run.error || "The research run ended without a completed report."}</p></article>}
        {run.status === "completed" && evidence.length === 0 && <p className="empty-note">No retained evidence was returned for this run.</p>}
        {run.status === "completed" && sourceCount === 0 && <p className="empty-note">No sources were returned for this run.</p>}
      </section>}

      {!run && !busy && <section className="welcome-note"><strong>Start with a market question.</strong><span>Your run, evidence, coverage, sources, and report will appear here.</span></section>}
      <footer>MarketScoutAI <span>Evidence first. Conclusions traceable.</span></footer>
    </main>
  );
}
