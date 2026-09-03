---
date: 2026-08-28T23:38:50-04:00
status: approved
source: ExitPlanMode
---

# Execution Plan: Cost-aware code-tier selection (supersedes RANKING_FIX_PLAN.md)

# Cost-aware code-tier selection (supersedes RANKING_FIX_PLAN.md)

## Context

`RANKING_FIX_PLAN.md` (untracked) proposes two fixes for the code-neighbor
starvation confirmed by the P1 validation gate (`3c62f37`): (1) replace
`ORDER BY target` with mention-count `edges.weight`, and (2) swap the
rank formula's `j`/`k` axes to make in-tier expansion breadth-first.

I tested both against `db/rl-stocks.db` and the live corpus before
planning. **Neither fix repairs either confirmed failure case**, and fix 2
makes one of them measurably worse. The plan's stated mechanism for
`legacy-1` is factually wrong. Evidence below; this plan replaces that one.

### What the data actually shows

**`legacy-1` ("write tests for ExitManager")** — both competing targets come
from the same seed doc, `EXIT_SIGNAL_TODO.md`:

| target | mentions | chunks | tokens |
|---|---|---|---|
| `scripts/analyze_reward_divergence.py` | **2** | **1** | **4413** |
| `src/exit_manager.py` | **1** | **1** | **1419** |

- *Fix 1 fails*: mention-count weight is **2 vs 1 in the wrong direction**.
  `ORDER BY weight DESC` cements `analyze_reward_divergence.py` ahead of
  `exit_manager.py` — same wrong outcome as alphabetical, now with a
  principled-looking justification. The plan's own regression test 1
  ("assert the more-referenced file is selected") would fail as written.
- *Fix 2 fails*: both files are **single chunks**. Breadth-first only
  reorders *across* `k`; with `k=0` for both, the swap is a no-op here.
  The plan calls target-major expansion "the direct mechanism behind both
  confirmed failures" — it is not the mechanism for this one.
- *Actual mechanism*: `scripts/analyze_reward_divergence.py` is 444 lines
  with **zero top-level `def`/`class`**, so `is_chunking_candidate()`
  (`code_chunks.py:141`) returns False and it lands as one indivisible
  4413-token chunk — **55% of an 8000-token budget in a single bite**,
  admitted first because it sits earlier in target order. 6 of 37
  referenced code files are single chunks >1500 tokens.

**`legacy-10` ("how do I roll back a promoted model")** — `utc_now` (k=1,
29 tok) vs `generate_rollback_guide` (k=21, 998 tok), both in
`scripts/sanitize_apply.py` (24 chunks):

- *Fix 2 actively regresses this.* Within one target, `k` order is
  unchanged by the swap — but promoting `k` to the major axis pushes
  `generate_rollback_guide` from `+0.0021` to `+0.21`, now behind the
  early chunks of **every other target** it previously outranked.

The common root cause is that the code tier carries **no relevance and no
cost signal at all** — only position. Per your decision, this plan adds
cost-awareness only and preserves the documented invariant that code
chunks have no `docs_fts` row.

## Approach

Three changes in `src/docgraph/context.py`, plus doc corrections. **No
`index.py` change and no reindex** — dropping the mention-count weight
means `db/rl-stocks.db` stays valid, so the gate rerun compares before/after
on an identical index.

### 1. Drop the mention-count weight entirely

Do not touch `_build_code_edges` (`index.py:295-360`, `:417-429`).
`edges.weight` stays `1.0` for `code_ref`. The evidence above shows the
signal points the wrong way on the one case we can check.

### 2. Symbol-first target ordering, no weight

Replace the `ORDER BY target` in the code-neighbor query
(`context.py:255-259`) with:

```sql
ORDER BY (target LIKE '%#%') DESC, target ASC LIMIT ?
```

