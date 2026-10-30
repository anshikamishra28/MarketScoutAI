"use client";

import { useState } from "react";
import type { ResearchEvidence } from "../types/research";

interface EvidenceLedgerProps { evidence?: ResearchEvidence[] | null }

function sourceLabel(item: ResearchEvidence): string {
  if (item.source_title?.trim() && !/^https?:\/\//i.test(item.source_title.trim())) return item.source_title;
  if (item.publisher?.trim()) return item.publisher;
  try { return new URL(item.source_url).hostname.replace(/^www\./, ""); } catch { return "Source"; }
}

export function EvidenceLedger({ evidence: suppliedEvidence }: EvidenceLedgerProps) {
  const evidence = suppliedEvidence ?? [];
  const [showAll, setShowAll] = useState(false);
  const seen = new Set<string>();
  const uniqueEvidence = evidence.filter((item) => {
    const claim = (item.claim || item.evidence_text || "").trim().toLowerCase().replace(/\s+/g, " ");
    const key = claim;
    if (!claim || seen.has(key)) return false;
    seen.add(key);
    return true;
  });
  const visible = uniqueEvidence.slice(0, 3);
  const remaining = uniqueEvidence.slice(3);
  return <details className="panel disclosure-panel evidence-panel concise-secondary">
    <summary className="disclosure-summary"><h3>Evidence</h3><span>{uniqueEvidence.length} concise evidence item{uniqueEvidence.length === 1 ? "" : "s"} · View evidence</span></summary>
    {!visible.length ? <p className="empty-note">No retained evidence was returned.</p> : <div className="evidence-list">
      {visible.map((item) => <article className="evidence-card" key={item.id}>
        <p className="evidence-claim">{item.claim || item.evidence_text}</p>
        <div className="evidence-source"><strong>{sourceLabel(item)}</strong>{item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer">View source</a>}</div>
      </article>)}
      {!!remaining.length && <>
        {showAll && remaining.map((item) => <article className="evidence-card" key={item.id}><p className="evidence-claim">{item.claim || item.evidence_text}</p><div className="evidence-source"><strong>{sourceLabel(item)}</strong>{item.source_url && <a href={item.source_url} target="_blank" rel="noopener noreferrer">View source</a>}</div></article>)}
        <button type="button" className="text-action" onClick={() => setShowAll((value) => !value)}>{showAll ? "Show less" : `Show more evidence (${remaining.length})`}</button>
      </>}
    </div>}
  </details>;
}
