# DocGraph V5 — candidate recall and honesty, not ranking

*Deliverable: save this document at the repo root as `D:\code\docgraph\V5_PLAN.md`
as part of execution.*

## Context

V4 shipped a code-tier ranking fix (oversized-whole-file demotion + breadth-first
expansion). The 2026-09-03 gate rerun showed it was a wash: usefulness stayed flat
at 25% (5/20 calls), fixing `legacy-1` while regressing `legacy-11` and `legacy-19`.
Follow-up log-replay experiments (`docs/validation/simulate_target_cap.py`,
`simulate_symbol_reserve.py`) then closed every remaining ranking question, and all
of them pointed the same direction:

- The proposed `CODE_TARGET_BUDGET_SHARE` per-target cap **cannot** fix `legacy-11`
  at any value — the answer sits at position 21 of 26 *within* one target, and a cap
  bounds a target's total without reordering inside it.
- `legacy-10`/`legacy-19` were never ranking problems: 79 and 491 tokens of code-tier
  room respectively, after the seed/co-location tiers spent the budget. 6 of 20 calls
  get <500 tokens of code-tier room; 12 of 20 get <2000.
- A symbol-tier reserve **can** make a symbol target outrank a filename fallback
  (≥70% of code-tier room on `legacy-7`) — but the pack still isn't useful, because
  the real answer for that task lives in `src/trading_env.py`, which was **never a
  candidate at all**.

A second corpus (`D:\code\audio` — no git, no `docs/`, ~10 disconnected sibling
subprojects) then exposed the same shape from a different angle: 38 of 42 possible
code refs came back `ambiguous` (only 4 resolved), and a subproject with zero
`code_ref` edges answered file-specific questions with irrelevant boilerplate rather
than admitting it had no code-linked context.

**Through-line: ranking only reorders the candidate pool. Every remaining failure is
about what gets *into* that pool, and about not signalling when the pool is empty.**

### The numbers that set V5's scope

Measured against rl-stocks (74 docs) during planning, read-only:

| Finding | Measurement |
|---|---|
| Ambiguous mentions dropped entirely | **180** |
| …that a shallowest-path tiebreak would resolve | **171 (95%)** |
| Docs discarded whole by `MAX_CODE_REFS_PER_DOC=10` | **5** |
| Doc→code edges lost to that hub skip | **96 of 190 resolvable (51%)** |

Concretely, `src/trading_env.py` fails to become a candidate for *two* independent
reasons at once: a `staging/src/trading_env.py` copy makes every bare
`trading_env.py` mention `ambiguous`, and the three docs that map it most directly
(`CLAUDE.md` 19 refs, `CONTEXT_MAP.md` 16, `context-map.md` 36) are each hub-skipped
wholesale. The docs whose entire purpose is mapping docs→code are precisely the ones
the hub rule throws away.

**Design correction found during planning:** subtree scoping alone does *not* fix
rl-stocks. Its docs live in `docs/` or at root while code lives in `src/`/`scripts/`,
so a "same top-level directory" scope finds nothing and falls through to today's
repo-wide behavior. Scoping fixes the `audio/` cross-project case; the **depth
tiebreak** is what fixes rl-stocks. V5 needs both, as ordered rules.

## Workstream 1 — Tiered basename disambiguation

**File:** `src/docgraph/code_refs.py::resolve_code_ref` (L55-76), plus its docstring
(L56-63) which currently documents the two-step contract. Sole call site:
`src/docgraph/index.py` L308-309 — **no signature change needed**; the source doc's
subtree is derivable from the existing `source_path` argument.

Replace the single repo-wide basename fallback with an ordered rule set, first match
wins:

