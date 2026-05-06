/**
 * Agent / module metadata returned by GET /api/agents/metadata.
 *
 * Drives the sidebar module-launchers, onboarding cards, the report-builder
 * panel, and LMS form quick-actions. The shape mirrors the backend agent's
 * pluggable AgentRegistry contract.
 */

export type AgentCategory = 'analytical' | 'transactional' | 'knowledge';

export type ReportColumnType = 'string' | 'number' | 'date' | 'boolean';

export type ReportAggregation = 'sum' | 'avg' | 'count' | 'min' | 'max';

export interface ReportColumn {
  name: string;
  label: string;
  type: ReportColumnType;
  groupable: boolean;
  filterable: boolean;
  aggregatable: boolean;
  values?: string[];
}

export interface ReportBuilderSchema {
  columns: ReportColumn[];
  aggregations: ReportAggregation[];
  default_filters?: Record<string, unknown>;
}

export interface FormActionRef {
  name: string;
  label: string;
}

export interface AgentMetadata {
  name: string;
  display_name: string;
  icon: string;
  description: string;
  category: AgentCategory;
  enabled: boolean;
  example_prompts: string[];
  report_builder?: ReportBuilderSchema;
  form_actions?: FormActionRef[];
}

// ── Form schema (LMS) ───────────────────────────────────────────────

export type FormFieldType =
  | 'select'
  | 'date'
  | 'text'
  | 'textarea'
  | 'number'
  | 'boolean';

export interface FormField {
  name: string;
  label: string;
  type: FormFieldType;
  options?: string[];
  required: boolean;
  max_length?: number;
  min?: number;
  max?: number;
  placeholder?: string;
}

export interface FormSchema {
  action: string;
  title: string;
  fields: FormField[];
  submit_label: string;
}

export interface FormSubmitResult {
  ok: boolean;
  message: string;
  request_id?: string;
}

// ── Report builder query plan ───────────────────────────────────────

export type FilterOp =
  | 'eq'
  | 'in'
  | 'between'
  | 'contains'
  | 'gte'
  | 'lte'
  | 'is';

export interface QueryFilter {
  column: string;
  op: FilterOp;
  value?: unknown;
  values?: unknown[];
  lo?: unknown;
  hi?: unknown;
  fy_label?: string;
  start?: string;
  end?: string;
}

export interface QueryOrderBy {
  column: string;
  direction: 'asc' | 'desc';
}

export interface QueryPlan {
  intent: 'aggregate' | 'list' | 'count';
  aggregate?: ReportAggregation;
  aggregate_column?: string;
  filters: QueryFilter[];
  group_by: string[];
  order_by: QueryOrderBy[];
  limit: number;
}

export interface ReportRowsResponse {
  rows: Record<string, unknown>[];
  columns?: string[];
  summary?: string;
  total_rows?: number;
  sql?: string;
  row_count?: number;
}

// ── New SSE event payloads ──────────────────────────────────────────

export interface PromptOption {
  label: string;
  prompt: string;
}

export interface AssumptionEvent {
  type: 'assumption';
  text: string;
  alternatives?: PromptOption[];
}

export interface DrillSuggestionsEvent {
  type: 'drill_suggestions';
  suggestions: PromptOption[];
}

export interface ClarificationEvent {
  type: 'clarification';
  question: string;
  options?: PromptOption[];
}

export interface LmsFormEvent {
  type: 'lms_form';
  form_id: string;
  title?: string;
  fields: unknown[];
  submit_label?: string;
}

export interface AssumptionNote {
  text: string;
  alternatives?: PromptOption[];
}

export interface ClarificationCard {
  question: string;
  options?: PromptOption[];
}
