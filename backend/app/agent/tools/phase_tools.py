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


class RunStep1Tool(Tool):
    name = "run_rcm_intake"
    description = (
        "Step 1. Recompute the RCM completeness view. The RCM upload already does this and marks step 1 "
        "done, so only call this after the RCM has been corrected/re-uploaded. Requires an RCM."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        from app.database import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM controls WHERE project_id = %s LIMIT 1", (ctx.project_id,))
                if cur.fetchone() is None:
                    return "No RCM has been uploaded yet. Ask the user to attach their RCM (Excel or CSV) — only a Control ID column is required."
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.phases import run_rcm_intake

        res = run_rcm_intake(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 1, "result": result})
        stats = result.get("stats") or {}
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Step 1: {stats.get('controls_in_racm', 0)} controls loaded, "
                f"{round((stats.get('racm_completeness_pct') or 0) * 100)}% average field completeness. "
                "NEXT STEP for the user: upload the SOPs and monthly workpapers for step 2 — a folder with one "
                "subfolder per Control ID, or individual .docx/.pdf/.txt/.xlsx files. Say this in the reply."
            ),
        )


class RunStep2Tool(Tool):
    name = "run_adequacy_assessment"
    description = (
        "Step 2. Reconcile each control's RCM row against the uploaded SOPs and monthly workpapers, judge "
        "design alignment, and check monthly workpaper coverage against the audit period. Requires step 1 "
        "done AND at least one SOP/workpaper uploaded."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        if not _phase_done(ctx, 1):
            return "Step 1 isn't finished yet."
        from app.database import get_conn

        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM adequacy_documents WHERE project_id = %s LIMIT 1", (ctx.project_id,))
                if cur.fetchone() is None:
                    return (
                        "No SOPs or workpapers uploaded. Ask the user to attach a folder (one subfolder per "
                        "Control ID, with the monthly workpapers inside) or individual SOP/workpaper files "
                        "(.docx, .pdf, .txt or .xlsx)."
                    )
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.phases import run_adequacy_assessment

        res = run_adequacy_assessment(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 2, "result": result})
        stats = result.get("stats") or {}
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Step 2 complete: {stats.get('adequate_count', 0)} adequate, "
                f"{stats.get('partially_adequate_count', 0)} partially adequate, "
                f"{stats.get('inadequate_count', 0)} inadequate; "
                f"{stats.get('unreconciled_count', 0)} control(s) not described in the documentation, "
                f"{stats.get('workpaper_gap_count', 0)} with missing workpaper months. "
                "NEXT STEP: step 3 (evidence). The user can enter the per-control evidence list in the right-hand "
                "panel and/or upload an evidence folder, then say 'proceed'; or say 'proceed' now to run step 3 "
                "against whatever evidence is already in. Offer both in the reply."
            ),
        )


class RunStep3Tool(Tool):
    name = "run_evidence_assessment"
    description = (
        "Step 3. Generate the required-documents list per control and reconcile it against the evidence the "
        "user declared (per-control list) and the files actually uploaded. Requires step 2 done."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        if not _phase_done(ctx, 2):
            return "Step 2 (adequacy assessment) isn't finished yet."
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.phases import run_evidence_assessment

        res = run_evidence_assessment(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 3, "result": result})
        stats = result.get("stats") or {}
        rollup = stats.get("severity_rollup") or {}
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Step 3 complete: {stats.get('avg_evidence_score', 0)}% average evidence completeness, "
                f"{stats.get('evidence_gaps_count', 0)} control(s) with a gap "
                f"(critical {rollup.get('critical', 0)}, high {rollup.get('high', 0)}, "
                f"medium {rollup.get('medium', 0)}, low {rollup.get('low', 0)}). "
                "NEXT STEP: step 4 (gap assessment) — you can run it now. Tell the user it's ready and that saying "
                "'proceed' will run it and produce the downloadable Excel summary."
            ),
        )


