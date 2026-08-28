"""
Agent tools. Each wraps the SAME route function the UI calls — the agent has
no privileged path, so ownership checks, phase claims, and preconditions all
apply identically whether a human clicked a button or the LLM chose a tool.
"""

from __future__ import annotations

import logging

from fastapi import HTTPException

from app.agent.core.types import AgentContext, Tool, ToolParameter, ToolResult

logger = logging.getLogger("agent.tools")


def _phase_done(ctx: AgentContext, phase: int) -> bool:
    return ctx.phase_status().get(str(phase)) == "done"


class RunPhase1Tool(Tool):
    name = "run_racm_validation"
    description = (
        "Phase 1. Validate the loaded RCM: score completeness, classify risk, build the risk heatmap and "
        "priority queue. If controls are missing a Risk Level this pauses to ask the user for a "
        "Probability x Impact weighting. Requires an RCM to have been uploaded."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        from app.database import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM controls WHERE project_id = %s LIMIT 1", (ctx.project_id,))
                if cur.fetchone() is None:
                    return "No RCM has been uploaded yet. Ask the user to attach their RCM (Excel or CSV)."
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.phases import run_risk_prioritization

        res = run_risk_prioritization(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 1, "result": result})

        if result.get("awaiting_weighting"):
            missing = result.get("controls_missing_risk_level") or []
            return ToolResult(
                success=True,
                data={"awaiting_weighting": True, "controls_missing_risk_level": missing},
                message=(
                    f"{len(missing)} control(s) have no Risk Level. The user must choose a Probability x Impact "
                    "weighting (default or custom) before I can infer them — the choice is shown in the right-hand "
                    "panel. Tell them to pick one there, or say 'use the default weighting' and I'll apply it."
                ),
            )
        if res.status == "awaiting_approval":
            n = result.get("controls_pending_inference", 0)
            return ToolResult(
                success=True,
                data={"pending": n},
                message=(
                    f"Inferred Risk Levels for {n} control(s). They're staged for review in the right-hand panel "
                    "and need the user's approval before Phase 2 can run."
                ),
            )
        stats = result.get("stats") or {}
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Phase 1 complete: {stats.get('controls_in_racm', 0)} controls, "
                f"{round((stats.get('racm_completeness_pct') or 0) * 100)}% complete, "
                f"{stats.get('high_risk_count', 0)} high-risk."
            ),
        )


class SetRiskWeightingTool(Tool):
    name = "set_risk_weighting"
    description = (
        "Apply the Probability x Impact weighting the user chose, then infer Risk Levels for controls that lack "
        "them. Use use_default=true for the standard model (Low=1, Medium=3, High=6; bands 5/17/35). Only pass "
        "custom weights if the user explicitly gave numbers."
    )
    parameters = [
        ToolParameter("use_default", "boolean", "True to use the standard weighting model.", required=True),
        ToolParameter("low", "integer", "Custom weight for Low (only if use_default is false)."),
        ToolParameter("medium", "integer", "Custom weight for Medium (only if use_default is false)."),
        ToolParameter("high", "integer", "Custom weight for High (only if use_default is false)."),
    ]

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.models.schemas import RiskWeightingRequest
        from app.routes.phases import set_risk_weighting

        use_default = bool(kwargs.get("use_default", True))
        body = RiskWeightingRequest(use_default=True)
        if not use_default:
            low, medium, high = kwargs.get("low"), kwargs.get("medium"), kwargs.get("high")
            if not all(isinstance(v, int) for v in (low, medium, high)):
                return ToolResult(
                    success=False,
                    error="missing weights",
                    message="A custom weighting needs whole-number weights for Low, Medium and High.",
                )
            # Bands scale with the weights so the top band stays reachable.
            body = RiskWeightingRequest(
                use_default=False,
                score_map={"low": low, "medium": medium, "high": high},
                bands=[
                    {"threshold": low * medium, "label": "Low"},
                    {"threshold": medium * medium + 1, "label": "Medium"},
                    {"threshold": high * high - 1, "label": "High"},
                ],
            )

        res = set_risk_weighting(ctx.project_id, body, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 1, "result": result})
        n = len(result.get("pending_risk_inferences") or {})
        return ToolResult(
            success=True,
            data={"inferred": n},
            message=(
                f"Applied the {'default' if use_default else 'custom'} weighting and inferred Risk Levels for "
                f"{n} control(s). They're staged in the right-hand panel for the user to approve."
            ),
        )


