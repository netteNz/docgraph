# RL-Stocks validation run — 2026-08-25

Closes the ≥20-call validation gate defined in
[`V4_NEXT_STEPS.md`](../V4_NEXT_STEPS.md). Corpus:
`D:\code\agentic-development\reinforcement-learning-stocks` (72 indexed docs,
104 co-location edges, 2 link edges, 91 `code_ref` edges over 37 code files,
542 `symbol` edges). Index: `db/rl-stocks.db`.

**Status: P1 usefulness gate closed for the selected-chunk metric (the one
`decision` is computed from), reviewed with real per-chunk used/unused
judgments via `src/docgraph/validation.py`, not exposure counts.
`budget_cut` review is partial (15 of 787 candidates) — see "What's not
covered" below.** An earlier version of this document reported exposure
rates as if they were usefulness rates; that was wrong and is corrected
here. See "Corrections from the first pass" for what changed and why.

## Reproducing

```bash
export DOCGRAPH_QUERY_LOG=docs/validation/rl-stocks_query_log.jsonl
PYTHONIOENCODING=utf-8 python -m docgraph.context \
  "D:/code/agentic-development/reinforcement-learning-stocks" db/rl-stocks.db \
  "<task>" --max-tokens 8000

python -m docgraph.validation report docs/validation/rl-stocks_query_log.jsonl
```

`docs/validation/rl-stocks_query_log.jsonl` — the raw 20-call retrieval log.
`docs/validation/rl-stocks_query_log.annotations.jsonl` — per-chunk
used/unused/uncertain judgments, written directly against the tool's schema
(not through the interactive `annotate` prompt — see "What's not covered").
`docs/validation/rl-stocks_report.json` — `validation.py report --json`
output.

## Tool-computed result

```
Calls: 20/20 reviewed (minimum 20)
Packs with used advanced context: 5 (25.0%)
Pre-registered threshold: 15.0%
Gate: keep_or_tune
Useful budget-cut candidates: 3 (4 uncertain)
```

| Tier | Exposed packs | Used packs | Precision | Selected/used chunks | Useful budget cuts |
|---|---:|---:|---:|---:|---:|
| filename `code_ref` | 17 | 5 | 29.4% | 115 / 8 | 3 / 11 reviewed |
| `link` | 2 | 0 | 0.0% | 3 / 0 | 0 / 2 reviewed |
| `seed` (cut only) | — | — | — | — | 0 / 4 reviewed |
| symbol-resolved `code_ref` | 0 | 0 | — | 0 / 0 | not exposed |

`decision: keep_or_tune` — 25% of calls had at least one genuinely-used
advanced-tier chunk, above the pre-registered 15% threshold. That clears
the gate as defined, but the margin is thin and the chunk-level detail
underneath it is weak: of the 115 selected `code_ref` chunks across 20
calls, only **8 (7%)** were judged actually used — most of what fills a
pack is unused filler that happened to fit the budget, not noise-free
signal. The pack-level 25%/29.4% numbers are real but sit on top of a lot
of dead weight per pack.

## Corrections from the first pass

A review of the first draft of this document caught several errors, all
verified against the raw log and `src/docgraph/context.py` before
correcting:

1. **"85% clears the usefulness bar" was wrong.** That number was the
   fraction of calls with a *selected* `code_ref` chunk — exposure, not
   usefulness. No per-chunk used/unused judgment existed at the time. The
   corrected, annotated number is 25% of calls with an actually-used
   chunk, and only 7% of individual selected chunks. Exposure and
   usefulness are now reported as separate rows and never conflated again
   in this document.
2. **"7 queries had a seed-tier chunk budget-cut" was wrong; it's 11.** The
   first pass reported the *maximum* per-call seed-cut count (7, on the
   `SparseEnsemble` call) as if it were the count of *affected calls*. The
   correct count, recomputed directly from the log: 11/20 calls had at
   least one seed-tier chunk lose its budget slot.
