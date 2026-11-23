# V4 Next Steps

## Current implementation

V3/V4 graph plumbing is present on `main`:

- referenced code files are surfaced as extension-colored `bucket='code'` nodes;
- directional doc-to-code `code_ref` edges are present in static and live graphs and rendered purple;
- Python code is sliced at def/class boundaries and may use bounded, intra-file `symbol` edges;
- JS/TS/Go/Rust are explicit whole-file fallbacks.

The graph remains file-level. Clicking a code node does not yet expose its chunks or internal symbol edges.

## Validation gate — run 2026-08-25, corrected 2026-08-25

20 real calls against the rl-stocks corpus, logged via `DOCGRAPH_QUERY_LOG`
and annotated per-chunk (used/unused/uncertain) with `src/docgraph/validation.py`.
Full results, per-tier evaluation, and a list of corrections applied after
review: [validation/RL_STOCKS_VALIDATION_NOTES.md](validation/RL_STOCKS_VALIDATION_NOTES.md).

An earlier version of this section reported *exposure* (85% of calls had a
selected `code_ref` chunk) as if it were *usefulness*. With real per-chunk
annotation the actual usefulness rate is 25% of calls (5/20, `decision:
keep_or_tune` against the 15% threshold) — clears the gate, but on thin
margin: only 8 of 115 selected `code_ref` chunks (7%) were judged actually
used. Outcome per tier:

1. filename-only `code_ref` — 25% of packs have a used chunk (7% of
   individual chunks), **keep, but tune** — clears the threshold but most
   of what it selects per pack is unused filler.
2. symbol-resolved `code_ref` — 0% of packs, never once selected across 20
   calls, **candidate for removal**.
3. symbol-neighbor expansion — 0% of packs (never reached), **candidate for removal**.
4. useful chunks displaced into `budget_cut` — confirmed twice (not once):
   `src/exit_manager.py` lost its slot to an unrelated whole-file chunk;
   separately, `generate_rollback_guide` lost its slot in one call to a
   same-file `utc_now()` helper, then *was* selected for a near-identical
   rephrased task in the next call — proving the miss is an ordering
   artifact, not a retrieval gap. Full `budget_cut` review (787 candidates)
   is not done; only 15 were reviewed.

   Correction (2026-08-28/09-03): the `exit_manager.py` miss was originally
   attributed to alphabetical `ORDER BY target` alone. The real mechanism,
   found while investigating a fix: `scripts/analyze_reward_divergence.py`
   is 444 lines with zero top-level `def`/`class`, so the code slicer can't
   split it — it lands as one indivisible 4413-token chunk (~55% of an
   8000-token budget in a single bite), admitted first purely because it
   sits earlier in target order. Alphabetical order picked which target
   went first; it's the chunk's unsliceable size that made winning that
   slot catastrophic for the other target.

## Ranking fix shipped (2026-09-03)

Two changes landed in `src/docgraph/context.py`, replacing the "Not yet
done" item above:

