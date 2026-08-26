# Implemented Changes

This document records the follow-up work implemented after the graph and
code-reference feature reached end-to-end functionality.

## Correctness and safety

- `code_ref` edges are now inserted only after their target code file was
  successfully read and added to the index. A read failure cannot leave a
  dangling edge or inflate the reported `code_edges` count.
- Retrieval now validates every indexed source file against its stored hash
  before querying or rendering. Changed, missing, or unreadable files raise
  `IndexStaleError` with a rebuild command instead of silently rendering a
  different section or falling back to a whole file.
- The live viewer sanitizes `marked` output with DOMPurify. If the sanitizer
  CDN is unavailable, it renders escaped source rather than unsanitized HTML.

## Tests and CI

- Added a GitHub Actions pytest workflow at `.github/workflows/test.yml`.
- Added pytest configuration and a test extra (`pip install -e ".[test]"`).
- Added regression coverage for unreadable code targets, stale/deleted source
  files, ambiguous basenames, oversized code-reference hubs, code-tier labels,
  and live-viewer sanitization.
- The existing disposable code fixtures are now collected by pytest.
- External organic/hub/code fixtures report each unavailable prerequisite
  separately under `pytest -ra`; a skipped fixture is explicitly not a pass.
  They require `DOCGRAPH_FIXTURE_REPOS_DIR` and the referenced repositories
  and databases.

## Validation instrumentation

- Retrieval and query logging now emit `tier_detail` for code-reference
  chunks: `filename`, `symbol_target`, `symbol_neighbor`, `symbol_preamble`,
  or `symbol_fallback`.
- `budget_cut` carries the same detail, enabling the ≥20-call study to measure
  filename-only code references, symbol resolution, symbol-neighbor expansion,
  and useful chunks displaced by the token budget independently.

## Documentation

- Updated `README.md` to describe link/code/symbol expansion, code nodes,
  directional `code_ref` edges, viewer sanitization, and index freshness.
- Added durable operational documents:
  - `docs/TESTING.md`
  - `docs/INDEXING.md`
  - `docs/ARCHITECTURE.md`
- Reconciled `docs/V4_NEXT_STEPS.md` with the current graph behavior.
- Reduced `docs/HANDOFF.md` to concise historical notes and links to the
  durable documentation.

## Still pending

- Run and annotate the ≥20-call real-use validation gate. No query-log data
  was available in this workspace, so usefulness has not been claimed.
- Based on that evidence, keep, tune, or remove filename, symbol-target, and
  symbol-neighbor tiers independently.
- Add graph edge toggles, directional indicators, and extension/bucket/
  connected-component filters after the usefulness decision.
