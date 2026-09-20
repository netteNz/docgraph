# Indexing and freshness

Build from the DocGraph repository root:

```bash
python -m docgraph.index /path/to/source-repo db/source-repo.db
```

Indexes are rebuild-only and contentless. SQLite retains hashes for each
indexed Markdown and reference-driven code file, while retrieval rereads the
source repository. A changed, missing, or unreadable file raises an
`IndexStaleError`; rebuild the index instead of receiving a silently changed
chunk or whole-file fallback.

Keep query logs and generated context packs outside indexed repositories so
they do not become retrievable source material after a rebuild.

`code_fts` stores a term index over code bodies (used only to rank code_ref
results, never to seed or gate them), so a code-heavy repo's `.db` grows
noticeably.
