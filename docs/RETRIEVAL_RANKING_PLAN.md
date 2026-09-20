# Give the code tier a relevance signal, and build the harness that proves it

## Context

A pass over the repo turned up one dominant accuracy defect and one blocking gap.

**The defect.** Code files deliberately get no `docs_fts` row (`src/docgraph/index.py:288-297`).
That invariant is load-bearing — `_SEED_SQL` and `_NEIGHBOR_SQL` both JOIN through `docs_fts`,
so a code chunk is structurally unreachable except via a `code_ref` edge, which is what keeps
DocGraph "reference-driven, not index-all-code." But it has an unintended consequence: **no
relevance signal exists for code chunks at all**, so every ordering decision inside the code
tier falls back to document or lexicographic order:

| Site | Current ordering | Consequence |
|---|---|---|
| `context.py:144` `_CODE_FILE_CHUNKS_SQL` | `ORDER BY c.id` (document order) | earliest function in a file wins the budget slot |
| `context.py:255-259` code_ref targets | `ORDER BY target LIMIT ?` (alphabetical) | alphabetically-first file wins `MAX_CODE_NEIGHBORS_PER_SEED` |
| `context.py:123` `_LINK_SQL` | `ORDER BY c.id LIMIT 1` | first section of a long link target, never the relevant one |

`docs/validation/RL_STOCKS_VALIDATION_NOTES.md` already documents this costing real retrieval
quality: the task "how do I roll back a promoted model" selected *only* `utc_now()` — a generic
timestamp helper early in a file — while `generate_rollback_guide()`, the on-topic function in
the **same file**, was budget-cut. One call later a rephrasing of the same question selected it.
The content was found; document order lost it. Across 20 annotated calls, only 8 of 115 selected
`code_ref` chunks (7%) were judged actually used.

The same pathology is visible right now in a local index. `db/veto-webapp.db` slices
`server/veto/machine_tsd.py` into 22 chunks, and `ORDER BY c.id` hands them out in this order:

```
server/veto/machine_tsd.py | (preamble)                  | 321 tok
server/veto/machine_tsd.py | picking_team_for_game       |  38
server/veto/machine_tsd.py | TSDMachineError             |   9
server/veto/machine_tsd.py | GuardError                  |   9
server/veto/machine_tsd.py | TurnError                   |   9
server/veto/machine_tsd.py | TSDMachine                  |   6
server/veto/machine_tsd.py | TSDMachine > __init__       | 178
...
server/veto/machine_tsd.py | TSDMachine > ban_slayer_map | 201   <- 17th
```

For a task about banning maps, three 9-token exception classes and an empty class header take
budget slots ahead of `ban_slayer_map`, purely because they are defined earlier in the file.
No query can change that today.

**The gap.** The 20-task labeled set backing the P1 gate is not reproducible on this machine.
`*.jsonl` is gitignored, so `rl-stocks_query_log.jsonl` and its annotations exist nowhere in the
repo — only the derived `report.json` and notes survived. The corpus itself is at a Windows path
(`D:\code\...`). `docs/V4_NEXT_STEPS.md` lists "re-run the same 20 tasks to prove a fix changes
outcomes" as the next step; **that is currently impossible.** And there is no automated
retrieval-quality regression test of any kind — `validation.py` measures human judgments after
the fact, it cannot gate a change.

So the two halves are worthless apart: the fix can't be verified without a harness, and a
harness with nothing to catch is busywork. Build both, harness first, with the two documented
failures as *failing* cases that the fix turns green.

**Intended outcome.** In-tier ordering carries relevance instead of filename/document order, and
a `pytest` run fails if that regresses.

---

## Part 1 — Retrieval accuracy harness (build first, red)

Follow the established fixture pattern exactly: a JSON case file, a standalone `_check(case)`
runner, and a thin parametrized pytest wrapper.

