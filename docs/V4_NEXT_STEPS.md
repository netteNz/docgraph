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

## Next UX work, after the gate

1. Add independent visibility toggles for `code_ref`, co-location, and structural edges; purple code edges can clutter large graphs.
2. Label or arrow directional edges so `code_ref` does not read as undirected.
3. Add extension, discovery-bucket, and connected-component filters.
4. Decide from observed demand whether clicking code nodes should reveal code chunks and internal symbol edges; consider edge bundling only afterward.

## Durability and test prerequisites

See [TESTING.md](TESTING.md) for the fixture corpus requirement and the important distinction between skipped and passed external fixtures. See [INDEXING.md](INDEXING.md) for rebuild/freshness behavior and [ARCHITECTURE.md](ARCHITECTURE.md) for the durable V2–V4 design.