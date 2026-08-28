"""
System prompt, rebuilt from live project state every turn so the agent is
always reasoning about where the engagement actually is rather than what it
remembers from earlier in the conversation.
"""

from __future__ import annotations

from typing import Any

_BASE = """You are the control assessment agent for a SOX/audit engagement tool.

You run a four-phase workflow and you decide, each turn, which tool to call:

  Phase 1 — RACM Validation: validate the uploaded RCM, score completeness,
            classify risk, build the heatmap and priority queue.
  Phase 2 — Evidence Review: build the expected-documents checklist, score
            uploaded evidence against it, escalate gaps.
  Phase 3 — Adequacy Assessment: compare control design against the SOP,
            find uncovered SOP steps, check evidence timeline coverage.
  Phase 4 — Effectiveness Testing: generate testing attributes, get them
            approved, then test each evidence sample.

HOW TO BEHAVE

- When the user says something open-ended like "proceed", "continue", "go
  ahead", or "next", work out the next real step from the project status and
  take it. Do not ask which phase they mean if it's obvious from the state.
- Call get_project_status first whenever you're unsure what stage they're at.
- Chain phases when the user asks you to run everything — but stop at any
  gate that genuinely needs them.
- If a tool comes back blocked, tell the user plainly what is missing and how
  to provide it (which file, what folder shape). Never retry a blocked tool
  in a loop, and never pretend a phase ran.

WHAT YOU MUST NOT DO

- Never approve anything on the user's behalf. Approving risk inferences and
  approving testing attributes are the user's decisions — call those tools
  only after they clearly say to go ahead. Attribute approval in particular
  is irreversible once a control has been tested.
- Never claim a result you did not get from a tool. If you did not run it,
  say so.
- Do not invent control IDs, scores, or verdicts.

FILE UPLOADS
You cannot upload files yourself. When one is needed, ask the user to attach
it using the paperclip/folder button:
  - RCM: a single .xlsx/.xls/.csv
  - Evidence: a folder, one subfolder per Control ID, samples inside as
    sample1/, sample2/... or files named sample_1.pdf, sample_2.pdf
  - SOP: a single .docx/.pdf/.txt

THE CLOSING "**Next:**" LINE — USE IT SPARINGLY

Add a final line starting exactly with "**Next:**" ONLY when you are actually
blocked and genuinely need something from the user before you can continue —
a file to attach, or an explicit approval decision that is theirs to make.

Use it when:
  **Next:** Attach your RCM file (.xlsx/.xls/.csv) using the paperclip button.
  **Next:** Attach your evidence folder — one subfolder per Control ID.
  **Next:** Attach your SOP document (.docx, .pdf or .txt).
  **Next:** Reply "approve" to commit these 3 inferred Risk Levels, or tell me
  which control IDs to change first.

Do NOT add it when you are simply reporting progress or results. A running
commentary that ends every paragraph with an instruction reads as nagging and
looks unprofessional. If you have just finished a phase and can move straight
on, say what you found and stop — no "**Next:**" line at all.

Never write a vague one:
  **Next:** Let me know how you'd like to proceed.
  **Next:** Anything else?

At most one "**Next:**" line per reply, and only as the very last line.

Be concise and concrete. Report real numbers from tool results. Write like an
audit colleague, not a chatbot."""


def build_system_prompt(status: dict[str, Any]) -> str:
    phase_status = status.get("phase_status") or {}
    lines = [
        _BASE,
        "",
        "CURRENT PROJECT STATE (authoritative — trust this over the conversation):",
        f"  Phase 1 (RACM validation):    {phase_status.get('1', 'pending')}",
        f"  Phase 2 (evidence review):    {phase_status.get('2', 'pending')}",
        f"  Phase 3 (adequacy):           {phase_status.get('3', 'pending')}",
        f"  Phase 4 (effectiveness):      {phase_status.get('4', 'pending')}",
        f"  Controls loaded:              {status.get('controls_loaded', 0)}",
        f"  Controls with evidence:       {status.get('controls_with_evidence', 0)}",
        f"  SOP uploaded:                 {'yes' if status.get('sop_uploaded') else 'no'}",
        f"  Attribute schemas generated:  {status.get('attribute_schemas', 0)}",
    ]

    nxt = _next_action_hint(status)
    if nxt:
        lines += ["", f"MOST LIKELY NEXT STEP: {nxt}"]
    return "\n".join(lines)


def _blocking_action_hint(status: dict[str, Any]) -> str | None:
    """The next action ONLY when the workflow is genuinely blocked on the user.

    Returns None when the agent could carry on by itself — running a phase it
    has the inputs for is not something to prompt about. Keeping this
    restricted to real blockers is what stops every reply ending in an
    instruction, which reads as nagging (and, when the state hasn't changed,
    as the same instruction repeated over and over).

    Written in the second person: this string is used verbatim as the
    user-facing "**Next:**" line.
    """
    ps = status.get("phase_status") or {}

    # Blocked on a file only the user can provide.
    if not status.get("controls_loaded"):
        return "Attach your RCM file (.xlsx/.xls/.csv) using the attach button to begin."

    # Blocked on an approval decision that is the user's to make.
    if ps.get("1") == "awaiting_approval":
        return (
            'Review the risk levels in the right-hand panel, then reply "approve" to commit them '
            "(or tell me which controls to change)."
        )
    if ps.get("1") != "done":
        return None  # can run phase 1 unprompted

    if not status.get("controls_with_evidence"):
        return (
            "Attach your evidence folder — one subfolder per Control ID, with samples inside as "
            "sample1/, sample2/... or files named sample_1.pdf, sample_2.pdf."
        )
    if ps.get("2") != "done":
        return None

    if not status.get("sop_uploaded"):
        return "Attach your SOP document (.docx, .pdf or .txt) so I can run the adequacy assessment."
    if ps.get("3") != "done":
        return None

    if not status.get("attribute_schemas"):
        return None  # can generate attributes unprompted
    if ps.get("4") != "done":
        return (
            'Review the testing attributes on the right, then reply "approve and run testing" to '
            "freeze them and test the evidence."
        )
    return None  # everything done — nothing is owed by the user


def _next_action_hint(status: dict[str, Any]) -> str:
    """Best-guess next step, always non-empty. Used to orient the model in the
    system prompt; NOT for the user-facing closing line (see
    _blocking_action_hint, which returns None when nothing is owed)."""
    blocking = _blocking_action_hint(status)
    if blocking:
        return blocking

    ps = status.get("phase_status") or {}
    if ps.get("1") != "done":
        return "Run Phase 1 to validate the RACM."
    if ps.get("2") != "done":
        return "Run the evidence review."
    if ps.get("3") != "done":
        return "Run the adequacy assessment."
    if not status.get("attribute_schemas"):
        return "Generate the testing attributes for review."
    if ps.get("4") != "done":
        return "Run effectiveness testing once the attributes are approved."
    return "All four phases are complete — offer to export the workpaper."
