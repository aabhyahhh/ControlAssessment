# ControlAssessment

A standalone, KPMG-branded, AI-driven 4-step control assessment tool:

1. **RCM Intake** — load the RCM. Only a Control ID column is required; every other field is optional and gets reconciled from the SOP in step 2. Reports field completeness.
2. **Adequacy Assessment** — upload the SOPs and monthly workpapers (one folder per Control ID, or individual files). Reconciles each control's RCM row against the documentation, judges design alignment, and checks that a workpaper exists for every month of the audit period (missing months are flagged).
3. **Evidence Requirements & Intake** — the engine generates the required-documents list per control; the user enters the evidence they hold (a structured per-control list); the two are reconciled against each other and against the files actually uploaded.
4. **Gap Assessment** — aggregates steps 1–3 into a per-control gap picture (received vs expected, where the gap lies, a severity of critical / high / medium / low) and a downloadable multi-sheet Excel summary. There is **no test-of-effectiveness workpaper**.

> **Sept 2026 redesign.** The tool previously ran RACM Validation & Risk Prioritization → Evidence Review → Adequacy → Effectiveness Testing, with LLM risk-level inference in step 1 and a TOE attribute/sample workpaper in step 4 (described in the changelog below, M3–M7). The current flow above supersedes it. Risk-level inference, the P×I weighting gate, attribute generation, and per-sample TOE testing have been removed. `init.sql` was edited in place (the retired `sop_uploads`, `control_attributes` and `control_test_results` tables are dropped on startup); there is no data migration.

This is an independent codebase — it shares no imports or files with the ControlIris project elsewhere in this repo. It reuses ControlIris's visual theme and architectural patterns only as reference.

## Layout

- `frontend/` — React 18 + Vite + TypeScript, KPMG-navy theme
- `backend/` — FastAPI (Python), Postgres for structured state, local disk for file storage
- `storage/` — local file storage root (gitignored): RCM uploads, evidence folders, SOP documents, generated artifacts

## Local setup

### Database

Uses a dedicated local Postgres 18 instance on **port 5433** (not the OS default 5432, which may be occupied by another Postgres install):

```
pg_ctl -D /opt/homebrew/var/postgresql@18 -l /tmp/ca_pg18.log -o "-p 5433" start
createdb -h /tmp -p 5433 control_assessment
```

### Backend

```
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python run_server.py     # http://localhost:4001, applies migrations on startup
```

### Frontend

```
cd frontend
npm install
npm run dev               # http://localhost:8090, proxies /api to the backend
```

## Status

