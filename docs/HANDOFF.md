# Historical handoff notes

This file is deliberately a short historical record, not operational documentation. Durable instructions now live in:

- [Testing](TESTING.md)
- [Indexing and freshness](INDEXING.md)
- [Architecture](ARCHITECTURE.md)
- [V4 next steps](V4_NEXT_STEPS.md)

## Timeline

- **2026-08-18:** V2 added directional Markdown `link` edges and bounded link expansion.
- **2026-08-20:** V3 added directional doc-to-code `code_ref` edges and reference-driven code nodes.
- **2026-08-22:** V4 added Python def/class slicing and bounded intra-file symbol expansion; static and live graph code nodes/`code_ref` edges were later reintroduced and color-coded.
- **2026-08-25:** Retrieval freshness validation, dangling-code-edge protection, sanitized live Markdown rendering, pytest/CI, and explicit external-fixture reporting were added.
- **2026-09-03:** Code-tier ranking fix (oversized-whole-file demotion +
  breadth-first expansion) shipped and gate-rerun; follow-up log-replay
  experiments settled the per-target-cap and symbol-tier-reserve questions
  it left open; a second, structurally opposite corpus (`D:\code\audio`,
  no git, no `docs/`, many disconnected sibling subprojects) surfaced a
  basename-collision resolution limit and a silent-fallback-with-zero-edges
  gap. See [V4_NEXT_STEPS.md](V4_NEXT_STEPS.md) for all of it.
- **2026-10-03:** V5 plan audited and amended (`V5_PLAN.md`); WS1 (tiered basename disambiguation) implemented with resolution counters and visualizer findings — gate run (bars 1-3, 5a met; 5b fails as predicted; bar 4 awaits WS3) — see [V4_NEXT_STEPS.md](V4_NEXT_STEPS.md).
- **2026-11-23:** Obsidian support (`--all-markdown` → bucket `vault`; `[[wikilinks]]` resolved by unique-shallowest stem into `link` edges; `%20` links decoded; graph draws `link` edges), WS3 weak-pack signal (`confidence` key + `> WEAK PACK` render line + viewer banner), WS4 `code_tier_room` (returned, logged, reported). V5 bar 4 now met; in-degree demotion (pending decision (b)) replayed and **not supported** — see [V4_NEXT_STEPS.md](V4_NEXT_STEPS.md). Known pre-existing failure: `run_link_fixtures.py` code fixture "exit signal todo plan" (`analyze_reward_divergence.py` is a candidate but budget-cut by the 2026-09-03 oversized-whole-file demotion, by design; the fixture only checks `chunks`).
- **2026-11-23 (later):** Qualified-path code-ref resolution (`rooted`/`suffix`; stale qualifier → dead; −4 archive edges, `experiments.py` in-degree unchanged) and heading-relevance ordering of the code tier (`CODE_HEADING_RELEVANCE`, match-count banded) — gate rerun 5/20 held; replay was post-hoc tuned on the v3 log, so out-of-sample evidence is still owed. See [V4_NEXT_STEPS.md](V4_NEXT_STEPS.md).

The historical features are implemented but their real-use usefulness study is still open; follow the independent-tier validation gate in [V4_NEXT_STEPS.md](V4_NEXT_STEPS.md).
