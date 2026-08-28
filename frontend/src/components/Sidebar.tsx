import BrandLogo from "./BrandLogo";
import type { ActiveStep, PhaseStatus, WorkflowProgress } from "../types";

interface PhaseDef {
  step: ActiveStep;
  key: keyof WorkflowProgress;
  label: string;
  sublabel: string;
}

const PHASES: PhaseDef[] = [
  { step: 1, key: "phase1", label: "RACM Validation", sublabel: "Validation & Risk Prioritization" },
  { step: 2, key: "phase2", label: "Evidence Review", sublabel: "Gap Identification" },
  { step: 3, key: "phase3", label: "Adequacy", sublabel: "SOP-Based Design Assessment" },
  { step: 4, key: "phase4", label: "Effectiveness", sublabel: "Control Testing" },
];

const STATUS_PCT: Record<PhaseStatus, number> = {
  pending: 0,
  running: 50,
  awaiting_approval: 90,
  done: 100,
  error: 0,
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
        <div className="tool-workflow-label">WORKFLOW</div>
        <div className="workflow-tree">
          {PHASES.map((phase) => {
            const status = workflowProgress[phase.key];
            const isActive = activeStep === phase.step;
            const pct = STATUS_PCT[status];
            const canNavigate = status !== "pending" || phase.step === highestDoneStep + 1;
            return (
              <button
                key={phase.key}
                type="button"
                className={`workflow-main${isActive ? " active" : ""}`}
                onClick={() => canNavigate && onStepChange(phase.step)}
                disabled={!canNavigate}
                style={{ cursor: canNavigate ? "pointer" : "default", opacity: canNavigate ? 1 : 0.55 }}
              >
                <span className={`workflow-dot ${status}${isActive ? " active" : ""}`} />
                <span>
                  <span style={{ display: "block" }}>{phase.label}</span>
                  <span style={{ display: "block", fontSize: 11.5, color: "#9eb2dd", fontWeight: 400 }}>
                    {phase.sublabel}
                  </span>
                </span>
                {status !== "pending" && <span className="workflow-pct">{pct}%</span>}
              </button>
            );
          })}
        </div>
      </div>
    </aside>
  );
}