`target LIKE '%#%'` is true only for symbol-resolved `path#heading` keys
(`split_code_key`'s reserved separator). This is the *only* change that
gives the deferred symbol-tier decision clean evidence: symbols were 0/20
in the gate, and until they can outrank filename fallbacks we cannot tell
"useless" from "unreachable". `target ASC` remains the deterministic
final tiebreak. Only 5 of 91 `code_ref` edges are symbol-resolved, so this
is a small, low-risk reordering.

### 3. Defer oversized chunks within the tier

Keep the existing rank formula's axis assignment (`j` major, `k` minor) —
swapping it regresses `legacy-10`. Add a size term instead:

```python
# A code chunk above this defers to the back of its own seed's code band.
OVERSIZED_CODE_CHUNK_TOKENS = 1500

penalty = 0.5 if cc["token_est"] > OVERSIZED_CODE_CHUNK_TOKENS else 0.0
ranked[cc["id"]] = CODE_TIER_BASE + i + penalty + j / 100.0 + k / 10000.0
```

Rank arithmetic (worth a comment at the constant): `j` ≤ 4 and `k` < 100
bound the fractional part at `0.04 + 0.0099 < 0.05`, so `+0.5` sorts every
oversized chunk after all normal chunks of the *same* seed while staying
strictly inside `[i, i+1)` — the next seed's band is untouched. This alone
flips `legacy-1`: `exit_manager.py` (1419) now precedes
`analyze_reward_divergence.py` (4413).

### 4. Per-target budget share in the fill loop

In the greedy fill (`context.py:310-320`), cap what any single code file
may contribute:

```python
CODE_TARGET_BUDGET_SHARE = 0.35  # of max_tokens, per referenced code file
```

Track running tokens per `meta[chunk_id]["path"]` for
`provenance == "code_ref"` chunks and skip further chunks from a file once
it exceeds its share. Skip-entirely rather than truncate, matching the
`MAX_LINK_FANOUT` / `MAX_CODE_REFS_PER_DOC` discipline already documented
in CLAUDE.md.

Note the deliberate tradeoff: at `max_tokens=8000` the 4413-token
`analyze_reward_divergence.py` chunk exceeds a 2800-token share and is
dropped from the pack outright rather than trimmed. That is the intended
"no context beats wrong context" behavior, but it does mean an unsliceable
large file becomes unreachable at small budgets — the slicer gap stays
open and should be recorded as known, not silently absorbed.

Also keep in mind the existing `if running + token_est > max_tokens and
selected: continue` admits an oversized chunk unconditionally when nothing
is selected yet; the per-target cap must be checked independently of that
branch or a single huge chunk still slips in on an empty pack.

## Files

- `src/docgraph/context.py` — the only code change (query at `:255-259`,
  rank at `:304`, fill loop at `:310-320`, two new constants near
  `MAX_CODE_NEIGHBORS_PER_SEED` at `:149`).
- `tests/test_index_and_retrieval.py` — regression tests, following the
  existing `tmp_path` synthetic-repo pattern of
  `test_ambiguous_code_basename_creates_no_edge` (not the external
  rl-stocks corpus).
- `RANKING_FIX_PLAN.md` — correct the two wrong mechanism claims rather
  than deleting it; the gate-rerun section (steps 1-6) stays valid and is
  still the follow-up commit.
- `docs/V4_NEXT_STEPS.md` — update the "Not yet done" paragraph, which
  currently attributes both misses to `ORDER BY` alone.

## Regression tests

Both assert against `retrieve()`'s returned `chunks` / `budget_cut`
(`path`, `heading`, `provenance`), not rendered markdown.

1. **Oversized-chunk deferral (`legacy-1` shape).** Synthetic repo: one doc
   backtick-mentioning two code files — an alphabetically-earlier,
   more-mentioned, unsliceable large one, and an alphabetically-later small
   one. Under a budget fitting only one, assert the *small* file's chunk is
   selected and the large one lands in `budget_cut`. Fails on `main` and
   fails under both of `RANKING_FIX_PLAN.md`'s fixes.
2. **Per-target share (`legacy-10` shape).** One doc mentioning two code
   files, one with many chunks totalling well over 35% of the budget.
   Assert the many-chunked file stops at its share and the other file still
   gets at least one chunk in.
3. **Non-regression guard.** Assert `generate_rollback_guide`-shaped
   ordering *within* a single file is unchanged — the axis swap is not
   being applied, and a test should pin that so it isn't reintroduced.

## Verification

1. `python -m pytest -ra` — full suite green including the three new tests.
2. No reindex needed. Directly re-run the two confirmed cases against the
   existing db and diff against the logged baseline:
   ```
   python -m docgraph.context "D:/code/agentic-development/reinforcement-learning-stocks" \
       db/rl-stocks.db "write tests for ExitManager" --max-tokens 8000
   python -m docgraph.context "D:/code/agentic-development/reinforcement-learning-stocks" \
       db/rl-stocks.db "how do I roll back a promoted model" --max-tokens 8000
   ```
   Expect `src/exit_manager.py` present in call 1. For call 2 expect only
   partial improvement — without a relevance signal, `generate_rollback_guide`
   is not guaranteed to beat `utc_now`; record the actual result rather than
   asserting a win.
3. Then the gate rerun exactly as `RANKING_FIX_PLAN.md` steps 1-6 specify,
   into a **new** `docs/validation/rl-stocks_query_log_v2.jsonl`, keeping
   the original as the "before" baseline.

## Commit boundary

Unchanged from your earlier instruction: the ranking fix + tests + doc
corrections is one commit, separate from the landed P1 gate (`3c62f37`).
The gate rerun (logs + updated notes) is the following commit.