class ApproveRiskInferencesTool(Tool):
    name = "approve_risk_inferences"
    description = (
        "Commit the staged Risk Level inferences after the user has approved them. Only call this when the user "
        "has clearly said to go ahead — this writes the inferred values into the working RCM."
    )
    parameters: list[ToolParameter] = []

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.phases import approve_risk_inferences

        res = approve_risk_inferences(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 1, "result": result})
        stats = result.get("stats") or {}
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Risk levels approved and applied. Phase 1 complete: {stats.get('controls_in_racm', 0)} controls, "
                f"{stats.get('high_risk_count', 0)} high-risk. Next the user needs to upload an evidence folder "
                "for Phase 2."
            ),
        )


class RunPhase2Tool(Tool):
    name = "run_evidence_review"
    description = (
        "Phase 2. Generate the expected-documents checklist per control, score the uploaded evidence against it, "
        "and escalate gaps. Requires Phase 1 done AND an evidence folder already uploaded."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        if not _phase_done(ctx, 1):
            return "Phase 1 isn't finished yet — complete the RACM validation (and any risk approval) first."
        from app.database import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM evidence_files WHERE project_id = %s LIMIT 1", (ctx.project_id,))
                if cur.fetchone() is None:
                    return (
                        "No evidence has been uploaded yet. Ask the user to attach their evidence folder — one "
                        "subfolder per Control ID, with samples inside as sample1/, sample2/... or sample_N-named "
                        "files."
                    )
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.phases import run_evidence_gap_analysis

        res = run_evidence_gap_analysis(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 2, "result": result})
        stats = result.get("stats") or {}
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Phase 2 complete: {stats.get('avg_evidence_score', 0)}% average evidence completeness, "
                f"{stats.get('evidence_gaps_count', 0)} escalated gap(s), "
                f"{stats.get('controls_without_evidence', 0)} control(s) with no evidence, "
                f"{stats.get('test_ready_controls', 0)} ready for testing. Phase 3 needs an SOP document."
            ),
        )


class RunPhase3Tool(Tool):
    name = "run_adequacy_assessment"
    description = (
        "Phase 3. Compare each control's design against the uploaded SOP, find SOP steps with no matching control, "
        "and check whether evidence dates cover the audit period. Requires Phase 2 done AND an SOP uploaded."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        if not _phase_done(ctx, 2):
            return "Phase 2 isn't finished yet — run the evidence review first."
        from app.database import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM sop_uploads WHERE project_id = %s LIMIT 1", (ctx.project_id,))
                if cur.fetchone() is None:
                    return (
                        "No SOP has been uploaded. Ask the user to attach the Standard Operating Procedure "
                        "document (.docx, .pdf or .txt) for this process."
                    )
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.phases import run_adequacy_assessment

        res = run_adequacy_assessment(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 3, "result": result})
        stats = result.get("stats") or {}
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Phase 3 complete: {stats.get('adequate_count', 0)} adequate, "
                f"{stats.get('partially_adequate_count', 0)} partially adequate, "
                f"{stats.get('inadequate_count', 0)} inadequate, "
                f"{stats.get('uncovered_sop_steps', 0)} SOP step(s) with no matching control, "
                f"{stats.get('timeline_issues_count', 0)} timeline issue(s)."
            ),
        )


class PreviewAttributesTool(Tool):
    name = "generate_testing_attributes"
    description = (
        "Phase 4 step 1. Generate the Yes/No testing attributes for every control. The user reviews and can edit "
        "them before approving. Requires Phase 3 done."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        if not _phase_done(ctx, 3):
            return "Phase 3 isn't finished yet — run the adequacy assessment first."
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.attributes import preview_attributes

        rows = preview_attributes(ctx.project_id, ctx.auth)
        payload = [r.model_dump() for r in rows]
        ctx.emit("attributes_ready", {"attributes": payload})
        issues = sum(len(r.quality_issues) for r in rows)
        return ToolResult(
            success=True,
            data={"controls": len(rows), "quality_issues": issues},
            message=(
                f"Generated testing attributes for {len(rows)} control(s)"
                + (f", with {issues} quality finding(s) flagged." if issues else ", all clean.")
                + " They're in the right-hand panel — the user should review and edit before approving, because "
                "approval freezes them against the test results."
            ),
        )


class ApproveAttributesAndTestTool(Tool):
    name = "approve_attributes_and_run_testing"
    description = (
        "Phase 4 step 2. Freeze the testing attributes and run control effectiveness testing against the evidence "
        "samples. Only call once the user has confirmed the attributes look right — approval is irreversible for "
        "any control that then gets tested."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        if not _phase_done(ctx, 3):
            return "Phase 3 isn't finished yet."
        from app.database import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM control_attributes WHERE project_id = %s LIMIT 1", (ctx.project_id,))
                if cur.fetchone() is None:
                    return "No testing attributes exist yet — generate them first."
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.attributes import approve_attributes
        from app.routes.phases import run_control_testing

        approve_attributes(ctx.project_id, ctx.auth)
        ctx.emit("token", {"text": "Attributes approved. Running effectiveness testing…\n"})

        res = run_control_testing(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 4, "result": result})
        stats = result.get("stats") or {}
        fmt = stats.get("format_issue_count", 0)
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Phase 4 complete across {result.get('tested_control_count', 0)} tested control(s): "
                f"{stats.get('effective', 0)} effective, {stats.get('partially_effective', 0)} with exceptions, "
                f"{stats.get('ineffective', 0)} ineffective. Overall control health "
                f"{round((result.get('overall_health_pct') or 0) * 100)}%."
                + (
                    f" {fmt} control(s) could not be tested because their evidence isn't organized into samples."
                    if fmt
                    else ""
                )
            ),
        )