**Reuse `_temp_index()` (`tests/run_code_fixtures.py:47`)** — it already builds a disposable temp
repo (one code file + a doc that references it), indexes it, and returns `(repo_root, db_path)`
with `shutil.rmtree` cleanup. Generalize it to accept *multiple* code files and a custom doc
body for Case B. Keep the existing single-file signature working; `run_code_fixtures.py`
depends on it.

### Files

- `tests/fixtures/retrieval_fixtures/` — synthetic corpus sources
- `tests/fixtures/retrieval_fixtures.json` — case definitions
- `tests/run_retrieval_fixtures.py` — `_check(case)` + `main()`, mirroring `run_code_fixtures.py`
- `tests/test_retrieval_fixtures.py` — parametrized wrapper, copy `tests/test_code_fixtures.py`

### Cases (both reconstruct documented failures; neither needs the original corpus)

**Case A — in-file ordering** (`rollback_tools.py`). A code file with a generic `utc_now()`
helper defined *early* and an on-topic `generate_rollback_guide()` defined *late*, plus a doc
that filename-references the file. Task: `"how do I roll back a promoted model"`.
Assert `generate_rollback_guide` ranks ahead of `utc_now`.

> **Hard constraint the fixture must satisfy.** `code_chunks.is_chunking_candidate`
> (`code_chunks.py:141`) only slices a file when `token_est(body) > 2000` **and** it has ≥2
> top-level defs. `token_est` is `len(text) // 4` (`sections.py:31`), so the fixture source must
> exceed **8000 characters**. A tidy 40-line fixture is never sliced, both functions collapse
> into one whole-file chunk, and the test passes vacuously while testing nothing. Pad with
> realistic filler and assert `is_chunking_candidate(body) is True` as a precondition inside the
> case, so a future edit that shrinks it fails loudly instead of silently.

**Case B — cross-file target ordering.** One doc referencing two code files where the
alphabetically-first is off-topic and the on-topic one sorts later, with the case's limits set so
`MAX_CODE_NEIGHBORS_PER_SEED` forces a choice. Assert the on-topic file is selected. This is the
`src/exit_manager.py` failure from the notes.

### Scoring, not just pass/fail

`_check` should return the observed rank alongside the boolean, and `main()` should print a small
table — so the harness reports *how much* better a change made things, not only whether it
crossed a line. Keep it to rank-of-expected and selected/total; do not build a second metrics
framework next to `validation.py`.

### Case schema (JSON)

```json
{
  "name": "in_file_ordering_rollback",
  "sources": ["rollback_tools.py"],
  "doc_body": "See `src/rollback_tools.py`.",
  "task": "how do I roll back a promoted model",
  "max_tokens": 800,
  "check": "rank_order",
  "expect": {
    "requires_chunking": true,
    "before": "generate_rollback_guide",
    "after": "utc_now"
  }
}
```

---

## Part 2 — `code_fts`: a relevance signal that cannot become a seed

### `src/docgraph/index.py`

