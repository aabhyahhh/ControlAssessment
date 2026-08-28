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

export interface RiskInference {
  value: string;
  source: string;
  confidence: string;
  reasoning: string;
  probability?: string;
  impact?: string;
  score?: number;
}

export interface RiskBand {
  threshold: number;
  label: string;
}

export interface RiskWeighting {
  score_map: Record<string, number>;
  bands: RiskBand[];
  is_default?: boolean;
}

export interface HeatmapCell {
  likelihood: string;
  impact: string;
  count: number;
  control_ids: string[];
}

export interface PriorityQueueRow {
  control_id: string;
  risk_rating: string;
  completeness_pct: number;
  description: string;
  rank: number;
}

export interface Phase1Result {
  stats?: {
    controls_in_racm: number;
    racm_completeness_pct: number;
    high_risk_count: number;
    exposure_metric: { themes: Record<string, number>; top_theme: string; top_theme_count: number };
  };
  completeness_pct?: number;
  missing_attributes?: { control_id: string; missing_fields: string[] }[];
  heatmap?: { axes: { likelihood: string[]; impact: string[] }; cells: HeatmapCell[] };
  priority_queue?: PriorityQueueRow[];
  pending_risk_inferences?: Record<string, RiskInference>;
  controls_pending_inference?: number;
  applied_risk_inferences?: Record<string, RiskInference>;
  awaiting_weighting?: boolean;
  controls_missing_risk_level?: string[];
  default_weighting?: RiskWeighting;
  default_matrix?: Record<string, string>;
  weighting_used?: RiskWeighting;
  risk_matrix?: Record<string, string>;
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

export interface EvidenceScoreRow {
  control_id: string;
  score: number;
  band: "good" | "fair" | "poor";
}

export interface EscalatedGap {
  control_id: string;
  risk_rating: string;
  severity: string;
  explanation: string;
}

export interface Phase2Result {
  stats?: {
    avg_evidence_score: number;
    controls_without_evidence: number;
    evidence_gaps_count: number;
    test_ready_controls: number;
  };
  required_documents?: Record<string, string[]>;
  evidence_scores?: EvidenceScoreRow[];
  document_completeness_donut?: { matched: number; missing: number };
  missing_documents?: { control_id: string; missing: string[] }[];
  escalated_gaps?: EscalatedGap[];
  format_flags?: { control_id: string; detected_mode: string }[];
}

export interface SopUploadResult {
  sop_upload_id: string;
  filename: string;
  parsed_step_count: number;
}

export interface FieldMismatch {
  field: string;
  rcm_value: string;
  sop_value: string;
}

export interface ControlAlignmentRow {
  control_id: string;
  alignment: "aligned" | "partial" | "misaligned";
  mismatches: FieldMismatch[];
}

export interface CoverageGap {
  sop_step_id: string;
  description: string;
  coverage: "none";
}

export interface DeficiencyRow {
  control_id: string;
  verdict: "Adequate" | "Partially adequate" | "Inadequate";
  score: number;
  weak_dimensions: string[];
  /** Per-dimension 0-100 scores from the adequacy engine. Optional because
   *  results stored before this field existed will not carry it. */
  dimension_scores?: Record<string, number>;
}

export interface TimelineSufficiencyRow {
  control_id: string;
  status: "sufficient" | "insufficient" | "undetermined";
  flags: string[];
  earliest_evidence_date: string | null;
  latest_evidence_date: string | null;
  expected_instances: number | null;
  evidence_instances_found: number;
  coverage_pct: number;
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

export interface AttributeItem {
  id: string;
  name: string;
  description: string;
}

export interface SampleColumnItem {
  key: string;
  header: string;
}

export interface ControlAttributes {
  control_id: string;
  worksteps: string[];
  attributes: AttributeItem[];
  sample_columns: SampleColumnItem[];
  quality_issues: string[];
  status: "pending" | "approved";
  updated_at: string;
}

export interface SampleResult {
  control_id: string;
  sample_id: string;
  result: "PASS" | "FAIL";
  attribute_results: Record<string, string>;
  attribute_reasoning: Record<string, string>;
  sample_details: Record<string, string>;
  remarks: string;
}

export interface ControlTestResult {
  control_id: string;
  /** Short label derived from the RCM description, for card headings.
   *  Optional: results stored before this field existed will not carry it. */
  control_title?: string;
  /** Inherent risk from the RCM row. */
  risk_level?: string | null;
  test_mode: string;
  total_samples: number;
  passed_samples: number;
  failed_samples: number;
  deviation_rate: number;
  effectiveness_status: string;
  deficiency_type: string | null;
  overall_remarks: string;
  sample_results: SampleResult[];
}

export interface SamplingResultRow {
  control_id: string;
  frequency: string;
  sample_size: number;
  fails: number;
  verdict: string;
  deficiency_type: string | null;
  deviation_rate: number;
}

export interface FormatIssue {
  control_id: string;
  detected_mode: string;
  message: string;
}

/** One FAILED sample, ranked for remediation. Scored from the control's
 *  Phase 1 risk level and its Phase 3 SOP alignment — see
 *  engines/remediation_engine.py for the weighting. */
export interface RemediationPriority {
  rank: number;
  control_id: string;
  sample_id: string;
  priority: string;
  score: number;
  risk_level: string;
  sop_alignment: string | null;
  in_sop: boolean;
  verdict: string;
  failed_attributes: string[];
  why: string;
  remarks: string;
}

export interface Phase4Result {
  stats?: {
    effective: number;
    partially_effective: number;
    ineffective: number;
    unclosed_exceptions: number;
    format_issue_count: number;
  };
  overall_health_pct?: number;
  tested_control_count?: number;
  material_weakness_indicators?: { control_id: string; reason: string }[];
  format_issues?: FormatIssue[];
  sampling_results?: SamplingResultRow[];
  control_results?: ControlTestResult[];
  remediation_priorities?: RemediationPriority[];
}

export interface Phase3Result {
  stats?: {
    adequate_count: number;
    partially_adequate_count: number;
    inadequate_count: number;
    uncovered_sop_steps: number;
    timeline_issues_count: number;
  };
  sop_upload?: { filename: string; parsed_step_count: number };
  control_alignment?: ControlAlignmentRow[];
  coverage_gaps?: CoverageGap[];
  control_type_mix?: { preventive: number; detective: number; corrective: number };
  deficiencies?: DeficiencyRow[];
  timeline_sufficiency?: TimelineSufficiencyRow[];
}