3. **The causal claim "code expansion can crowd out seed-tier chunks" was
   wrong.** `code_ref` chunks rank at `seed_limit*2` or higher
   (`CODE_TIER_BASE` in `context.py`) — strictly after every seed and every
   co-location neighbor in the greedy fill order, so a code chunk can never
   be the reason an earlier-ranked seed gets skipped. The budget fill is a
   single greedy first-fit pass in rank order (`context.py`'s `for chunk_id,
   _rank in ordered: ... if running + m["token_est"] > max_tokens and
   selected: continue`) — an item is only skipped because the cumulative
   running total *before* it (from earlier seeds, or from a co-location
   neighbor interleaved at `i+0.5` between two seeds) already used up the
   remaining budget. The correct mechanism: an early seed or its neighbor
   consuming a large token count can leave a *later* seed no room, never a
   code chunk.
4. **"The ExitManager query wasn't logged" was wrong.** It is the first
   record in `rl-stocks_query_log.jsonl` (`call_id: legacy-1`, task "write
   tests for ExitManager"). It was logged; the earlier document just
   described it from memory instead of checking the file.

## Findings, with real per-chunk annotation

**Filename-only `code_ref` clears the gate, but on thin margin and heavy
per-chunk noise.** 5/20 calls (25%) had a genuinely useful selected chunk —
clean hits look like `export_signals_for_dashboard.py` (call `legacy-15`,
task "how do I export signals for the dashboard": the file and 2 of its 3
functions judged used) or `analytics_dashboard.py` (`legacy-18`). But many
calls pull in chunks with no real connection to the task — e.g.
`legacy-5` ("GPU acceleration configured for training") selected exactly
two chunks, both a generic `utc_now()` timestamp helper from an unrelated
sanitization script; `legacy-12` ("reward hybrid fix") selected four
chunks, all hash/timestamp utilities from the same unrelated script. This
recurs enough (`sanitize_apply.py`/`sanity_scan.py` utility functions
appear as selected chunks for GPU config, model rollback, and reward-fix
tasks alike) that it looks systemic rather than incidental: a small, cheap,
early-in-file chunk from a frequently-referenced utility script keeps
winning a budget slot regardless of topic, simply because it's small enough
to fit after a bigger, on-topic chunk from the same tier already got cut.

**Symbol-resolved `code_ref` and symbol-neighbor expansion never got
selected — real, not just unannotated absence.** Because they were never
present in any pack across 20 calls, there was nothing to annotate;
"0 used" here is a structural fact about the ranking (confirmed against
`context.py`: filename-level candidates from the same seed rank ahead of
symbol groups whenever both exist), not a judgment call.

**Budget displacement of useful content is confirmed twice, not once.**
- `legacy-1` ("write tests for ExitManager"): `src/exit_manager.py`, the
  class under test, lost its slot to `analyze_reward_divergence.py` (a
  4413-token whole-file chunk, unrelated topic) — confirmed useful when
  reviewed.
- `legacy-10` ("how do I roll back a promoted model"): the *only* selected
  chunk was `sanitize_apply.py`'s generic `utc_now()` helper (unused); the
  actually on-topic function in the same file,
  `generate_rollback_guide`, was budget-cut. The same function, same file,
  *was* selected and judged used one call later in `legacy-11` ("what is
  the rollback guide procedure") — proving the miss in `legacy-10` isn't
  because the content doesn't exist or can't be found, but because
  in-file chunk ordering (`ORDER BY c.id`, i.e. document order) put
  `utc_now()` ahead of `generate_rollback_guide()` for one phrasing of
  an equivalent question and not the other.

**Seed-tier displacement is real (11/20 calls), and now correctly
attributed.** It's caused by earlier seeds/co-location neighbors consuming
budget before a later-ranked seed's turn — never by code_ref or link tiers,
which always rank below every seed. Worth tuning `seed_limit` independently
of anything code/symbol-tier related.

**Link tier — still no new evidence.** 2/20 calls, 3 chunks, 0 judged used
(both were plausible-but-not-actually-on-topic reads of
`ENVIRONMENT_REALISM_AUDIT_2026_04_02.md`). Consistent with the corpus's
thin 2-link-edge count; sample too small to move the existing "unproven in
production" assessment either way.

## What's not covered

`budget_cut` review here is a small, explicitly-scoped subset (15 of 787
cut candidates across the log — the calls that selected nothing advanced,
plus a couple of items called out during manual inspection), not the full
counterfactual. Full `budget_cut` review would need real per-item judgment
on ~787 candidates; that wasn't attempted here rather than being rushed.
The `budget_cut_useful`/`budget_cut_uncertain` columns above should be read
as a lower bound, not a rate — they say "at least 3 confirmed useful cuts
exist," not "3/787 cut candidates are useful."

Annotations were written directly against `validation.py`'s JSONL schema by
a single reviewing pass (this session) rather than through
`validation.py annotate`'s interactive per-chunk prompt — the schema and
resulting `report` computation are identical either way, but a second,
independent reviewer pass would strengthen confidence in the individual
used/unused calls, particularly the `uncertain` ones.

## Recommendation

1. Treat the symbol-resolution tier (V4) as a real removal candidate — it
   has now been given 20 real chances to win a selection slot and never
   has, with a confirmed structural reason (filename-level candidates from
   the same seed always outrank it).
2. Fix in-tier chunk ordering so a small, early-in-file, topic-irrelevant
   chunk doesn't systematically win a budget slot over a later, on-topic
   chunk from the same file (the `generate_rollback_guide` case is a clean,
   reproducible repro for testing a fix). Replacing `ORDER BY target` /
   `ORDER BY c.id` with anything relevance-bearing is the same fix
   identified for the cross-file `ORDER BY target` problem (the
   `exit_manager.py` case) — both are instances of "lexicographic/document
   order stands in for relevance where nothing relevance-bearing exists."
3. Before re-running this gate again, decide whether to invest in
   completing full `budget_cut` review (787 candidates) or accept the
   selected-chunk-only gate as sufficient going forward — right now the
   `useful`/`not_useful` breakdown among cuts is too small a sample to be
   more than anecdotal support for point 2.

**Correction (2026-09-03):** point 2 above proposed replacing
`ORDER BY target` / `ORDER BY c.id` with a relevance-bearing signal.
Testing that literally (mention-count `edges.weight` as the replacement
tiebreak) against this corpus showed the signal points the wrong way on
the confirmed `exit_manager.py` case — `analyze_reward_divergence.py` has
*more* mentions (2 vs. 1), so weight-ordering cements the same wrong
target ahead, just with a more principled-looking justification. See
`docs/plans/2026-08-28-233850-cost-aware-code-tier-selection-supersedes-ranking-.md`
for the full evidence. The fix that actually shipped replaces neither
`ORDER BY` clause: it adds a rank-time demotion for oversized whole-file
chunks (`OVERSIZED_WHOLE_FILE_BUDGET_FRACTION`) and reorders which axis of
the in-tier rank formula is major (breadth-first `k`-major instead of
target-major `j`-major). `ORDER BY target` remains the plain alphabetical
tiebreak for cross-file target selection; symbol-first ordering was tried
separately and reverted (see `docs/V4_NEXT_STEPS.md`). See that file's
"Ranking fix shipped" section for the after-numbers from the gate rerun.

## Gate rerun after the ranking fix (2026-09-03)

Same reproduction recipe as above, pointed at a new log file so the
original stays the "before" baseline:

```bash
export DOCGRAPH_QUERY_LOG=docs/validation/rl-stocks_query_log_v2.jsonl
PYTHONIOENCODING=utf-8 python -m docgraph.context \
  "D:/code/agentic-development/reinforcement-learning-stocks" db/rl-stocks.db \
  "<task>" --max-tokens 8000

python -m docgraph.validation report docs/validation/rl-stocks_query_log_v2.jsonl
```

Same 20 task strings from `rl-stocks_query_log.jsonl`, same `db/rl-stocks.db`
(no reindex — the fix is retrieval-only). Annotated the same way as the
first pass (per-chunk judgment written directly against `validation.py`'s
JSONL schema): `docs/validation/rl-stocks_query_log_v2.annotations.jsonl`.

### Tool-computed result (after)

```
Calls: 20/20 reviewed (minimum 20)
Packs with used advanced context: 5 (25.0%)
Pre-registered threshold: 15.0%
Gate: keep_or_tune
Useful budget-cut candidates: 3 (0 uncertain)
```

| Tier | Exposed packs | Used packs | Precision | Selected/used chunks | Useful budget cuts |
|---|---:|---:|---:|---:|---:|
| filename `code_ref` | 18 | 5 | 27.8% | 143 / 8 | 3 / 5 reviewed |
| `link` | 3 | 0 | 0.0% | 6 / 0 | 0 / 0 reviewed |
| symbol-resolved `code_ref` | 0 | 0 | — | 0 / 0 | not exposed |

The pack-level usefulness rate is **numerically identical to the first
pass, 25% (5/20)** — but the two numbers are not the same evidence. The
*set* of used calls changed:

- **`legacy-1` (write tests for ExitManager) — flips as intended.**
  `src/exit_manager.py` is now selected and judged used.
  `scripts/analyze_reward_divergence.py` — the 4413-token unsliceable blob
  that starved it out before — is now budget-cut at rank `20.5`, exactly
  where the oversized-whole-file demotion places it. This is the fix
  working as designed on the case it was built for.
- **`legacy-5` (GPU acceleration configured for training) — new hit.**
  `src/train_bot.py` (1542 tokens, under the demotion threshold) is now
  selected and is a plausible real answer for this task; the first pass
  never surfaced it, only the same unrelated `utc_now()` cluster.
- **`legacy-10` (how do I roll back a promoted model) — still doesn't
  flip.** `generate_rollback_guide` is still budget-cut (rank `22.21`);
  the only selected advanced chunk this time is an unrelated
  `test_sanitize_apply.py` preamble. The seed/co-location tiers consumed
  most of the 8000-token budget before the code tier's turn — this call's
  miss was never really about in-tier ordering.
- **`legacy-11` (what is the rollback guide procedure) — regresses.**
  `generate_rollback_guide` *was* selected and judged used for this exact
  call in the first pass. It is now budget-cut. Cause: breadth-first
  `k`-major expansion now interleaves **three** code_ref targets for this
  seed (`sanitize_apply.py`, `sanity_scan.py`, and `test_sanitize_apply.py`
  — a target not present in the first pass's selection at all), so the
  budget is spent going shallow across all three targets instead of deep
  into the one where the answer sits at position `k=21`. This is exactly
  the trade-off the superseding plan predicted was possible but didn't
  have a repro for: breadth-first is not a strict improvement over
  target-major, it just moves which shape of miss is more likely.
- **`legacy-19` (how is news data integrated into features) — regresses.**
  `src/news_data.py`'s `SentimentResult` — selected and used in the first
  pass — is now budget-cut in favor of `src/market_data.py`'s interval
  helpers (the same file that was noise in the first pass, now winning
  outright).
- **Symbol-resolved `code_ref` is still 0/20**, same as the first pass.
  This is expected, not new evidence either way: symbol-first ordering was
  tried and reverted, so this configuration gives symbol targets no
  promotion over filename fallbacks — the mechanism that caused 0/20 the
  first time is unchanged. **Caveat, stated explicitly per the gate-rerun
  plan**: this confirms symbols are still *unreached* under this specific
  configuration, not that they are *useless* — that distinction still
  requires a run where a symbol target can actually outrank a filename
  fallback, which hasn't been done.

### Decision

Do not remove the symbol-resolution tier: its "candidate for removal"
status from the first pass is neither confirmed nor cleared by this rerun,
since the rerun never gave it a fair chance to surface. Do not report the
ranking fix as a net usefulness improvement on this 20-call set: it
repaired the case it was designed for (`legacy-1`), left the other
confirmed case unrepaired (`legacy-10`), and introduced two new regressions
(`legacy-11`, `legacy-19`) via the same breadth-first mechanism that fixed
`legacy-1`'s sibling case. The net pack-level rate is flat. This is useful,
honest evidence that in-tier ordering changes trade one failure mode for
another rather than eliminating the underlying problem (no relevance
signal in the code tier at all) — consistent with what
`docs/plans/2026-08-28-233850-cost-aware-code-tier-selection-supersedes-ranking-.md`
already said about the root cause.
