export type RetailerStatus = "checked" | "unavailable" | "blocked" | "failed";

export interface ProductIdentity {
  brand: string;
  model: string;
  model_number: string;
  ram: string;
  storage: string;
  variant: string;
}

export interface PriceComparisonProductRequest {
  brand: string;
  model?: string;
  model_number?: string;
  ram?: string;
  storage?: string;
  variant?: string;
}

export interface PriceComparisonRequest {
  products: PriceComparisonProductRequest[];
  retailers: string[];
}

export interface PriceObservation {
  id?: string;
  retailer: string;
  product: ProductIdentity;
  price: string;
  currency: string;
  seller: string | null;
  discount: string | null;
  observed_at: string;
  source_url: string;
}

export type DiscoveryOutcome =
  | "exact_product_found"
  | "not_found_through_available_public_discovery"
  | "retailer_or_product_page_unavailable"
  | "discovery_or_fetch_failed"
  | "product_page_parse_failed"
  | "ambiguous_product_variants"
  | "retailer_adapter_unavailable"
  | string;

export interface DiscoveryStrategy {
  source: string;
  descriptor: string;
  success: boolean;
  candidate_count: number;
  error?: string | null;
}

export interface CandidateDiagnostic {
  url: string;
  discovered_by: string[];
  discovery_descriptors?: string[];
  fetched: boolean;
  http_status?: number | null;
  extracted_identity?: ProductIdentity | null;
  match: "matched" | "rejected" | "not_evaluated" | string;
  rejection_reason?: string | null;
  error?: string | null;
}

export interface ProductDiscoveryDiagnostics {
  strategies: DiscoveryStrategy[];
  candidates: CandidateDiagnostic[];
  exact_product_found: boolean;
  final_outcome: DiscoveryOutcome;
  error?: string;
}

export interface ProductRetailerDiagnostic {
  product: ProductIdentity;
  discovery: ProductDiscoveryDiagnostics;
}

export interface DiscoveryDiagnostics {
  products: ProductRetailerDiagnostic[];
}

export interface RetailerResult {
  retailer: string;
  status: RetailerStatus;
  checked_at: string;
  message: string | null;
  source_url: string | null;
  diagnostics?: DiscoveryDiagnostics | null;
}

export interface PriceComparisonResult {
  comparison_id: string;
  status: "queued" | "running" | "completed" | "failed";
  request: PriceComparisonRequest;
  products: ProductIdentity[];
  retailer_checks: RetailerResult[];
  offers: PriceObservation[];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  error: string | null;
}

export interface StartPriceComparisonResponse {
  comparison_id: string;
  status: "queued" | "running" | "completed" | "failed";
  status_url: string;
}

export interface PriceComparisonStatusResponse {
  comparison_id: string;
  status: PriceComparisonResult["status"];
  created_at: string;
  updated_at: string;
  completed_at: string | null;
  error: string | null;
  retailer_checks: Array<Pick<RetailerResult, "retailer" | "status" | "checked_at" | "message" | "source_url">>;
}
