"use client";

import { useMemo } from "react";
import type { ResearchCoverage, ResearchEvidence, ResearchSource } from "../types/research";

interface Props { content: string; question: string; coverage?: ResearchCoverage | null; evidence?: ResearchEvidence[] | null; sources?: ResearchSource[] | null; conflicts?: Array<{ message: string; claims: string[] }> | null }
type Section = { title: string; paragraphs: string[] };

function cleanLine(line: string): string {
  return line.replace(/^\s*[-*]\s+/, "").replace(/^\s*\d+[.)]\s+/, "")
    .replace(/\[(?:TARGET_SEGMENT|INDIA_MARKET_CONTEXT|GLOBAL_CONTEXT|OUT_OF_SCOPE|UNCLASSIFIED)\]\s*/gi, "")
    .replace(/\[[^\]]+\]\([^)]*\)/g, "")
    .replace(/\([^()]*(?:https?:\/\/[^\s)]+|confidence|relevance)[^()]*\)/gi, "")
    .replace(/\s+/g, " ").trim();
}
function parseReport(content: string): Section[] {
  const sections: Section[] = [];
  let current: Section = { title: "Overview", paragraphs: [] };
  for (const raw of content.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const heading = line.match(/^#{1,4}\s+(.+)$/);
    if (heading) {
      if (current.paragraphs.length) sections.push(current);
      current = { title: heading[1].replace(/\[[^\]]+\]/g, "").trim(), paragraphs: [] };
    } else if (/^[-*]\s+|^\d+[.)]\s+/.test(line)) current.paragraphs.push(cleanLine(line));
    else if (!/^\[?(?:INDIA_MARKET_CONTEXT|GLOBAL_CONTEXT|OUT_OF_SCOPE|TARGET_SEGMENT)\]?$/i.test(line)) current.paragraphs.push(cleanLine(line));
  }
  if (current.paragraphs.length) sections.push(current);
  return sections;
}
function unique(items: string[], limit = Infinity): string[] {
  const seen = new Set<string>(); const output: string[] = [];
  for (const item of items) {
    const key = item.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();
    if (!key || seen.has(key)) continue;
    seen.add(key); output.push(item);
    if (output.length >= limit) break;
  }
  return output;
}
function domain(url: string): string { try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return "Source"; } }
function sourceName(source: ResearchSource): string { return source.title?.trim() && !/^https?:\/\//i.test(source.title.trim()) ? source.title : source.publisher?.trim() || domain(source.url); }

export function ResearchReport({ content, question, coverage, evidence, sources, conflicts = [] }: Props) {
  const evidenceItems = evidence ?? [];
  const sourceItems = sources ?? [];
  const conflictItems = conflicts ?? [];
  const parsed = useMemo(() => parseReport(content), [content]);
  const overview = parsed.find((section) => /market overview|overview|executive summary/i.test(section.title))?.paragraphs.slice(0, 2) ?? [];
  const findings = unique(parsed.filter((section) => /finding|insight|trend|opportunit|risk|competitor|segment|pricing/i.test(section.title)).flatMap((section) => section.paragraphs), 5);
  const insights = unique(parsed.filter((section) => /insight|trend|opportunit|risk/i.test(section.title)).flatMap((section) => section.paragraphs).filter((item) => !findings.some((finding) => finding.toLowerCase() === item.toLowerCase())), 4);
  const primaryFindings = findings.length ? findings : unique(evidenceItems.map((item) => item.claim || item.evidence_text || ""), 4);
  const executiveSummary = primaryFindings[0] || overview[0] || `The research assessed ${evidenceItems.length} evidence statements across ${sourceItems.length} sources.`;
  const marketOverview = overview.filter((item) => item.toLowerCase() !== executiveSummary.toLowerCase());
  const additionalFindings = primaryFindings.slice(primaryFindings[0] === executiveSummary ? 1 : 0);
  const conciseSources = Array.from(new Map(sourceItems.filter((source) => source.url).map((source) => [source.url, source])).values());
  const sourceLines = conciseSources.map((source) => `- ${sourceName(source)}${source.publisher ? ` - ${source.publisher}` : ""}${source.url ? `: ${source.url}` : ""}`);
  const supported = coverage?.sufficient?.length ?? 0;
  const partial = coverage?.weak?.length ?? 0;
  const unresolved = coverage?.unanswered?.length ?? 0;

  function download() {
    const markdown = [
      `# ${question || "Market research report"}`, "", "## Executive summary", executiveSummary,
      "", "## Key findings", ...(additionalFindings.length ? additionalFindings.map((item) => `- ${item}`) : ["- No additional concise findings were returned."]),
      "", "## Market overview", ...(marketOverview.length ? marketOverview : ["No additional overview details were returned."]),
      "", "## Key insights", ...(insights.length ? insights.map((item) => `- ${item}`) : ["- No separate insights were returned."]),
      "", "## Research coverage", `- Supported: ${supported}`, `- Partially supported: ${partial}`, `- Unresolved: ${unresolved}`,
      "", "## Sources", ...(sourceLines.length ? sourceLines : ["- No sources were returned."]), "",
    ].join("\n");
    const href = URL.createObjectURL(new Blob([markdown], { type: "text/markdown;charset=utf-8" }));
    const anchor = document.createElement("a"); anchor.href = href;
    anchor.download = `${(question || "marketscout-report").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "").slice(0, 72) || "marketscout-report"}.md`;
    document.body.appendChild(anchor); anchor.click(); anchor.remove(); window.setTimeout(() => URL.revokeObjectURL(href), 1000);
  }

  const methodology = parsed.filter((section) => /method|limit/i.test(section.title)).flatMap((section) => section.paragraphs).slice(0, 8);
  return <article className="panel report concise-report">
    <header className="report-heading"><div><p className="eyebrow">FINAL REPORT</p><h2>Market intelligence</h2><p className="report-question">{question}</p></div><button type="button" className="report-download" onClick={download}>Download Report</button></header>
    <section className="report-executive"><h3>Executive summary</h3><p>{executiveSummary}</p></section>
    <div className="report-content-grid">
      <section className="report-highlight"><h3>Key findings</h3>{additionalFindings.length ? <ul>{additionalFindings.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p>No additional concise findings were returned.</p>}</section>
      <section className="report-overview"><h3>Market overview</h3>{marketOverview.length ? marketOverview.map((item, index) => <p key={`${index}-${item}`}>{item}</p>) : <p>No additional overview detail was returned.</p>}</section>
      <section className="report-insights"><h3>Key insights</h3>{insights.length ? <ul>{insights.map((item, index) => <li key={`${index}-${item}`}>{item}</li>)}</ul> : <p>No separate insight section was returned.</p>}</section>
      <section className="report-coverage"><h3>Research coverage</h3><div><span><strong>{supported}</strong> Supported</span><span><strong>{partial}</strong> Partially supported</span><span><strong>{unresolved}</strong> Unresolved</span></div><p>Coverage reflects the research result returned by the backend.</p></section>
    </div>
    {!!conflictItems.length && <details className="report-secondary"><summary>View source differences ({conflictItems.length})</summary><p>Some sources report differing figures. Values may refer to different segments, dates, or market definitions.</p><ul>{unique(conflictItems.map((item) => item.message), 12).map((message) => <li key={message}>{message}</li>)}</ul></details>}
    <details className="report-secondary"><summary>View methodology &amp; limitations</summary>{methodology.length ? <ul>{methodology.map((line, index) => <li key={`${index}-${line}`}>{line}</li>)}</ul> : <p>Research is based on the sources and evidence returned for this request. Some requested details may remain unresolved.</p>}</details>
  </article>;
}
