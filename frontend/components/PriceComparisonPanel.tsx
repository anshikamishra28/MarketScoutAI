"use client";

import { useEffect, useState } from "react";
import { getPriceComparison, getPriceComparisonStatus, startPriceComparison } from "../lib/api";
import type { PriceComparisonRequest, PriceComparisonResult } from "../types/price-comparison";
import { PriceComparisonForm } from "./PriceComparisonForm";
import { PriceComparisonResults } from "./PriceComparisonResults";

export function PriceComparisonPanel() {
  const [comparisonId, setComparisonId] = useState("");
  const [status, setStatus] = useState<"queued" | "running" | "completed" | "failed" | "">("");
  const [result, setResult] = useState<PriceComparisonResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pollError, setPollError] = useState("");

  async function start(request: PriceComparisonRequest) {
    setBusy(true);
    setError("");
    setPollError("");
    setResult(null);
    setStatus("queued");
    try {
      const response = await startPriceComparison(request);
      setStatus(response.status);
      setComparisonId(response.comparison_id);
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : "Could not start the price comparison.");
      setBusy(false);
      setStatus("");
    }
  }

  useEffect(() => {
    if (!comparisonId) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const current = await getPriceComparisonStatus(comparisonId);
        if (cancelled) return;
        setStatus(current.status);
        setPollError("");
        if (current.status === "completed" || current.status === "failed") {
          try {
            const detail = await getPriceComparison(comparisonId);
            if (!cancelled) setResult(detail);
          } catch (detailError) {
            if (!cancelled) setError(detailError instanceof Error ? detailError.message : "Could not load comparison details.");
          }
          if (!cancelled) setBusy(false);
          return;
        }
      } catch (pollingError) {
        if (!cancelled) setPollError(pollingError instanceof Error ? pollingError.message : "Connection issue. Retrying comparison status.");
      }
      if (!cancelled) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 0);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [comparisonId]);

  return <section className="comparison-panel" id="price-comparison">
    <PriceComparisonForm busy={busy} error={error} onSubmit={(request) => { setComparisonId(""); void start(request); }} />
    {busy && <div className="comparison-progress" role="status"><span className="progress-indicator" />
      Comparison {comparisonId ? `· ${comparisonId}` : "is being queued"} · {status || "starting"}</div>}
    {pollError && <p className="network-banner comparison-network">{pollError}</p>}
    {status === "failed" && !result && <p className="comparison-error" role="alert">{error || "The price comparison failed."}</p>}
    {result && <PriceComparisonResults result={result} />}
    {!result && !busy && !error && <p className="comparison-empty">Enter a product identity to check current retailer listings.</p>}
  </section>;
}
