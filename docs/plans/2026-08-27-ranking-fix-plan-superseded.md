# Fix code-neighbor selection fairness (separate commit from P1 gate)

> **Superseded (2026-08-28):** the "Two independent bugs" mechanism claims
> below were shown wrong by evidence gathered while planning the fix — see
> `docs/plans/2026-08-28-233850-cost-aware-code-tier-selection-supersedes-ranking-.md`
> for the full data. Neither fix repaired either confirmed failure case, and
> the breadth-first swap alone would have made `legacy-10` worse. The
> mention-count-weight proposal (Bug 1) and symbol-first ordering were both
> tried/considered and rejected — see that plan and `docs/V4_NEXT_STEPS.md`
> for what actually shipped instead (oversized-whole-file demotion +
> breadth-first `k`-major expansion, no weight change, `ORDER BY target`
> kept). The "Regression tests" and "Rerun the validation gate" sections
> below stay accurate as the process this session followed; the "Two
> independent bugs" root-cause analysis does not.

## Context

The rl-stocks 20-call validation gate (`docs/validation/RL_STOCKS_VALIDATION_NOTES.md`,
committed in `3c62f37`) found the `code_ref` retrieval tier clears the
15%-usefulness threshold only on thin margin (25% of calls, 7% of
individual selected chunks), and confirmed — twice, independently — that
the on-topic chunk for a task exists, is correctly indexed, and still gets
starved out of the pack by an unrelated chunk purely due to arbitrary
ordering:

1. **`legacy-1`** ("write tests for ExitManager"): `src/exit_manager.py`
   lost its budget slot to `scripts/analyze_reward_divergence.py` (a
   4413-token whole-file chunk, unrelated topic) because target selection
   sorts alphabetically and `analyze_reward_divergence.py` < `exit_manager.py`.
2. **`legacy-10`** ("how do I roll back a promoted model"): the only
   selected chunk was a generic `utc_now()` helper; `generate_rollback_guide`
   — the actually on-topic function, in the *same file* — was budget-cut.
   The same function *was* selected and judged used one call later
   (`legacy-11`, "what is the rollback guide procedure") — proving this is
   a pure ordering artifact, not a retrieval gap: `utc_now()` is simply
   defined earlier in the file, and in-file chunk expansion is
   document-order (`ORDER BY c.id`), target-major (one target's whole
   group gets enumerated before the next target gets any chunks).

The symbol-resolution tier (V4) was flagged "candidate for removal" in that
same gate — 0/20 calls ever selected a symbol-resolved chunk. But per
user instruction, that call is deferred: fix the two ordering bugs first,
regression-test the two confirmed failure cases, rerun the same 20 calls,
and only then decide symbols' fate — this tests whether symbols were
genuinely useless or merely unreachable under the current (broken)
ordering, which the current evidence can't distinguish.

This plan covers the ordering fix + regression tests + gate rerun, as a
commit separate from the already-landed P1 validation-gate work.

## Two independent bugs, two independent fixes

### Bug 1 — cross-file target selection is alphabetical