class RunStep4Tool(Tool):
    name = "run_gap_assessment"
    description = (
        "Step 4. Aggregate steps 1-3 into the per-control gap picture: received vs expected, where the gap "
        "lies, and a severity (critical/high/medium/low). The downloadable Excel summary is built from this. "
        "Requires step 3 done."
    )
    parameters: list[ToolParameter] = []

    def preconditions(self, ctx: AgentContext) -> str | None:
        if not _phase_done(ctx, 3):
            return "Step 3 (evidence assessment) isn't finished yet."
        return None

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.phases import run_gap_assessment

        res = run_gap_assessment(ctx.project_id, ctx.auth)
        result = res.result or {}
        ctx.emit("results_ready", {"phase": 4, "result": result})
        stats = result.get("stats") or {}
        rollup = stats.get("severity_rollup") or {}
        return ToolResult(
            success=True,
            data=stats,
            message=(
                f"Step 4 complete: {stats.get('controls_assessed', 0)} controls assessed — "
                f"{stats.get('fully_covered', 0)} fully covered, {stats.get('serious', 0)} with a "
                f"critical/high gap. Severity: critical {rollup.get('critical', 0)}, high {rollup.get('high', 0)}, "
                f"medium {rollup.get('medium', 0)}, low {rollup.get('low', 0)}. "
                "All four steps are done. NEXT STEP: tell the user to say 'export' (or use the Reports panel) to "
                "download the gap-assessment Excel summary."
            ),
        )


class ExportTool(Tool):
    name = "export_report"
    description = (
        "Generate the downloadable gap-assessment Excel — the multi-sheet summary covering every step "
        "(received vs expected, where the gap lies, severity, summary against RCM + SOP + evidence)."
    )
    parameters: list[ToolParameter] = []

    def execute(self, ctx: AgentContext, **kwargs) -> ToolResult:
        from app.routes.export import export_final_report

        artifact = export_final_report(ctx.project_id, ctx.auth)
        ctx.emit("artifact_ready", {"artifact": artifact.model_dump(mode="json")})
        return ToolResult(
            success=True,
            data={"filename": artifact.filename},
            message=f"Exported \"{artifact.filename}\". It's downloadable from the Reports panel.",
        )


class GetStatusTool(Tool):
    name = "get_project_status"
    description = (
        "Read the current state of the engagement: which steps are done, and what the tool is waiting on. "
        "Call this first when you're unsure what stage the user is at."
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
                cur.execute("SELECT count(*) AS n FROM adequacy_documents WHERE project_id = %s", (ctx.project_id,))
                adequacy_docs = cur.fetchone()["n"]
                cur.execute("SELECT count(*) AS n FROM declared_evidence WHERE project_id = %s", (ctx.project_id,))
                declared = cur.fetchone()["n"]

        data = {
            "phase_status": status,
            "controls_loaded": controls,
            "controls_with_evidence": evidence,
            "adequacy_documents": adequacy_docs,
            "controls_with_declared_evidence": declared,
        }
        return ToolResult(success=True, data=data, message=f"Current state: {data}")


ALL_TOOLS: list[Tool] = [
    GetStatusTool(),
    RunStep1Tool(),
    RunStep2Tool(),
    RunStep3Tool(),
    RunStep4Tool(),
    ExportTool(),
]

TOOLS_BY_NAME: dict[str, Tool] = {t.name: t for t in ALL_TOOLS}


def execute_tool(name: str, ctx: AgentContext, arguments: dict) -> ToolResult:
    tool = TOOLS_BY_NAME.get(name)
    if tool is None:
        return ToolResult(success=False, error="unknown tool", message=f"No such tool: {name}")

    blocked = tool.preconditions(ctx)
    if blocked:
        return ToolResult(success=False, error="precondition", message=blocked)

    try:
        return tool.execute(ctx, **arguments)
    except HTTPException as e:
        return ToolResult(success=False, error="http", message=str(e.detail))
    except Exception as e:
        logger.exception("Tool %s failed", name)
        return ToolResult(success=False, error="exception", message=f"{name} failed: {e}")
