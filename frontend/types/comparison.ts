export type ComparisonStatus = "queued" | "running" | "completed" | "failed";
export type SourceStatus = "pending" | "checked" | "partial" | "unavailable" | "blocked" | "failed" | "unsupported";
export type ComparisonValueType = "scalar" | "range" | "categorical" | "boolean" | "structured";

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

export interface EntityReference {
  key: string;
  display_name: string;
  entity_type?: string | null;
  identifiers?: Record<string, JsonValue>;
  aliases?: string[];
}

export interface AttributeDefinition {
  key: string;
  label: string;
  value_type: ComparisonValueType;
  unit?: string | null;
  currency?: string | null;
  comparison_rule?: string | null;
}

export interface SourceReference {
  key: string;
  name: string;
  source_type?: string | null;
  url?: string | null;
}

export interface ComparisonRequest {
  user_request: string;
  entities?: EntityReference[];
  attributes?: AttributeDefinition[];
  context?: Record<string, JsonValue> | null;
  source_preferences?: SourceReference[];
}

export interface SourceCheck {
  source: SourceReference;
  status: SourceStatus;
  checked_at?: string | null;
  diagnostics?: Record<string, JsonValue> | null;
  error?: string | null;
}

export interface Observation {
  entity_key: string;
  attribute_key: string;
  source_key: string;
  raw_value: JsonValue;
  normalized_value?: JsonValue;
  value_type: ComparisonValueType;
  unit?: string | null;
  currency?: string | null;
  observed_at: string;
  source_url?: string | null;
  context?: Record<string, JsonValue> | null;
}

export interface ComparisonObservedValue {
  raw_value: JsonValue;
  normalized_value: JsonValue;
  value_type: ComparisonValueType;
  source_key: string;
  source_url: string | null;
  observed_at: string | null;
  unit?: string | null;
  currency?: string | null;
}

export interface EntityAttributeAnalysis {
  entity_key: string;
  entity_name: string;
  status: "observed" | "unresolved" | "conflicting" | string;
  observations: ComparisonObservedValue[];
  comparable_value: JsonValue;
  note: string | null;
}

export interface AttributeAnalysis {
  attribute_key: string;
  label: string;
  value_type: ComparisonValueType;
  comparison_rule: string | null;
  status: "complete" | "unresolved" | string;
  entities: EntityAttributeAnalysis[];
  ranking: Array<{ rank: number; entity_key: string; value: JsonValue }>;
  winner_entity_key: string | null;
  limitations: string[];
}

export interface ComparisonAnalysis {
  schema_version: number;
  comparison_id: string;
  attributes: AttributeAnalysis[];
  unresolved_information: string[];
}

export interface ComparisonResult {
  comparison_id: string;
  status: ComparisonStatus;
  request: ComparisonRequest;
  entities: EntityReference[];
  attributes: AttributeDefinition[];
  source_checks: SourceCheck[];
  observations: Observation[];
  analysis: ComparisonAnalysis | Record<string, JsonValue> | string | null;
  unresolved: string[];
  errors: string[];
  created_at: string;
  updated_at: string;
}

export interface StartComparisonResponse {
  comparison_id: string;
  status: ComparisonStatus;
  status_url: string;
}

export interface ComparisonStatusResponse {
  comparison_id: string;
  status: ComparisonStatus;
  created_at: string;
  updated_at: string;
  error: string | null;
  errors: string[];
}