1. **Oversized-whole-file demotion.** A whole-file code chunk
   (`heading IS NULL`) whose token count exceeds
   `OVERSIZED_WHOLE_FILE_BUDGET_FRACTION` (0.25) of `max_tokens` gets a
   rank penalty (`+0.5`, sorts after all normal chunks in the same seed's
   code band, never spilling into the next seed's band). This is a
   demotion, not a hard cap or a trim — it only defers the chunk to the
   back of its own tier. Small preambles and all symbol chunks (`heading
   NOT NULL`) are exempt: size alone isn't grounds to demote a named
   function, which is often exactly the answer.
2. **Breadth-first `k`-major expansion.** The rank formula's axes were
   swapped so all targets' position-0 chunk outranks any target's
   position-1 chunk, round-robin across targets, instead of one target's
   whole expansion group finishing before the next target gets a chunk in.
   This targets the `generate_rollback_guide`-vs-`utc_now()` case: two
   *separate* symbol targets in the *same file* (not two positions within
   one target's group), where target-major expansion let the
   earlier-defined target's slot claim priority regardless of relevance.

**Deliberately not changed:**
- `ORDER BY target` (plain alphabetical) is still the tiebreak for
  cross-file target selection. Symbol-first ordering
  (`ORDER BY (target LIKE '%#%') DESC, target ASC`) was tried and
  reverted — it shifts every later target down one slot, and on rl-stocks
  that pushed `src/exit_manager.py` past `MAX_CODE_NEIGHBORS_PER_SEED`,
  removing it as a candidate entirely.
- `edges.weight` stays hardcoded `1.0`. A mention-count weighting scheme
  was considered and rejected: on the confirmed `exit_manager.py` failure,
  mention count points the wrong way (2 mentions for the unrelated file
  vs. 1 for the correct one).
- No per-target budget-share cap exists. A `CODE_TARGET_BUDGET_SHARE`
  constant with per-path token accounting in the fill loop was proposed
  but never implemented; the fill loop still tracks only a single scalar
  `running` against `max_tokens`.

**Known deferred gap:** an unsliceable large file is now demoted rather
than trimmed, which means at a small enough budget it can become
effectively unreachable (it always defers behind everything else in its
band, and a small budget may never have room left once that band is
reached). This is recorded as a known limitation, not fixed here.

See [validation/RL_STOCKS_VALIDATION_NOTES.md](validation/RL_STOCKS_VALIDATION_NOTES.md)
for the before/after gate rerun this fix motivated.

## Gate rerun after the ranking fix (2026-09-03)

Same 20 rl-stocks tasks re-run against the unchanged `db/rl-stocks.db` (no
reindex needed — the fix is retrieval-only), logged to
`docs/validation/rl-stocks_query_log_v2.jsonl` and annotated the same way as
the first pass. Full detail:
[validation/RL_STOCKS_VALIDATION_NOTES.md](validation/RL_STOCKS_VALIDATION_NOTES.md#gate-rerun-after-the-ranking-fix-2026-09-03).

- **`legacy-1` (ExitManager) flips as intended**: `src/exit_manager.py` is
  now selected; `analyze_reward_divergence.py` (the 4413-token unsliceable
  blob that starved it before) is now budget-cut by the oversized-whole-file
  demotion.
- **`legacy-10`/`legacy-11` (rollback guide) do not flip the way hoped, and
  one regresses**: `legacy-10` still never selects `generate_rollback_guide`
  (a different, tiny, off-topic chunk wins instead — the seed tier simply
  consumed most of the budget first). `legacy-11` is a genuine regression:
  `generate_rollback_guide` *was* selected and used in the first pass for
  this exact call, and is now budget-cut, because breadth-first expansion
  now spreads the budget shallowly across three code_ref targets for that
  seed (a third target, `test_sanitize_apply.py`, is newly in the mix)
  instead of going deep into the one target where the answer sits at
  position 21.
- **`legacy-19` (news integration) also regresses**: `src/news_data.py`'s
  `SentimentResult` — selected and used in the first pass — is now
  budget-cut in favor of `market_data.py`'s interval helpers.
- **Overall usefulness rate is unchanged: 25% (5/20 calls)**, but the
  *composition* changed — `legacy-1` and `legacy-5` (a new plausible hit,
  `src/train_bot.py`, on a GPU-configuration task) became used calls;
  `legacy-11` and `legacy-19` stopped being used calls. The fix traded one
  set of wins for another rather than producing a net improvement.
- **Symbol-resolved `code_ref` is still 0/20** — no symbol-tier chunk was
  ever selected in this rerun either. Expected: symbol-first ordering was
  tried and reverted (see above), so this configuration gives symbols no
  promotion over filename fallbacks. **Caveat, not a clean verdict**: this
  is evidence about *this specific configuration* (breadth-first + demotion,
  `ORDER BY target` unchanged), not proof symbols are inherently useless —
  that question still needs a run where symbols can actually outrank a
  filename fallback before it's answered cleanly.

**Decision**: keep the symbol-resolution tier's code and edges (removal
isn't justified — it's never been tested in a configuration where it could
win), but its "candidate for removal" flag from the first pass stands
un-resolved rather than confirmed. Do not claim the ranking fix as a net
usefulness win; it fixed one confirmed case, left one unrepaired, and
regressed two previously-good ones on this same 20-call set.

## Follow-up experiments (2026-09-03): rollback-guide edge check, symbol-tier reserve

Three open questions from the gate rerun were resolved without touching
`context.py`, using log-replay scripts against `rl-stocks_query_log_v2.jsonl`
(no reindex, no DB access — both scripts read only the log):
[`validation/simulate_target_cap.py`](validation/simulate_target_cap.py) and
[`validation/simulate_symbol_reserve.py`](validation/simulate_symbol_reserve.py).

1. **`CODE_TARGET_BUDGET_SHARE` (the proposed per-target cap) does not fix
   `legacy-11` at any value.** Replaying the code-tier fill under caps from
   0.5 down to 0.2 of available room: `generate_rollback_guide` never wins,
   because it sits at position 21 of 26 in `sanitize_apply.py`'s expansion
   group. A cap bounds a target's *total* tokens; it doesn't reorder
   *within* a target, so 20 same-file chunks still enumerate ahead of it
   regardless of cap value. Only target-major depth (the pre-fix behavior)
   reaches it. **Decision: don't build the cap.**

2. **`legacy-10` and `legacy-19` were never code-tier ranking problems.**
   Computing `code_tier_room` (budget minus non-`code_ref` selected tokens)
   per call: `legacy-10` had 79 tokens of room left for code, `legacy-19`
   had 491 — both after the seed/co-location tiers had already spent
   essentially the whole budget. No amount of in-tier reordering or
   per-target capping can matter when the tier's total room is smaller than
   the answer. This generalizes: 6 of 20 calls in the v2 log get <500 tokens
   of code-tier room, 12 of 20 get <2000. **Follow-up**: `code_tier_room`
   should become a first-class field in `validation.py`'s report — it's the
   confound under every per-tier precision number, and right now it's only
   derivable by replaying the log by hand.

3. **Rollback-guide `code_ref` edge is not a resolution bug.**
   `SANITIZE_APPLY_GUIDE.md` mentions "rollback guide" only in prose
   ("Generates rollback guide", "Provides full rollback guide") — never
   `generate_rollback_guide` in backticks. The edge that does surface the
   function exists only because the doc separately backtick-mentions
   `sanitize_apply.py` by filename, and the function falls out of that
   whole-file/symbol expansion by position. Per the "keywords never touch
   code" invariant, `legacy-10`/`legacy-11` are **structurally undecidable**,
   not a bug to chase with more resolution logic.

4. **Symbol-resolved `code_ref` CAN outrank a filename fallback when given
   enough room — but that doesn't make it useful.** A symbol-tier budget
   reserve was replayed against `legacy-7` and `legacy-10` only (the two
   calls where a symbol group exists in the log): at a reserve ≥70% of
   `legacy-7`'s code-tier room (≥1258 of 1797 tokens — enough to fit both
   the preamble and `_run_ensemble`, 1136 tokens combined), the symbol
   target wins the slot for the first time in any configuration tested.
   Below that threshold, it loses twice over: it doesn't fit its own
   reserve, *and* falls back to losing a rank-order contest against
   unrelated targets' filename-tier chunks. **But it isn't a useful hit**:
   `run_exp9_walkforward.py` never mentions `observation_space` at all — the
   real answer for that task lives in `src/trading_env.py`, which was never
   a `code_ref` candidate to begin with. Winning the slot only proves the
   ordering mechanism *can* work; it doesn't touch the actual gap (the right
   file never became a candidate). `legacy-10`'s symbol group (740 tokens)
   exceeds even its full 79-token code-tier room, so no reserve fraction
   changes that call's outcome — reconfirms finding 2 unconditionally.

