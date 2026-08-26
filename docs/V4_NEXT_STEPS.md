# V4 Next Steps

## Current implementation

V3/V4 graph plumbing is present on `main`:

- referenced code files are surfaced as extension-colored `bucket='code'` nodes;
- directional doc-to-code `code_ref` edges are present in static and live graphs and rendered purple;
- Python code is sliced at def/class boundaries and may use bounded, intra-file `symbol` edges;
- JS/TS/Go/Rust are explicit whole-file fallbacks.

The graph remains file-level. Clicking a code node does not yet expose its chunks or internal symbol edges.

## Validation gate — required before expanding V4

Use `DOCGRAPH_QUERY_LOG` for at least 20 real calls, annotating each selected link/code/symbol-derived chunk as actually used, unused, or uncertain at the time of the call. The log's `tier_detail` field distinguishes code-reference paths. Evaluate independently:

1. filename-only `code_ref` chunks;
2. symbol-resolved `code_ref` chunks;
3. symbol-neighbor expansion; and
4. useful chunks displaced into `budget_cut`.

Do not treat V2–V4 as one tier. Keep, tune, or remove each tier from this evidence. The original 15%-of-packs usefulness threshold is a provisional kill criterion; record any revised threshold before inspecting the results.

## Next UX work, after the gate

1. Add independent visibility toggles for `code_ref`, co-location, and structural edges; purple code edges can clutter large graphs.
2. Label or arrow directional edges so `code_ref` does not read as undirected.
3. Add extension, discovery-bucket, and connected-component filters.
4. Decide from observed demand whether clicking code nodes should reveal code chunks and internal symbol edges; consider edge bundling only afterward.

## Durability and test prerequisites

See [TESTING.md](TESTING.md) for the fixture corpus requirement and the important distinction between skipped and passed external fixtures. See [INDEXING.md](INDEXING.md) for rebuild/freshness behavior and [ARCHITECTURE.md](ARCHITECTURE.md) for the durable V2–V4 design.
