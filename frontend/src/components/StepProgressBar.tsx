export type StepStatus = "pending" | "running" | "done" | "error";

export interface StepDef {
  label: string;
  status: StepStatus;
}

interface StepProgressBarProps {
  steps: StepDef[];
}

const STEP_COLORS: Record<StepStatus, string> = {
  pending: "#d1d5db",
  running: "#005EB8",
  done: "#16a34a",
  error: "#dc2626",
};

export default function StepProgressBar({ steps }: StepProgressBarProps) {
  return (
    <div className="step-bar">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1;
        return (
          <div key={step.label} className="step-bar-item">
            <div className="step-bar-node-wrap">
              <div
                className={`step-bar-node ${step.status}`}
                style={{
                  borderColor: STEP_COLORS[step.status],
                  background: step.status !== "pending" ? STEP_COLORS[step.status] : "transparent",
                }}
              >
                {step.status === "done" && (
                  <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
                    <path d="M2 5l2.5 2.5L8 3" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                )}
                {step.status === "running" && <div className="step-bar-pulse" />}
                {step.status === "error" && <span style={{ color: "#fff", fontSize: 10, fontWeight: 700 }}>!</span>}
              </div>
              {!isLast && (
                <div
                  className="step-bar-line"
                  style={{ background: step.status === "done" ? "#16a34a" : "#e5e7eb" }}
                />
              )}
            </div>
            <div className={`step-bar-label ${step.status}`}>{step.label}</div>
          </div>
        );
      })}
    </div>
  );
}