**Revised decision**: the symbol-resolution tier's "candidate for removal"
question was never really about tier ordering — proven reachable, but the
one case that reaches it doesn't produce a useful pack because the
candidate pool itself is missing the right file. Do not chase further
in-tier ordering changes (cap, reserve, symbol-first `ORDER BY`) expecting a
usefulness improvement; any further work here should target *candidate
recall* (why `trading_env.py` never became a `code_ref` candidate for a
task about its own observation space) rather than ranking.

## Second-corpus validation (2026-09-03): `D:\code\audio`

Indexed and queried against a structurally opposite corpus to rl-stocks: not
a git repo, no `docs/` directory, ~10 disconnected sibling subprojects
(Vite scaffolds, an audio visualizer, FL Studio notes) rather than one
coherent codebase. Full corpus (`db/audio.db`, 8 markdown docs after bucket
filtering and content-hash dedup) and an isolated single subproject
(`D:\code\audio\live-audio-player`, `db/live-audio-player.db`, 1 doc — the
unmodified Vite boilerplate README) were both tested.

1. **Basename-collision ambiguity scales badly across a directory of
   unrelated sibling projects.** `_discover_code_files` builds its candidate
   pool via `rglob` across the *entire* repo root, and `resolve_code_ref`'s
   basename fallback matches globally against that pool. On `audio/`, 42 of
   134 discovered code files (31%) share a basename with an unrelated file
   in a *different* subproject (`main.jsx` ×4, `vite.config.js` ×4,
   `AudioPlayer.jsx` ×3, etc.) — 38 of 42 possible code refs came back
   `ambiguous`, only 4 resolved. This failure mode never appears on
   rl-stocks (one coherent project, no basename collisions). **Not fixed
   here** — recorded as a real generalization limit: basename-fallback
   resolution assumes repo-wide basename uniqueness, which holds for a
   single project but not a directory of independent siblings.

