import { ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ChatBubble from "../components/ChatBubble";
import ChatInput, { type ChatInputHandle } from "../components/ChatInput";
import PhaseProgress from "../components/PhaseProgress";
import Sidebar from "../components/Sidebar";
import TypingIndicator from "../components/TypingIndicator";
import Phase1RiskPane from "../components/panes/Phase1RiskPane";
import Phase2EvidencePane from "../components/panes/Phase2EvidencePane";
import Phase3AdequacyPane from "../components/panes/Phase3AdequacyPane";
import Phase4TestingPane from "../components/panes/Phase4TestingPane";
import AttributePreviewPane from "../components/panes/AttributePreviewPane";
import { getProject } from "../services/projectService";
import { appendChatMessage, listChatMessages, sendChatMessage } from "../services/chatService";
import { uploadEvidenceFolder, uploadRcm, uploadSop } from "../services/uploadService";
import {
  approveRiskInferences,
  getPhaseResult,
  runAdequacyAssessment,
  runAllRemainingPhases,
  runControlTesting,
  runEvidenceGapAnalysis,
  runRiskPrioritization,
  setRiskWeighting,
} from "../services/phaseService";
import {
  approveAttributes,
  getPhaseProgress,
  listAttributes,
  modifyAttribute,
  previewAttributes,
  removeAttribute,
} from "../services/attributeService";
import PhaseActionsBar from "../components/PhaseActionsBar";
import RepositoryPanel from "../components/RepositoryPanel";
import {
  downloadArtifact,
  exportAttributes,
  exportFinalReport,
  exportPhase,
  exportRcm,
  listArtifacts,
  overrideAttributes,
  overrideRcm,
} from "../services/exportService";
import { ApiError } from "../services/api";
import type { StageProgress } from "../services/attributeService";
import type {
  ActiveStep,
  Artifact,
  ChatMessage,
  ControlAttributes,
  Phase1Result,
  Phase2Result,
  Phase3Result,
  Phase4Result,
  PhaseStatus,
  Project,
  WorkflowProgress,
} from "../types";

const DEFAULT_WORKFLOW_PROGRESS: WorkflowProgress = {
  phase1: "pending",
  phase2: "pending",
  phase3: "pending",
  phase4: "pending",
};

/** Human-readable captions for the tools the agent can call, shown beside the
 *  typing dots. Keys must match the tool names in agent/tools/phase_tools.py.
 *  An unmapped tool falls back to a generic "Working…", so adding a tool
 *  backend-side degrades gracefully rather than showing a raw identifier. */
const TOOL_LABELS: Record<string, string> = {
  get_project_status: "Checking where we are…",
  run_racm_validation: "Validating the RACM…",
  set_risk_weighting: "Applying the risk weighting…",
  approve_risk_inferences: "Committing the risk levels…",
  run_evidence_review: "Reviewing evidence…",
  run_adequacy_assessment: "Assessing design adequacy…",
  generate_testing_attributes: "Generating testing attributes…",
  approve_attributes_and_run_testing: "Testing controls against evidence…",
  export_report: "Building the workpaper…",
};

/**
 * Joins count clauses, dropping any whose count is zero.
 *
 * "12 organized into samples, 0 with no sample structure, 0 with no evidence"
 * spends most of its words on things that didn't happen. A zero here is the
 * absence of a finding, and an absent finding doesn't need reporting — the
 * reader only needs what is actually true of their engagement.
 *
 * `fallback` covers the case where every count is zero, so the sentence never
 * collapses to nothing.
 */
function summarizeCounts(parts: { count: number; text: string }[], fallback: string): string {
  const kept = parts.filter((p) => p.count > 0).map((p) => p.text);
  if (kept.length === 0) return fallback;
  if (kept.length === 1) return kept[0];
  return `${kept.slice(0, -1).join(", ")} and ${kept[kept.length - 1]}`;
}

const PHASE_TITLES: Record<ActiveStep, string> = {
  1: "RACM Validation & Risk Prioritization",
  2: "Control Evidence Review & Gap Identification",
  3: "Adequacy Assessment",
  4: "Control Effectiveness Assessment",
};

function deriveWorkflowProgress(project: Project): WorkflowProgress {
  const status = project.phase_status;
  return {
    phase1: (status["1"] ?? "pending") as PhaseStatus,
    phase2: (status["2"] ?? "pending") as PhaseStatus,
    phase3: (status["3"] ?? "pending") as PhaseStatus,
    phase4: (status["4"] ?? "pending") as PhaseStatus,
  };
}

export default function Workspace() {
  const { projectId } = useParams<{ projectId: string }>();
  const navigate = useNavigate();
  const chatInputRef = useRef<ChatInputHandle>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<(() => void) | null>(null);

  const [project, setProject] = useState<Project | null>(null);
  const [workflowProgress, setWorkflowProgress] = useState<WorkflowProgress>(DEFAULT_WORKFLOW_PROGRESS);
  const [activeStep, setActiveStep] = useState<ActiveStep>(1);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  /** What the agent is currently doing, shown beside the typing dots. Null
   *  means "working" with no more specific description. */
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  /** Live progress of whichever long-running phase is in flight, keyed by
   *  stage ("adequacy" | "attributes" | "testing"). Polled centrally rather
   *  than per call site, so every phase gets a bar for free. */
  const [stageProgress, setStageProgress] = useState<Record<string, StageProgress>>({});
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [phase1Result, setPhase1Result] = useState<Phase1Result | null>(null);
  const [phase1Busy, setPhase1Busy] = useState(false);
  const [phase2Result, setPhase2Result] = useState<Phase2Result | null>(null);
  const [phase2Busy, setPhase2Busy] = useState(false);
  const [phase3Result, setPhase3Result] = useState<Phase3Result | null>(null);
  const [phase3Busy, setPhase3Busy] = useState(false);
  const [sopUploaded, setSopUploaded] = useState(false);
  const [phase4Result, setPhase4Result] = useState<Phase4Result | null>(null);
  const [phase4Busy, setPhase4Busy] = useState(false);
  const [attributeSchemas, setAttributeSchemas] = useState<ControlAttributes[] | null>(null);
  const [phase4View, setPhase4View] = useState<"results" | "attributes">("results");
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [showRepository, setShowRepository] = useState(false);
  const [exportBusy, setExportBusy] = useState(false);
  const [runAllBusy, setRunAllBusy] = useState(false);

  const [dataPaneCollapsed, setDataPaneCollapsed] = useState(false);
  const [dataPaneWidth, setDataPaneWidth] = useState(() => Math.round(window.innerWidth * 0.39));
  const isDraggingRef = useRef(false);
  const dragStartXRef = useRef(0);
  const dragStartWidthRef = useRef(dataPaneWidth);
  const prevDataPaneWidthRef = useRef(dataPaneWidth);

  useEffect(() => {
    if (!projectId) return;
    getProject(projectId)
      .catch(() => {
        // The project is gone (deleted here or in another tab) or was never
        // ours. Without this the page sat on "Loading project…" forever,
        // because `project` stays null and nothing else clears that state.
        navigate("/projects", { replace: true });
        return null;
      })
      .then((p) => {
        if (!p) return;
        setProject(p);
        setWorkflowProgress(deriveWorkflowProgress(p));
        setActiveStep(p.current_phase);
        if (p.phase_status["1"] !== "pending") {
          getPhaseResult<Phase1Result>(projectId, 1)
            .then((res) => setPhase1Result(res.result))
            .catch(() => undefined);
        }
        if (p.phase_status["2"] !== "pending") {
          getPhaseResult<Phase2Result>(projectId, 2)
            .then((res) => setPhase2Result(res.result))
            .catch(() => undefined);
        }
        if (p.phase_status["3"] !== "pending") {
          getPhaseResult<Phase3Result>(projectId, 3)
            .then((res) => {
              setPhase3Result(res.result);
              setSopUploaded(true);
            })
            .catch(() => undefined);
        }
        if (p.phase_status["4"] !== "pending") {
          getPhaseResult<Phase4Result>(projectId, 4)
            .then((res) => setPhase4Result(res.result))
            .catch(() => undefined);
        }
        // Attribute schemas drive Phase 4's pre-testing review screen.
        listAttributes(projectId)
          .then((rows) => setAttributeSchemas(rows.length ? rows : null))
          .catch(() => undefined);
        listArtifacts(projectId)
          .then(setArtifacts)
          .catch(() => undefined);
        // Restore the transcript so leaving the workspace and coming back
        // doesn't lose the conversation.
        listChatMessages(projectId)
          .then((rows) => {
            if (rows.length) setMessages(rows);
            setHistoryLoaded(true);
          })
          .catch(() => setHistoryLoaded(true));
    });
  }, [projectId, navigate]);

  useEffect(() => {
    // Only greet once the stored transcript has been checked — otherwise the
    // welcome message races the history fetch and gets prepended to a
    // conversation that's already underway.
    if (historyLoaded && messages.length === 0 && project) {
      setMessages([
        {
          id: "welcome",
          role: "assistant",
          content:
            `Hello — I'm your control assessment agent for "${project.name}". I'll run the four-phase ` +
            "assessment: RACM validation, evidence review, adequacy assessment, and control effectiveness " +
            "testing.\n\n**Next:** Attach your RCM file (.xlsx/.xls/.csv) using the attach button to begin.",
          createdAt: new Date().toISOString(),
        },
      ]);
    }
  }, [project, messages.length, historyLoaded]);

  useEffect(() => {
    chatScrollRef.current?.scrollTo({ top: chatScrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

  // One poller for every long-running phase, active only while something is
  // in flight. Central rather than per-call-site so adequacy, attribute
  // generation and testing all get a progress bar without each duplicating
  // the loop — and so a phase started from CHAT is covered too.
  useEffect(() => {
    if (!projectId || !isStreaming) {
      setStageProgress({});
      return;
    }
    let live = true;
    const tick = async () => {
      while (live) {
        try {
          const res = await getPhaseProgress(projectId);
          if (live) setStageProgress(res.stages ?? {});
        } catch {
          /* a failed poll costs only this tick's update */
        }
        await new Promise((r) => setTimeout(r, 1500));
      }
    };
    void tick();
    return () => {
      live = false;
    };
  }, [projectId, isStreaming]);

  useEffect(() => {
    return () => {
      abortRef.current?.();
    };
  }, []);

  /** The workflow state the hint is derived from. Passing this explicitly is
   *  what makes the hint correct at the moment a message is pushed: a caller
   *  that has just received a fresh phase result cannot read it back from
   *  state (React batches updates, so the closure still holds the OLD value)
   *  — it has to hand the new value in. Omitted fields fall back to state. */
  interface HintState {
    p1?: Phase1Result | null;
    p2?: Phase2Result | null;
    p3?: Phase3Result | null;
    p4?: Phase4Result | null;
    sop?: boolean;
    attrs?: ControlAttributes[] | null;
    /** Suppress the line outright: for "…running X now" messages, where the
     *  result follows in seconds and the user is not being asked for
     *  anything. */
    none?: true;
  }

  /** Mirrors the backend's _blocking_action_hint: the next action ONLY when
   *  the workflow is genuinely blocked on the user (a file to attach, or an
   *  approval that is theirs to give). Returns null when the tool can carry
   *  on by itself, so progress updates don't each end in an instruction. */
  const nextActionHint = useCallback(
    (over: HintState = {}): string | null => {
      if (over.none) return null;
      // Read from the loaded phase results, NOT from the `project` snapshot —
      // that object is fetched once on mount and never refreshed, so keying
      // off it produced stale advice ("attach your evidence folder") after
      // the evidence was already in.
      const p1 = over.p1 !== undefined ? over.p1 : phase1Result;
      const p2 = over.p2 !== undefined ? over.p2 : phase2Result;
      const p3 = over.p3 !== undefined ? over.p3 : phase3Result;
      const p4 = over.p4 !== undefined ? over.p4 : phase4Result;
      const sop = over.sop !== undefined ? over.sop : sopUploaded;
      const attrs = over.attrs !== undefined ? over.attrs : attributeSchemas;

      if (!p1) {
        return "Attach your RCM file (.xlsx/.xls/.csv) using the attach button to begin.";
      }
      if (p1.awaiting_weighting) {
        return "Choose a Probability × Impact weighting on the right (default or custom) and I'll infer the missing Risk Levels.";
      }
      if (Object.keys(p1.pending_risk_inferences ?? {}).length > 0) {
        return 'Review the inferred Risk Levels on the right, then click "Approve & Continue".';
      }
      if (!p2) {
        return "Attach your evidence folder — one subfolder per Control ID, with samples inside as sample1/, sample2/… or files named sample_1.pdf.";
      }
      if (!p3 && !sop) {
        return "Attach your SOP document (.docx, .pdf or .txt) so I can run the adequacy assessment.";
      }
      if (p3 && attrs && !p4) {
        return "Review the testing attributes on the right, then approve them to run effectiveness testing.";
      }
      return null;
    },
    [phase1Result, phase2Result, phase3Result, phase4Result, sopUploaded, attributeSchemas],
  );

  /** Adds an agent line to the thread AND persists it, so phase summaries
   *  and upload confirmations survive leaving the workspace.
   *
   *  Appends a closing "**Next:**" call-to-action only when the workflow is
   *  actually blocked on the user. These UI-generated lines bypass the agent,
   *  so they need the same restraint the backend applies — otherwise a run of
   *  progress updates each repeats the same stale instruction. */
  const pushAssistantMessage = useCallback(
    (content: string, hintState?: HintState) => {
      const hint = nextActionHint(hintState ?? {});
      const withNext =
        content.includes("**Next:**") || !hint ? content : `${content}\n\n**Next:** ${hint}`;
      setMessages((prev) => [
        ...prev,
        {
          id: `a-${Date.now()}-${Math.random()}`,
          role: "assistant",
          content: withNext,
          createdAt: new Date().toISOString(),
        },
      ]);
      if (projectId) void appendChatMessage(projectId, "assistant", withNext).catch(() => undefined);
    },
    [projectId, nextActionHint],
  );

  const pushUserMessage = useCallback(
    (content: string) => {
      setMessages((prev) => [
        ...prev,
        { id: `u-${Date.now()}-${Math.random()}`, role: "user", content, createdAt: new Date().toISOString() },
      ]);
      if (projectId) void appendChatMessage(projectId, "user", content).catch(() => undefined);
    },
    [projectId],
  );

  const runPhase1 = useCallback(
    async (pid: string) => {
      setPhase1Busy(true);
      try {
        const res = await runRiskPrioritization(pid);
        setPhase1Result(res.result);
        setWorkflowProgress((prev) => ({ ...prev, phase1: res.status }));
        setActiveStep(1);
        if (res.status === "awaiting_approval") {
          // Phase 1 now has two distinct gates: choosing the risk weighting,
          // then approving the inferred levels. Say which one is waiting.
          if (res.result.awaiting_weighting) {
            const missing = res.result.controls_missing_risk_level?.length ?? 0;
            pushAssistantMessage(
              `${missing} control${missing === 1 ? " has" : "s have"} no Risk Level in this RCM. I can infer them ` +
                "from Probability × Impact — choose the weighting on the right (default or your own) and I'll apply it.",
              { p1: res.result },
            );
          } else {
            const n = res.result.controls_pending_inference ?? 0;
            pushAssistantMessage(
              `I inferred a Risk Level for ${n} control${n === 1 ? "" : "s"}. Review them in the panel on the right — approve to continue.`,
              { p1: res.result },
            );
          }
        } else {
          const stats = res.result.stats;
          // Stay on Phase 1 so the user can actually read the visualisation
          // they just generated. The pane advances when they ask to proceed,
          // not the instant a phase finishes.
          pushAssistantMessage(
            `RACM validated: ${stats?.controls_in_racm ?? 0} controls, ${Math.round((stats?.racm_completeness_pct ?? 0) * 100)}% complete, ${stats?.high_risk_count ?? 0} high-risk. Review the results on the right — tell me to proceed when you're ready for evidence review.`,
            { p1: res.result },
          );
        }
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run risk prioritization."}`);
      } finally {
        setPhase1Busy(false);
      }
    },
    [pushAssistantMessage],
  );

  const handleChooseWeighting = useCallback(
    async (body: {
      use_default: boolean;
      score_map?: Record<string, number>;
      bands?: { threshold: number; label: string }[];
    }) => {
      if (!projectId) return;
      setPhase1Busy(true);
      try {
        const res = await setRiskWeighting(projectId, body);
        setPhase1Result(res.result);
        setWorkflowProgress((prev) => ({ ...prev, phase1: res.status }));
        const n = Object.keys(res.result.pending_risk_inferences ?? {}).length;
        pushAssistantMessage(
          `Applied the ${body.use_default ? "default" : "custom"} Probability × Impact weighting and inferred ` +
            `risk levels for ${n} control${n === 1 ? "" : "s"}. Review them on the right before I continue.`,
          { p1: res.result },
        );
      } catch (err) {
        pushAssistantMessage(
          `[error] ${err instanceof ApiError ? err.message : "Failed to apply the risk weighting."}`,
        );
      } finally {
        setPhase1Busy(false);
      }
    },
    [projectId, pushAssistantMessage],
  );

  const handleApproveInferences = useCallback(async () => {
    if (!projectId) return;
    setPhase1Busy(true);
    try {
      const res = await approveRiskInferences(projectId);
      setPhase1Result(res.result);
      setWorkflowProgress((prev) => ({ ...prev, phase1: res.status }));
      const stats = res.result.stats;
      pushAssistantMessage(
        `Risk levels approved. RACM validated: ${stats?.controls_in_racm ?? 0} controls, ${Math.round((stats?.racm_completeness_pct ?? 0) * 100)}% complete, ${stats?.high_risk_count ?? 0} high-risk. Review the results on the right — tell me to proceed when you're ready for evidence review.`,
        { p1: res.result },
      );
    } catch (err) {
      pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to approve risk inferences."}`);
    } finally {
      setPhase1Busy(false);
    }
  }, [projectId, pushAssistantMessage]);

  const runPhase2 = useCallback(
    async (pid: string) => {
      setPhase2Busy(true);
      try {
        const res = await runEvidenceGapAnalysis(pid);
        setPhase2Result(res.result);
        setWorkflowProgress((prev) => ({ ...prev, phase2: res.status }));
        setActiveStep(2);
        const stats = res.result.stats;
        const findings = summarizeCounts(
          [
            {
              count: stats?.evidence_gaps_count ?? 0,
              text: `${stats?.evidence_gaps_count} escalated gap${(stats?.evidence_gaps_count ?? 0) === 1 ? "" : "s"}`,
            },
            {
              count: stats?.test_ready_controls ?? 0,
              text: `${stats?.test_ready_controls} control${(stats?.test_ready_controls ?? 0) === 1 ? "" : "s"} ready for testing`,
            },
          ],
          "",
        );
        pushAssistantMessage(
          `Evidence review complete: ${stats?.avg_evidence_score ?? 0}% average completeness` +
            (findings ? `, ${findings}` : "") +
            ". Review the details on the right, then let's move on to the adequacy assessment.",
          { p2: res.result },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run evidence gap analysis."}`);
      } finally {
        setPhase2Busy(false);
      }
    },
    [pushAssistantMessage],
  );

  const handleFolderSelect = useCallback(
    async (fileList: FileList) => {
      if (!projectId) return;
      const fileCount = fileList.length;
      pushUserMessage(`Uploaded evidence folder (${fileCount} file${fileCount === 1 ? "" : "s"})`);
      setIsStreaming(true);
      setBusyLabel(`Uploading ${fileCount} file${fileCount === 1 ? "" : "s"} and reviewing evidence…`);
      try {
        const res = await uploadEvidenceFolder(projectId, fileList);
        const multiSample = res.controls.filter((c) => c.detected_mode === "multi_sample").length;
        const invalidFormat = res.controls.filter((c) => c.detected_mode === "invalid_format").length;
        const noEvidence = res.controls.filter((c) => c.detected_mode === "no_evidence").length;
        pushAssistantMessage(
          `Saved ${res.total_files_saved} file${res.total_files_saved === 1 ? "" : "s"} across ${res.controls.length} controls: ` +
            summarizeCounts(
              [
                { count: multiSample, text: `${multiSample} organized into samples` },
                { count: invalidFormat, text: `${invalidFormat} with evidence but no sample structure` },
                { count: noEvidence, text: `${noEvidence} with no evidence` },
              ],
              "none could be classified",
            ) +
            "." +
            (res.unmatched_control_ids.length
              ? ` I couldn't match these folder names to a Control ID: ${res.unmatched_control_ids.join(", ")}.`
              : "") +
            " Running evidence gap analysis now…",
          { none: true },
        );
        await runPhase2(projectId);
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to upload evidence folder."}`);
      } finally {
        setIsStreaming(false);
        setBusyLabel(null);
      }
    },
    [projectId, pushAssistantMessage, pushUserMessage, runPhase2],
  );

  const runPhase3 = useCallback(
    async (pid: string) => {
      setPhase3Busy(true);
      try {
        const res = await runAdequacyAssessment(pid);
        setPhase3Result(res.result);
        setWorkflowProgress((prev) => ({ ...prev, phase3: res.status }));
        setActiveStep(3);
        const stats = res.result.stats;
        pushAssistantMessage(
          `Adequacy assessment complete: ` +
            summarizeCounts(
              [
                { count: stats?.adequate_count ?? 0, text: `${stats?.adequate_count} adequate` },
                {
                  count: stats?.partially_adequate_count ?? 0,
                  text: `${stats?.partially_adequate_count} partially adequate`,
                },
                { count: stats?.inadequate_count ?? 0, text: `${stats?.inadequate_count} inadequate` },
                {
                  count: stats?.uncovered_sop_steps ?? 0,
                  text: `${stats?.uncovered_sop_steps} SOP step${(stats?.uncovered_sop_steps ?? 0) === 1 ? "" : "s"} with no matching control`,
                },
                {
                  count: stats?.timeline_issues_count ?? 0,
                  text: `${stats?.timeline_issues_count} timeline issue${(stats?.timeline_issues_count ?? 0) === 1 ? "" : "s"}`,
                },
              ],
              "no findings",
            ) +
            ". Review the details on the right, then let's move on to control effectiveness testing.",
          { p3: res.result, sop: true },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run adequacy assessment."}`);
      } finally {
        setPhase3Busy(false);
      }
    },
    [pushAssistantMessage],
  );

  const runPhase4 = useCallback(
    async (pid: string) => {
      setPhase4Busy(true);
      try {
        const res = await runControlTesting(pid);
        setPhase4Result(res.result);
        setWorkflowProgress((prev) => ({ ...prev, phase4: res.status }));
        setActiveStep(4);
        const stats = res.result.stats;
        pushAssistantMessage(
          `Testing complete across ${res.result.tested_control_count ?? 0} control(s): ` +
            summarizeCounts(
              [
                { count: stats?.effective ?? 0, text: `${stats?.effective} effective` },
                { count: stats?.partially_effective ?? 0, text: `${stats?.partially_effective} with exceptions` },
                { count: stats?.ineffective ?? 0, text: `${stats?.ineffective} ineffective` },
              ],
              "no controls returned a verdict",
            ) +
            `. Overall control health is ` +
            `${Math.round((res.result.overall_health_pct ?? 0) * 100)}%.` +
            ((stats?.format_issue_count ?? 0) > 0
              ? ` ${stats?.format_issue_count} control(s) could not be tested because their evidence isn't organized into samples — they're listed separately and excluded from the health score.`
              : ""),
          { p4: res.result },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run control testing."}`);
      } finally {
        setPhase4Busy(false);
      }
    },
    [pushAssistantMessage],
  );

  const handlePreviewAttributes = useCallback(async () => {
    if (!projectId) return;
    setPhase4Busy(true);
    setIsStreaming(true);
    setBusyLabel("Generating testing attributes…");
    pushAssistantMessage("Generating testing attributes for each control — this takes a moment…", { none: true });

    try {
      const rows = await previewAttributes(projectId);
      setAttributeSchemas(rows);
      setActiveStep(4);
      const failed = rows.filter((r) => r.attributes.length === 0);
      const issues = rows.reduce((n, r) => n + r.quality_issues.length, 0);
      pushAssistantMessage(
        `Generated attributes for ${rows.length} control(s).` +
          (issues > 0 ? ` ${issues} quality finding(s) flagged for review.` : " All passed the quality gate.") +
          (failed.length > 0 ? ` ${failed.length} control(s) need manual attributes.` : "") +
          " Review and edit them on the right, then approve to start testing.",
      );
    } catch (err) {
      pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to generate attributes."}`);
    } finally {
      setPhase4Busy(false);
      setIsStreaming(false);
      setBusyLabel(null);
    }
  }, [projectId, pushAssistantMessage]);

  const handleApproveAttributes = useCallback(async () => {
    if (!projectId) return;
    // Approval is a decision the user made — record it in the transcript from
    // their side, so the thread reads as a conversation and the workpaper's
    // audit trail shows who approved, not just that approval happened.
    pushUserMessage("Approve");
    setPhase4Busy(true);
    setIsStreaming(true);
    setBusyLabel("Approving attributes and running effectiveness testing…");
    try {
      const rows = await approveAttributes(projectId);
      setAttributeSchemas(rows);
      pushAssistantMessage("Attributes approved and frozen. Running control effectiveness testing now…", { none: true });
      await runPhase4(projectId);
    } catch (err) {
      pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to approve attributes."}`);
    } finally {
      setPhase4Busy(false);
      setIsStreaming(false);
      setBusyLabel(null);
    }
  }, [projectId, pushAssistantMessage, pushUserMessage, runPhase4]);

  const handleModifyAttribute = useCallback(
    async (controlId: string, attributeNo: number, body: { name?: string; description?: string }) => {
      if (!projectId) return;
      setPhase4Busy(true);
      try {
        const updated = await modifyAttribute(projectId, controlId, attributeNo, body);
        setAttributeSchemas((prev) =>
          (prev ?? []).map((s) => (s.control_id === controlId ? updated : s)),
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to update attribute."}`);
      } finally {
        setPhase4Busy(false);
      }
    },
    [projectId, pushAssistantMessage],
  );

  const handleRemoveAttribute = useCallback(
    async (controlId: string, attributeNo: number) => {
      if (!projectId) return;
      setPhase4Busy(true);
      try {
        const updated = await removeAttribute(projectId, controlId, attributeNo);
        setAttributeSchemas((prev) =>
          (prev ?? []).map((s) => (s.control_id === controlId ? updated : s)),
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to remove attribute."}`);
      } finally {
        setPhase4Busy(false);
      }
    },
    [projectId, pushAssistantMessage],
  );

  const refreshAfterRunAll = useCallback(
    async (pid: string) => {
      const [p, attrs, arts] = await Promise.all([
        getProject(pid),
        listAttributes(pid).catch(() => [] as ControlAttributes[]),
        listArtifacts(pid).catch(() => [] as Artifact[]),
      ]);
      setProject(p);
      setWorkflowProgress(deriveWorkflowProgress(p));
      setAttributeSchemas(attrs.length ? attrs : null);
      setArtifacts(arts);
      const fetches: Promise<void>[] = [];
      if (p.phase_status["1"] !== "pending")
        fetches.push(getPhaseResult<Phase1Result>(pid, 1).then((r) => setPhase1Result(r.result)).catch(() => undefined));
      if (p.phase_status["2"] !== "pending")
        fetches.push(getPhaseResult<Phase2Result>(pid, 2).then((r) => setPhase2Result(r.result)).catch(() => undefined));
      if (p.phase_status["3"] !== "pending")
        fetches.push(getPhaseResult<Phase3Result>(pid, 3).then((r) => setPhase3Result(r.result)).catch(() => undefined));
      if (p.phase_status["4"] !== "pending")
        fetches.push(getPhaseResult<Phase4Result>(pid, 4).then((r) => setPhase4Result(r.result)).catch(() => undefined));
      await Promise.all(fetches);
      setActiveStep(p.current_phase);
    },
    [],
  );

  const handleRunAll = useCallback(async () => {
    if (!projectId) return;
    setRunAllBusy(true);
    setIsStreaming(true);
    pushAssistantMessage("Running the remaining phases…", { none: true });
    try {
      const res = await runAllRemainingPhases(projectId);
      await refreshAfterRunAll(projectId);
      pushAssistantMessage(res.message);
    } catch (err) {
      pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run the remaining phases."}`);
    } finally {
      setRunAllBusy(false);
      setIsStreaming(false);
    }
  }, [projectId, pushAssistantMessage, refreshAfterRunAll]);

  const handleExport = useCallback(
    async (kind: "attributes" | "final") => {
      if (!projectId) return;
      setExportBusy(true);
      try {
        const artifact = kind === "final" ? await exportFinalReport(projectId) : await exportAttributes(projectId);
        setArtifacts((prev) => [artifact, ...prev]);
        pushAssistantMessage(`Exported "${artifact.filename}" — download it from the Reports panel.`);
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Export failed."}`);
      } finally {
        setExportBusy(false);
      }
    },
    [projectId, pushAssistantMessage],
  );

  /** Export a phase (or the working RCM) and immediately hand the user the
   *  file — one click, rather than export-then-find-it-in-Reports. */
  const handlePhaseDownload = useCallback(
    async (what: "rcm" | number) => {
      if (!projectId) return;
      setExportBusy(true);
      try {
        const artifact = what === "rcm" ? await exportRcm(projectId) : await exportPhase(projectId, what);
        setArtifacts((prev) => [artifact, ...prev]);
        await downloadArtifact(projectId, artifact.id, artifact.filename);
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Export failed."}`);
      } finally {
        setExportBusy(false);
      }
    },
    [projectId, pushAssistantMessage],
  );

  /** The multi-sheet workpaper covering all four phases — the filed
   *  deliverable, as opposed to a single phase's working sheet. */
  const handleWorkpaperDownload = useCallback(async () => {
    if (!projectId) return;
    setExportBusy(true);
    try {
      const artifact = await exportFinalReport(projectId);
      setArtifacts((prev) => [artifact, ...prev]);
      await downloadArtifact(projectId, artifact.id, artifact.filename);
    } catch (err) {
      pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Could not build the workpaper."}`);
    } finally {
      setExportBusy(false);
    }
  }, [projectId, pushAssistantMessage]);

  const handleOverrideUpload = useCallback(
    async (kind: "rcm" | "attributes", file: File) => {
      if (!projectId) return;
      setExportBusy(true);
      try {
        const res = kind === "rcm"
          ? await overrideRcm(projectId, file)
          : await overrideAttributes(projectId, file);
        pushAssistantMessage(res.message);
        // Pull the corrected values straight back into the UI.
        if (kind === "rcm") {
          const rows = await getPhaseResult<Phase1Result>(projectId, 1).catch(() => null);
          if (rows) setPhase1Result(rows.result);
        } else {
          const rows = await listAttributes(projectId).catch(() => null);
          if (rows) setAttributeSchemas(rows.length ? rows : null);
        }
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Could not apply those edits."}`);
      } finally {
        setExportBusy(false);
      }
    },
    [projectId, pushAssistantMessage],
  );

  const handleDownloadArtifact = useCallback(
    async (artifact: Artifact) => {
      if (!projectId) return;
      try {
        await downloadArtifact(projectId, artifact.id, artifact.filename);
      } catch {
        pushAssistantMessage(`[error] Could not download "${artifact.filename}".`);
      }
    },
    [projectId, pushAssistantMessage],
  );

  const handleSopSelect = useCallback(
    async (file: File) => {
      if (!projectId) return;
      pushUserMessage(`Uploaded SOP: ${file.name}`);
      setIsStreaming(true);
      setBusyLabel("Parsing the SOP and assessing adequacy…");
      try {
        const res = await uploadSop(projectId, file);
        setSopUploaded(true);
        pushAssistantMessage(
          `Parsed "${res.filename}" into ${res.parsed_step_count} process steps. Running the adequacy assessment now…`,
          { none: true },
        );
        await runPhase3(projectId);
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to upload SOP."}`);
      } finally {
        setIsStreaming(false);
        setBusyLabel(null);
      }
    },
    [projectId, pushAssistantMessage, pushUserMessage, runPhase3],
  );

  const handleFileSelect = useCallback(
    async (file: File) => {
      if (!projectId) return;
      // Route by file TYPE, not the active phase — the attach menu is always
      // available now, so a user can drop an SOP while sitting on Phase 1.
      const ext = file.name.toLowerCase().split(".").pop() ?? "";
      if (["docx", "pdf", "txt"].includes(ext)) {
        await handleSopSelect(file);
        return;
      }
      pushUserMessage(`Uploaded: ${file.name}`);
      setIsStreaming(true);
      setBusyLabel("Loading the RCM and running risk prioritization…");
      try {
        const res = await uploadRcm(projectId, file);
        pushAssistantMessage(
          `Loaded ${res.row_count} controls from "${file.name}". Mapped ${Object.keys(res.column_map).length} columns` +
            (res.passthrough.length ? `, kept ${res.passthrough.length} as passthrough` : "") +
            (res.still_missing.length ? `. Still unresolved: ${res.still_missing.join(", ")}` : "") +
            ". Running risk prioritization now…",
          // The RCM is in and the run follows immediately — nothing is owed
          // by the user here, so no "**Next:**" line.
          { none: true },
        );
        await runPhase1(projectId);
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to upload RCM."}`);
      } finally {
        setIsStreaming(false);
        setBusyLabel(null);
      }
    },
    [projectId, handleSopSelect, pushAssistantMessage, pushUserMessage, runPhase1],
  );

  const handleSend = useCallback(
    (text: string) => {
      if (!projectId) return;
      const userMsg: ChatMessage = {
        id: `u-${Date.now()}`,
        role: "user",
        content: text,
        createdAt: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, userMsg]);
      setIsStreaming(true);
      setBusyLabel("Thinking…");

      let assistantBuffer = "";
      const assistantId = `a-${Date.now()}`;

      abortRef.current = sendChatMessage(projectId, text, {
        onToolStart: ({ tool_name }) => {
          setBusyLabel(TOOL_LABELS[tool_name] ?? "Working…");
        },
        onToken: (chunk) => {
          // First token means the agent is composing prose, not running a
          // tool — drop the dots so they don't sit under the growing reply.
          setBusyLabel(null);
          assistantBuffer += chunk;
          setMessages((prev) => {
            const existing = prev.find((m) => m.id === assistantId);
            if (existing) {
              return prev.map((m) => (m.id === assistantId ? { ...m, content: assistantBuffer } : m));
            }
            return [
              ...prev,
              { id: assistantId, role: "assistant", content: assistantBuffer, createdAt: new Date().toISOString() },
            ];
          });
        },
        onResultsReady: ({ phase, result }) => {
          // Push the agent's phase output straight into the matching pane —
          // discarding it here meant a phase run from chat updated the
          // sidebar but left the visualisations blank until a page reload.
          if (phase === 1) setPhase1Result(result as Phase1Result);
          if (phase === 2) setPhase2Result(result as Phase2Result);
          if (phase === 3) {
            setPhase3Result(result as Phase3Result);
            setSopUploaded(true);
          }
          if (phase === 4) setPhase4Result(result as Phase4Result);
          setActiveStep(phase as ActiveStep);

          // Phase 1 can finish in a gate state (weighting choice / risk
          // approval), so only mark it done when it really is.
          const p1 = result as Phase1Result;
          const gated =
            phase === 1 &&
            (!!p1?.awaiting_weighting || Object.keys(p1?.pending_risk_inferences ?? {}).length > 0);
          setWorkflowProgress(
            (prev) =>
              ({
                ...prev,
                [`phase${phase}`]: gated ? "awaiting_approval" : "done",
              }) as WorkflowProgress,
          );
        },
        onAttributesReady: ({ attributes }) => {
          setAttributeSchemas(attributes.length ? attributes : null);
          setActiveStep(4);
        },
        onArtifactReady: ({ artifact }) => {
          setArtifacts((prev) => [artifact, ...prev.filter((a) => a.id !== artifact.id)]);
        },
        onAwaitingApproval: ({ phase }) => {
          setWorkflowProgress((prev) => ({ ...prev, [`phase${phase}`]: "awaiting_approval" }) as WorkflowProgress);
        },
        onError: ({ message }) => {
          setMessages((prev) => [
            ...prev,
            { id: `err-${Date.now()}`, role: "assistant", content: `[error] ${message}`, createdAt: new Date().toISOString() },
          ]);
          setIsStreaming(false);
          setBusyLabel(null);
        },
        onDone: () => {
          setIsStreaming(false);
          setBusyLabel(null);
        },
      });
    },
    [projectId],
  );

  const handleDragStart = useCallback(
    (e: React.MouseEvent) => {
      e.preventDefault();
      isDraggingRef.current = true;
      dragStartXRef.current = e.clientX;
      const startWidth = dataPaneCollapsed ? prevDataPaneWidthRef.current : dataPaneWidth;
      dragStartWidthRef.current = startWidth;
      document.body.style.cursor = "col-resize";
      document.body.style.userSelect = "none";

      const onMouseMove = (ev: MouseEvent) => {
        if (!isDraggingRef.current) return;
        const delta = dragStartXRef.current - ev.clientX;
        const rawWidth = dragStartWidthRef.current + delta;
        setDataPaneCollapsed(false);
        setDataPaneWidth(Math.min(Math.max(rawWidth, 60), Math.round(window.innerWidth * 0.6)));
      };
      const onMouseUp = (ev: MouseEvent) => {
        isDraggingRef.current = false;
        document.body.style.cursor = "";
        document.body.style.userSelect = "";
        const delta = dragStartXRef.current - ev.clientX;
        const finalWidth = dragStartWidthRef.current + delta;
        if (finalWidth < 180) {
          prevDataPaneWidthRef.current = startWidth > 200 ? startWidth : Math.round(window.innerWidth * 0.48);
          setDataPaneCollapsed(true);
        } else {
          setDataPaneCollapsed(false);
          setDataPaneWidth(Math.min(Math.max(finalWidth, 320), Math.round(window.innerWidth * 0.6)));
        }
        document.removeEventListener("mousemove", onMouseMove);
        document.removeEventListener("mouseup", onMouseUp);
      };
      document.addEventListener("mousemove", onMouseMove);
      document.addEventListener("mouseup", onMouseUp);
    },
    [dataPaneWidth, dataPaneCollapsed],
  );

  const phaseLabel = useMemo(() => PHASE_TITLES[activeStep], [activeStep]);

  /** Titles for the stage keys the backend reports (engines/progress.py). */
  const STAGE_TITLES: Record<string, string> = useMemo(
    () => ({
      adequacy: "Assessing design adequacy",
      attributes: "Generating testing attributes",
      testing: "Testing controls against evidence",
    }),
    [],
  );

  /** Only one long phase runs at a time (the claim lock enforces it), so the
   *  first reported stage is the one to show. */
  const activeStageEntry = useMemo(() => {
    const entries = Object.entries(stageProgress);
    return entries.length ? entries[0] : null;
  }, [stageProgress]);
  const activeStageProgress = activeStageEntry?.[1] ?? null;
  const allPhasesDone = useMemo(
    () => (["phase1", "phase2", "phase3", "phase4"] as const).every((k) => workflowProgress[k] === "done"),
    [workflowProgress],
  );

  if (!project) {
    return (
      <div style={{ height: "100vh", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--muted)" }}>
        Loading project…
      </div>
    );
  }

  return (
    <div className="workspace-page">
      <Sidebar
        projectName={project.name}
        workflowProgress={workflowProgress}
        activeStep={activeStep}
        onStepChange={setActiveStep}
      />

      <div className="workspace-main">
        <header className="workspace-header">
          <div className="workspace-header-left">
            <button className="workspace-back-link" onClick={() => navigate("/projects")}>
              ← Projects
            </button>
            <span className="workspace-process">{phaseLabel}</span>
          </div>
          <div className="workspace-header-right">
            {!allPhasesDone && (
              <button
                className="kpmg-btn ghost attr-btn-sm"
                disabled={runAllBusy || isStreaming}
                onClick={handleRunAll}
                title="Run every remaining phase in order, pausing at anything that needs you"
              >
                {runAllBusy ? "Running…" : "Run Remaining Phases"}
              </button>
            )}
            <button
              className={`kpmg-btn ${showRepository ? "primary" : "ghost"} attr-btn-sm`}
              onClick={() => setShowRepository((v) => !v)}
              title="Reports and exports"
            >
              Reports{artifacts.length > 0 ? ` (${artifacts.length})` : ""}
            </button>
            <span className="workspace-status">
              <span className="dot" />
              {isStreaming ? "working" : "idle"}
            </span>
          </div>
        </header>

        <div className="workspace-body">
          <div className={`workspace-chat-col${dataPaneCollapsed ? "" : ""}`}>
            <section className="workspace-assistant-head">
              <div className="assistant-icon">AI</div>
              <div>
                <h2>Agent</h2>
                <p>Control Assessment Assistant</p>
              </div>
            </section>

            <div className="workspace-chat-scroll" ref={chatScrollRef}>
              <div className="workspace-chat-inner">
                {messages.map((m) => (
                  <ChatBubble key={m.id} message={m} />
                ))}
                {isStreaming && busyLabel !== null && (
                  <TypingIndicator
                    label={
                      // Whichever phase is running carries its live control
                      // count on the dots — these are the longest waits here.
                      activeStageProgress && activeStageProgress.total > 0
                        ? `${busyLabel} (${activeStageProgress.done}/${activeStageProgress.total} controls)`
                        : busyLabel
                    }
                  />
                )}
              </div>
            </div>

            <ChatInput
              ref={chatInputRef}
              onSend={handleSend}
              onFileSelect={handleFileSelect}
              onFolderSelect={handleFolderSelect}
              disabled={isStreaming}
              showUpload
              acceptFile=".xlsx,.xls,.csv,.docx,.pdf,.txt"
              placeholder={
                activeStep === 1
                  ? "Message the agent, or attach an RCM to begin…"
                  : activeStep === 2
                    ? "Message the agent, or attach an evidence folder…"
                    : activeStep === 3
                      ? "Message the agent, or attach an SOP document…"
                      : "Message the agent…"
              }
            />
          </div>

          <div className="data-pane-drag-handle" onMouseDown={handleDragStart} />

          {dataPaneCollapsed ? (
            <div
              className="workspace-data-pane data-pane-collapsed-strip"
              onClick={() => {
                setDataPaneCollapsed(false);
                setDataPaneWidth(prevDataPaneWidthRef.current);
              }}
            >
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M15 18l-6-6 6-6" />
              </svg>
              <span className="data-pane-collapsed-label">{phaseLabel}</span>
            </div>
          ) : (
            <div
              className="workspace-data-pane"
              /* --pane-measure is the shared content width every section in
                 every phase aligns to. Deriving it from the pane's own width
                 (rather than a fixed px value) keeps charts, cards and tables
                 on one axis at any drag position, while the cap stops lines
                 from growing unreadably wide on a very wide pane.

                 The 48px subtracted is .data-pane-scroll's horizontal
                 padding. There is deliberately NO lower clamp: an earlier
                 `Math.max(280, …)` floor held the measure above the space
                 actually available once the pane was dragged near its
                 minimum, so every section rendered wider than its container
                 and spilled sideways. Clamping only the upper bound means
                 the measure can always shrink to fit. */
              style={
                {
                  width: dataPaneWidth,
                  "--pane-measure": `${Math.min(dataPaneWidth - 48, 980)}px`,
                } as CSSProperties
              }
            >
              <div className="data-pane-header">
                <span className="data-pane-title">{showRepository ? "Reports & Exports" : phaseLabel}</span>
                <div className="data-pane-header-actions">
                  {showRepository && (
                    <button className="kpmg-btn ghost attr-btn-sm" onClick={() => setShowRepository(false)}>
                      Back to {phaseLabel.split(" ")[0]}
                    </button>
                  )}
                  {/* Explicit control alongside the drag handle: dragging all
                      the way to the edge works, but is not discoverable. */}
                  <button
                    type="button"
                    className="data-pane-collapse-btn"
                    title="Minimise panel"
                    aria-label="Minimise results panel"
                    onClick={() => {
                      prevDataPaneWidthRef.current = dataPaneWidth;
                      setDataPaneCollapsed(true);
                    }}
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
              <div className="data-pane-scroll">
                {activeStageEntry && activeStageEntry[0] !== "attributes" && (
                  <PhaseProgress
                    title={STAGE_TITLES[activeStageEntry[0]] ?? "Working"}
                    done={activeStageEntry[1].done}
                    total={activeStageEntry[1].total}
                    label={activeStageEntry[1].label}
                  />
                )}
                {showRepository ? (
                  <RepositoryPanel
                    artifacts={artifacts}
                    busy={exportBusy}
                    canExportFinalReport={phase1Result !== null}
                    hasAttributes={(attributeSchemas ?? []).length > 0}
                    onExportAttributes={() => handleExport("attributes")}
                    onExportFinalReport={() => handleExport("final")}
                    onDownload={handleDownloadArtifact}
                  />
                ) : activeStep === 1 && phase1Result ? (
                  <>
                    <PhaseActionsBar
                      downloadLabel="Download working RCM"
                      onDownload={() => handlePhaseDownload("rcm")}
                      onOverride={(f) => handleOverrideUpload("rcm", f)}
                      overrideLabel="Upload corrected RCM"
                      overrideHint="Edit any field and re-upload. Blank = no change; a single '-' clears a value."
                      busy={exportBusy}
                    />
                    <Phase1RiskPane
                      result={phase1Result}
                      onApproveInferences={handleApproveInferences}
                      onChooseWeighting={handleChooseWeighting}
                      approving={phase1Busy}
                    />
                  </>
                ) : activeStep === 2 && phase2Result ? (
                  <>
                    <PhaseActionsBar
                      downloadLabel="Download Phase 2 results"
                      onDownload={() => handlePhaseDownload(2)}
                      busy={exportBusy}
                    />
                    <Phase2EvidencePane result={phase2Result} />
                  </>
                ) : activeStep === 3 && phase3Result ? (
                  <>
                    <PhaseActionsBar
                      downloadLabel="Download Phase 3 results"
                      onDownload={() => handlePhaseDownload(3)}
                      busy={exportBusy}
                    />
                    <Phase3AdequacyPane
                      result={phase3Result}
                      periodStart={project.audit_period_start}
                      periodEnd={project.audit_period_end}
                    />
                  </>
                ) : activeStep === 4 && (phase4Result || attributeSchemas) ? (
                  <>
                    {phase4Result && attributeSchemas && (
                      // Both views exist once testing has run — make them
                      // switchable, otherwise finishing a run permanently
                      // hides the attributes with no way back.
                      <div className="phase4-view-toggle">
                        <button
                          type="button"
                          className={`kpmg-btn ${phase4View === "results" ? "primary" : "ghost"} attr-btn-sm`}
                          onClick={() => setPhase4View("results")}
                        >
                          Test Results
                        </button>
                        <button
                          type="button"
                          className={`kpmg-btn ${phase4View === "attributes" ? "primary" : "ghost"} attr-btn-sm`}
                          onClick={() => setPhase4View("attributes")}
                        >
                          Attributes
                        </button>
                      </div>
                    )}
                    {phase4Result && (phase4View === "results" || !attributeSchemas) ? (
                      <>
                        <PhaseActionsBar
                          // The full multi-sheet workpaper, not the single
                          // Phase 4 sheet — this is the deliverable a
                          // reviewer actually files.
                          downloadLabel="Download workpaper"
                          onDownload={handleWorkpaperDownload}
                          busy={exportBusy}
                        />
                        <Phase4TestingPane result={phase4Result} attributeSchemas={attributeSchemas} />
                      </>
                    ) : attributeSchemas ? (
                      <>
                        <PhaseActionsBar
                          downloadLabel="Download attributes"
                          onDownload={async () => {
                            if (!projectId) return;
                            setExportBusy(true);
                            try {
                              const a = await exportAttributes(projectId);
                              setArtifacts((prev) => [a, ...prev]);
                              await downloadArtifact(projectId, a.id, a.filename);
                            } catch (err) {
                              pushAssistantMessage(
                                `[error] ${err instanceof ApiError ? err.message : "Export failed."}`,
                              );
                            } finally {
                              setExportBusy(false);
                            }
                          }}
                          onOverride={(f) => handleOverrideUpload("attributes", f)}
                          overrideLabel="Upload edited attributes"
                          overrideHint="Row order sets attribute order. Already-tested controls are refused."
                          busy={exportBusy}
                        />
                        <AttributePreviewPane
                          schemas={attributeSchemas}
                          busy={phase4Busy}
                          onApprove={handleApproveAttributes}
                          onModify={handleModifyAttribute}
                          onRemove={handleRemoveAttribute}
                          onRegenerate={handlePreviewAttributes}
                          testedControlIds={(phase4Result?.control_results ?? []).map((r) => r.control_id)}
                        />
                      </>
                    ) : null}
                  </>
                ) : activeStep === 4 ? (
                  <div style={{ padding: 20 }}>
                    <p style={{ color: "var(--muted)", marginTop: 0 }}>
                      Generate the testing attributes for each control, review them, then run effectiveness
                      testing against the evidence samples uploaded in Phase 2.
                    </p>
                    <button className="kpmg-btn primary" disabled={phase4Busy} onClick={handlePreviewAttributes}>
                      {phase4Busy ? "Generating…" : "Generate Testing Attributes"}
                    </button>
                    {phase4Busy && (
                      <PhaseProgress
                        title="Generating testing attributes"
                        done={stageProgress.attributes?.done ?? 0}
                        total={stageProgress.attributes?.total ?? 0}
                        label={stageProgress.attributes?.label}
                      />
                    )}
                  </div>
                ) : (
                  <p style={{ color: "var(--muted)", padding: 20 }}>
                    {activeStep === 1
                      ? "Attach an RCM (Excel or CSV) using the paperclip button to begin."
                      : activeStep === 2
                        ? "Attach an evidence folder using the folder button to begin — one subfolder per Control ID."
                        : activeStep === 3
                          ? "Attach an SOP document (Word, PDF, or text) using the paperclip button to begin."
                          : "Waiting for the agent to reach this phase…"}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
