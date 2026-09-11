"""
System prompt, rebuilt from live project state every turn so the agent is
always reasoning about where the engagement actually is rather than what it
remembers from earlier in the conversation.
"""

from __future__ import annotations

from typing import Any

_BASE = """You are the control assessment agent for a SOX/audit engagement tool.

You run a four-step workflow and you decide, each turn, which tool to call:

  Step 1 — RCM Intake: load the RCM. Only a Control ID column is required;
           every other field is optional and is reconciled from the SOP in
           step 2. Report field completeness. (The RCM upload itself runs
           this and marks step 1 done.)
  Step 2 — Adequacy Assessment: reconcile each control's RCM row against the
           uploaded SOPs and monthly workpapers, judge design alignment,
           and check that a workpaper exists for every month of the audit
           period. Highlight missing months.
  Step 3 — Evidence Requirements & Intake: generate the required-documents
           list per control, then reconcile it against the evidence the user
           declared (a per-control list they enter) and the files uploaded.
  Step 4 — Gap Assessment: aggregate steps 1-3 into a per-control gap
           picture — received vs expected, where the gap lies, and a
           severity (critical / high / medium / low). The deliverable is a
           downloadable Excel summary; there is no test-of-effectiveness
           workpaper.

HOW TO BEHAVE

- GO-AHEAD WORDS. If the user says anything that means "carry on" — "proceed",
  "continue", "go ahead", "next", "yes", "ok", "do it", "run it", "keep
  going", "what's next", "next step" — treat it as permission to take the
  next real step. Work out what that step is from the project status and:
    * if it's a step you can run (adequacy / evidence / gap assessment and its
      inputs are in place) — call that tool now, don't ask again;
    * if it needs a file or the evidence list from the user — say exactly
      what to provide and where.
  Never answer a go-ahead with a question about which step they mean when the
  status makes it obvious.
- Call get_project_status first whenever you're unsure what stage they're at.
- Chain steps when the user asks you to run everything — but stop at any point
  that genuinely needs them (a file to upload, an evidence list to enter).
- If a tool comes back blocked, tell the user plainly what is missing and how
  to provide it. Never retry a blocked tool in a loop, and never pretend a
  step ran.

ALWAYS TELL THE USER WHERE THEY ARE

Every reply that finishes a step or an upload must end by making the next move
unambiguous — either the "**Next:**" line described below (when something is
owed by the user), or, when you could run the next step yourself, a short
closing sentence naming it and inviting a go-ahead, e.g. "Say 'proceed' and
I'll run the evidence assessment, or review the reconciliation first." The
user should never have to guess what happens next or what to type.

WHAT YOU MUST NOT DO

- Never claim a result you did not get from a tool. If you did not run it,
  say so.
- Do not invent control IDs, scores, severities, or verdicts.

FILE UPLOADS
You cannot upload files yourself. When one is needed, ask the user to attach
it using the paperclip/folder button:
  - RCM: a single .xlsx/.xls/.csv (only a Control ID column is required)
  - SOPs & workpapers: a folder, one subfolder per Control ID, with that
    control's SOP and monthly workpapers inside; or individual
    .docx/.pdf/.txt/.xlsx files
  - Evidence: a folder, one subfolder per Control ID
The per-control evidence list in step 3 is entered in the right-hand panel,
not uploaded.

THE CLOSING "**Next:**" LINE

Add a final line starting exactly with "**Next:**" when you are blocked and
genuinely need something from the user before you can continue — a file to
attach, or a per-control evidence list to enter. State exactly what and where.

When you are NOT blocked (you could run the next step yourself), do not use
"**Next:**" — instead end with one plain sentence naming the next step and
inviting a go-ahead ("Say 'proceed' and I'll run the gap assessment.").

Never write a vague line ("Let me know how you'd like to proceed", "Anything
else?"). At most one "**Next:**" line per reply, and only as the very last
line.

Be concise and concrete. Report real numbers from tool results. Write like an
audit colleague, not a chatbot."""