2. **Tier starvation reproduces on a second, unrelated corpus.** Querying
   "how does the web audio player playlist manager work" at
   `--max-tokens 4000`: `FEATURES.md`'s own seed-tier sections consumed
   nearly the whole budget, budget-cutting the `code_ref` edge to
   `PlaylistManager.jsx` — which exists and is exactly on-topic. Raising the
   budget to 12000 surfaces it cleanly (6958 of 12000 tokens used). Same
   mechanism as `legacy-10`/`legacy-19` above, now confirmed independent of
   corpus — strengthens the case that this is systemic tier-share behavior,
   not an rl-stocks artifact.

3. **With zero `code_ref` edges, retrieval silently falls back to
   irrelevant prose instead of surfacing "no code-linked context available."**
   On the isolated `live-audio-player` subproject (1 doc, the generic Vite
   README, no filename backtick-mentions anywhere so 0 code_ref edges),
   querying "how does App.jsx render the audio player" and "what does
   main.jsx do" both returned the identical 213-token boilerplate README
   chunk (OR-matched on generic words like "React") with no indication
   either file was even considered. Because code chunks get no `docs_fts`
   row and are only reachable via a `code_ref` edge (see `CLAUDE.md`'s
   doc→code section), a corpus with no doc-to-code backtick mentions makes
   the entire source tree structurally unreachable no matter how
   specifically a task names a file — and the tool returns a plausible-looking
   but wrong answer rather than an empty or flagged one. Worth deciding
   whether `build_pack`/`docgraph_context` should surface a low-confidence
   signal when a pack's only chunks are weak OR-fallback matches with no
   code_ref/link/co-location support at all — not attempted here, this run
   only surfaces the gap.

## Next UX work, after the gate

1. Add independent visibility toggles for `code_ref`, co-location, and structural edges; purple code edges can clutter large graphs.
2. Label or arrow directional edges so `code_ref` does not read as undirected.
3. Add extension, discovery-bucket, and connected-component filters.
4. Decide from observed demand whether clicking code nodes should reveal code chunks and internal symbol edges; consider edge bundling only afterward.