**[Shown wrong by evidence — see superseding-plan note above.]** The
mention-count weight proposed as this bug's fix points the wrong direction
on the confirmed case (`analyze_reward_divergence.py` has 2 mentions vs.
`exit_manager.py`'s 1) and was rejected; it was never implemented.

`context.py`'s code-neighbor query (~line 255-259):

```python
code_targets = conn.execute(
    "SELECT target FROM edges WHERE source = ? AND kind = 'code_ref' "
    "ORDER BY target LIMIT ?",
    (row["path"], MAX_CODE_NEIGHBORS_PER_SEED),
).fetchall()
```

`ORDER BY target` is lexicographic string sort — no relevance signal.
This decides which up-to-5 (of possibly more) `code_ref` targets a seed
even gets to expand.

**Fix — two parts:**

- **Evidence-bearing weight.** `edges.weight` already exists in the schema
  but every `code_ref`/`symbol` edge is inserted with a hardcoded `1.0`
  (`index.py` `_build_code_edges`, lines ~427 and ~410/413). Change it to
  carry real evidence: how many times a doc actually mentions that target.
  In `_build_code_edges`:
  - `filename_targets` (line 307) is currently a `set[str]`; change to
    `collections.Counter[str]`, incrementing per resolved mention from
    `extract_code_mentions(r["body"])` instead of just adding to a set.
  - `symbol_targets`/`resolved_symbol_files` (lines 325-344) similarly:
    count resolved `(code_path, heading)` occurrences from
    `extract_symbol_mentions(r["body"])` instead of a plain `set()`.
  - Line 346's merge (`targets = (filename_targets - resolved_symbol_files)
    | symbol_targets`) becomes a `dict[target] -> weight` merge instead of
    a set union — carry counts through, not just membership.
  - `per_doc_targets: dict[str, set[str]]` (line 303) becomes
    `dict[str, dict[str, int]]` (target -> mention count).
  - The edge-insert loop (lines 417-429): write `weight=<count>` instead of
    the hardcoded `1.0`.
  - `len(targets) > MAX_CODE_REFS_PER_DOC` (line 349) still works
    unchanged against `dict` keys.

- **Query ordering.** Replace the `ORDER BY target` query in `context.py`
  with:
  ```sql
  ORDER BY (target LIKE '%#%') DESC, weight DESC, target ASC LIMIT ?
  ```
  `target LIKE '%#%'` is true for symbol-resolved targets (`path#heading`,
  per `split_code_key`'s reserved separator) and false for filename-only
  targets — this directly implements "prioritize symbol-resolved targets
  over filename fallbacks." `weight DESC` uses the new mention-count
  evidence as the next tiebreak. `target ASC` remains only as the final
  deterministic tiebreak (same role `ORDER BY target` played before, now
  demoted to last resort).

### Bug 2 — within-tier expansion is target-major, not breadth-first

**[Shown wrong as the sole mechanism for `legacy-1` — see superseding-plan
note above.]** Both `legacy-1` targets are single chunks, so the
breadth-first swap alone is a no-op there; the actual `legacy-1` mechanism
is the unsliceable 4413-token whole-file chunk (see
`docs/V4_NEXT_STEPS.md`). The breadth-first swap itself *was* shipped — it
targets the `legacy-10` (`generate_rollback_guide`) case, not `legacy-1`.

`context.py`'s per-target group-expansion loop (~line 260-308) ranks each
selected chunk as:

```python
ranked[cc["id"]] = CODE_TIER_BASE + i + j / 100.0 + k / 10000.0
```

where `j` = index of the target within the seed's up-to-5 selected targets,
`k` = index of the chunk within that target's expansion group (whole-file
chunks in doc order for filename-only; preamble+target+neighbors for
symbol-resolved). Because `j` is the *major* axis (÷100) and `k` is
*minor* (÷10000), every chunk of target `j=0` ranks ahead of every chunk of
target `j=1` — a large or many-chunked file (e.g. `backtest_exit_rules.py`,
20 chunks; `sanitize_apply.py`, 26 chunks) fully consumes the tier's share
of the token budget before a smaller/later target gets a single chunk in.
This is the direct mechanism behind both confirmed failures above.

**Fix:** swap which index is major/minor so allocation is breadth-first
across targets instead of target-major:

```python
ranked[cc["id"]] = CODE_TIER_BASE + i + k / 100.0 + j / 10000.0
```

Now all targets' position-0 chunk (their preamble, or first chunk in doc
order) rank ahead of any target's position-1 chunk, etc. — round-robin
allocation, so a large file's tail no longer starves a smaller/rarer
target's earlier (often more central — preamble/def-signature) chunks. The
greedy budget-fill loop itself (`ordered = sorted(ranked.items(), ...)`,
further down) is untouched — this only changes selection *priority*, not
the fill algorithm.

Note: `k` can exceed 99 for an unusually large file (more than 99 chunks),
which would collide with the next integer step of `i`. This hasn't been an
issue at `j`'s current ÷100 scale in production data (largest observed
group was 26 chunks) — carry the same headroom forward, but add a
one-line comment noting the assumption so a future change to chunk-size
thresholds doesn't silently reintroduce collision risk.

## Regression tests

