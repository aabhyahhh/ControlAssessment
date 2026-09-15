export interface User {
  id: string;
  email: string;
  name: string | null;
  created_at: string;
}

export type Framework = "generic" | "sox" | "itgc" | "iso27001";

export interface Project {
  id: string;
  name: string;
  framework: Framework;
  audit_period_start: string;
  audit_period_end: string;
  current_phase: 1 | 2 | 3 | 4;
  phase_status: Record<"1" | "2" | "3" | "4", PhaseStatus>;
  status: string;
  created_at: string;
  updated_at: string;
}

export type PhaseStatus = "pending" | "running" | "awaiting_approval" | "done" | "error";

export interface WorkflowProgress {
  phase1: PhaseStatus;
  phase2: PhaseStatus;
  phase3: PhaseStatus;
  phase4: PhaseStatus;
}

export type ActiveStep = 1 | 2 | 3 | 4;

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "tool";
  content: string;
  createdAt: string;
}

export interface RcmUploadResult {
  rcm_upload_id: string;
  row_count: number;
  column_map: Record<string, string>;
  passthrough: string[];
  still_missing: string[];
  header_row_index: number;
}

export interface ControlCompletenessRow {
  control_id: string;
  control_description: string;
  completeness_pct: number;
  missing_fields: string[];
}

export interface RcmFieldCompleteness {
  field: string;
  populated: number;
  blank: number;
  blank_control_ids: string[];
}

export interface RcmCompletenessAnalytics {
  fields: RcmFieldCompleteness[];
  total_controls: number;
  controls_with_blanks: number;
  fields_requiring_reconciliation: string[];
}

export interface Phase1Analytics {
  control_population: { total: number };
  rcm_completeness: RcmCompletenessAnalytics;
}

export interface Phase1Result {
  stats?: {
    controls_in_racm: number;
    racm_completeness_pct: number;
  };
  completeness_pct?: number;
  missing_attributes?: { control_id: string; missing_fields: string[] }[];
  controls?: ControlCompletenessRow[];
  analytics?: Phase1Analytics;
}

export interface PhaseResult<T = Record<string, unknown>> {
  phase: number;
  status: PhaseStatus;
  result: T;
  approved_at: string | null;
  updated_at: string;
}

export interface Control {
  id: string;
  control_id: string;
  control_description: string | null;
  risk_description: string | null;
  risk_level: string | null;
  control_type: string | null;
  control_nature: string | null;
  control_frequency: string | null;
  control_owner: string | null;
  process: string | null;
  raw_row: Record<string, unknown>;
}

export interface EvidenceFolderControlSummary {
  control_id: string;
  detected_mode: "multi_sample" | "invalid_format" | "no_evidence";
  sample_count: number;
  file_count: number;
}

export interface EvidenceUploadResult {
  controls: EvidenceFolderControlSummary[];
  total_files_saved: number;
  unmatched_control_ids: string[];
}

export type Severity = "critical" | "high" | "medium" | "low";

// ── Step 2: Adequacy (SOPs + monthly workpapers) ──────────────────────────

export interface ReconcileFieldStatus {
  rcm_value: string;
  doc_value: string;
  status: "supported" | "contradicted" | "absent" | "undetermined";
}

export interface ReconciliationRow {
  control_id: string;
  /** null when it could not be assessed (no LLM / no control-specific text). */
  reconciliation_pct: number | null;
  described_in_docs: boolean;
  fields: Record<string, ReconcileFieldStatus>;
}

export interface WorkpaperCoverageRow {
  control_id: string;
  months_expected: string[];
  months_present: string[];
  months_missing: string[];
  coverage_pct: number;
}

export interface FieldMismatch {
  field: string;
  rcm_value: string;
  sop_value: string;
}

export interface ControlAlignmentRow {
  control_id: string;
  alignment: "aligned" | "partial" | "misaligned" | "not_assessed";
  mismatches: FieldMismatch[];
}

export interface CoverageGap {
  sop_step_id: string;
  description: string;
  coverage: "none";
}

export interface ControlSopGapField {
  field: string;
  status: "contradicted" | "undocumented";
  rcm_value: string;
  doc_value: string;
}