## Durability and test prerequisites

See [TESTING.md](TESTING.md) for the fixture corpus requirement and the important distinction between skipped and passed external fixtures. See [INDEXING.md](INDEXING.md) for rebuild/freshness behavior and [ARCHITECTURE.md](ARCHITECTURE.md) for the durable V2–V4 design.
## V5 WS1 implemented (2026-10-03): tiered basename disambiguation

`code_refs.py::resolve_code_ref_detailed` replaces the repo-wide
unique-basename fallback with ordered rules — exact path → unique basename →
subtree-scoped (shallowest-path tiebreak *within* the scope, never escaping it)
→ repo-wide shallowest-path tiebreak; a tie stays ambiguous. `resolve_code_ref`
remains as a 2-tuple wrapper. `index.py` now reports per-method counters and
lists hub-skipped docs, and writes two diagnostic-only tables
(`code_ref_audit`, `hub_skips`; never read by `retrieve()`).

Measured on fresh indexes (`db/rl-stocks-v5.db`, `db/audio-v5.db`; baseline
`db/rl-stocks.db` untouched):

| corpus | exact | basename | scoped | depth | ambiguous | hub-skipped docs |
|---|---|---|---|---|---|---|
| rl-stocks | 107 | 296 | 7 | 165 | 9 | 5 (same 5 as before) |
| audio | 25 | 4 | 38 | 0 | **0** (was 38) | 1 |

- WS2's premise did not hold: hub-skipped docs stay at 5 and the loss *ratio*
  falls (replay: 51% → 40%), so WS2 is decoupled from WS1 (see `V5_PLAN.md`).
- rl-stocks ambiguous is 9 vs the replay's 8 because the counter also includes
  ambiguous symbol matches.
- Gate (rl-stocks 20-call rerun to `_v3.jsonl`, `audio/`, legacy-7 recall) not
  yet run; WS3/WS4 not started.

Visualizer (`visualize.py` / `serve.py`, shared `RESOLUTION_JS`): `code_ref`
edges are colored by resolution method; docs with ambiguous refs get a red
ring, hub-skipped docs a dashed amber ring; edges dropped by the hub rule show
as dotted grey ghost edges (only where the target node exists); tooltips list
per-method counts, ambiguous mentions, and dead refs. Indexes built before
this change render with no findings.

Viewer UI pass (same day), all in the shared `viewer_ui.py`: clickable legend
rows toggle edge kinds, resolution methods and file buckets; `code_ref` edges
carry arrowheads (so direction reads); a file search box (`/` to focus); and
click-a-node opens a pinned detail panel listing every mention with how it
resolved, ambiguous mentions with candidate counts, inbound references for code
files, and the hub-skip note (target links are clickable and re-focus the
graph). Tooltips now position on hover and HTML-escape corpus text.

## V5 gate run (2026-10-03)

Same 20 rl-stocks tasks, same 74 markdown docs, `db/rl-stocks-v5.db` (WS1 index),
logged to `docs/validation/rl-stocks_query_log_v3.jsonl`; annotations in
`..._v3.annotations.jsonl` (**assistant-annotated, not user-reviewed**: v2
judgments carried over for identical chunks, new chunks judged by the same
rubric — the legacy-19 `SentimentResult` "used" call is the one judgment that
moves the rate). WS3 (weak-pack signal) and WS4 (`code_tier_room`) are **not
built yet**, so bar 4 is untested.

