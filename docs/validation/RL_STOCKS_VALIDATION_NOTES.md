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