export interface ControlSopGap {
  control_id: string;
  gaps: ControlSopGapField[];
  gap_count: number;
}

export type DimensionState = "supported" | "contradicted" | "undocumented" | "not_assessed";

export interface DeficiencyRow {
  control_id: string;
  verdict: "Adequate" | "Partially adequate" | "Inadequate" | "Not assessed";
  weak_dimensions: string[];
  dimension_states?: Record<string, DimensionState>;
}

export interface AdequacyDocSummary {
  control_id: string | null;
  doc_kind: "sop" | "workpaper";
  filename: string;
  period_month: string | null;
  parsed_step_count: number;
}

export interface AdequacyUploadResult {
  documents: AdequacyDocSummary[];
  total_files_saved: number;
  unmatched_control_ids: string[];
}

export interface ReconciliationFieldCounts {
  field: string;
  supported: number;
  contradicted: number;
  undocumented: number;
  undetermined: number;
  control_ids: {
    supported: string[];
    contradicted: string[];
    undocumented: string[];
    undetermined: string[];
  };
}

export interface ReconciliationSummaryAnalytics {
  cell_counts: { supported: number; contradicted: number; undocumented: number; undetermined: number };
  pct_supported: number | null;
  pct_contradicted: number | null;
  pct_undocumented: number | null;
  pct_undetermined: number | null;
  most_contradicted_fields: { field: string; control_count: number }[];
  controls_by_exception_count: { control_id: string; contradicted: number; undetermined: number }[];
  /** Same four buckets as `cell_counts`, broken out per RCM field — the
   *  source for the "what the documents establish" bar chart. */
  by_field: ReconciliationFieldCounts[];
}

export interface WorkpaperCoverageAnalytics {
  controls_complete: number;
  controls_with_missing: number;
  total_missing_control_months: number;
  overall_coverage_pct: number | null;
  months_most_missing: { month: string; missing_control_count: number }[];
}

export interface DesignProfileDimension {
  dimension: string;
  supported: number;
  contradicted: number;
  undocumented: number;
  not_assessed: number;
}

export interface DesignProfileAnalytics {
  dimensions: DesignProfileDimension[];
  total_controls: number;
  /** False only when every control is "not_assessed" (no LLM available). */
  assessed: boolean;
}

export interface Phase2Analytics {
  adequacy_summary: {
    adequate: number;
    partially_adequate: number;
    inadequate: number;
    not_in_docs: number;
    total: number;
  };
  reconciliation_summary: ReconciliationSummaryAnalytics;
  workpaper_coverage: WorkpaperCoverageAnalytics;
  design_profile: DesignProfileAnalytics;
}

export interface Phase2Result {
  stats?: {
    adequate_count: number;
    partially_adequate_count: number;
    inadequate_count: number;
    uncovered_sop_steps: number;
    workpaper_gap_count: number;
    unreconciled_count: number;
  };
  reconciliation?: ReconciliationRow[];
  control_alignment?: ControlAlignmentRow[];
  coverage_gaps?: CoverageGap[];
  control_sop_gaps?: ControlSopGap[];
  deficiencies?: DeficiencyRow[];
  workpaper_coverage?: WorkpaperCoverageRow[];
  analytics?: Phase2Analytics;
}

// ── Step 3: Evidence requirements & intake ────────────────────────────────

export interface DeclaredEvidenceItem {
  name: string;
  note?: string | null;
}

export interface DeclaredEvidence {
  control_id: string;
  items: DeclaredEvidenceItem[];
  updated_at?: string | null;
}

export interface EvidenceScoreRow {
  control_id: string;
  score: number;
  band: "good" | "fair" | "poor";
}

export interface EvidencePerControlRow {
  control_id: string;
  required: string[];
  declared: string[];
  uploaded_filenames: string[];
  matched: string[];
  declared_not_uploaded: string[];
  missing: string[];
  extra_declared: string[];
  score: number;
  severity: Severity | null;
}

export interface EscalatedGap {
  control_id: string;
  severity: Severity;
  explanation: string;
}

