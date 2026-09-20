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
   `src/exit_manager.py` lost its slot to an unrelated whole-file chunk via
   alphabetical `ORDER BY target`; separately, `generate_rollback_guide`
   lost its slot in one call to a same-file, alphabetically/document-order-earlier
   `utc_now()` helper, then *was* selected for a near-identical rephrased
   task in the next call — proving the miss is an ordering artifact, not a
   retrieval gap. Both are now fixed cases: `exit_manager.py`'s alphabetical
   `ORDER BY target` and `generate_rollback_guide`'s document-order tiebreak
   are exactly what relevance ranking (above) replaces — see
   `cross_file_target_ordering_exit_manager` and `in_file_ordering_rollback`
   in `tests/fixtures/retrieval_fixtures.json`. Full `budget_cut` review
   (787 candidates) is not done; only 15 were reviewed.

**Update, 2026-09-20:** in-tier chunk ordering is fixed — see
[RETRIEVAL_RANKING_PLAN.md](RETRIEVAL_RANKING_PLAN.md). `code_ref` chunks
are now ranked by `code_fts` relevance instead of document/alphabetical
order, with a reserved budget share so a seed-heavy pack can't starve the
tier to zero before it's reached; `link` chunks and targets are ranked by
`docs_fts` relevance the same way. The "candidate for removal" call on the
symbol tier above turned out to rest on a false premise (filename and
symbol targets are mutually exclusive per file, `index.py:346` — they were
never actually competing for the same slot; symbol targets are simply
rare, ~6% of `code_ref` edges across the checked-in indexes), so it was
**not** removed. Re-measuring the symbol tier and re-running this 20-task
set against the fixed ordering are both still outstanding — see
RETRIEVAL_RANKING_PLAN.md's Follow-ups.

## Next UX work, after the gate

1. Add independent visibility toggles for `code_ref`, co-location, and structural edges; purple code edges can clutter large graphs.
2. Label or arrow directional edges so `code_ref` does not read as undirected.
3. Add extension, discovery-bucket, and connected-component filters.
4. Decide from observed demand whether clicking code nodes should reveal code chunks and internal symbol edges; consider edge bundling only afterward.

## Durability and test prerequisites

See [TESTING.md](TESTING.md) for the fixture corpus requirement and the important distinction between skipped and passed external fixtures. See [INDEXING.md](INDEXING.md) for rebuild/freshness behavior and [ARCHITECTURE.md](ARCHITECTURE.md) for the durable V2–V4 design.