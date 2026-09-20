# Architecture

Discovery indexes documentation into SQLite/FTS5, splitting oversized Markdown
at headings. The index records three retrieval edge families:

- `colocation`: bidirectional, immediate-directory relationships;
- `link`: directional Markdown links, capped per source document;
- `code_ref`: directional documentation-to-code references, optionally
  symbol-resolved to a Python def/class chunk.

Referenced code files are `bucket='code'` nodes with no `docs_fts` row, so a
task query can never make one a *seed* — they are reachable only through
`code_ref`. They do have their own `code_fts` table (added alongside the
`code_ref` tier's relevance ranking — see
[RETRIEVAL_RANKING_PLAN.md](RETRIEVAL_RANKING_PLAN.md)), used only to rank
*which* `code_ref` candidate wins a slot, never to admit one on its own.
Python receives AST-based def/class slicing and bounded intra-file `symbol`
edges; JS/TS/Go/Rust remain whole-file targets. All hub policies are
skip-not-truncate, and both the `code_ref` and `link` tiers rank their
candidates (and their in-target chunk pick) by FTS relevance rather than
document or alphabetical order.