| Bar | Result |
|---|---|
| 1. rl-stocks usefulness ≥ 25% | **25% (5/20), met** — composition churned again: legacy-5 lost `src/train_bot.py` (now budget-cut), legacy-19 regained `SentimentResult`; legacy-1/15/16/18 held. If legacy-19 were judged uncertain the rate is 20%. |
| 2. audio ambiguity falls materially | **Met** — 38 ambiguous / 4 resolved → 0 ambiguous (38 scoped). |
| 3. hub-skip loss ratio ≤ 51% | **Met** — rl-stocks 104/258 = 40% (5 hub docs, unchanged); audio 15/24 = 62% (was 15/19 = 79%). |
| 4. live-audio-player flags itself | Not testable until WS3 — **met 2026-11-23**, see below. |
| 5a. legacy-7 recall (`src/trading_env.py` a candidate) | **Met** — selected as preamble/class-preamble chunks. |
| 5b. legacy-7 selection (answer chunk in pack) | **Fails, as predicted** — `TradingEnv > __init__` (2169 tok, holds `observation_space`) is budget-cut against 1797 tok of code-tier room. |

Counters: code files indexed 38 → 46, `code_ref` edges 95 → 157, selected
`code_ref` chunks across the 20 calls 143 → 164, symbol tiers newly exposed in
packs (symbol_target 2, symbol_neighbor 2; still 0 used).

**Finding — recall rose, usefulness did not; the cost is noise from generic
filenames.** `src/experiments.py` now has 19 inbound edges, 18 of them via the
depth tiebreak (it shares a basename with `src/dashboard/pages/experiments.py`,
so every incidental mention used to be dropped as ambiguous). Its small helper
chunks (`_parse_float_list`, `_as_naive_datetime`, …) now appear in 10 of 20
packs as unrelated filler and are what displaced `src/train_bot.py` (legacy-5)
and `agent-api/api/main.py`/`phase1_diagnostic.py` (legacy-16, uncertain in
v2). Same pattern as the V4 ranking fix: a recall win traded against a precision
loss, and `code_tier_room` (<2000 tok in 12/20 calls) remains the binding
constraint. Per-seed cap exposure grew as predicted (4 seeds / 6 targets
dropped by `MAX_CODE_NEIGHBORS_PER_SEED`; was 1 / 1).

audio: at 4000 tokens `PlaylistManager.jsx` is now a candidate but still
budget-cut (tier starvation, unchanged); at 12000 it is selected.

**Decision pending (user):** WS1 meets every pre-registered bar that can
currently be tested, so it should ship; but the filler problem is real. Options,
none chosen: (a) accept, finish WS3/WS4 first so room is measurable; (b) demote
code targets referenced by many docs (a ranking change, outside V5's stated
scope — needs its own evidence); (c) do nothing until a weak-pack signal exists.

## WS3/WS4 and the in-degree demotion replay (2026-11-23)

**WS4 built.** `retrieve()` returns `code_tier_room` (budget − non-`code_ref`
selected tokens); `_log_query` logs it; `validation.py report` prints a
median / under-2000 bullet, reconstructing it for older logs that have
`budget` but not the field. v3 log: median ~1795, 12/20 calls under 2000.

**WS3 built; bar 4 met.** `confidence = {weak, reasons, seed_count,
best_coverage, non_seed_support}`; weak when the best seed chunk covers
< `WEAK_COVERAGE_FLOOR` (0.5) of the task's words (5-char prefix match), when
OR-fallback has no non-seed support, or when nothing matched.

| Set | Result |
|---|---|
| live-audio-player "how does App.jsx render the audio player" | weak (coverage 0.29, low_coverage + or_fallback_no_support) |
| live-audio-player "what does main.jsx do" | weak (coverage 0.25, same reasons) |
| rl-stocks 20 calls | 1 flagged (legacy-3, OR without support); 0 of the 5 used packs flagged; best coverage on the other 19 is 0.62-1.00 |

Known blind spots (Obsidian vault testing): a title-index hub doc can be a
high-coverage sole seed; a lexically-covered but wrong pack is not caught.

**Decision (b) replayed: not supported.** `docs/validation/simulate_indegree_demotion.py`
re-fills each v3 call's code tier with chunks of targets whose distinct-source
`code_ref` in-degree ≥ N moved last (baseline replay reproduces the logged
selection in 20/20 calls). Bars were written into the script before running.

