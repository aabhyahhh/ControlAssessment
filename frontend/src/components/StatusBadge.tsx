const VARIANT_MAP: Record<string, "red" | "amber" | "green" | "critical" | "neutral"> = {
  // Critical is the system-computed escalation above High — it must read as
  // more severe than High, not fall through to neutral grey.
  critical: "critical",
  high: "red",
  "high/serious": "red",
  inadequate: "red",
  misaligned: "red",
  ineffective: "red",
  "not effective": "red",
  invalid: "red",
  "invalid format": "red",
  fail: "red",
  poor: "red",
  insufficient: "red",
  "no coverage": "red",
  "no evidence": "red",
  "not adequate": "red",
  "material weakness": "red",
  "significant deficiency": "red",
  deficiency: "amber",
  tested: "green",

  medium: "amber",
  "medium/moderate": "amber",
  "partially adequate": "amber",
  partial: "amber",
  "effective with exceptions": "amber",
  "partially effective": "amber",
  fair: "amber",
  running: "amber",
  awaiting_approval: "amber",
  pending: "amber",

  // Genuinely unknown states — never "attention" (amber) or "problem" (red).
  // Missing/undetermined data must never be dressed up as a finding.
  undetermined: "neutral",
  "not assessed": "neutral",
  "no data": "neutral",
  "not available": "neutral",
  "not applicable": "neutral",
  "n/a": "neutral",

  low: "green",
  adequate: "green",
  // An approved attribute schema is a completed step, so it reads green like
  // every other done state — it was falling through to neutral grey, which
  // made approval look no different from "pending".
  approved: "green",
  effective: "green",
  aligned: "green",
  pass: "green",
  good: "green",
  done: "green",
  sufficient: "green",
};

type Variant = "red" | "amber" | "green" | "critical" | "neutral";

function inferVariant(label: string): Variant {
  const key = label.trim().toLowerCase();
  if (key in VARIANT_MAP) return VARIANT_MAP[key];
  for (const [k, v] of Object.entries(VARIANT_MAP)) {
    if (key.includes(k)) return v;
  }
  return "neutral";
}

interface StatusBadgeProps {
  label: string;
  variant?: Variant;
}

export default function StatusBadge({ label, variant }: StatusBadgeProps) {
  const resolved = variant ?? inferVariant(label);
  return <span className={`status-badge status-badge-${resolved}`}>{label}</span>;
}