- **M0 — Scaffold**: done. FastAPI app boots, Postgres migration runner creates all 12 tables, Vite frontend renders the themed shell and proxies to the backend.
- **M1 — Auth + Landing/Login/Projects**: done. Register/login/me, JWT auth, project CRUD with audit-period capture, `Landing/Login/Register/Projects.tsx`.
- **M2 — Workspace skeleton**: done. 3-column layout (sidebar/chat/resizable data pane), SSE chat plumbing (stub echo loop still backs free-text chat), sidebar step sync.
- **M3 — Phase 1 (RACM Validation & Risk Prioritization) end-to-end**: done. `rcm_normalizer.py` (header detection, marker normalization, alias + LLM column mapping), `rcm_overlay.py` (non-destructive edit accessor), `risk_scorer.py` (completeness, risk-level inference cascade, heatmap, priority queue), RCM upload endpoint, Phase 1 run/approve endpoints with a human-in-the-loop gate on inferred risk levels, `Phase1RiskPane.tsx` + `RiskHeatmap.tsx` + `GaugeRing.tsx` + `MetricCard.tsx` + `StatusBadge.tsx`. Verified via a full browser-driven run (register → create project → upload RCM → approve inferred risk level → view heatmap/priority queue), zero console errors.
- **M4 — Phase 2 (Evidence Review & Gap Identification) end-to-end**: done. `evidence_router.py` (shared multi_sample/invalid_format/no_evidence classifier — no single-sample fallback, per the build's explicit deviation from the generalized spec), `evidence_gap_engine.py` (LLM-generated required-documents checklist, token-overlap document matching, gap escalation by risk × completeness, completeness donut), evidence-folder upload endpoint (`/upload-folder`, multipart with per-file relative paths, single-root-folder + junk-file + Unicode-dash-normalized Control ID matching), Phase 2 run endpoint gated on Phase 1 approval, `Phase2EvidencePane.tsx` + `MiniDonut.tsx` evidence bars + escalated-gap cards. Also fixed a real navigation gap found during testing: the sidebar previously only unlocked phases that already had non-"pending" status, which made a freshly-completed phase's *next* phase unreachable — `Sidebar.tsx` now also unlocks the phase immediately following the highest completed one, and `Workspace.tsx` auto-advances `activeStep` after Phase 1 finishes. Verified via a full browser-driven run exercising all three evidence-folder classification modes in one upload (multi_sample/invalid_format/no_evidence), zero console errors. Note: Azure OpenAI calls are currently blocked by a virtual-network/firewall rule from this dev environment (403) — LLM-dependent inference (risk-level inference, required-documents generation) falls back gracefully to keyword/default values as designed, but hasn't been verified against real LLM output in this environment.
- **M5 — Phase 3 (Adequacy Assessment) end-to-end**: done. `text_extraction.py` (docx/pdf/txt, no OCR), `sop_adequacy_engine.py` (LLM SOP-to-process-step parsing with a paragraph-split fallback, per-control design-field alignment against the relevant SOP section, whole-process coverage-gap detection, dimension-based deficiency classification, control-type mix), `timeline_sufficiency.py` (filename-regex-then-LLM evidence dating, frequency-aware coverage checks — cadence-gap for Daily/Weekly, period-bucket for Monthly/Quarterly/Annual, in-window-only for event-driven — producing `sufficient`/`insufficient`/`undetermined` with `out_of_period`/`partial_coverage`/`gap`/`undetermined` flags), SOP upload endpoint, Phase 3 run endpoint gated on Phase 2 completion **and** a SOP being present, `Phase3AdequacyPane.tsx`. Verified end-to-end: the deliberate RCM-says-Monthly/SOP-says-Weekly mismatch is caught as `misaligned` with a `control_frequency` mismatch row; coverage gaps catch SOP steps with no matching control; and all three timeline states were reproduced with crafted evidence dates (in-period-but-partial, entirely out-of-period, and undated/undetermined). Browser E2E through all three phases, zero console errors.
- **M6 — Phase 4 (Control Effectiveness Testing) end-to-end**: done. `attribute_quality_gate.py` (the deterministic rule-based gate from ATTRIBUTE_GENERATION_ENGINE_SPEC.md Section 4), `attribute_engine.py` (3-stage draft → critic → gate+repair pipeline with the full authoring rulebook), `testing_engine.py` (multi-sample TOE-style evaluation, the 5 consistency rules enforced in code as well as prompt, deviation-rate → deficiency bands, risk-weighted health score), attribute preview/edit/approve endpoints, Phase 4 run endpoint, `AttributePreviewPane.tsx` + `Phase4TestingPane.tsx`.

  **Defects from the reference implementation deliberately NOT ported** (spec Section 8): the quality gate re-runs on *every* mutation path, not just generation (#1); one shared generation module with a single consistent style directive (#2/#3); `risk_description`/`risk_level` are fed into the generation prompt (#4); unresolved quality findings are surfaced in the API response and UI rather than swallowed (#8); removing the last attribute of a control is blocked (#9); generation failure is a first-class returned state, never a silently empty schema (#13). Schemas freeze on approval — post-approval mutation returns 409, because test results are keyed to the frozen positional attribute IDs.

  Verified end-to-end: attributes generate clean against the quality gate; a deliberately-generic edit is immediately flagged; the last-attribute floor and the post-approval freeze both return the right errors; and testing correctly discriminated a planted defect (a sample missing CFO approval failed on exactly that attribute while complete samples passed), with format-issue controls excluded from the run and reported separately rather than defaulted to a verdict. Browser E2E through all four phases, zero console errors.

- **M7 — Cross-phase polish, exports, run-all**: done. `export_engine.py` (attribute workbook matching ATTRIBUTE_GENERATION_ENGINE_SPEC.md Section 6 byte-for-byte — sheet name, headers, widths 16/12/35/60, `#2F5496` bold-white-11pt header fill — plus an 8-sheet final report), `routes/export.py` (generate/list/download with a path-containment check on download), `POST /phases-run-all`, `RepositoryPanel.tsx`, and header controls for both.

  The final report is **universe-preserving**: every control in the RCM appears exactly once on the Control Universe sheet, with untested controls carrying an explicit reason ("No evidence uploaded for this control") rather than being filtered out — a control silently missing from an audit deliverable is worse than one marked untested. Sheets: Control Universe, Phase 1 Risk, Phase 2 Evidence, Phase 3 Adequacy, Phase 3 SOP Gaps, Phase 4 Samples (one row per sample with its attribute grid), Phase 4 Summary, Attributes.

  `run-all` runs each not-yet-done phase in order and **stops at the first genuine gate rather than skipping it**, reporting exactly what's blocking. Verified against all four stop conditions: no RCM at all; the Phase 1 risk-inference approval gate; no SOP at Phase 3 (the case the plan calls out explicitly); and no approved attributes at Phase 4. Verified chaining Phases 2→3 in a single call.

  Verified end-to-end in the browser: Reports panel opens, final report exports, and a real 12KB `.xlsx` downloads through the authenticated blob path — zero console errors.

### Post-M7 work (2026-08-25)

**1. Fully self-contained.** The app had two runtime dependencies on the public internet: the KPMG logo was hot-linked from `upload.wikimedia.org` (3 files) and Inter was pulled from Google Fonts. Both would break in an air-gapped or offline deployment and leaked a referrer on every page load. Replaced with a local inline-SVG `BrandLogo` component (uses `currentColor`, so it inverts cleanly on the navy sidebar with no CSS filter) and the bundled `@fontsource/inter` package. Verified: **zero external URLs** remain in source outside the Azure OpenAI API itself. Nothing in `backend/` or `frontend/` imports or reads from anywhere outside `ControlAssessment/`.

**2. Concurrency / transaction gaps closed.**
- *Phase-run races*: preconditions were read through a separate short-lived connection, so two concurrent runs of the same phase both saw the gate open, both ran the full LLM pipeline, and the second clobbered the first. Fixed with a **claim** pattern — `_claim_phase()` takes a row lock only long enough to verify preconditions and flip `phase_status` to `running`, then releases it before the slow LLM work. A second caller blocks on the lock, wakes to find `running`, and gets a clean 409. Verified: 4 simultaneous Phase 1 runs → exactly one 200, three 409s. `_release_phase_claim()` clears the claim on failure so a crash can't lock a phase permanently (verified a precondition failure never leaves a stuck `running`).
- *`approve_risk_inferences` double commit*: the overlays were committed separately from `phase_results`, so a failure in between left overlays durably applied while the phase still advertised the same inferences as pending. Now one transaction — scoring reads the uncommitted overlays through the same connection, so it sees exactly what will be persisted.

**3. Risk-level inference with user-chosen weighting.** Replicates ControlIris's `infer_risk_level.py` model in `engines/risk_inference.py`: `Score = P_weight × I_weight`, mapped through band thresholds, with the 3×3 matrix **derived** from weights+bands rather than hardcoded (change either and the matrix follows). Verified to reproduce ControlIris's documented matrix exactly, including `Critical` as a system-computed escalation on High×High.

When an RCM has controls with no Risk Level, Phase 1 now **stops and asks** rather than silently picking a model — the weighting materially changes every rating, so it's an audit judgement, not a default. `POST /phases/1/weighting` accepts `use_default` or a custom `score_map`+`bands`, validated for the orderings that make the model meaningful (Low<Medium<High, ascending thresholds, reachable top band) with a plain-English rejection otherwise. Inference cascade per control: **compute** (both P and I present → pure arithmetic, no LLM) → **infer P/I then compute** (LLM rates probability and impact separately, so the *user's* weighting decides the level, not the model's opinion) → **conservative default**, flagged low-confidence. Every result carries P, I, score, source, confidence, and reasoning so a computed rating is distinguishable from an inferred one. `run-all` stops at this gate too, naming it specifically.

### Agent loop, per-step exports, and overrides (2026-08-25)

**The agent is now real.** `backend/app/agent/` was four empty files; chat returned a canned echo. Built:
- `agent/core/types.py` — `Tool` ABC with per-tool `preconditions()`, so hard rules live in code rather than only in the prompt.
- `agent/tools/phase_tools.py` — 9 tools, each wrapping the **same route function the UI button calls**, so ownership checks, phase claims, and preconditions apply identically whether a human clicked or the LLM chose.
- `agent/prompts/system.py` — system prompt rebuilt from **live project state every round**, so mid-turn state changes can't go stale.
- `agent/core/loop.py` — LLM decides each turn; loops until it stops calling tools (max 8 rounds).
- `routes/chat.py` — the agent runs on a worker thread pushing SSE frames onto a queue, so a multi-minute phase streams progress instead of buffering. Keep-alive comments every 15s.

The frontend's existing 8-event SSE contract is now actually served (`tool_start`/`tool_end`/`results_ready` were previously never emitted).

**Safety boundary:** the agent may run phases and export files, but **never approves on the user's behalf** — approving risk inferences and approving testing attributes require an explicit instruction. Verified: told to "proceed" at a pending approval gate, it applied the weighting and *asked* rather than approving.

**This fixes the "Phase 2 isn't wired up" problem.** Typing "proceed" now calls `get_project_status`, sees Phase 1 done and evidence present, runs Phase 2 itself, and reports real numbers — verified end to end.

**Per-step download + override.** Every phase pane has a `PhaseActionsBar`:
- `POST /export-phase/{1..4}` — one workbook per phase; `POST /export-rcm` — the working RCM after normalization and overrides.
- `POST /override-rcm` — edit any field offline and re-upload. Applied as **non-destructive overlays**; the original upload stays the audit trail.
- `POST /override-attributes` — re-upload edited attributes; row order is authoritative for IDs, every control is re-run through the quality gate, and already-tested controls are **refused** (their results are keyed to the frozen IDs).

Merge semantics are deliberate (the reference implementation's defaults surprise people): a control absent from the sheet is **left alone, never deleted**; a blank cell means "no change"; only `-` clears a value. And only genuine differences are written — an early version stamped 23 overlay rows for 3 real edits, which would have made the audit trail read as if 23 fields were hand-edited.

### UX pass (2026-08-25)

**Chat persistence.** The transcript was lost on navigating away and back. Two causes: the frontend never called the existing `GET /chat` endpoint, and `pushAssistantMessage` only wrote to React state — upload confirmations and phase summaries never reached the DB at all. Added `POST /chat/messages` plus `listChatMessages()`, and the mount effect now restores the thread (gated on `historyLoaded` so the welcome message can't race the fetch and prepend itself to an existing conversation). Verified: 6 bubbles before navigating away, 5 restored — the one difference is the ephemeral welcome line, which is correctly not persisted.

**Mandatory "Next:" line.** Every agent reply now ends with a concrete call to action. This is enforced twice: as a rule in the system prompt with good/bad examples, and — because a prompt rule is a tendency rather than a guarantee — as `_ensure_next_line()` in the loop, which appends the deterministic hint derived from live project state whenever the model omits it. `ChatBubble` renders `**bold**` inline (it was showing literal asterisks) and styles the closing line as a highlighted call-to-action.

**Attach menu.** The paperclip now opens a menu with **Attach file** and **Attach folder** rather than guessing the upload mode from the active phase. Files route by extension, not phase — so an SOP can be attached while sitting on Phase 1, which the old phase-guessing made impossible.

**Visual system.** All charts moved onto ControlIris's pastel family (`#dbeafe` / `#dcfce7` / `#fef9c3` / `#fee2e2`, plus violet/teal/sky), each pastel paired with a saturated "ink" tone so values stay legible on the tint. Added: staggered card entrances, a gauge that sweeps and counts up together, donut arcs that draw on mount, heatmap cells that cascade in, and bars that grow from zero. Every chart element raises a floating info card on hover (`useHoverCard`) — the heatmap's lists the actual control IDs in that cell. The card renders through a portal with `position: fixed` because one anchored inside the data pane gets clipped by its `overflow: auto`. All motion is disabled under `prefers-reduced-motion`.

**Follow-up verification pass.** A stricter re-test (comparing exact chat text before/after a round-trip, rather than counting bubbles) caught four things the first pass had missed:
- `onResultsReady` did `void result` — it **discarded the phase output entirely**, so a phase run from chat updated the sidebar but left the right-hand pane blank until a reload. Now pushes into the matching pane and switches `activeStep`. Also wired the previously-unhandled `attributes_ready` / `artifact_ready` events.
- UI-generated messages (upload confirmations, phase summaries) had **no `**Next:**` line** — they bypass the agent, so the backend guarantee didn't cover them. `pushAssistantMessage` now appends a client-side hint.
- That client hint keyed off the `project` snapshot, which is fetched once on mount and never refreshed — producing stale advice ("attach your evidence folder") after the evidence was already in. Now derived from the loaded phase results.
- `Critical` — the most severe risk rating — rendered **neutral grey** while `High` was red, because it wasn't in the badge map. Added a distinct `critical` variant above red.

- **Remaining known gaps**: framework packs (SOX/ITGC/ISO yaml); the remediation *window* (re-upload corrected evidence for failed controls and re-test — only the priority list exists today); the cross-engagement attribute reuse library; `remap_column` for correcting a bad RCM column mapping in place (the RCM override sheet covers field values, not header mapping); and the optional sampling engine. `StepProgressBar.tsx` is built but never rendered. Chat history is persisted to `chat_messages` but not reloaded on page refresh. Agent playbooks (embedding-retrieved few-shot examples) were not built — the system prompt carries the rules directly instead.

**Route-naming gotcha:** attribute preview/approve use `/attributes-preview` and `/attributes-approve` (hyphen), not `/attributes/preview`. A literal path segment under `/attributes/` would be shadowed by `POST /attributes/{control_id}` (add_attribute) and silently rejected as a malformed add-attribute request — which is exactly what happened before the rename.

### Screenshot-driven UX round (2026-08-25)

Fourteen items reported against the running tool. Four had root causes worth recording:

**Empty Phase 2 export was a race, not a data bug.** The exported workbook had headers and no rows, while the stored result held all 12 controls. The evidence-folder upload resets the phase-2 row to `status='pending', result='{}'` *in place*, and `export-phase` only checked that a row **existed** — so an export taken inside that ~24-second window produced a header-only file and recorded it as a legitimate artifact with HTTP 200. Fixed at both ends: the export now requires `status='done'` **and** a non-empty result (409 otherwise, which reads correctly as "retry once the run finishes"), and the upload keeps the previous result while flipping only the status, closing the window rather than just guarding it. `export_final_report` read all four phase rows with the same `result or {}` pattern and had the identical hole.

**Stale "Next:" lines came from reading React state that hadn't committed.** The agent kept saying "Attach your RCM file" after the RCM was loaded. `pushAssistantMessage` derived its hint from `phase1Result`, but every caller invokes it immediately after `setPhase1Result(...)` — React batches updates, so the closure still saw `null`. Callers now pass the freshly-returned result explicitly (`{ p1: res.result }`), with a `{ none: true }` escape for transient "…running now" messages. The backend applies the same restraint in reverse: `_blocking_action_hint()` returns `None` unless the workflow is genuinely blocked on the user, and `_ensure_next_line()` **strips** a line the model added when nothing is owed, rather than only appending one when it's missing.

**No timeout on any of the nine AzureOpenAI clients — and the first fix made it worse.** Attribute generation hung past 15 minutes with its progress frozen at 0/3 and nothing in the log. Adding `timeout=` with `max_retries=2` did not help: the SDK retries on timeout *silently*, so a call that legitimately takes ~45s was multiplied by this engine's own 3 attempts across a 3-stage pipeline. Bounds now live in `llm_utils` (`LLM_TIMEOUT_SECONDS=120`, `LLM_MAX_RETRIES=1` — deliberately below the SDK default of 2), and `attribute_engine` passes `max_retries=0` so every attempt is logged and counted in exactly one place. Measured after the fix: 44s per schema call, 4 attributes, 5 worksteps.

**Verifying long LLM phases through one browser session doesn't work.** Chromium drops multi-minute in-flight requests with `ERR_NETWORK_IO_SUSPENDED`, which surfaces as "⚠ Failed to run adequacy assessment" even though the backend returned 200 and wrote a complete result. Check the DB and backend log before believing a client-side failure, and drive late phases from a project whose earlier phases are already `done`.

The rest were presentation fixes: a three-dot typing indicator captioned with the tool actually running; the pane no longer jumps to the next phase the moment one finishes (it advances when the user asks); per-control progress during attribute generation, polled from a new `attributes-progress` endpoint; missing-fields and missing-documents rendered as collapsible per-control rows with per-document icons instead of comma-joined paragraphs; timeline sufficiency drawn as an actual timeline against the audit period rather than a date table; evidence bars moved to pastel fills with hover cards; the always-empty Mismatches column now rendered only when some control has mismatches, alongside a joined Design Verdict column; `approved` added to the badge map (it was falling through to neutral grey); "Approve" echoed into the transcript from the user's side; the "Top Exposure" card removed (it rendered the literal word "other" for RCMs with no `control_type`); and chat pinned to vertical-only scrolling with `overflow-wrap: anywhere`, since long filenames were widening the whole transcript.

### Phase 2 evidence dashboard (2026-08-26)

Two panels added to the top of Phase 2, from a supplied mockup: an **evidence coverage grid** (every expected document per control, filled = received, hollow = never arrived) and an **escalation funnel** (how the population narrows to the controls that block sign-off). Escalated-gap cards were restyled to the mockup's shape — control ID, shortfall bar, severity chip.

**The grid's columns are derived, not fixed.** The mockup shows six fixed columns (SOP, EXEC LOG, SIGN-OFF, SOURCE, RECON, EXCEPTION), but `required_documents` is free text generated per control and its length varies (3 for one control, 6 for another in real payloads). Hardcoding six columns would either drop real documents or invent empty cells. Each document is instead classified into a stable category from its own wording, and **only categories actually present in that engagement become columns** — so a run with no reconciliation documents simply has no RECON column rather than a column of fabricated blanks.

**Four cell states, after a verification pass found two states were not enough.** `received` (every expected document of that kind arrived), `partial` (some did, some did not), `missing` (none did), and `n/a` (the engine expected no document of that kind for this control). Collapsing `partial` into `missing` made a control that supplied 3 of 4 documents look identical to one that supplied none.

**The `n/a` state also needed a guard.** Categories are derived per control, so a category absent from one control's list rendered as a neutral empty cell — which reads as "not required". For a control that received *nothing*, that is the opposite of the finding: CTRL-003 scored 0% with all 6 documents missing, yet showed two reassuring `n/a` cells. Rows with zero coverage now carry an explicit **NO EVIDENCE** flag beside the control ID.

**Palette:** the mockup's purple is replaced with KPMG blue (`--blue-3`, verified as `rgb(37, 99, 235)` in the rendered DOM), and the funnel's dark card uses the brand navy gradient rather than a purple-black.

**Nothing is hardcoded**, and this is asserted rather than assumed: the test intercepts the real `/phases/2` response and compares it against the rendered DOM. The decisive assertion is `cell_states_match_api`, which **rebuilds the entire expected grid independently from the payload** — re-running the classifier, the bucketing and the state logic in the test — then compares cell by cell. An earlier version only counted hollow cells, and passed while a 0%-coverage control displayed neutral `n/a` cells. Counting a category of element is not the same as verifying what it says. 16/16, zero console errors.

Two layout bugs the data assertions could not catch, found by reading the screenshot: the score column clipped `83%` to `83`, and `.funnel-title` inherited `.pane-subsection h4`'s dark colour, rendering the title invisible on the navy panel. Both now have their own assertions.

### Screenshot round 2 + verification pass (2026-08-26)

**The attribute-generation blocker was a one-line encoder bug.** `_sse()` in `chat.py` called `json.dumps` without `default=str`, and `ControlAttributesResponse.updated_at` is a `datetime` — so the `attributes_ready` event raised "Object of type datetime is not JSON serializable" mid-stream and the generator looked broken. Fixed in the encoder, not at the call site, so no future event payload can hit it.

**ControlIris study (read-only).** Our 3-stage draft → critic → repair pipeline already matches `TOD_Engine.generate_schema()`. Two findings worth recording: (a) ControlIris passes only 8 control fields and deliberately omits `risk_description`/`risk_level`, which ours includes — we are ahead of the reference, not behind; (b) **it is fast because of caching, not batching** — there is no multi-control batching anywhere in its attribute generation. It caches schemas by Control ID, which means it pays full price for two controls with identical text; we key our dedupe on the prompt inputs instead and collapse those.

**COSO / COBIT / IFC do not exist as a testing framework in ControlIris** — they appear only in web-search tool descriptions and prompt prose, with zero references in its export code. There was no framework-driven workpaper format to port, so the existing report was extended to 9 sheets with a Remediation Plan instead.

**What the follow-up verification caught** (the first pass claimed more than it had tested):
- "Emoji replaced with icons" had only covered the Phase 2 pane. A full-page sweep found `⚠` in the Phase 1 pane and in **21 chat error messages** — the earlier check only scanned the data pane, so it could never have seen them. Errors now carry an `[error]` marker rendered as a lucide icon with a red bubble edge.
- **Status badges had no border at all**, so pale variants dissolved into the tinted pane — the most widespread instance of the exact problem reported. Now `border: 1px solid currentColor`, which ties each badge's edge to its own ink with no per-variant rule.
- `.status-badge-neutral` and the sample-attribute chips still used the pre-tint `#eef1f6`, now within a point of `--pane-bg`.
- **Two `.hover-card` portals mounted at once** in the Phase 2 pane — one `useHoverCard()` hook but `{card}` rendered twice. Surfaced only because a strict-mode locator refused the ambiguity.
- A 0% evidence bar rendered nothing at all, reading as "no data" rather than "scored zero". Zero scores now keep a 3px sliver.

**A note on stale-history assertions.** A `no_zero_stats` check failed against a message persisted *before* the fix. Confirmed as a false alarm two ways: by exercising `summarizeCounts` directly, and by driving a fresh upload end-to-end ("1 organized into samples, 1 with evidence but no sample structure and 1 with no evidence" — zeros dropped). Transcript assertions must be scoped to messages generated after the change, or they test history rather than behaviour.

### Delete project (2026-08-25)

`DELETE /api/projects/{project_id}` plus a trash icon on each card in `/projects`.

**None of the ten tables referencing `projects(id)` is declared `ON DELETE CASCADE`**, so a bare `DELETE FROM projects` fails on a foreign-key violation. The route clears each child table explicitly from a module-level tuple (`_PROJECT_CHILD_TABLES`), verified against `information_schema` as an exact 10/10 match — a table missing from that list would be a runtime FK error, so re-check it if the schema gains a table.

The ownership check and the deletes share one transaction, with `SELECT ... FOR UPDATE` on the project row so a phase run starting mid-delete blocks rather than writing children back behind it. A project the caller doesn't own returns **404, not 403** — whether another user's project exists isn't something this endpoint should disclose. File cleanup (`delete_project_files`) runs *after* the commit and is deliberately best-effort: orphaned bytes on disk are recoverable, but rows deleted behind a request that then reported failure are not.

The icon is hidden until its card is hovered (a delete affordance on every card at rest invites a misclick on the one irreversible control here) and revealed on `:focus-visible` too, since keyboard users never trigger `:hover`. It calls `stopPropagation` — the whole card is a navigation target, so without that it would open the workspace instead. Confirmation is a modal naming the project and listing what is lost, with a red `danger` button so it never looks like the ordinary primary action.

Verified: 11/11 browser checks (hidden at rest, shown on hover, no navigation on click, confirm names the project, cancel is a no-op, card removed live, removal survives a reload) and an API-level pass covering cross-user delete → 404 with the victim intact, unauthenticated → 401, double delete → 404, and a full-data project (controls, phase results, evidence, attributes, test results, chat) leaving **all 11 tables clean and both storage directories removed**.

### Palette refresh (2026-08-25)

Re-themed to a supplied mockup. Everything routes through tokens in `styles.css`, so the palette is changed in one place rather than per component.

- **Pane distinction.** The chat column is now pure white (`--chat-bg`) and the data pane a cool blue-grey (`--pane-bg: #eef2fb`), with white cards sitting on the tint. Previously both were near-white and the split relied on a 1px border. Verified computed: `rgb(255,255,255)` vs `rgb(238,242,251)`.
- **Sidebar** is a deep indigo→blue vertical gradient rather than flat navy, and the active step is a distinct lighter-blue block with an inset left rule (it was a 8%-white wash, barely visible).
- **Brand blues** brightened one step (`--blue: #0a2472`, `--blue-2: #1e40af`, `--blue-3: #2563eb`); the four hardcoded `#00338d → #005eb8` gradients now reference the tokens, and shadows/focus rings were retinted from the old navy RGB so they harmonise.
- **Charts.** Added `--series-blue/violet/teal` for categorical series: the control-type donut now draws in solid brand colour with round legend dots, while *quantitative* fills stay pastel so values printed on them remain legible. Phase 2's donut deliberately keeps green/red — matched vs missing is semantic, not categorical.
- **Metric cards** dropped the pastel top rule (it washed out to invisible against the tint) — the tone now shows in the value's colour alone.
- **"Next:" callout** gained a ⓘ glyph via `::before`, so it reads as guidance rather than another sentence. Done in CSS, not markup, so every path that renders a `**Next:**` line gets it for free.

**One non-obvious consequence.** Darkening the pane made the empty-track grey (`#eef1f6`) almost identical to the new tint, so unfilled bar/gauge track vanished and the bars read as floating fragments with no scale. Added `--track` / `--track-strong`, applied to the evidence bars, attribute progress bar, timeline track and gridlines, plus the `MiniDonut` and `GaugeRing` background rings (both had the grey hardcoded in the SVG). Worth remembering: **changing a surface colour silently breaks anything tuned to contrast against the old one.**

### API-call optimisation pass (2026-08-25)

A follow-up audit of every LLM call path, aimed at wall-clock time. Four real findings:

**A new AzureOpenAI client was built for every call.** Nine call sites each constructed their own client, and several sat inside per-control or per-sample loops — so every call threw away the keep-alive connection and paid a fresh TLS handshake. Measured at **~1.3s of pure overhead per call** (3.31s → 2.16s). All nine now share one connection-pooled client from `llm_utils.get_llm_client()`, keyed on credential and retry policy (`attribute_engine` keeps its own `max_retries=0` instance because it does its own logged retrying).

A bare `lru_cache` was not enough: it is thread-safe but not thread-*atomic*, and since every engine fans straight out into a `ThreadPoolExecutor`, a cold start had all N threads miss and each build a client. Now a double-checked lock — verified as **1 distinct client from a cold 16-thread start**, where the unlocked version produced 8.

**Sample evaluation was fully sequential.** `test_control` looped over samples one at a time, so the control-level pool was the *only* source of parallelism: a 12-control × 5-sample engagement issued 60 calls but never had more than 4 in flight. Samples now run concurrently (`_CONTROL_WORKERS × _SAMPLE_WORKERS` = 4×4 = 16 peak). Measured **2.5× faster** on samples alone, with sample order preserved for the workpaper and per-sample failures still isolated as `NOT_EVALUATED` rather than counted as deviations.

**Attribute generation was capped at 5 workers.** Raised to 8 to match the other per-control engines. Each worker runs its control's calls in sequence (draft → critic → optional repair), so the width *is* the concurrent-call count rather than a multiplier on it. Measured: **8 controls in 117.5s vs 3 controls in 110.8s** — near-flat scaling, confirming true parallelism. Amortized cost fell from 36.9s to 14.7s per control.

**Two calls were silently truncating.** `sop_adequacy_engine._alignment_for_control` (2000) and `evidence_gap_engine._generate_checklist_for_control` (1500) both hit `finish_reason=length` on real data. This is a correctness bug as much as a cost one: the call burns its full token budget and then falls back — every control silently downgraded to a "partial" alignment verdict, or to the generic checklist. Raised to 3500 and 2500. `llm_utils.parse_json_response` is what surfaced this, which is exactly what it was added for.

Not changed, having been checked and found already sound: `risk_scorer` (3-tier cascade — direct value, then keyword map, LLM only for what neither resolves), `timeline_sufficiency` (filename regex first, LLM only for unresolved names), `rcm_normalizer` (alias match first, one call for leftovers), `find_coverage_gaps` (word-overlap, no API call), and `_attempt_repair` (fires only when the deterministic gate finds issues).

### Post-M6 verification pass (2026-08-25)

A four-angle review of all M5/M6 code found and fixed 10 more correctness bugs. The three most serious would each have produced **wrong audit conclusions**, not errors:

1. **Fixed-30-day bucketing failed perfect monthly evidence.** `timeline_sufficiency` bucketed dates by `days // 30`, so twelve real month-end reconciliations collided into 11 buckets → 92% coverage → `insufficient`. This would have fired on nearly every correctly-evidenced monthly control. Replaced with calendar bucketing (`(year, month)`, `(year, quarter)`, `(year,)`); perfect monthly/quarterly/annual evidence now reads 100% / `sufficient`, while genuinely missing periods are still caught.
2. **A valid evidence layout got silently zero test coverage.** `CTRL-001/sample_1.pdf` (sample-named files, no subfolders — a documented layout) derived no `sample_id`, was stored flat, and then failed the anchored `SAMPLE_FILENAME_RE` because `save_evidence_file` prefixes a UUID. Every such control was classified `invalid_format` and excluded from testing. Sample-named files are now routed into a real `sample_N/` subdirectory.
3. **Infrastructure failures were recorded as control failures.** An unreadable sample or a missing LLM key returned `result: "FAIL"` with every attribute `"No"` — indistinguishable from a real deviation, so a transient outage would manufacture Material Weaknesses across a whole engagement. Added a distinct `NOT_EVALUATED` state that aggregation excludes from the deviation rate entirely.

Also fixed: a mistyped evidence-folder name wiped all existing evidence (now a 422 that changes nothing); `clear_evidence_root` ran outside the transaction, so a failure mid-upload left rows pointing at deleted files (→ false Material Weakness); unknown/missing `control_frequency` reported `sufficient` instead of `undetermined`; a control with zero samples reported "All 0 sample(s) passed" while still counting against the health score; `"Not Tested"` controls sat in the health-score denominator; the conditional-N/A gate only matched the literal `"n/a"`, false-flagging correct `"NA"`/`"Not applicable"` wording; the date parser abandoned a filename after one invalid date instead of trying later valid ones; and a weekly control missing 15 of 52 weeks passed because the daily/weekly branch never let coverage affect status.

**Two UI dead-ends** were also fixed: finishing Phase 4 permanently hid the attribute pane (now a Results/Attributes toggle), and an LLM failure *after* approval left a read-only pane with no buttons at all (schemas now freeze on having **test results**, not on approval, so regeneration remains available).

### Important: reasoning-model token budgets

The configured Azure OpenAI deployment (`gpt-5.2-chat`) is a **reasoning model** — it spends part of `max_completion_tokens` on hidden reasoning tokens *before* emitting any visible output. A budget that looks generous for the expected JSON can still return **empty content** with a normal `finish_reason: "stop"`. Because every call site parsed responses as `json.loads(content or "{}")`, an empty response silently degraded to the same fallback path as a legitimate "no data" answer — so an LLM feature could appear to work while actually never returning real output.

This was found during M5 (a deliberately-planted SOP/RCM frequency mismatch was never being reported) and fixed everywhere: all six LLM call sites now use `engines/llm_utils.py::parse_json_response()`, which logs a warning when content is empty despite a normal finish reason, and every budget was raised (300/500 → 1500-2500). When adding new LLM calls, use that helper and give the budget real headroom.

**Post-M4 verification pass (2026-08-25):** a multi-angle code review of everything built so far (M0-M4) surfaced 6 confirmed correctness/data-integrity bugs, all fixed and re-verified:
- `evidence_gap_engine._severity()` had a gap where a High-risk control with a 50-69% evidence score never escalated — rewritten with complete band coverage (every risk rating escalates below the 50% threshold, severity scales by rating).
- Re-uploading an evidence folder deleted the DB rows but left old files on disk, which `detect_control_test_mode()` would still pick up — added `clear_evidence_root()`, called before every folder upload writes new files.
- The chat SSE error path never emitted a `done` event, so a backend failure mid-stream left the frontend's `isStreaming` flag stuck `true` forever (chat input permanently disabled) — fixed on both ends: backend now always emits `done` after `error` (plus logs the exception server-side instead of swallowing it silently), frontend's `onError` handler now also resets `isStreaming` as defense in depth.
- `Settings` accepted the insecure default `JWT_SECRET` ("dev-secret-change-me") with no guard — added an `ENVIRONMENT` setting; anything other than `development` now refuses to boot if the default secret is still active (verified: blocks in a simulated production config, only warns in development).
- `register()`'s email-uniqueness check was a plain SELECT-then-INSERT with an unhandled race window — added a `UniqueViolation` catch that returns a clean 409 instead of a raw 500 (verified under 5 concurrent duplicate registrations: exactly one 200, four clean 409s, no 500s).
- Evidence-folder upload read every file's bytes into memory before validating the single-root-folder constraint — split into a cheap string-only validation pass followed by the read/save pass, so a malformed multi-root upload rejects immediately without buffering file content. Also added a guard against two differently-cased/spelled folder names silently merging into the same control's evidence set (now rejects with a 422 instead of merging silently).

All fixes re-verified via a full Playwright browser regression run (Phase 1 → Phase 2, zero console errors) plus targeted API tests for each fix. Deferred (real but lower-severity, tracked for a later cleanup pass): duplicated `_require_project` helper across 3 route files, per-file (non-batched) evidence DB inserts, unvalidated `phase` path parameter, CSV uploads always reporting `header_row_index: 1`, chat history never reloading on page refresh, and a blocking (non-threaded) LLM call in the RCM column-matching path that stalls the event loop.

See `/Users/abhaya/.claude/plans/wiggly-hopping-sketch.md` for the full implementation plan and build sequencing (M0-M7).
