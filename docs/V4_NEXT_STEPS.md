# V4 Next Steps — Graph Plumbing & MCP Registration

Independent tracking doc, separate from `docs/HANDOFF.md`'s session log.
HANDOFF.md records what V4 *did*; this records what's still *open* — pick
up either thread without re-deriving it from the other.

## Open

### 1. Graph plumbing (`visualize.py` / `serve.py`) doesn't know about V4 yet

Both are explicitly **file-level** graphs (per `CLAUDE.md`: "file-level (not
chunk-level) D3 force-directed graphs"). V4 introduces two things neither
has ever had to represent:

- **Chunk-level code nodes.** A code file that used to be one node with one
  `code_ref` edge in is now potentially N chunks (preamble + defs/methods).
  `graph_data(db_path)` currently queries at the `docs` level, so a sliced
  file still renders as a single node — this is *probably* fine for the
  file-level view's purpose (corpus-shape overview), but worth confirming
  `graph_data`'s node/edge query doesn't silently double-count or drop
  anything now that `chunks` has multiple rows per code doc.
- **`kind='symbol'` edges are intra-file.** At file-level granularity every
  symbol edge is a self-loop (source doc == target doc) and would either
  need to be filtered out of the file-level graph entirely (safest,
  matches "this view doesn't show chunk-level structure" already being
  true for markdown H2/H3 chunks) or surfaced some other way.

**Decision needed**: does a chunk-level detail view for code files belong
in `serve.py` at all, or does V4's value stay entirely in `docgraph_context`
output and the graph stays a corpus-shape tool that's deliberately blind to
sub-file structure (consistent with how it already treats markdown
sections)? No audit has been done on whether anyone actually wants this —
don't build it speculatively.

If the answer turns out to be "yes, worth it": the natural extension is a
node-expand-on-click for `bucket='code'` nodes showing their chunks +
`symbol` edges as a small internal subgraph, reusing `serve.py`'s existing
task-box/highlight machinery rather than a new page.

### 2. MCP registration — rebuilt index, registered servers not yet confirmed current

`docs/HANDOFF.md`'s live-index table lists these registered servers:

| DB file | Registered MCP server name |
|---|---|
| `db/docgraph-trading.db` | `docgraph-trading-dashboard` |
| `db/docgraph.db` | `docgraph-rl-stocks` |

`db/docgraph.db` (rl-stocks) was rebuilt during V4 implementation and is
current. `db/docgraph-trading.db` (trading-dashboard) was **not**
rebuilt — it still reflects V3's whole-file code inclusion, even though the
Phase 0 audit found it has a chunking-candidate file too
(`backend/indicators/engine.py`, 16 chunks).

**Open questions, not yet resolved:**
- Does `claude mcp list` need anything re-registered, or does the existing
  registration transparently pick up the rebuilt `db/docgraph.db` on next
  call (retrieval opens a fresh sqlite3 connection per `docgraph_context`
  call — no server restart should be needed, but this hasn't been verified
  against a live registered session, only via the CLI directly)?
- Should `db/docgraph-trading.db` be rebuilt now to get V4's benefit on
  `engine.py`, or left alone until there's a concrete task that would
  exercise it?
- `db/coinbase_rl_bot.db` and `db/document_parser.db` are indexed but not
  registered as MCP servers at all (per HANDOFF.md) — out of scope for V4
  specifically, noted here only so it isn't conflated with the two above.

## Verification checklist for whoever picks this up

- [ ] Confirm `docgraph_context` via the registered `docgraph-rl-stocks`
      MCP tool (not just the CLI) returns sliced code chunks, to rule out
      any server-side caching/staleness.
- [ ] Decide file-level-vs-chunk-level scope for `visualize.py`/`serve.py`
      before writing any code for it — this is a design question, not an
      implementation one yet.
- [ ] If trading-dashboard gets rebuilt, re-run `tests/run_link_fixtures.py`
      after, same regression-check discipline used for rl-stocks.