export interface EvidenceStatusMatrixRow {
  control_id: string;
  expected: number;
  received: number;
  declared_not_uploaded: number;
  missing: number;
}

export interface Phase3Analytics {
  expected_total: number;
  declared_total: number;
  uploaded_total: number;
  covered_total: number;
  gap_total: number;
  controls_fully_covered: number;
  controls_partial: number;
  controls_no_evidence: number;
  gap_by_severity: Record<Severity, number>;
  /** Fixed columns from the engine's own reconciliation — never a guessed
   *  document-category grid. */
  status_matrix: EvidenceStatusMatrixRow[];
}

export interface ContradictedEvidenceField {
  field: string;
  rcm_value: string;
  doc_value: string;
  justification_status: string;
  justification_verdict: "justified" | "partially_justified" | "not_justified" | null;
}

export interface ControlEvidenceCategories {
  control_id: string;
  reconciled_from_sop_and_workpaper: string[];
  contradicted_in_sop_or_workpaper: ContradictedEvidenceField[];
  missing_from_evidence_folder: string[];
}

export interface Phase3Result {
  stats?: {
    avg_evidence_score: number;
    controls_without_evidence: number;
    evidence_gaps_count: number;
    severity_rollup: Record<Severity, number>;
  };
  required_documents?: Record<string, string[]>;
  evidence_scores?: EvidenceScoreRow[];
  per_control?: EvidencePerControlRow[];
  escalated_gaps?: EscalatedGap[];
  format_flags?: { control_id: string; detected_mode: string }[];
  control_evidence_categories?: ControlEvidenceCategories[];
  analytics?: Phase3Analytics;
}

// ── Justification emails (Step 2 mismatch follow-up) ─────────────────────

export interface JustificationEmailItem {
  id: string;
  control_id: string;
  field: string | null;
  mismatch_description: string;
  response_text: string | null;
  response_attachment_name: string | null;
  response_uploaded_at: string | null;
  analysis_verdict: "justified" | "partially_justified" | "not_justified" | null;
  analysis_reasoning: string | null;
  analyzed_at: string | null;
}

export interface JustificationEmail {
  id: string;
  recipient_email: string;
  subject: string;
  sent_at: string;
  send_status: "sent" | "failed";
  error_message?: string | null;
  items: JustificationEmailItem[];
}

export interface SendJustificationEmailRequest {
  recipient_email: string;
  subject: string;
  body: string;
  items: { control_id: string; field: string | null; mismatch_description: string }[];
}

// ── Step 4: Gap assessment ───────────────────────────────────────────────

export interface GapAssessmentRow {
  control_id: string;
  control_description: string;
  severity: Severity | null;
  expected_documents: string[];
  received_documents: string[];
  missing_documents: string[];
  rcm_field_gaps: string[];
  sop_alignment: string | null;
  reconciliation_pct: number | null;
  design_verdict: string | null;
  workpaper_months_missing: string[];
  gap_areas: string[];
  summary: string;
}

export interface CoverageFunnelStage {
  stage: string;
  count: number;
  /** Controls excluded from this stage because they could not be assessed
   *  (e.g. no reconciliation data) — kept apart from controls that were
   *  assessed and genuinely didn't qualify. */
  unassessed: number;
}

export interface GapAreaConcentration {
  area: string;
  control_count: number;
  control_ids: string[];
}

export interface Phase4Analytics {
  severity_distribution: Record<Severity | "none", number>;
  coverage_funnel: CoverageFunnelStage[];
  gap_area_concentration: GapAreaConcentration[];
}

export interface Phase4Result {
  stats?: {
    controls_assessed: number;
    severity_rollup: Record<Severity | "none", number>;
    fully_covered: number;
    partial: number;
    serious: number;
  };
  rows?: GapAssessmentRow[];
  analytics?: Phase4Analytics;
}

export interface Artifact {
  id: string;
  project_id: string;
  phase: number | null;
  filename: string;
  artifact_type: string | null;
  created_at: string;
}

export interface RunAllResult {
  completed_phases: number[];
  stopped_at_phase: number | null;
  blocked_reason: string | null;
  message: string;
}

