"use client";

import { useEffect, useState, type FormEvent } from "react";
import { EvidenceLedger } from "../components/EvidenceLedger";
import { RequirementCoverage } from "../components/RequirementCoverage";
import { ResearchActivity } from "../components/ResearchActivity";
import { ResearchMetrics } from "../components/ResearchMetrics";
import { ResearchPrompt } from "../components/ResearchPrompt";
import { ResearchReport } from "../components/ResearchReport";
import { SourcesList } from "../components/SourcesList";
import { ComparisonResult } from "../components/ComparisonResult";
import { ComparisonWorkflow } from "../components/ComparisonWorkflow";
import { getComparison, getComparisonStatus, getResearchDetails, getResearchReport, getResearchSources, getResearchStatus, startResearch } from "../lib/api";
import type { ResearchRun, ResearchSource } from "../types/research";
import type { ComparisonResult as ComparisonResultData } from "../types/comparison";

const terminal = (status: string) => status === "completed" || status === "failed";

export default function Home() {
  const [activeMode, setActiveMode] = useState<"research" | "compare">("research");
  const [question, setQuestion] = useState("");
  const [run, setRun] = useState<ResearchRun | null>(null);
  const [sources, setSources] = useState<ResearchSource[]>([]);
  const [report, setReport] = useState("");
  const [error, setError] = useState("");
  const [pollingError, setPollingError] = useState("");
  const [busy, setBusy] = useState(false);
  const [loadingFinalData, setLoadingFinalData] = useState(false);
  const [comparisonId, setComparisonId] = useState("");
  const [comparisonStatus, setComparisonStatus] = useState("");
  const [comparisonResult, setComparisonResult] = useState<ComparisonResultData | null>(null);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonBusy, setComparisonBusy] = useState(false);
  const [theme, setTheme] = useState<"light" | "dark">("light");

  useEffect(() => {
    const saved = window.localStorage.getItem("marketscout-theme");
    const selected = saved === "dark" ? "dark" : "light";
    setTheme(selected);
    document.documentElement.dataset.theme = selected;
  }, []);

  function toggleTheme() {
    const selected = theme === "light" ? "dark" : "light";
    setTheme(selected);
    document.documentElement.dataset.theme = selected;
    window.localStorage.setItem("marketscout-theme", selected);
  }

  function onWorkflowExecutionStarted(id: string, status: string) {
    setComparisonId(id);
    setComparisonStatus(status);
    setComparisonError("");
    setComparisonResult(null);
    setComparisonBusy(true);
  }

  function onComparisonRequestStarted() {
    setComparisonId("");
    setComparisonStatus("");
    setComparisonResult(null);
    setComparisonError("");
    setComparisonBusy(false);
  }

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

  useEffect(() => {
    if (!comparisonId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const status = await getComparisonStatus(comparisonId);
        if (cancelled) return;
        setComparisonError("");
        setComparisonStatus(status.status);
        if (status.status === "completed" || status.status === "failed") {
          const result = await getComparison(comparisonId);
          if (cancelled) return;
          setComparisonResult(result);
          setComparisonBusy(false);
          return;
        }
      } catch (comparisonPollError) {
        if (cancelled) return;
        setComparisonError(comparisonPollError instanceof Error ? `Connection issue. Retrying: ${comparisonPollError.message}` : "Connection issue. Retrying comparison status.");
      }
      if (!cancelled) timer = setTimeout(poll, 1500);
    };
    void poll();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [comparisonId]);

  const evidence = run?.evidence ?? [];
  const sourceCount = run?.sources_count ?? sources.length;

  return (
    <main className="shell">
      <header className="dashboard-header">
        <a className="brand" href="#"><span className="mark">M</span> MarketScout<span>AI</span></a>
        <div className="header-actions"><div className="header-caption"><span className="badge"><i /> Autonomous Market Intelligence</span></div>
          <button type="button" className="theme-toggle" onClick={toggleTheme} aria-label={`Switch to ${theme === "light" ? "dark" : "light"} mode`} aria-pressed={theme === "dark"}>{theme === "light" ? "Dark mode" : "Light mode"}</button></div>
      </header>

      <nav className="workspace-switch" aria-label="MarketScoutAI capabilities">
        <button type="button" aria-pressed={activeMode === "research"} onClick={() => setActiveMode("research")}>
          Market Research
        </button>
        <button type="button" aria-pressed={activeMode === "compare"} onClick={() => setActiveMode("compare")}>
          Compare
        </button>
      </nav>

      <div hidden={activeMode !== "research"}>
        <ResearchPrompt question={question} busy={busy} error={error} onQuestionChange={setQuestion} onSubmit={start} />

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

        {run.status === "completed" && report ? <ResearchReport content={report} question={run.question ?? question} coverage={run.coverage} evidence={evidence} sources={sources} conflicts={run.conflicts} /> : run.status === "completed" ? (
          <article className="panel report"><div className="panel-title"><h3>Final market intelligence report</h3></div>
            <p className="muted">{loadingFinalData ? "Loading the completed report…" : "The report is not ready from the API yet."}</p>
          </article>
        ) : null}
        <ResearchMetrics run={run} sourceCount={sourceCount} evidenceCount={evidence.length} />
        <RequirementCoverage run={run} />
        {(run.status === "running" || run.status === "queued") ? <ResearchActivity run={run} /> : <details className="panel activity-history-disclosure"><summary className="disclosure-summary"><h3>Research activity</h3><span>{run.iterations} iterations · View timeline</span></summary><ResearchActivity run={run} /></details>}
        <EvidenceLedger evidence={evidence} />
        <SourcesList sources={sources} />
        {run.status === "failed" && <article className="panel failure"><h3>Research failed</h3><p>{run.error || "The research run ended without a completed report."}</p></article>}
        {run.status === "completed" && evidence.length === 0 && <p className="empty-note">No retained evidence was returned for this run.</p>}
        {run.status === "completed" && sourceCount === 0 && <p className="empty-note">No sources were returned for this run.</p>}
        </section>}

        {!run && !busy && <section className="welcome-note"><strong>Start with a market question.</strong><span>Your run, evidence, coverage, sources, and report will appear here.</span></section>}
      </div>

      <div hidden={activeMode !== "compare"}>
        <ComparisonWorkflow busy={comparisonBusy} error={comparisonError} onRequestStarted={onComparisonRequestStarted} onExecutionStarted={onWorkflowExecutionStarted} />
        <ComparisonResult result={comparisonResult} comparisonId={comparisonId} status={comparisonStatus} loading={comparisonBusy} error={comparisonError} />
      </div>

      <footer>MarketScoutAI <span>Evidence first. Conclusions traceable.</span></footer>
    </main>
  );
}
