import type {
  ResearchReportResponse,
  ResearchRequest,
  ResearchRun,
  ResearchSourcesResponse,
  ResearchStatusResponse,
  StartResearchResponse,
} from "../types/research";
import type {
  PriceComparisonRequest,
  PriceComparisonResult,
  PriceComparisonStatusResponse,
  StartPriceComparisonResponse,
} from "../types/price-comparison";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export async function startResearch(request: ResearchRequest): Promise<StartResearchResponse> {
  const response = await fetch(`${API}/research`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  });
  if (!response.ok) throw new Error(await response.text());
  return readJson<StartResearchResponse>(response);
}

export async function getResearchDetails(researchId: string): Promise<ResearchRun> {
  return readJson<ResearchRun>(await fetch(`${API}/research/${researchId}`));
}

export async function getResearchStatus(researchId: string): Promise<ResearchStatusResponse> {
  return readJson<ResearchStatusResponse>(await fetch(`${API}/research/${researchId}/status`));
}

export async function getResearchSources(researchId: string): Promise<ResearchSourcesResponse> {
  return readJson<ResearchSourcesResponse>(await fetch(`${API}/research/${researchId}/sources`));
}

export async function getResearchReport(researchId: string): Promise<ResearchReportResponse | null> {
  const response = await fetch(`${API}/research/${researchId}/report`);
  if (!response.ok) return null;
  return readJson<ResearchReportResponse>(response);
}

async function comparisonJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `Price comparison API request failed (${response.status})`);
  }
  return readJson<T>(response);
}

export async function startPriceComparison(request: PriceComparisonRequest): Promise<StartPriceComparisonResponse> {
  return comparisonJson<StartPriceComparisonResponse>(await fetch(`${API}/price-comparisons`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(request),
  }));
}

export async function getPriceComparisonStatus(comparisonId: string): Promise<PriceComparisonStatusResponse> {
  return comparisonJson<PriceComparisonStatusResponse>(
    await fetch(`${API}/price-comparisons/${encodeURIComponent(comparisonId)}/status`),
  );
}

export async function getPriceComparison(comparisonId: string): Promise<PriceComparisonResult> {
  return comparisonJson<PriceComparisonResult>(
    await fetch(`${API}/price-comparisons/${encodeURIComponent(comparisonId)}`),
  );
}