class ExportTool(Tool):
    name = "export_report"
    description = (
        "Generate a downloadable Excel file. kind='final_report' for the multi-sheet workpaper covering every "
        "phase; kind='attributes' for the editable testing-attribute workbook."
    )
    parameters = [
        ToolParameter(
            "kind", "string", "Which file to export.", required=True, enum=["final_report", "attributes"]
        ),
    ]

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.export import export_attributes, export_final_report

        kind = kwargs.get("kind", "final_report")
        artifact = export_attributes(ctx.project_id, ctx.auth) if kind == "attributes" else export_final_report(
            ctx.project_id, ctx.auth
        )
        ctx.emit("artifact_ready", {"artifact": artifact.model_dump(mode="json")})
        return ToolResult(
            success=True,
            data={"filename": artifact.filename},
            message=f"Exported \"{artifact.filename}\". It's downloadable from the Reports panel.",
        )


class GetStatusTool(Tool):
    name = "get_project_status"
    description = (
        "Read the current state of the engagement: which phases are done, and what the tool is waiting on. Call "
        "this first when you're unsure what stage the user is at."
    )
    parameters: list[ToolParameter] = []

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.database import get_conn
        from psycopg.rows import dict_row

        status = ctx.phase_status()
        with get_conn() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute("SELECT count(*) AS n FROM controls WHERE project_id = %s", (ctx.project_id,))
                controls = cur.fetchone()["n"]
                cur.execute(
                    "SELECT count(DISTINCT control_id) AS n FROM evidence_files WHERE project_id = %s",
                    (ctx.project_id,),
                )
                evidence = cur.fetchone()["n"]
                cur.execute("SELECT count(*) AS n FROM sop_uploads WHERE project_id = %s", (ctx.project_id,))
                sops = cur.fetchone()["n"]
                cur.execute(
                    "SELECT count(*) AS n FROM control_attributes WHERE project_id = %s", (ctx.project_id,)
                )
                attrs = cur.fetchone()["n"]

        data = {
            "phase_status": status,
            "controls_loaded": controls,
            "controls_with_evidence": evidence,
            "sop_uploaded": sops > 0,
            "attribute_schemas": attrs,
        }
        return ToolResult(success=True, data=data, message=f"Current state: {data}")


ALL_TOOLS: list[Tool] = [
    GetStatusTool(),
    RunPhase1Tool(),
    SetRiskWeightingTool(),
    ApproveRiskInferencesTool(),
    RunPhase2Tool(),
    RunPhase3Tool(),
    PreviewAttributesTool(),
    ApproveAttributesAndTestTool(),
    ExportTool(),
]

TOOLS_BY_NAME: dict[str, Tool] = {t.name: t for t in ALL_TOOLS}


def execute_tool(name: str, ctx: AgentContext, arguments: dict) -> ToolResult:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return ToolResult(success=False, error="unknown tool", message=f"No such tool: {name}")

    blocked = tool.preconditions(ctx)
    if blocked:
        # A precondition is not an error — it's information the agent should
        # relay so the user knows exactly what to do next.
        return ToolResult(success=False, error="precondition", message=blocked)

    try:
        return tool.execute(ctx, **arguments)
    except HTTPException as e:
        return ToolResult(success=False, error="http", message=str(e.detail))
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return ToolResult(success=False, error="exception", message=f"{name} failed: {e}")
