import { ChevronRight } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { useNavigate, useParams } from "react-router-dom";
import ChatBubble from "../components/ChatBubble";
import ChatInput, { type ChatInputHandle } from "../components/ChatInput";
import PhaseProgress from "../components/PhaseProgress";
import Sidebar from "../components/Sidebar";
import StepHeader from "../components/StepHeader";
import TypingIndicator from "../components/TypingIndicator";
import RcmIntakePane from "../components/panes/RcmIntakePane";
import AdequacyPane from "../components/panes/AdequacyPane";
import EvidencePane from "../components/panes/EvidencePane";
import GapAssessmentPane from "../components/panes/GapAssessmentPane";
import { getProject } from "../services/projectService";
import { appendChatMessage, listChatMessages, sendChatMessage } from "../services/chatService";
import {
  uploadAdequacyFile,
  uploadAdequacyFolder,
  uploadControlEvidenceFile,
  uploadEvidenceFolder,
  uploadRcm,
} from "../services/uploadService";
import { listDeclaredEvidence, upsertDeclaredEvidence } from "../services/evidenceService";
import { listJustificationEmails } from "../services/justificationService";
import { listControls } from "../services/uploadService";
import {
  getPhaseProgress,
  getPhaseResult,
  runAdequacyAssessment,
  runAllRemainingPhases,
  runEvidenceAssessment,
  runGapAssessment,
  runRcmIntake,
  type StageProgress,
} from "../services/phaseService";
import PhaseActionsBar from "../components/PhaseActionsBar";
import RepositoryPanel from "../components/RepositoryPanel";
import {
  downloadArtifact,
  exportFinalReport,
  exportPhase,
  exportRcm,
  listArtifacts,
  overrideRcm,
} from "../services/exportService";
import { ApiError } from "../services/api";
import type {
  ActiveStep,
  Artifact,
  ChatMessage,
  Control,
  DeclaredEvidence,
  DeclaredEvidenceItem,
  JustificationEmail,
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

const TOOL_LABELS: Record<string, string> = {
  get_project_status: "Checking where we are…",
  run_rcm_intake: "Reading the RCM…",
  run_adequacy_assessment: "Reconciling SOPs and workpapers…",
  run_evidence_assessment: "Assessing evidence requirements…",
  run_gap_assessment: "Building the gap assessment…",
  export_report: "Building the Excel summary…",
};

const STEP_TITLES: Record<ActiveStep, string> = {
  1: "RCM Intake",
  2: "Adequacy Assessment",
  3: "Evidence Requirements & Intake",
  4: "Gap Assessment",
};

const STAGE_TITLES: Record<string, string> = {
  upload: "Processing uploaded documents",
  adequacy: "Reconciling SOPs and workpapers",
  evidence: "Generating the evidence checklist",
};

/** "N of M ___" unit per stage — upload progress counts files, the others
 *  count controls. */
const STAGE_UNITS: Record<string, string> = {
  upload: "files",
};

function summarizeCounts(parts: { count: number; text: string }[], fallback: string): string {
  const kept = parts.filter((p) => p.count > 0).map((p) => p.text);
  if (kept.length === 0) return fallback;
  if (kept.length === 1) return kept[0];
  return `${kept.slice(0, -1).join(", ")} and ${kept[kept.length - 1]}`;
}

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
  const [busyLabel, setBusyLabel] = useState<string | null>(null);
  const [stageProgress, setStageProgress] = useState<Record<string, StageProgress>>({});
  const [historyLoaded, setHistoryLoaded] = useState(false);

  const [controls, setControls] = useState<Control[]>([]);
  const [phase1Result, setPhase1Result] = useState<Phase1Result | null>(null);
  const [phase2Result, setPhase2Result] = useState<Phase2Result | null>(null);
  const [phase2Busy, setPhase2Busy] = useState(false);
  const [phase3Result, setPhase3Result] = useState<Phase3Result | null>(null);
  const [phase3Busy, setPhase3Busy] = useState(false);
  const [phase4Result, setPhase4Result] = useState<Phase4Result | null>(null);
  const [phase4Busy, setPhase4Busy] = useState(false);
  const [declaredEvidence, setDeclaredEvidence] = useState<DeclaredEvidence[]>([]);
  const [declaredBusy, setDeclaredBusy] = useState(false);
  const [justificationEmails, setJustificationEmails] = useState<JustificationEmail[]>([]);

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
        navigate("/projects", { replace: true });
        return null;
      })
      .then((p) => {
        if (!p) return;
        setProject(p);
        setWorkflowProgress(deriveWorkflowProgress(p));
        setActiveStep(p.current_phase);
        if (p.phase_status["1"] !== "pending") {
          getPhaseResult<Phase1Result>(projectId, 1).then((r) => setPhase1Result(r.result)).catch(() => undefined);
        }
        if (p.phase_status["2"] !== "pending") {
          getPhaseResult<Phase2Result>(projectId, 2).then((r) => setPhase2Result(r.result)).catch(() => undefined);
        }
        if (p.phase_status["3"] !== "pending") {
          getPhaseResult<Phase3Result>(projectId, 3).then((r) => setPhase3Result(r.result)).catch(() => undefined);
        }
        if (p.phase_status["4"] !== "pending") {
          getPhaseResult<Phase4Result>(projectId, 4).then((r) => setPhase4Result(r.result)).catch(() => undefined);
        }
        listControls(projectId).then(setControls).catch(() => undefined);
        listDeclaredEvidence(projectId).then(setDeclaredEvidence).catch(() => undefined);
        listJustificationEmails(projectId).then(setJustificationEmails).catch(() => undefined);
        listArtifacts(projectId).then(setArtifacts).catch(() => undefined);
        listChatMessages(projectId)
          .then((rows) => {
            if (rows.length) setMessages(rows);
            setHistoryLoaded(true);
          })
          .catch(() => setHistoryLoaded(true));
      });
  }, [projectId, navigate]);

  useEffect(() => {
    if (historyLoaded && messages.length === 0 && project) {
      setMessages([
        {
          id: "welcome",
          role: "assistant",
          content:
            `Hello — I'm your control assessment agent for "${project.name}". The workflow has four steps: ` +
            "RCM intake, adequacy assessment against your SOPs and monthly workpapers, evidence requirements " +
            "and intake, and a gap assessment.\n\n**Next:** Attach your RCM file (.xlsx/.xls/.csv) using the " +
            "attach button — only a Control ID column is required.",
          createdAt: new Date().toISOString(),
        },
      ]);
    }
  }, [project, messages.length, historyLoaded]);

  useEffect(() => {
    chatScrollRef.current?.scrollTo({ top: chatScrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);

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

  useEffect(() => () => abortRef.current?.(), []);

  /** The workflow state the hint is derived from. Passing this explicitly is
   *  what makes the hint correct at the moment a message is pushed: a caller
   *  that has just changed phase1Result/workflowProgress cannot read the new
   *  value back from state in the same synchronous block (React batches
   *  updates, so the closure still holds the OLD value) — it has to hand the
   *  new value in here. Omitted fields fall back to current state. */
  interface HintState {
    hasRcm?: boolean;
    phase2Done?: boolean;
    phase3Done?: boolean;
    phase4Done?: boolean;
  }

  /** The next thing the user should do or type — always non-null so a reply
   *  never leaves them guessing. Mirrors the agent's own guidance. */
  const nextActionHint = useCallback(
    (over: HintState = {}): string => {
      const hasRcm = over.hasRcm ?? phase1Result !== null;
      const phase2Done = over.phase2Done ?? workflowProgress.phase2 === "done";
      const phase3Done = over.phase3Done ?? workflowProgress.phase3 === "done";
      const phase4Done = over.phase4Done ?? workflowProgress.phase4 === "done";

      if (!hasRcm) {
        return "Attach your RCM file (.xlsx/.xls/.csv) — only a Control ID column is required.";
      }
      if (!phase2Done) {
        return "Attach your SOPs and monthly workpapers — a folder with one subfolder per Control ID, or individual files. The adequacy assessment runs automatically once they're in.";
      }
      if (!phase3Done) {
        return 'Enter the per-control evidence list on the right and/or attach your evidence folder, then click "Run evidence assessment" (or say "proceed" to the agent).';
      }
      if (!phase4Done) {
        return 'Click "Run gap assessment" on the right, or say "proceed" to the agent, to produce the Excel summary.';
      }
      return 'All four steps are done — use "Download gap assessment (Excel)" above, or the Reports panel, to get the summary.';
    },
    [phase1Result, workflowProgress],
  );

  const pushAssistantMessage = useCallback(
    (content: string, opts?: { suppressNext?: boolean; hintState?: HintState }) => {
      const hint = opts?.suppressNext ? null : nextActionHint(opts?.hintState ?? {});
      const withNext =
        content.includes("**Next:**") || !hint ? content : `${content}\n\n**Next:** ${hint}`;
      setMessages((prev) => [
        ...prev,
        { id: `a-${Date.now()}-${Math.random()}`, role: "assistant", content: withNext, createdAt: new Date().toISOString() },
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

  // ── Step 2: adequacy ────────────────────────────────────────────────────
  const runStep2 = useCallback(
    async (pid: string) => {
      setPhase2Busy(true);
      try {
        const res = await runAdequacyAssessment(pid);
        setPhase2Result(res.result);
        setWorkflowProgress((prev) => ({ ...prev, phase2: res.status }));
        setActiveStep(2);
        const s = res.result.stats;
        pushAssistantMessage(
          `Adequacy assessment complete: ` +
            summarizeCounts(
              [
                { count: s?.adequate_count ?? 0, text: `${s?.adequate_count} adequate` },
                { count: s?.partially_adequate_count ?? 0, text: `${s?.partially_adequate_count} partially adequate` },
                { count: s?.inadequate_count ?? 0, text: `${s?.inadequate_count} inadequate` },
                { count: s?.unreconciled_count ?? 0, text: `${s?.unreconciled_count} not described in the docs` },
                { count: s?.workpaper_gap_count ?? 0, text: `${s?.workpaper_gap_count} with missing workpaper months` },
              ],
              "no findings",
            ) + ". Review the reconciliation and workpaper coverage on the right.",
          { hintState: { phase2Done: res.status === "done" } },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run adequacy assessment."}`);
      } finally {
        setPhase2Busy(false);
      }
    },
    [pushAssistantMessage],
  );

  const handleAdequacyFolder = useCallback(
    async (fileList: FileList) => {
      if (!projectId) return;
      const n = fileList.length;
      pushUserMessage(`Uploaded SOP/workpaper folder (${n} file${n === 1 ? "" : "s"})`);
      setIsStreaming(true);
      setBusyLabel(`Uploading ${n} file${n === 1 ? "" : "s"}…`);
      try {
        const res = await uploadAdequacyFolder(projectId, fileList);
        const sop = res.documents.filter((d) => d.doc_kind === "sop").length;
        const wp = res.documents.filter((d) => d.doc_kind === "workpaper").length;
        pushAssistantMessage(
          `Saved ${res.total_files_saved} file${res.total_files_saved === 1 ? "" : "s"} (${sop} SOP, ${wp} workpaper)` +
            (res.unmatched_control_ids.length
              ? `. Couldn't match these folder names to a Control ID: ${res.unmatched_control_ids.join(", ")}`
              : "") +
            ". Running the adequacy assessment now…",
          { suppressNext: true },
        );
        await runStep2(projectId);
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to upload the folder."}`);
      } finally {
        setIsStreaming(false);
        setBusyLabel(null);
      }
    },
    [projectId, pushAssistantMessage, pushUserMessage, runStep2],
  );

  const handleAdequacyFile = useCallback(
    async (file: File) => {
      if (!projectId) return;
      pushUserMessage(`Uploaded: ${file.name}`);
      setIsStreaming(true);
      setBusyLabel("Reading the document…");
      try {
        const res = await uploadAdequacyFile(projectId, file);
        const d = res.documents[0];
        // The upload marks step 2 pending if it was done — reflect that.
        const p = await getProject(projectId).catch(() => null);
        if (p) {
          setProject(p);
          setWorkflowProgress(deriveWorkflowProgress(p));
        }
        setActiveStep(2);
        pushAssistantMessage(
          `Added "${d.filename}" as ${d.doc_kind === "sop" ? "an SOP" : "a workpaper"}` +
            (d.period_month ? ` for ${d.period_month}` : "") +
            (d.parsed_step_count ? ` (${d.parsed_step_count} process steps)` : "") +
            '. Upload the rest, then click "Run adequacy assessment" on the right (or say "proceed" to the agent).',
          { suppressNext: true },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to upload the document."}`);
      } finally {
        setIsStreaming(false);
        setBusyLabel(null);
      }
    },
    [projectId, pushAssistantMessage, pushUserMessage],
  );

  // ── Step 3: evidence ────────────────────────────────────────────────────
  const runStep3 = useCallback(
    async (pid: string) => {
      setPhase3Busy(true);
      try {
        const res = await runEvidenceAssessment(pid);
        setPhase3Result(res.result);
        setWorkflowProgress((prev) => ({ ...prev, phase3: res.status }));
        setActiveStep(3);
        const s = res.result.stats;
        const rollup = s?.severity_rollup;
        pushAssistantMessage(
          `Evidence assessment complete: ${s?.avg_evidence_score ?? 0}% average completeness, ` +
            `${s?.evidence_gaps_count ?? 0} control(s) with a gap` +
            (rollup
              ? ` (critical ${rollup.critical ?? 0}, high ${rollup.high ?? 0}, medium ${rollup.medium ?? 0}, low ${rollup.low ?? 0})`
              : "") +
            ".",
          { hintState: { phase3Done: res.status === "done" } },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run evidence assessment."}`);
      } finally {
        setPhase3Busy(false);
      }
    },
    [pushAssistantMessage],
  );

  const handleEvidenceFolder = useCallback(
    async (fileList: FileList) => {
      if (!projectId) return;
      const n = fileList.length;
      pushUserMessage(`Uploaded evidence folder (${n} file${n === 1 ? "" : "s"})`);
      setIsStreaming(true);
      setBusyLabel(`Uploading ${n} file${n === 1 ? "" : "s"}…`);
      try {
        const res = await uploadEvidenceFolder(projectId, fileList);
        pushAssistantMessage(
          `Saved ${res.total_files_saved} evidence file${res.total_files_saved === 1 ? "" : "s"} across ${res.controls.length} controls` +
            (res.unmatched_control_ids.length
              ? `. Unmatched folder names: ${res.unmatched_control_ids.join(", ")}`
              : "") +
            ". Enter the per-control evidence list on the right, then run the evidence assessment.",
          { suppressNext: true },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to upload evidence."}`);
      } finally {
        setIsStreaming(false);
        setBusyLabel(null);
      }
    },
    [projectId, pushAssistantMessage, pushUserMessage],
  );

  const handleSaveDeclared = useCallback(
    async (controlId: string, items: DeclaredEvidenceItem[]) => {
      if (!projectId) return;
      setDeclaredBusy(true);
      try {
        const saved = await upsertDeclaredEvidence(projectId, controlId, items);
        setDeclaredEvidence((prev) => {
          const rest = prev.filter((d) => d.control_id !== controlId);
          return [...rest, saved].sort((a, b) => a.control_id.localeCompare(b.control_id));
        });
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to save the evidence list."}`);
      } finally {
        setDeclaredBusy(false);
      }
    },
    [projectId, pushAssistantMessage],
  );

  const handleAttachEvidenceFile = useCallback(
    async (controlId: string, file: File) => {
      if (!projectId) return;
      setDeclaredBusy(true);
      try {
        await uploadControlEvidenceFile(projectId, controlId, file);
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to attach the file."}`);
      } finally {
        setDeclaredBusy(false);
      }
    },
    [projectId, pushAssistantMessage],
  );

  // ── Step 4: gap assessment ──────────────────────────────────────────────
  const runStep4 = useCallback(
    async (pid: string) => {
      setPhase4Busy(true);
      try {
        const res = await runGapAssessment(pid);
        setPhase4Result(res.result);
        setWorkflowProgress((prev) => ({ ...prev, phase4: res.status }));
        setActiveStep(4);
        const s = res.result.stats;
        const rollup = s?.severity_rollup;
        pushAssistantMessage(
          `Gap assessment complete across ${s?.controls_assessed ?? 0} control(s): ${s?.fully_covered ?? 0} fully covered, ` +
            `${s?.serious ?? 0} with a critical/high gap` +
            (rollup
              ? `. Severity — critical ${rollup.critical ?? 0}, high ${rollup.high ?? 0}, medium ${rollup.medium ?? 0}, low ${rollup.low ?? 0}`
              : "") +
            ". Download the Excel summary from the actions bar.",
          { hintState: { phase4Done: res.status === "done" } },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run gap assessment."}`);
      } finally {
        setPhase4Busy(false);
      }
    },
    [pushAssistantMessage],
  );

  // ── RCM upload / step 1 ─────────────────────────────────────────────────
  const handleRcmFile = useCallback(
    async (file: File) => {
      if (!projectId) return;
      pushUserMessage(`Uploaded: ${file.name}`);
      setIsStreaming(true);
      setBusyLabel("Loading the RCM…");
      try {
        const res = await uploadRcm(projectId, file);
        const [p, ctrls, r1] = await Promise.all([
          getProject(projectId),
          listControls(projectId).catch(() => [] as Control[]),
          getPhaseResult<Phase1Result>(projectId, 1).catch(() => null),
        ]);
        setProject(p);
        setWorkflowProgress(deriveWorkflowProgress(p));
        setControls(ctrls);
        if (r1) setPhase1Result(r1.result);
        setActiveStep(1);
        pushAssistantMessage(
          `Loaded ${res.row_count} controls from "${file.name}". Mapped ${Object.keys(res.column_map).length} columns` +
            (res.still_missing.length
              ? `; ${res.still_missing.length} recommended field(s) blank and will be reconciled in step 2`
              : "") +
            ".",
          { hintState: { hasRcm: true } },
        );
      } catch (err) {
        pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to upload RCM."}`);
      } finally {
        setIsStreaming(false);
        setBusyLabel(null);
      }
    },
    [projectId, pushAssistantMessage, pushUserMessage],
  );

  const handleFileSelect = useCallback(
    async (file: File) => {
      const ext = file.name.toLowerCase().split(".").pop() ?? "";
      // .xls/.csv are RCM-only formats. A bare .xlsx is the RCM on step 1
      // (where no adequacy docs are wanted yet) and an adequacy doc after.
      if (ext === "xls" || ext === "csv") {
        await handleRcmFile(file);
        return;
      }
      if (ext === "xlsx" && activeStep === 1) {
        await handleRcmFile(file);
        return;
      }
      if (["docx", "pdf", "txt", "xlsx", "xlsm"].includes(ext)) {
        await handleAdequacyFile(file);
        return;
      }
      await handleRcmFile(file);
    },
    [activeStep, handleRcmFile, handleAdequacyFile],
  );

  // ── Run all / exports ──────────────────────────────────────────────────
  const refreshAfterRunAll = useCallback(
    async (pid: string) => {
      const [p, decl, arts] = await Promise.all([
        getProject(pid),
        listDeclaredEvidence(pid).catch(() => [] as DeclaredEvidence[]),
        listArtifacts(pid).catch(() => [] as Artifact[]),
      ]);
      setProject(p);
      setWorkflowProgress(deriveWorkflowProgress(p));
      setDeclaredEvidence(decl);
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
    pushAssistantMessage("Running the remaining steps…", { suppressNext: true });
    try {
      const res = await runAllRemainingPhases(projectId);
      await refreshAfterRunAll(projectId);
      pushAssistantMessage(res.message);
    } catch (err) {
      pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Failed to run the remaining steps."}`);
    } finally {
      setRunAllBusy(false);
      setIsStreaming(false);
    }
  }, [projectId, pushAssistantMessage, refreshAfterRunAll]);

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

  const handleReportDownload = useCallback(async () => {
    if (!projectId) return;
    setExportBusy(true);
    try {
      const artifact = await exportFinalReport(projectId);
      setArtifacts((prev) => [artifact, ...prev]);
      await downloadArtifact(projectId, artifact.id, artifact.filename);
    } catch (err) {
      pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Could not build the report."}`);
    } finally {
      setExportBusy(false);
    }
  }, [projectId, pushAssistantMessage]);

  const handleExportFinalReport = useCallback(async () => {
    if (!projectId) return;
    setExportBusy(true);
    try {
      const artifact = await exportFinalReport(projectId);
      setArtifacts((prev) => [artifact, ...prev]);
      pushAssistantMessage(`Exported "${artifact.filename}" — download it from the Reports panel.`);
    } catch (err) {
      pushAssistantMessage(`[error] ${err instanceof ApiError ? err.message : "Export failed."}`);
    } finally {
      setExportBusy(false);
    }
  }, [projectId, pushAssistantMessage]);

  const handleOverrideRcm = useCallback(
    async (file: File) => {
      if (!projectId) return;
      setExportBusy(true);
      try {
        const res = await overrideRcm(projectId, file);
        pushAssistantMessage(res.message);
        const [ctrls, r1] = await Promise.all([
          listControls(projectId).catch(() => null),
          runRcmIntake(projectId).catch(() => null),
        ]);
        if (ctrls) setControls(ctrls);
        if (r1) setPhase1Result(r1.result);
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

  const handleSend = useCallback(
    (text: string) => {
      if (!projectId) return;
      setMessages((prev) => [
        ...prev,
        { id: `u-${Date.now()}`, role: "user", content: text, createdAt: new Date().toISOString() },
      ]);
      setIsStreaming(true);
      setBusyLabel("Thinking…");

      let assistantBuffer = "";
      const assistantId = `a-${Date.now()}`;

      abortRef.current = sendChatMessage(projectId, text, {
        onToolStart: ({ tool_name }) => setBusyLabel(TOOL_LABELS[tool_name] ?? "Working…"),
        onToken: (chunk) => {
          setBusyLabel(null);
          assistantBuffer += chunk;
          setMessages((prev) => {
            const existing = prev.find((m) => m.id === assistantId);
            if (existing) return prev.map((m) => (m.id === assistantId ? { ...m, content: assistantBuffer } : m));
            return [
              ...prev,
              { id: assistantId, role: "assistant", content: assistantBuffer, createdAt: new Date().toISOString() },
            ];
          });
        },
        onResultsReady: ({ phase, result }) => {
          if (phase === 1) setPhase1Result(result as Phase1Result);
          if (phase === 2) setPhase2Result(result as Phase2Result);
          if (phase === 3) setPhase3Result(result as Phase3Result);
          if (phase === 4) setPhase4Result(result as Phase4Result);
          setActiveStep(phase as ActiveStep);
          setWorkflowProgress((prev) => ({ ...prev, [`phase${phase}`]: "done" }) as WorkflowProgress);
        },
        onArtifactReady: ({ artifact }) => {
          setArtifacts((prev) => [artifact, ...prev.filter((a) => a.id !== artifact.id)]);
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

  const phaseLabel = useMemo(() => STEP_TITLES[activeStep], [activeStep]);
  const controlIds = useMemo(() => controls.map((c) => c.control_id), [controls]);

  const activeStageEntry = useMemo(() => {
    const entries = Object.entries(stageProgress);
    return entries.length ? entries[0] : null;
  }, [stageProgress]);
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
                title="Run every remaining step in order, pausing at anything that needs you"
              >
                {runAllBusy ? "Running…" : "Run Remaining Steps"}
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
          <div className="workspace-chat-col">
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
                      activeStageEntry && activeStageEntry[1].activity
                        ? `${activeStageEntry[1].activity}…`
                        : activeStageEntry && activeStageEntry[1].total > 0
                          ? `${busyLabel} (${activeStageEntry[1].done}/${activeStageEntry[1].total})`
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
              onAdequacyFolderSelect={handleAdequacyFolder}
              onEvidenceFolderSelect={handleEvidenceFolder}
              disabled={isStreaming}
              showUpload
              acceptFile=".xlsx,.xls,.csv,.docx,.pdf,.txt"
              placeholder={
                activeStep === 1
                  ? "Message the agent, or attach an RCM to begin…"
                  : activeStep === 2
                    ? "Message the agent, or attach SOPs and workpapers…"
                    : activeStep === 3
                      ? "Message the agent, or attach an evidence folder…"
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
              style={
                {
                  width: dataPaneWidth,
                  "--pane-measure": `${Math.min(dataPaneWidth - 48, 980)}px`,
                } as CSSProperties
              }
            >
              <div className="data-pane-header">
                {/* The step title/description/tabs live in StepHeader below,
                    inside the scroll area, so they can sit beside the same
                    content they describe — this bar keeps only the chrome
                    that isn't step-specific (Repository has no StepHeader,
                    so it still needs a title here). */}
                {showRepository && <span className="data-pane-title">Reports & Exports</span>}
                <div className="data-pane-header-actions" style={!showRepository ? { marginLeft: "auto" } : undefined}>
                  {showRepository && (
                    <button className="kpmg-btn ghost attr-btn-sm" onClick={() => setShowRepository(false)}>
                      Back to {phaseLabel.split(" ")[0]}
                    </button>
                  )}
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
                {!showRepository && (
                  <StepHeader
                    activeStep={activeStep}
                    workflowProgress={workflowProgress}
                    onStepChange={setActiveStep}
                    isStreaming={isStreaming}
                  />
                )}
                {activeStageEntry && (
                  <PhaseProgress
                    title={STAGE_TITLES[activeStageEntry[0]] ?? "Working"}
                    done={activeStageEntry[1].done}
                    total={activeStageEntry[1].total}
                    label={activeStageEntry[1].label}
                    activity={activeStageEntry[1].activity}
                    unit={STAGE_UNITS[activeStageEntry[0]] ?? "controls"}
                  />
                )}
                {showRepository ? (
                  <RepositoryPanel
                    artifacts={artifacts}
                    busy={exportBusy}
                    canExportFinalReport={phase1Result !== null}
                    onExportFinalReport={handleExportFinalReport}
                    onDownload={handleDownloadArtifact}
                  />
                ) : activeStep === 1 && phase1Result ? (
                  <>
                    <PhaseActionsBar
                      downloadLabel="Download working RCM"
                      onDownload={() => handlePhaseDownload("rcm")}
                      onOverride={handleOverrideRcm}
                      overrideLabel="Upload corrected RCM"
                      overrideHint="Edit any field and re-upload. Blank = no change; a single '-' clears a value."
                      busy={exportBusy}
                    />
                    <RcmIntakePane result={phase1Result} />
                  </>
                ) : activeStep === 2 ? (
                  phase2Result ? (
                    <>
                      <PhaseActionsBar
                        downloadLabel="Download Step 2 results"
                        onDownload={() => handlePhaseDownload(2)}
                        busy={exportBusy}
                      />
                      <AdequacyPane
                        result={phase2Result}
                        projectId={projectId}
                        justificationEmails={justificationEmails}
                        onJustificationEmailsChange={setJustificationEmails}
                      />
                    </>
                  ) : (
                    <div style={{ padding: 20 }}>
                      <p style={{ color: "var(--muted)", marginTop: 0 }}>
                        Attach your SOPs and monthly workpapers — a folder with one subfolder per Control ID, or
                        individual .docx/.pdf/.txt/.xlsx files — then the adequacy assessment runs automatically.
                      </p>
                      <button
                        className="kpmg-btn primary"
                        disabled={phase2Busy || workflowProgress.phase1 !== "done"}
                        onClick={() => projectId && runStep2(projectId)}
                      >
                        {phase2Busy ? "Running…" : "Run adequacy assessment"}
                      </button>
                    </div>
                  )
                ) : activeStep === 3 ? (
                  <>
                    {phase3Result && (
                      <PhaseActionsBar
                        downloadLabel="Download Step 3 results"
                        onDownload={() => handlePhaseDownload(3)}
                        busy={exportBusy}
                      />
                    )}
                    <EvidencePane
                      result={phase3Result}
                      controlIds={controlIds}
                      declared={declaredEvidence}
                      busy={phase3Busy || declaredBusy}
                      onSaveList={handleSaveDeclared}
                      onAttachFile={handleAttachEvidenceFile}
                      onRun={() => projectId && runStep3(projectId)}
                    />
                  </>
                ) : activeStep === 4 ? (
                  phase4Result ? (
                    <GapAssessmentPane
                      result={phase4Result}
                      onDownload={handleReportDownload}
                      downloadBusy={exportBusy}
                    />
                  ) : (
                    <div style={{ padding: 20 }}>
                      <p style={{ color: "var(--muted)", marginTop: 0 }}>
                        The gap assessment aggregates steps 1–3 into a per-control gap picture and an Excel summary.
                      </p>
                      <button
                        className="kpmg-btn primary"
                        disabled={phase4Busy || workflowProgress.phase3 !== "done"}
                        onClick={() => projectId && runStep4(projectId)}
                      >
                        {phase4Busy ? "Running…" : "Run gap assessment"}
                      </button>
                    </div>
                  )
                ) : (
                  <p style={{ color: "var(--muted)", padding: 20 }}>
                    Attach an RCM (Excel or CSV) using the paperclip button to begin — only a Control ID column is
                    required.
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