| Variant | Used kept (of 8) | Useful cuts gained (of 5) | Newly selected, unreviewed | ≥8-degree tokens |
|---|---:|---:|---:|---:|
| baseline | 8 | 0 | 0 | 10747 |
| deg ≥ 4 | 7 | 0 | 60 | — |
| deg ≥ 6 | 8 | 0 | 63 | — |
| deg ≥ 8 | 7 | 0 | 54 | 70 |
| deg ≥ 12 | 8 | 1 | 44 | 57 |

- It removes the filler (≥8-degree tokens 10.7k → ~70) but the freed room goes
  to other unreviewed chunks, not to the useful budget-cut ones.
- **The IDF premise is wrong for this corpus:** 3 of the 5 useful budget-cut
  chunks live on high in-degree targets themselves (`train_bot.py` 9,
  `trading_env.py` 10, `sanitize_apply.py` 7). Widely referenced files are
  both the filler *and* where the answers are.
- deg ≥ 4 and ≥ 8 each lose a used chunk; the ≥ 8 loss (legacy-19
  `SentimentResult`, in-degree 1) is a greedy-packing effect — demoting a
  60-token preamble lets a 306-token test file fit first in a 491-token room.
  At small rooms the fill is order-chaotic, so any reordering is noisy.
- deg ≥ 12 passes the bars but is in effect "demote `src/experiments.py`"
  (the only target ≥ 12) and gains one chunk (`train_bot.py`, legacy-5) —
  a single-target fix, too overfit to ship as a constant.

Conclusion: ranking within the code tier is not the lever; the useful chunks
are lost to room (`code_tier_room`), chunk position inside a target, and
greedy skip-fill. Next candidates: a target-relevance signal using the task's
words against code chunk headings (symbol names) instead of corpus-wide degree,
or fixing the depth-tiebreak's `experiments.py` resolution at index time.

## Heading relevance + qualified-path resolution (2026-11-23)

Follow-up to the refuted in-degree demotion. Two changes, evaluated on the same
20 rl-stocks tasks against a reindexed `db/rl-stocks-v6.db`, logged to
`docs/validation/rl-stocks_query_log_v4.jsonl` (annotations carry the rule in
their `note`: **assistant-annotated, not user-reviewed**; identical v3 chunk →
v3 judgment; v3 "useful" budget-cut chunk now selected → "used"; 3 heading-matched
chunks judged after reading their bodies; 13 non-relevant `src/experiments.py`
helpers → "unused"; the last 10 heading-matched, off-topic-by-title chunks →
"unused" **without reading their bodies**).

**A. Index time (`code_refs.py`).** A path-qualified mention no longer falls
into the basename tiers. New methods: `rooted` (repo-root-relative), `suffix`
(known file ends with the qualifier, or — for foreign absolute paths like
`/Users/x/proj/src/a.py` — the longest known multi-segment path the mention
ends with). A qualifier matching nothing is `dead`. Before, `docs/X.md`
writing `src/dashboard/pages/experiments.py` resolved to `src/experiments.py`
via the depth tiebreak (wrong file).

v5 → v6: code_ref edges 157 → 153, code files 46 → 44, resolution
(mentions) exact 107, rooted 204, suffix 28, basename 133, scoped 7, depth 84.
**`src/experiments.py` in-degree is unchanged at 19** — as predicted, most of
its mentions genuinely mean it, so this fixes wrong edges, not the filler.
**Cost:** 4 edges lost, 0 gained — archived docs that name
`scripts/run_*.py` for files since moved to `scripts/archive/`; the old
unique-basename fallback resolved these correctly, the stale-qualifier→dead rule
does not. A "unique basename despite a stale qualifier" fallback would recover
them but also admit invented paths (`backend/app.py` → any lone `app.py`);
left as dead (no edges beats wrong edges). Hub-skipped docs unchanged (5); the
V5 bar-3 *ratio* was not recomputed.

