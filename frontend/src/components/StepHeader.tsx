import { canNavigateToStep, WORKFLOW_STEPS } from "../workflowSteps";
import type { ActiveStep, WorkflowProgress } from "../types";

const STEP_TITLE: Record<ActiveStep, string> = {
  1: "RCM Intake",
  2: "Adequacy Assessment",
  3: "Evidence Requirements & Intake",
  4: "Gap Assessment",
};

const STEP_DESCRIPTION: Record<ActiveStep, string> = {
  1: "Control inventory, and how much of each recommended field the matrix carries before reconciliation.",
  2: "RCM reconciled against the SOPs, and whether a workpaper exists for every month of the audit period.",
  3: "Expected documents per control, followed through declaration, upload and match.",
  4: "Received versus expected, attributed to the earliest break in the chain, with rules-based severity.",
};

const TAB_LABEL: Record<ActiveStep, string> = {
  1: "RCM",
  2: "Adequacy",
  3: "Evidence",
  4: "Gap",
};

interface StepHeaderProps {
  activeStep: ActiveStep;
  workflowProgress: WorkflowProgress;
  onStepChange: (step: ActiveStep) => void;
  /** Whether the agent/tool layer is doing work right now — a process
   *  indicator, not an assessment result (see workflowSteps.ts / Sidebar). */
  isStreaming: boolean;
}

/**
 * Shared eyebrow + title + description + breadcrumb tabs, rendered once
 * above whichever step pane is active. The breadcrumb reuses the exact same
 * navigability rule as the Sidebar's workflow tree (`canNavigateToStep`) so
 * the two can never disagree about which step is currently reachable.
 */
export default function StepHeader({ activeStep, workflowProgress, onStepChange, isStreaming }: StepHeaderProps) {
  return (
    <div className="step-header">
      <div className="step-header-top">
        <span className="step-header-eyebrow">STEP {activeStep} OF 4</span>
        <span className="step-header-status" title="Whether the agent is working right now — not an assessment result">
          <span className={`step-header-status-dot${isStreaming ? " working" : ""}`} />
          {isStreaming ? "working" : "idle"}
        </span>
      </div>
      <h2 className="step-header-title">{STEP_TITLE[activeStep]}</h2>
      <p className="step-header-description">{STEP_DESCRIPTION[activeStep]}</p>
      <div className="step-header-tabs" role="tablist" aria-label="Workflow step">
        {WORKFLOW_STEPS.map((s) => {
          const canNavigate = canNavigateToStep(s.step, workflowProgress);
          const isActive = s.step === activeStep;
          return (
            <button
              key={s.step}
              type="button"
              role="tab"
              aria-selected={isActive}
              className={`step-header-tab${isActive ? " active" : ""}`}
              disabled={!canNavigate}
              onClick={() => canNavigate && onStepChange(s.step)}
              title={!canNavigate ? `${s.label} isn't reachable yet` : s.label}
            >
              <span className="step-header-tab-dot" aria-hidden="true" />
              {TAB_LABEL[s.step]}
            </button>
          );
        })}
      </div>
    </div>
  );
}
