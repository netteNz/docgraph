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
   retrieval gap. Full `budget_cut` review (787 candidates) is not done;
   only 15 were reviewed.

Not yet done: removing/reranking the symbol tier, fixing in-tier chunk
ordering (`ORDER BY target` / `ORDER BY c.id` carry no relevance signal),
and re-running this same 20-task set to confirm a fix changes outcomes, not
just ranking theory.

## Next UX work, after the gate

1. Add independent visibility toggles for `code_ref`, co-location, and structural edges; purple code edges can clutter large graphs.
2. Label or arrow directional edges so `code_ref` does not read as undirected.
3. Add extension, discovery-bucket, and connected-component filters.
4. Decide from observed demand whether clicking code nodes should reveal code chunks and internal symbol edges; consider edge bundling only afterward.

## Durability and test prerequisites

See [TESTING.md](TESTING.md) for the fixture corpus requirement and the important distinction between skipped and passed external fixtures. See [INDEXING.md](INDEXING.md) for rebuild/freshness behavior and [ARCHITECTURE.md](ARCHITECTURE.md) for the durable V2–V4 design.