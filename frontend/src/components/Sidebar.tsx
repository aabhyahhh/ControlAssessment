import BrandLogo from "./BrandLogo";
import type { ActiveStep, PhaseStatus, WorkflowProgress } from "../types";

interface PhaseDef {
  step: ActiveStep;
  key: keyof WorkflowProgress;
  label: string;
  sublabel: string;
}

const PHASES: PhaseDef[] = [
  { step: 1, key: "phase1", label: "RCM Intake", sublabel: "Control inventory & completeness" },
  { step: 2, key: "phase2", label: "Adequacy", sublabel: "SOPs, workpapers & reconciliation" },
  { step: 3, key: "phase3", label: "Evidence", sublabel: "Requirements & intake" },
  { step: 4, key: "phase4", label: "Gap Assessment", sublabel: "Received vs expected" },
];

/** Step-progress labels, not analytical results — this tree tracks how far
 *  the WORKFLOW has moved, never what the assessment found. A step showing
 *  "Done" here says nothing about how many controls are adequately
 *  documented, covered, or gap-free; that lives only in the data pane's own
 *  analytics. Never render this as a bare "100%" next to a step name — on a
 *  screen that also shows real coverage/completeness percentages, an
 *  identical-looking pill invites exactly the confusion the two numbers must
 *  never create. */
const STATUS_LABEL: Record<PhaseStatus, string> = {
  pending: "Not started",
  running: "Running…",
  awaiting_approval: "Review needed",
  done: "Done",
  error: "Error",
};

interface SidebarProps {
  projectName: string;
  workflowProgress: WorkflowProgress;
  activeStep: ActiveStep;
  onStepChange: (step: ActiveStep) => void;
}

export default function Sidebar({ projectName, workflowProgress, activeStep, onStepChange }: SidebarProps) {
  // A phase is reachable once it has its own progress, or once the phase
  // immediately before it is done — otherwise there'd be no way to reach
  // an upcoming phase's upload screen after the prior one just finished.
  const highestDoneStep = PHASES.reduce(
    (max, p) => (workflowProgress[p.key] === "done" && p.step > max ? p.step : max),
    0,
  );

  return (
    <aside className="tool-sidebar">
      <div className="tool-sidebar-header">
        <div className="kpmg-logo-row">
          <BrandLogo className="kpmg-logo-img sidebar" height={24} />
        </div>
        <div className="tool-project-label">Project</div>
        <div className="tool-project-name">{projectName}</div>
      </div>

      <div className="tool-workflow">
        <div
          className="tool-workflow-label"
          title="Step progress — how far the workflow has moved, not the assessment result"
        >
          WORKFLOW
        </div>
        <div className="workflow-tree">
          {PHASES.map((phase) => {
            const status = workflowProgress[phase.key];
            const isActive = activeStep === phase.step;
            const canNavigate = status !== "pending" || phase.step === highestDoneStep + 1;
            return (
              <button
                key={phase.key}
                type="button"
                className={`workflow-main${isActive ? " active" : ""}`}
                onClick={() => canNavigate && onStepChange(phase.step)}
                disabled={!canNavigate}
                style={{ cursor: canNavigate ? "pointer" : "default", opacity: canNavigate ? 1 : 0.55 }}
                title={`${phase.label}: ${STATUS_LABEL[status]} — step progress, not an assessment result`}
              >
                <span className={`workflow-dot ${status}${isActive ? " active" : ""}`} />
                <span>
                  <span style={{ display: "block" }}>{phase.label}</span>
                  <span style={{ display: "block", fontSize: 11.5, color: "#9eb2dd", fontWeight: 400 }}>
                    {phase.sublabel}
                  </span>
                </span>
                {status !== "pending" && (
                  <span className={`workflow-step-status status-${status}`}>{STATUS_LABEL[status]}</span>
                )}
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