Add to `SCHEMA` (`:448`), mirroring `docs_fts` exactly:

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS code_fts USING fts5(
    indexed_title, body, content='', tokenize='porter'
);
```

**Add `DROP TABLE IF EXISTS code_fts;` to `DROP` (`:441`). This is the single easiest way to ship
this broken.** `build()` runs `DROP + SCHEMA` unconditionally; omit the DROP and a rebuild leaves
stale contentless-FTS rows whose rowids collide with freshly-assigned `chunks.id`, and a
contentless FTS5 insert on an occupied rowid raises `UNIQUE constraint failed`.

Populate inside `_build_code_edges`'s chunk loop (`:376-386`). That loop currently discards the
insert's `lastrowid` — capture it:

```python
cc = conn.execute(
    "INSERT INTO chunks(doc_id,path,heading,indexed_title,token_est) VALUES(?,?,?,?,?)",
    (doc_id, code_path, c.heading, indexed_title, c.token_est),
)
fts_title = c.heading if c.heading is not None else filename
conn.execute(
    "INSERT INTO code_fts(rowid,indexed_title,body) VALUES(?,?,?)",
    (cc.lastrowid, fts_title, c.text),
)
```

`CodeChunk` is `(heading, text, token_est)` — the body field is **`text`**, and both branches of
`_code_chunks_for` (`:279-281`) populate it.

`indexed_title` must follow `_insert`'s narrower `fts_title` rule (`:169`, reasoning at
`:164-168`): **the chunk's own heading, filename only for the `None` preamble.** The filename is
constant across every chunk of a file, so including it everywhere adds an identical term to every
in-file score and flattens exactly the ranking being added. Worse, a code-tier task usually *does*
mention the filename — that's why the `code_ref` edge exists — so it would match every chunk
equally and collapse back to document order through the tiebreak. Cross-file ordering doesn't need
it either; that's handled by `MIN(bm25)` per path below.

**The invariant holds:** `_SEED_SQL`/`_NEIGHBOR_SQL` keep joining `docs_fts`, untouched, so code
chunks remain unreachable as seeds or co-location neighbors. Update the comment at `index.py:291`
— "No docs_fts row for code chunks" is about to become half the story, and the next reader needs
to know `code_fts` exists and why it is a *separate table* rather than a flag on the existing one.

### `src/docgraph/context.py`

**Reorder, never filter.** The code_ref tier is deliberately unconditional — see `:115-122` on why
gating on task vocabulary defeats the purpose. A `WHERE ... MATCH` JOIN silently drops every
non-matching chunk and converts an unconditional tier into a gated one. Use `LEFT JOIN` so the row
set is identical to today's, only permuted.

**(a) `_CODE_FILE_CHUNKS_SQL` (`:144`)** — params become `(query, path)`:

```sql
SELECT c.id, c.path, c.indexed_title, c.token_est, c.heading, m.score
FROM chunks c
LEFT JOIN (SELECT rowid AS rid, bm25(code_fts) AS score
           FROM code_fts WHERE code_fts MATCH ?) m ON m.rid = c.id