1. **Exact relative path** — unchanged (L65-68).
2. **Subtree-scoped basename** — filter `known_code_paths` to those sharing
   `source_path`'s top-level directory; exactly one match → resolved; two or more →
   apply the step-3 depth tiebreak *within that scope only* (a tie stays ambiguous, and
   resolution never escapes the scope into another subproject — "no edges beats wrong
   edges"); zero → fall through to step 3 repo-wide. Fixes the
   `audio/` case (`web-audio-app/FEATURES.md` → `web-audio-app/src/...`). Root-level
   docs (`base == ""`) have no subtree and skip this step — this is load-bearing:
   `tests/test_index_and_retrieval.py::test_ambiguous_code_basename_creates_no_edge`
   (L61-69) is exactly that shape and must keep passing unchanged.
3. **Repo-wide basename with shallowest-path tiebreak** — among basename matches,
   if exactly one sits at the minimum path depth, resolve to it; a tie at minimum
   depth stays ambiguous. Fixes `src/trading_env.py` (depth 2) vs
   `staging/src/trading_env.py` (depth 3), and 171 of 180 ambiguous mentions overall.
   Rationale consistent with the codebase's "no edges beats wrong edges" bias: a
   canonical top-level location beating a nested copy is a defensible rule, and a
   genuine tie still yields no edge.
4. Otherwise `ambiguous` / `dead`, unchanged.

**Instrumentation (required, not optional):** add counters distinguishing
`resolved_exact` / `resolved_scoped` / `resolved_depth` / `ambiguous` in
`_build_code_edges` (counters at `index.py` L301, returned dict L433-438), surfaced
through `build()` (L112-126) and the CLI print (L503-509). Without these the fix
can't be measured against the 38/42 `audio/` baseline.

**Add the first unit test for `resolve_code_ref` in isolation** — none exists today.
Cover: exact hit, scoped hit, depth tiebreak, tie-at-min-depth stays ambiguous,
root-doc skips scoping, and scoped-multi (`proj/a/utils.py`, `proj/b/x/utils.py`,
root `utils.py`, doc in `proj/` → `proj/a/utils.py`, never the root copy).

## Workstream 2 — `MAX_CODE_REFS_PER_DOC` hub rule (coupled to WS1, do not skip)

**Audit correction (2026-10-03, read-only replay of WS1's rules on rl-stocks):** the
original premise here — that WS1 pushes more docs over the hub threshold and raises the
51% loss — did not hold. Hub-skipped docs stay at 5 → 5; edges lost go 96/190 (51%) →
104/258 (**40%**): the count rises slightly but the ratio falls. audio/: 1 → 1 hub doc.
WS2 is therefore **decoupled from WS1** and not a ship blocker; its diagnostic ships with
WS1's instrumentation commit, and the decision below is measure-then-decide.
Caveat: the root `CLAUDE.md` negative control in `link_fixtures.json` passes *only*
because `CLAUDE.md` is hub-skipped (19 resolved targets, 20 after WS1). Any WS2 outcome
that un-skips it must re-decide that fixture.

The skip-not-truncate principle is deliberate and documented (`CLAUDE.md`), so this
workstream is **measure-then-decide**, not a predetermined change:

1. Add a diagnostic to the index run reporting, per hub-skipped doc, how many
   distinct resolved refs it had (the data already exists at `index.py` L346-354).
2. Re-measure hub-skip loss after WS1 lands.
3. Then choose between: raising the constant, exempting docs whose bucket/name marks
   them as maps (`CONTEXT_MAP.md`-shaped), or keeping the rule and accepting the loss.
   Record the decision and its evidence in `docs/V4_NEXT_STEPS.md` regardless of
   outcome — an unchanged rule with a measured justification is a valid result.

## Workstream 3 — Weak-pack confidence signal

**Files:** `src/docgraph/context.py::retrieve` (return dict built L418-425) and
`_render` (header block L479-482).

Add a `confidence` (or `weak`) key to `retrieve()`'s returned dict, and one extra
line in `_render`'s header after the existing summary line. Everything downstream
keeps working: the MCP tool (`mcp_server.py` L30-52) returns a plain string and
nothing parses `_render`'s output; `serve.py` JSON-dumps the dict and its template
only reads known keys, so a new key is inert.

Signal inputs already available inside `retrieve` before L418: `query_used == "OR"`,
seed count, whether every selected chunk is `provenance == "seed"` (no link/code_ref/
neighbor support), and bm25 `score` magnitudes in `meta`.

**Important caveat to design around:** `query_used` alone under-detects the failure.
It is `"AND"` even when AND matched a single weak seed, and no field currently records
seed count or score. The `live-audio-player` case that motivated this was OR-matched
(so `query_used` catches it), but an AND-match on one generic doc would not be
flagged. Base the signal on *absence of non-seed support* + seed count, not on
`query_used` alone.

If the field should appear in the query log, add it to `_log_query`'s explicit
whitelist (`context.py` L447-462) — it does not propagate automatically.

**Nothing currently tests `_render` or `build_pack` output text at all** — add the
first such test alongside this.

## Workstream 4 — `code_tier_room` instrumentation

`code_tier_room` = `budget` − Σ `token_est` of selected chunks with
`provenance != "code_ref"`. It is the confound under every per-tier precision number
in the validation report and is currently only recoverable by replaying logs by hand.

- **Compute it in `retrieve()`** at `context.py` L418-425 (not in `_log_query`), so it
  reaches the structured return, `serve.py`'s `/context` JSON, and the log alike —
  the same reasoning the existing comment at L368-372 gives for `budget_cut`. Then add
  it to `_log_query`'s whitelist (L447-462).
- **Read it defensively** in `validation.py::summarize` (L143-231) via
  `entry.get("code_tier_room")` — the existing
  `docs/validation/rl-stocks_query_log_v2.jsonl` predates the field.
- **Render it** in `render_summary` (L234-257) as a bullet in the L235-249 list, not a
  new table column. If it must be a column, the separator row at L248 must gain a
  column too — easy to miss and it silently breaks the markdown table.
- **Test fixture gotcha:** `tests/test_validation.py::_entry` (L16-20) builds log
  entries with no `budget` and no `token_est`, so any code reading `entry["budget"]`
  will KeyError. Use `.get()` with defaults or extend the helper.

## Validation gate

Re-run the existing 20-call rl-stocks set **and** the `audio/` corpus. Reuses
`DOCGRAPH_QUERY_LOG` + `python -m docgraph.validation report` exactly as the V4 gate
did (recipe: `docs/validation/RL_STOCKS_VALIDATION_NOTES.md` L206-223).

Pre-register these bars before running:

1. **rl-stocks must not regress** below the current 25% (5/20) pack-level usefulness.
   Log to `rl-stocks_query_log_v3.jsonl` so v2 stays the baseline; annotate the same way.
2. **`audio/` ambiguity must fall materially** from the 38-ambiguous / 4-resolved
   baseline. Report the new counter breakdown from WS1.
3. **Hub-skip loss must be re-measured** post-WS1: the *ratio* (lost / resolvable
   distinct edges) must not exceed the current 51% (96/190); report absolute counts
   alongside. (Replay predicts ~40%, 104/258.) If the ratio rises, WS2 must act first.
5. **legacy-7 (`observation_space`), scored in two parts.** (a) *Recall* — `src/trading_env.py`
   appears in the call's `chunks` or `budget_cut` with provenance `code_ref`; this is the
   WS1 pass criterion. (b) *Selection* — whether it was selected, plus the call's
   `code_tier_room` (WS4); reported, not gated. (b) is **expected to fail at 8000 tokens**:
   `observation_space` lives in chunk `TradingEnv > __init__` (position 13 of 21, ~2169
   tokens), larger than the call's ~1797-token code-tier room. That is a known
   room/position limit, not a WS1 regression.
4. **The `live-audio-player` case must now flag itself** — same two queries
   ("how does App.jsx render the audio player", "what does main.jsx do") must carry
   the WS3 weak signal.

Also run the existing suites: `python -m pytest tests/`, plus
`python tests/run_link_fixtures.py` and `tests/run_code_fixtures.py`. Watch the
`link_fixtures.json` `code` bucket's **`CLAUDE.md` negative control** specifically —
it is protected by the hub skip (19+ resolved targets), not by an absence of refs, so
WS1 cannot flip it (replay: 19 → 20 targets, still skipped); it is a WS2 tripwire. If it
flips, investigate rather than update the fixture.

## Execution order

WS1 (with WS2's per-hub diagnostic folded into the same instrumentation commit), then WS4
(instrumentation makes the gate legible), then WS3 (independent, no interaction with
the others), then the gate. Update `docs/V4_NEXT_STEPS.md` and `docs/HANDOFF.md` with
results — including negative ones — the same way the V4 gate reruns are recorded.

## Explicitly out of scope

**Recorded, not changed:** retrieve-time `MAX_CODE_NEIGHBORS_PER_SEED=5` with
alphabetical `ORDER BY target` truncates more once WS1 adds targets (replay: 1 seed/1
target dropped → 4 seeds/6 dropped, e.g. `TIER2_EXECUTION_PLAN.md` loses `trading_env.py`).
Report the count at the gate; don't act on it yet.

No new edge kinds (import parsing, symbol-name prose matching). No further in-tier
ranking changes — the cap, the reserve, and symbol-first `ORDER BY` are all settled
and none of them move usefulness. Revisit only if V5's recall work changes the
candidate pool enough to make ordering matter again.
