export interface ResearchRequest {
  question: string;
}

export interface StartResearchResponse {
  id: string;
  status: string;
  status_url: string;
}

export interface ResearchPlan {
  research_goal: string;
  sub_questions: string[];
  information_needed: string[];
  search_queries: string[];
}

export interface ResearchCoverage {
  sufficient: string[];
  weak: string[];
  unanswered: string[];
  requirement_details?: RequirementCoverageDetail[];
}

export interface RequirementCoverageDetail {
  requirement: string;
  status: "Supported" | "Weak" | "UNRESOLVED / INSUFFICIENT EVIDENCE" | string;
  supporting_evidence_count?: number;
  supporting_evidence?: string[];
}

export interface ResearchEvidence {
  id: string;
  claim: string;
  evidence_text?: string;
  source_title: string;
  source_url: string;
  publisher: string;
  published_at?: string;
  source_type: string;
  content_scope?: string;
  relevance?: number;
  confidence: number;
  quality_score?: number;
  category_relevance?: number;
  segment_relevance?: number;
  geographic_relevance?: number;
  evidence_scope?: string;
}

export interface SourceEvaluation {
  usable?: boolean;
  confidence?: number;
  relevance?: number;
  source_type?: string;
  reason?: string;
}

export interface ResearchSource {
  id: string;
  url: string;
  title: string;
  publisher: string;
  published_at: string;
  source_type: string;
  content_scope: string;
  search_query: string;
  snippet: string;
  fetch_error: string | null;
  evaluation: SourceEvaluation;
}

export interface ResearchSourcesResponse {
  sources: ResearchSource[];
  evidence: ResearchEvidence[];
}

export interface ResearchStatusResponse {
  id: string;
  status: string;
  iterations: number;
  updated_at: string;
  activity: string[];
  error: string | null;
}

export interface ResearchReportResponse {
  content: string;
  created_at: string;
}

export interface ResearchRun {
  id: string;
  question?: string;
  status: string;
  iterations: number;
  created_at?: string;
  updated_at?: string;
  plan?: ResearchPlan;
  activity?: string[];
  missing?: string[];
  coverage?: ResearchCoverage;
  conflicts?: Array<{ message: string; claims: string[] }>;
  error?: string | null;
  sources_count?: number;
  evidence?: ResearchEvidence[];
  report?: ResearchReportResponse | null;
}