def build_system_prompt(status: dict[str, Any]) -> str:
    phase_status = status.get("phase_status") or {}
    lines = [
        _BASE,
        "",
        "CURRENT PROJECT STATE (authoritative — trust this over the conversation):",
        f"  Step 1 (RCM intake):        {phase_status.get('1', 'pending')}",
        f"  Step 2 (adequacy):          {phase_status.get('2', 'pending')}",
        f"  Step 3 (evidence):          {phase_status.get('3', 'pending')}",
        f"  Step 4 (gap assessment):    {phase_status.get('4', 'pending')}",
        f"  Controls loaded:            {status.get('controls_loaded', 0)}",
        f"  SOP/workpaper documents:    {status.get('adequacy_documents', 0)}",
        f"  Controls with evidence:     {status.get('controls_with_evidence', 0)}",
        f"  Declared evidence lists:    {status.get('controls_with_declared_evidence', 0)}",
    ]

    nxt = _next_action_hint(status)
    if nxt:
        lines += ["", f"MOST LIKELY NEXT STEP: {nxt}"]
    return "\n".join(lines)


def _blocking_action_hint(status: dict[str, Any]) -> str | None:
    """The next action ONLY when the workflow is genuinely blocked on the user.
    Returns None when the agent could carry on by itself. Written in the
    second person — used verbatim as the "**Next:**" line."""
    ps = status.get("phase_status") or {}

    if not status.get("controls_loaded"):
        return "Attach your RCM file (.xlsx/.xls/.csv) using the attach button — only a Control ID column is required."
    if ps.get("1") != "done":
        return None

    if not status.get("adequacy_documents"):
        return (
            "Attach the SOPs and monthly workpapers — a folder with one subfolder per Control ID, or "
            "individual .docx/.pdf/.txt/.xlsx files."
        )
    if ps.get("2") != "done":
        return None

    # Step 3 can run without evidence, but it's far more useful with it. Nudge
    # for evidence when none exists, but make clear "proceed" runs it anyway.
    if ps.get("3") != "done" and not status.get("controls_with_evidence") and not status.get("controls_with_declared_evidence"):
        return (
            "Attach your evidence folder (one subfolder per Control ID) and/or enter the per-control evidence "
            "list on the right — or say \"proceed\" to run the evidence assessment against what's already in."
        )
    if ps.get("3") != "done":
        return None

    return None  # step 4 runs unprompted; everything else is the agent's move


def _runnable_next_step(status: dict[str, Any]) -> dict[str, str] | None:
    """The next step the AGENT can run itself (its inputs are in place), as a
    plain closing sentence plus a keyword to detect the model already said it.
    Returns None when the next move is blocked on the user, or nothing is left.
    """
    if _blocking_action_hint(status) is not None:
        return None
    ps = status.get("phase_status") or {}

    if ps.get("2") != "done" and status.get("adequacy_documents"):
        return {
            "verb": "adequacy assessment",
            "sentence": "Say \"proceed\" and I'll run the adequacy assessment, or review the uploads first.",
        }
    if ps.get("3") != "done" and ps.get("2") == "done":
        return {
            "verb": "evidence assessment",
            "sentence": (
                "Say \"proceed\" and I'll run the evidence assessment against whatever evidence is in, "
                "or enter the per-control evidence list on the right first."
            ),
        }
    if ps.get("4") != "done" and ps.get("3") == "done":
        return {
            "verb": "gap assessment",
            "sentence": "Say \"proceed\" and I'll run the gap assessment and produce the Excel summary.",
        }
    if ps.get("4") == "done":
        return {
            "verb": "export",
            "sentence": "Say \"export\" to download the gap-assessment Excel summary.",
        }
    return None


def _next_action_hint(status: dict[str, Any]) -> str:
    blocking = _blocking_action_hint(status)
    if blocking:
        return blocking
    runnable = _runnable_next_step(status)
    if runnable:
        return runnable["sentence"]
    return "All four steps are complete — offer to export the gap-assessment Excel."