Add to `tests/test_index_and_retrieval.py`, following the existing
tmp_path-fixture style (see `test_ambiguous_code_basename_creates_no_edge`
for the pattern: synthetic small repo, not the external rl-stocks corpus —
keeps tests fast and deterministic).

1. **ExitManager-shaped case (bug 1 regression).** A markdown doc backtick-
   mentions two code files: one alphabetically earlier and large/multi-
   chunk, one alphabetically later and the actual answer (small, single
   mention). Under a token budget too small to fit both fully, assert the
   correct (later-sorting, singly-mentioned or more-referenced) file's
   chunk is selected and the alphabetically-earlier one is not — or is
   budget-cut instead. Before the fix this would select the wrong one.

2. **generate_rollback_guide-shaped case (bug 2 regression).** One code
   file with several functions: an early-defined generic-sounding one and
   a later-defined one that's the actual mention target (matches via
   `extract_symbol_mentions`/backtick symbol reference, or is simply the
   higher-mention-count target). Under a small token budget, assert the
   later-defined, on-topic chunk survives selection — before the fix, the
   earlier-defined chunk would win purely by `ORDER BY c.id` document
   order under target-major expansion.

Both assert against `retrieve()`'s returned `chunks`/`budget_cut` (same
shape used throughout `test_index_and_retrieval.py`), not the rendered
markdown — check `path`/`heading`/`provenance` fields directly.

## Rerun the validation gate (separate follow-up, same session or next)

Once A (weight) + B (cross-file order) + C (breadth-first) + D (tests) are
in and `pytest -ra` passes clean:

1. Rebuild `db/rl-stocks.db` (same command as before, from this repo's
   root): `python -m docgraph.index "D:/code/agentic-development/reinforcement-learning-stocks" db/rl-stocks.db`.
2. Re-run the **exact same 20 tasks** from
   `docs/validation/rl-stocks_query_log.jsonl` (the task strings, not the
   old results) through `python -m docgraph.context ... --max-tokens 8000`
   with `DOCGRAPH_QUERY_LOG` pointed at a **new** file (e.g.
   `docs/validation/rl-stocks_query_log_v2.jsonl`) — keep the original as
   the documented "before" baseline, don't overwrite it.
3. Annotate the new log for real per-chunk used/unused judgment via
   `python -m docgraph.validation annotate` / `report`, exactly as done
   for the first pass (`docs/validation/RL_STOCKS_VALIDATION_NOTES.md`
   documents the annotation approach used).
4. Compare before/after:
   - Did `src/exit_manager.py` and `generate_rollback_guide` now get
     selected in their respective calls (the two confirmed cases)?
   - Did any symbol-resolved chunk get selected at all this time (0/20
     before)? If yes, was it judged used?
   - Did overall `usefulness_rate` / per-tier precision improve, stay flat,
     or regress?
5. Decide the symbol tier's fate from this second, ordering-fair pass:
   - Symbol chunks now surface and get used at a non-trivial rate → keep.
   - Symbol chunks still never surface, or surface but are never used,
     even with fair ordering → removal is now justified on clean evidence
     (not the confounded "maybe just unreachable" evidence from pass 1).
6. Update `docs/V4_NEXT_STEPS.md` and
   `docs/validation/RL_STOCKS_VALIDATION_NOTES.md` with the "after" numbers
   and the final symbol-tier decision, same corrections-transparency style
   used in the first pass (state what changed and why, don't just
   overwrite silently).

## Commit boundary

Per explicit instruction: the ordering fix (bugs 1+2 + regression tests)
is its own commit, separate from the already-landed P1 gate commit
(`3c62f37`). The gate rerun is a natural following commit (log files +
updated docs) — can be same sitting, but keep it a distinct commit from
the code change so "here's the fix" and "here's the evidence the fix
worked" stay separable in history.

## Verification

- `python -m pytest -ra` — full suite green, including the two new
  regression tests, before touching the validation gate.
- Manually re-run the two confirmed failure-case tasks via
  `python -m docgraph.context ... "write tests for ExitManager"` and
  `... "how do I roll back a promoted model"` against the rebuilt
  `db/rl-stocks.db`, spot-check the rendered pack now includes
  `src/exit_manager.py` / `generate_rollback_guide` before running the
  full 20-call rerun.
