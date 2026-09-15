import type { ActiveStep, WorkflowProgress } from "./types";

export interface StepDef {
  step: ActiveStep;
  key: keyof WorkflowProgress;
  label: string;
  sublabel: string;
}

/** The four-step workflow, in order. Single source of truth for anything
 *  that lists or navigates the steps — the Sidebar's workflow tree and the
 *  data pane's breadcrumb tabs both read from this, so they can never
 *  disagree about a step's label or navigability. */
export const WORKFLOW_STEPS: StepDef[] = [
  { step: 1, key: "phase1", label: "RCM Intake", sublabel: "Control inventory & completeness" },
  { step: 2, key: "phase2", label: "Adequacy", sublabel: "SOPs, workpapers & reconciliation" },
  { step: 3, key: "phase3", label: "Evidence", sublabel: "Requirements & intake" },
  { step: 4, key: "phase4", label: "Gap Assessment", sublabel: "Received vs expected" },
];

/** Highest step whose workflow status is "done". 0 if none. */
export function highestDoneStep(workflowProgress: WorkflowProgress): number {
  return WORKFLOW_STEPS.reduce(
    (max, p) => (workflowProgress[p.key] === "done" && p.step > max ? p.step : max),
    0,
  );
}

/** A step is reachable once it has its own progress, or once the step
 *  immediately before it is done — otherwise there'd be no way to reach an
 *  upcoming step's upload screen right after the prior one just finished. */
export function canNavigateToStep(step: ActiveStep, workflowProgress: WorkflowProgress): boolean {
  const status = workflowProgress[WORKFLOW_STEPS[step - 1].key];
  return status !== "pending" || step === highestDoneStep(workflowProgress) + 1;
}
