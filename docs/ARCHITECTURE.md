# Architecture

Discovery indexes documentation into SQLite/FTS5, splitting oversized Markdown
at headings. The index records three retrieval edge families:

- `colocation`: bidirectional, immediate-directory relationships;
- `link`: directional Markdown links, capped per source document;
- `code_ref`: directional documentation-to-code references, optionally
  symbol-resolved to a Python def/class chunk.

Referenced code files are `bucket='code'` nodes without FTS rows, so they are
reachable only through `code_ref`. Python receives AST-based def/class slicing
and bounded intra-file `symbol` edges; JS/TS/Go/Rust remain whole-file targets.
All hub policies are skip-not-truncate.
