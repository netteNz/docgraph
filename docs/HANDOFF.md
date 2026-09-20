# Historical handoff notes

This file is deliberately a short historical record, not operational documentation. Durable instructions now live in:

- [Testing](TESTING.md)
- [Indexing and freshness](INDEXING.md)
- [Architecture](ARCHITECTURE.md)
- [V4 next steps](V4_NEXT_STEPS.md)
- [Retrieval ranking](RETRIEVAL_RANKING_PLAN.md)

## Timeline

- **2026-08-18:** V2 added directional Markdown `link` edges and bounded link expansion.
- **2026-08-20:** V3 added directional doc-to-code `code_ref` edges and reference-driven code nodes.
- **2026-08-22:** V4 added Python def/class slicing and bounded intra-file symbol expansion; static and live graph code nodes/`code_ref` edges were later reintroduced and color-coded.
- **2026-08-25:** Retrieval freshness validation, dangling-code-edge protection, sanitized live Markdown rendering, pytest/CI, and explicit external-fixture reporting were added.
- **2026-09-20:** `code_ref` and `link` tiers switched from document/alphabetical
  ordering to relevance ranking (`code_fts`/`docs_fts`), the code tier got a
  reserved budget share so it can't be starved to zero before it's reached,
  and a rank-formula collision at 100+ chunks in one file was widened. See
  [RETRIEVAL_RANKING_PLAN.md](RETRIEVAL_RANKING_PLAN.md).

The historical features are implemented but their real-use usefulness study is still open; follow the independent-tier validation gate in [V4_NEXT_STEPS.md](V4_NEXT_STEPS.md).