WHERE c.path = ?
ORDER BY (m.score IS NULL), m.score, c.id
```

`bm25` is negative, lower is better; `(m.score IS NULL)` sorts non-matching chunks last; `c.id`
keeps document order as the tiebreak within each group. Apply at both call sites (`:290`
`symbol_fallback`, `:299` `filename`).

**Do not reorder the symbol group at `:282-286`.** Preamble → target → neighbors is a semantic
contract tied to the `symbol_preamble`/`symbol_target`/`symbol_neighbor` tier details; bm25 there
would rank a neighbor above the resolved target.

**(b) code_ref target ordering (`:255-259`)** — drop `ORDER BY target LIMIT ?` from the SQL, fetch
all targets, and order in Python against a per-path score map computed **once** before the seed
loop:

```python
_CODE_PATH_SCORE_SQL = (
    "SELECT c.path AS path, MIN(m.score) AS score FROM chunks c "
    "JOIN (SELECT rowid AS rid, bm25(code_fts) AS score "
    "      FROM code_fts WHERE code_fts MATCH ?) m ON m.rid = c.id GROUP BY c.path"
)
```

Sort each seed's targets by `(score is None, score, target)` and then apply
`MAX_CODE_NEIGHBORS_PER_SEED`. Unmatched files keep alphabetical order and stay last — identical
to today when nothing matches. The cap now truncates by relevance rather than alphabet.

**(c) Query mode: OR, unconditionally** — independent of the seeds' resolved `query_used`. AND
over a 6-word task matches essentially zero code chunks, every score returns NULL, and the code
silently falls back to document order: the defect restored, invisibly. bm25's IDF already does the
discrimination AND was standing in for. Divergence from the seeds is harmless because these bm25
values are never compared across tiers — code chunks are placed by the positional
`CODE_TIER_BASE + i + j/100 + k/10000` formula, and bm25 only decides `j` and `k` within it. Mode
must match the seeds only in the *neighbor* tier (`:216`), where it is a precision gate.

**(d) Back-compat — raise, don't degrade.** Old `db/*.db` files have no `code_fts`, and would hit
`sqlite3.OperationalError: no such table` partway through `retrieve()`, after
`_require_fresh_sources` already passed. Add a `_require_schema(conn)` beside it (`:45`) checking
`sqlite_master` and raising `IndexStaleError` with the same rebuild instruction. Every existing
caller already handles that exception, and it matches the rebuild-only contract in
`docs/INDEXING.md`. Silently degrading to document order would reinstate the exact bug being
fixed, with no signal.

Also add a line to `docs/INDEXING.md`: `code_fts` stores code bodies' term index, so a code-heavy
repo's `.db` grows noticeably.

### Deferred to a separate commit

- **The `_LINK_SQL` fix (`:123`).** Same class of defect, and links target markdown which already
  has `docs_fts` rows — but it contradicts the documented "first chunk = where a reader following
  the link would land" rationale at `:118-122`, which needs rewriting rather than overriding.
  Bundling it also muddies attribution for the Case A repro. Do it after, on its own. **Landed —
  see Part 5.**
- **Rank-collision widening.** `k/10000` overflows the `j/100` step at ≥100 chunks in one file.
  Pre-existing, but this change makes a high-`k` on-topic chunk the *expected* case rather than a
  rarity, so a latent bug becomes reachable. Widen to `k/1_000_000`; switching `ranked` to tuple
  keys is cleaner but changes the `rank` field in the query-log schema, so it needs its own change.
  **Landed — see Part 4.**

### Explicitly out of scope

- **The greedy budget fill (`:313-319`).** Its `continue` (not `break`) lets a small low-ranked
  chunk slip in after a larger higher-ranked one was cut — the notes blame this for "small cheap
  utility chunk keeps winning a slot." Leave it. `break` wastes budget; the real problem was that
  the small chunk was *irrelevant*, which relevance ordering fixes at the source. Re-measure first.
- **Removing the symbol tier.** `docs/V4_NEXT_STEPS.md` recommends deleting it as "never selected,
  structurally outranked by filename-level candidates from the same seed." **That premise is
  false.** At `index.py:346`, `targets = (filename_targets - resolved_symbol_files) | symbol_targets`
  makes the two *mutually exclusive per file* — a file that resolves a symbol has its filename
  target removed, so they never compete. Symbol targets are simply **rare**: the checked-in indexes
  show 5/84 `code_ref` edges in `db/docgraph.db`, 1/4 and 1/6 elsewhere (~6%), and the ones that do
  resolve look meaningful (`src/market_data.py#merge_news_features`,
  `src/news_data.py#fetch_yahoo_news`). Do not delete working code on a wrong diagnosis.
  Re-measure after this fix, since relevance ordering changes what wins a slot.

---

## Verification

1. **Red first.** Add the Part 1 harness, run `pytest tests/test_retrieval_fixtures.py -ra`, and
   confirm both cases **fail** against current `main`. A case that passes before the fix is testing
   the wrong thing — fix the fixture, not the assertion.
2. **Full suite green.** `pytest -ra`.

   Watch `test_filename_only_code_refs_are_labeled_for_validation`
   (`tests/test_index_and_retrieval.py:68`) above all — it is the single most valuable existing
   guard for this change. It indexes `worker.py` containing only `def run(): return 1`, retrieves
   the task `"deployment"`, and asserts a `code_ref` chunk comes back. The body shares no
   vocabulary with the task, so if the reorder is implemented as a filter it matches nothing, gets
   dropped, and this goes red. **Treat a failure here as proof the reorder became a gate, not as a
   test to update.**

   `retrieve_group_size` (`tests/run_code_fixtures.py:139`) asserts only on `len(code_chunks)`;
   membership is unchanged and only order differs, so it should stay green — same for the
   `MAX_SYMBOL_FANOUT` fallback at `context.py:287-291`.
3. **Green after.** Land Part 2, re-run — both new cases pass, nothing else regresses.
4. **Real corpus, end to end.** Reindex and retrieve against this repo itself:
   ```bash
   python -m docgraph.index . db/docgraph-self.db
   python -m docgraph.context . db/docgraph-self.db "how does the token budget trim work" --max-tokens 4000
   ```
   Confirm the returned code chunks are topically related to budgeting. Then confirm an *old*
   index (`db/veto-webapp.db`) now raises `IndexStaleError` rather than degrading silently.
5. **The veto-webapp case from Context.** Reindex that repo and retrieve a banning-related task;
   `TSDMachine > ban_slayer_map` should now outrank the 9-token exception classes. This is the
   clearest real-corpus before/after available locally.
6. **Graph surfaces still render.** `python -m docgraph.serve . db/docgraph-self.db --port 8765`
   and the static `visualize.py` path both read the schema; confirm neither breaks on the new
   table. Note `score` stops being `NULL` for `code_ref` chunks — no current reader in `serve.py`,
   `visualize.py`, or `validation.py` touches it, but confirm nothing distinguishes tiers by
   `score is None`.

---

## Measured results (post-implementation, 2026-09-20)

All verification steps above were executed. Summary of what changed on real corpora.

**Red first (step 1).** With the implementation stashed, both new fixtures fail on `main`:
`in_file_ordering_rollback` and `cross_file_target_ordering_exit_manager`. With it applied, the
full suite is `26 passed, 7 skipped` (the 7 are `test_external_link_fixtures.py`, skipped because
`DOCGRAPH_FIXTURE_REPOS_DIR` is unset and `db/coinbase_rl_bot.db` is absent on this machine).
`test_filename_only_code_refs_are_labeled_for_validation` stayed green — the reorder did not
become a gate.

**The veto-webapp case (step 5).** Task: *"how does banning a slayer map work in the veto
machine"*, reindexed from `/Users/nettenz/projects/web-development/veto-webapp`. In-file rank of
`TSDMachine > ban_slayer_map` within `server/veto/machine_tsd.py`:

| | Before (document order) | After (`code_fts` bm25) |
|---|---|---|
| `TSDMachine > ban_slayer_map` | 17th | 3rd |
| 9-token exception classes (`TSDMachineError`, `GuardError`, `TurnError`) | 3rd–5th | 16th–18th |

Cross-file ordering likewise places `machine_tsd.py` ahead of `views.py`, `models.py`,
`serializers.py` and `manage.py`, where alphabetical order previously did not.

**Back-compat (step 4).** Retrieval against a pre-`code_fts` index raises `IndexStaleError` with
the rebuild instruction, as designed. **Operational consequence not anticipated in the plan:** all
four indexes in `db/` predate this table, and three of them back registered MCP servers
(`chunking-ui-docs`, `rl-stocks-docs`, `veto-webapp-docs`). They must be rebuilt at the same time
this lands or those servers fail on every call. `db/*.db` is gitignored, so this is a local step,
not part of the commit.

**Graph surfaces (step 6).** `visualize.py` renders the new schema without error. `serve.py` was
not smoke-tested.

### The deferred greedy-fill defect is now measurable — and it bites

The plan left the greedy budget fill (`context.py:313-319`) out of scope pending re-measurement.
Here is that measurement. On the same veto task at `--max-tokens 3000`, two markdown seeds consume
2498 tokens; the 321-token file preamble takes most of the remainder; `ban_slayer_map` (201 tok,
now correctly ranked 3rd) is **cut**, and the fill's `continue` then admits `confirm_tsd`, the
6-token empty `TSDMachine` header and the 9-token `TSDMachineError` behind it.

So relevance ordering is correct and the budget fill still hands the slot to the wrong chunk. The
premise for leaving it alone ("the real problem was that the small chunk was *irrelevant*, which
relevance ordering fixes at the source") is now falsified at realistic budgets: the small chunks
winning slots are no longer the irrelevant ones, they are simply the ones that fit.

**Resolved by budget reservation** (next section).

---

## Part 3 — Reserve budget for the code tier

Code chunks rank strictly below every doc tier (`CODE_TIER_BASE = seed_limit * 2`), so a single
greedy pass lets seeds consume the whole budget before the code tier is reached. `code_fts` fixed
*which* code chunk should win a slot; it could not create a slot to win.

**The fix.** Fill in two passes instead of one. The doc tiers fill against
`max_tokens - code_reserve`; the code tier then fills against the *full* `max_tokens`, inheriting
whatever the doc pass left unspent. The reservation is therefore a floor for code, never a cap.

`CODE_TIER_BUDGET_SHARE = 0.3`, retrieve-time tunable like `MAX_CODE_NEIGHBORS_PER_SEED`.

**The reserve is capped at actual code demand** (`min(share * max_tokens, sum of code token_est)`).
A task with no code candidates reserves nothing and gets byte-for-byte the old behavior. Without
that cap, every doc-only query would pay a 30% tax for a tier it is not using — verified: a
markdown-only corpus returns `code_reserve == 0`.

Two invariants the two-pass fill preserves deliberately:

- **The single-candidate exemption.** The original `and selected` guard admits the highest-ranked
  candidate even when it alone exceeds the budget, because an empty pack is worse than an
  over-budget one. Only the *globally* first candidate keeps that exemption.
- **Rank order of the pack.** `selected` is rebuilt from `ordered`, not from fill order, so the
  emitted pack is ordered exactly as the single-pass fill produced it.

`code_reserve` is added to `retrieve()`'s result for observability. The query-log schema is
untouched, so the `rank`-field concern noted under "Deferred" does not apply.

### Measured

New harness case `code_tier_budget_starvation` (synthetic, `rollback_runbook.md` + the existing
`rollback_tools.py`), red on the parent commit and green after:

| At `max_tokens=1800` | Before | After |
|---|---|---|
| Tokens spent on seeds | 1791 of 1800 | 1204 |
| `generate_rollback_guide` (rank 20.0, 326 tok) | budget-cut | selected |
| Code chunks in pack | 1 (a smaller, lower-ranked one) | 3 |

The doc fixture must stay above the 2000-token markdown split threshold
(`sections.CHUNKING_TOKEN_THRESHOLD`) or it indexes as a single seed and starves nothing — the
same vacuous-pass trap as Case A's `requires_chunking` guard, which the case also sets.

Real corpus, the veto-webapp case at `max_tokens=3000`: `TSDMachine > ban_slayer_map` is now
**selected** at rank 3, where before it was correctly ranked and then cut. The trade is visible
and intended — a 1782-token architecture seed is displaced by a 576-token one to make room.

## Part 4 — Widen the code-tier chunk step (rank-collision defect)

The rank-collision item under "Deferred to a separate commit" above is a **threshold raise, not a
fix**. `context.py`'s code tier ranks a chunk at `CODE_TIER_BASE + i + j/100 + k/CODE_TIER_CHUNK_STEP`
(now factored into `_code_tier_rank`); the three terms only nest correctly while `k`'s step stays
strictly under `j`'s step of `1/100`. `k` is unbounded — the `filename` and `symbol_fallback` paths
emit every chunk of a file with no cap — so a large enough file still collides.

Landed: `CODE_TIER_CHUNK_STEP = 1_000_000`, replacing the previous implicit `10_000`. The collision
boundary moves from 101 chunks in one file to 10,001. That is not a float-precision constraint —
`ulp(20.0) ≈ 3.6e-15`, so even a `1e-9` step keeps 200,000 distinct k-values apart — it is purely
arithmetic (`k < CODE_TIER_CHUNK_STEP / 100`), and the comment at the constant's definition records
that rather than a precision claim.

**Still deferred, correctly this time:** a `(base+i, j, k)` tuple sort key removes the collision
entirely rather than raising its threshold, but `rank` is a float in the `_log_query` JSONL schema
and rides the `/context` HTTP payload transitively through `serve.py` (the whole `retrieve()` dict
is serialized — there is no single declaration site for the field). Moved to Follow-ups below.

### Measured

No corpus exercises 100+ chunks in one file, so this is verified by direct arithmetic rather than
a synthetic fixture (a fixture clearing the chunking floor at 101 defs would be ~300 lines of
padding testing three divisions — not a good trade, and exactly what `requires_chunking` guards
exist to discourage). `tests/test_index_and_retrieval.py::test_code_tier_rank_nests_at_the_chunk_cap`
asserts the nesting invariant at the real constants' boundary (`k = CODE_TIER_CHUNK_STEP//100 - 1`)
and fails against the old `10_000`, satisfying red-first without a synthetic corpus.

Consumers audited: `sorted()` at the tier-merge step is the only behavioral reader (stable sort,
monotone key — order unaffected for every `k` under the old threshold, changed only for the
`k >= 100` cases that were already broken). `_log_query`'s schema (field name, type) is unchanged.
`validation.py`, `visualize.py`, `mcp_server.py` have no reference to `rank`. No test asserts an
absolute rank value.

Full suite: **28 passed, 7 skipped** (one new unit test; no regressions).

This commit does **not** unblock Part 5 below — `k` exists only in the code tier's formula; the
link tier's rank has no `k` term and this change leaves it untouched.

## Part 5 — Order the link tier by relevance

`_LINK_SQL` took the target's first chunk in document order (`ORDER BY c.id LIMIT 1`), a proxy for
"where a reader following the link would land" adopted because inclusion carried no query to
disambiguate a long multi-chunk target with. That query was available the whole time — every link
target is markdown, and `docs_fts` has always had a row for every markdown chunk — it was simply not
consulted.

Landed: `_LINK_SQL` is now a `LEFT JOIN` against `bm25(docs_fts)`, structurally identical to
`_CODE_FILE_CHUNKS_SQL`, ordered `(m.score IS NULL), m.score, c.id LIMIT 1`. Reorder-never-filter in
its strongest form: when nothing in the target matches, every score is NULL and the `c.id` tiebreak
returns bit-for-bit the row the old query returned — not just the same row set permuted, but the
same row whenever no signal exists. No new table, no reindex, no `IndexStaleError` path.

**Query mode is OR, unconditionally — for a different reason than the code tier's OR.** The code
tier diverges to OR because AND over a task string matches ~zero code chunks. That argument does not
transfer here; link targets are markdown prose and AND matches prose fine. The reason that does hold
is this tier's own premise: a link edge earns its place on targets *lexically disjoint* from the task
(`link_fixtures.json`'s organic cases sit at jaccard 0.10–0.33). AND demands every task word in one
chunk, so on exactly those targets every score comes back NULL and the fix silently no-ops on the
cases that motivated it. OR costs nothing here because this is not an admission decision — the target
is already in the pack, and OR only decides which of its own sibling sections wins the slot, where a
generic shared word scores about equally across all of them and bm25's IDF gives the weight to rare
terms. The rationale comment at the query's definition records both halves of this, since the
adjacent code-tier comment reaches the same conclusion by the opposite argument.

The `_LINK_SQL` comment (superseding the retired one) is the definitive rationale; see
`context.py`.

### Measured

New harness case `link_target_relevant_chunk` (synthetic: a short source doc linking to a
10,600-char target with an off-topic first H2, an unrelated middle H2, and the on-topic H2 last),
red on the parent commit and green after:

| | Before | After |
|---|---|---|
| Link chunk heading selected | `None` (intro) | `"Rolling Back A Promoted Model"` |
| `score` field | always `NULL` | real bm25 value |

**AND-mode check** (evidence for the OR choice, not just the argument): with the fix's SQL in place
but the query mode temporarily forced to AND, the case fails — `score` comes back `NULL` for every
chunk of the target (no chunk matches all 6 task words) and selection silently falls back to
`c.id`, reproducing the exact no-op the OR argument predicts. Confirmed directly by re-running the
fixture under both modes.

**Real corpus.** Reindexed this repo itself (10 files, 9 link edges). For the task "what is the
fixture corpus requirement for testing," the link chunk from `docs/validation/RL_STOCKS_VALIDATION_NOTES.md`
(a genuine 7-chunk doc) is selected via its intro (`score=-2.29`) — checked against all 7 chunks'
individual bm25 scores directly and confirmed the intro is honestly the best match for that query,
not a vacuous fallback. This repo's docs don't happen to contain a link target where the on-topic
section is *not* the first chunk, so no non-intro example was available locally; the synthetic
fixture is the definitive evidence for the reorder itself, and this run is evidence the scoring
mechanism produces real (not always-first) results on real data.

**Budget interaction.** The two tight-budget fixtures (`in_file_ordering_rollback` at 800 tokens,
`code_tier_budget_starvation` at 1800) cannot be perturbed by this change: `rollback_runbook.md`
contains zero `[` characters, so neither generates a link edge. That is a fact about the current
fixtures, not a guarantee — the next person who adds a markdown link to a fixture doc has changed
the budget arithmetic for that case, since link chunks compete in the doc-tier budget pass
(`max_tokens - code_reserve`) and a differently-sized chunk can now win or lose that competition.

`test_external_link_fixtures.py`'s 7 cases all skip on this machine (no external corpora); they
were not runnable, and this change rests on the new synthetic case as its only regression guard,
naming that gap rather than implying coverage that doesn't exist.

`score` is no longer `NULL` for link chunks; no consumer branches on it (checked: only SQL aliases,
`_CODE_PATH_SCORE_SQL`'s dict comprehension, `_target_sort_key`, and a pass-through in the result
dict reference the field).

Full suite: **29 passed, 7 skipped** (one new fixture case; no regressions).

## Part 6 — Cut link targets by relevance, not alphabetically (planned)

`context.py`'s link edge query still does `ORDER BY target LIMIT ?`, the same alphabetical-cap
defect Part 2 fixed for the code tier. Not landed in Part 5 because it is a **membership** change —
which targets appear at all, not merely which chunk of an already-included one wins — and the only
tests that can see link-tier membership regressions (`test_external_link_fixtures.py`) skip on this
machine. Bundling it with Part 5's pure reorder would make a real regression unbisectable. See
Follow-ups.

## Follow-ups (not this change)

- Every number in `RL_STOCKS_VALIDATION_NOTES.md` was measured under document order. After this
  lands they must be **re-run, not compared against** — note that in the document so a future
  reader doesn't treat them as a baseline.
- Re-run the P1 gate against a corpus reachable from this machine, and commit the query log plus
  annotations somewhere the gitignore allows — otherwise the next fix is unverifiable for exactly
  the reason this one nearly was.
- Re-measure the symbol tier post-fix and settle keep-vs-remove on real numbers.
- **Tuple-keyed rank** (`(base+i, j, k)` instead of a single float) removes the k/j collision
  entirely rather than raising its threshold. Blocked on `rank`'s float type in the `_log_query`
  JSONL schema and the `/context` HTTP payload — needs a schema migration, not just a formula
  change.
- **The link tier's alphabetical target cap** (Part 6, not yet landed) — mirror
  `_target_sort_key`/`_CODE_PATH_SCORE_SQL`'s `LIMIT -1` anti-flattening guard for a
  `_LINK_PATH_SCORE_SQL`, drop `ORDER BY target LIMIT ?`, sort all targets by
  `(score is None, score, target)` before slicing to `MAX_LINK_NEIGHBORS_PER_SEED`. Needs a fixture
  with 6–10 resolvable link targets (index-time `MAX_LINK_FANOUT = 10` drops a hub doc's edges
  entirely above 10) with the on-topic one sorting alphabetically last.
- **`tier_detail` is never set for link chunks**; `validation.py` special-cases the absence.
  Populating it changes what the validation report groups on — a separate change with its own
  measurement.