**B. Query time (`context.py`, `CODE_HEADING_RELEVANCE`).** Code chunks are
ordered by how many task word-stems their heading (def/class name, CamelCase and
snake_case split, 5-char prefix; `init/self/main/get/set/run/test` ignored)
shares — more first, from any seed, then unmatched — with breadth-first order,
the oversized-blob penalty and the seed/link tiers untouched. Logged per chunk
as `relevant`. Generic words never count: a stopword list of function words
and task verbs was added after review showed "data" (legacy-19), "one"
(coinbase), "write" (`_write_summary`, 827 tok, legacy-1) and "compute"
(`compute_metrics`) all matching unrelated headings.

Replay (`docs/validation/simulate_heading_relevance.py`; bars written before
the first run; baseline reproduces the logged selection 20/20):

| Variant | Used kept (of 8) | Useful cuts gained (of 5) | Lost used chunk displaced by same-file relevant chunk |
|---|---:|---:|---|
| binary (approved plan) | 7 | 1 (legacy-11) | **No** — a 452-token `_validate_training_data_quality` in `market_data.py`, matched only on the generic stem "data", ate the 491-token room → bar 1 clause 2 **failed** |
| match-count (shipped) | 7 | 1 (legacy-11) | Yes — `aggregate_daily_news_features` (same file) |

The match-count variant was added *after* the binary variant failed on this log,
so its replay is **not out-of-sample**; only the live rerun below is.

**Live rerun (v6, v4 log).**
- Bar 1, usefulness ≥ 25%: **25% (5/20), met** — packs 1, 11, 15, 16, 18.
  legacy-11 gains `generate_rollback_guide` (the v2→v3 regression recovered);
  legacy-19 loses `SentimentResult` (its replacement `aggregate_daily_news_features`
  is unreviewed; judged "uncertain" it would not change the count, judged "used"
  it would make 6/20 — a judgment I did not make). Composition churned again.
- WS3 unchanged: 1 weak call (legacy-3). `code_tier_room` unchanged (median ~1795, 12/20 < 2000).
- ~29 chunks newly selected across ~10 calls; 13 of them non-relevant
  `src/experiments.py` helpers (legacy-2, 9, 17, …) that are **not** from
  relevance: the four lost archive edges freed room that the filler took.
  Of the heading-matched chunks, 3 were read (`aggregate_daily_news_features`
  and `RewardEvaluator > calculate` → uncertain, `_expected_observation_dim` →
  unused) and 10 judged unused from title alone. **None judged clearly used.**
  (An earlier draft of this section said 51 unreviewed chunks; 23 of those were
  co-location `neighbor` chunks the annotation schema doesn't cover.)
- legacy-7 (`TradingEnv > __init__`, 2169 tok) is still budget-cut: no heading
  match for "observation space", and room is ~1797.
- Fixtures: link/code unchanged (only the pre-existing "exit signal todo plan"
  fails); `CLAUDE.md` negative control passes. pytest 61 passed, 7 skipped.

**Second and third corpus (same day).**
- `audio` (JS components, no sliced code): a clean no-op — identical edges and
  identical packs in 20/20 queries with relevance on or off, and baseline-vs-new
  resolver. Shows no regression; gives **no** evidence about the ordering,
  since the heading slicer only handles Python.
- `coinbase-rl-bot` (Python, 87 sliced code chunks), 30 tasks taken from the
  repo's own doc section titles (not code names): 9 change. Plausible wins:
  "Confirmed critical issues" → `find_confirmed_edge`, "Crypto Experiment
  Strategist" → `CryptoTradingEnv` chunks. A false positive ("one" →
  `run_one_multiplier`) led to the function-word stopwords. Doc titles are not
  real retrieval tasks and there is no ground truth, so this is
  consistent-with-mechanism, not proof.

**Reading:** a modest, mechanism-consistent win (one regression recovered, the
usefulness bar held) on a sample of 8 used chunks with assistant labels. It does
not remove the filler or fix room starvation. Still owed: user review of the
v4 annotations, and a real task set on a Python corpus other than rl-stocks.
The flag (`CODE_HEADING_RELEVANCE`) can be switched off without reindexing.
