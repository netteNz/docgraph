# V4 Next Steps — Graph Plumbing & MCP Registration

Independent tracking doc, separate from `docs/HANDOFF.md`'s session log.
HANDOFF.md records what V4 *did*; this records what's still *open* — pick
up either thread without re-deriving it from the other.

## Resolved (2026-08-22, macOS session)

### 1. Graph plumbing — the double-count/self-loop concern was a non-issue; the real bug was elsewhere

Neither of this item's original worries panned out on inspection:
`graph_data(db_path)` selects from `docs`, never `chunks`, so chunk-level
slicing can't double-count; its edge query hard-filters `kind = 'colocation'`,
so `symbol` self-loops were never reachable in the first place.

The actual defect was one level up and predates V4 — it landed in V3.
`_build_code_edges` inserts referenced code files into `docs` with
`bucket='code'`, and `graph_data`'s query had no bucket filter, so every
referenced code file rendered as a file-level graph node with: no color
(fell through to the same gray as `root`), no legend row, a dangling
`#glow-code` filter reference on hover, and — since code docs have zero
`colocation` edges of their own — a fabricated `add_structural_ties`
hub-and-spoke edge invented per directory. **Fixed**: `graph_data`'s query
in `visualize.py` now filters `WHERE bucket != 'code'`; `serve.py` inherits
the fix for free since it imports `graph_data` directly. Verified: reindexed
rl-stocks (65 files), `graph_data()` returns zero `bucket='code'` nodes, node
count matches the markdown-doc count exactly.

The **decision needed** ("does a chunk-level detail view for code files
belong in `serve.py`?") is still genuinely open — not resolved by this fix,
just no longer confused with it. Still don't build it speculatively; no
audit has been done on whether anyone wants it. See "Open" below.

### 2. Path portability — the actual root cause of most of this doc's original friction

Not something this doc originally tracked, but worth recording here since it
explains why several items above were harder to verify than they should
have been: `docs.path` (and everything derived from it) was stored via
`str(path.relative_to(repo_root))`, which renders with the OS-native
separator — the same repo indexed on Windows vs. macOS produced a different
database (backslash- vs forward-slash-joined paths), and every fixture,
JSON/MCP response, and filename-mention match inherited the split.
**Fixed**: `index.py`'s four path-to-string sites now use `.as_posix()`
(`PurePosixPath` where a re-derived `.parent` was involved); `links.py`'s
`resolve_link` and `code_refs.py`'s `resolve_code_ref` switched from
`os.path` to `posixpath` accordingly. `docs.path`/`edges.source`/`target`
are now canonically forward-slash on every platform. `run_code_fixtures.py`
(platform-clean) re-verified 10/10 after the change.

One correction worth recording so it isn't miscredited later: don't read
the `code_ref` edge count as evidence of this fix mattering. Checked
empirically — `ntpath.normpath`/`ntpath.basename` already treat `/` as a
valid separator and convert it, so `resolve_code_ref`'s original Windows-run
matching against forward-slash doc mentions was never actually broken by
this. (rl-stocks did reindex at 65 files / 84 `code_ref` edges here vs. the
72 / 94 HANDOFF's Windows run reported — that's corpus drift, the repo has
moved on since, not a matching-behavior change.)

`tests/fixtures/link_fixtures.json` was ported to be genuinely portable as
part of this: forward-slash expected paths, and `repo_root` replaced with a
short `repo` name resolved against a `DOCGRAPH_FIXTURE_REPOS_DIR` env var at
runtime (so the same file is valid on any machine with the referenced repos
checked out locally, no per-OS fork). `run_link_fixtures.py` now skips
(doesn't fail) a fixture whose repo/db isn't present on the running machine
— `coinbase-rl-bot` and its db aren't present on this machine, so those 2
of 7 fixtures skip cleanly; the other 5 (1 organic, 1 hub, 3 code) pass. One
fixture (`context map architecture data flow dependencies`, a negative
control) needed tightening from "zero `code_ref` chunks in the pack" to
"zero `code_ref` chunks with `via=CLAUDE.md`" — real corpus drift added a
`README.md` that now co-seeds the same task and has its own unrelated, real
`code_ref` edges; `CLAUDE.md` itself still correctly has none.

### 3. MCP registration — confirmed via the registered tool, not just the CLI

Registered `rl-stocks-docs` (macOS, `-e DOCGRAPH_QUERY_LOG=...` included at
registration time — see "Open" item 2 below for why that flag matters) and
confirmed via a real call through the registered tool (not the CLI) that
`docgraph_context` returns sliced def/class-level chunks, not whole files —
e.g. a 26-token `_active_news_cols` chunk selected in preference to the
1235-token whole `scripts/backtest_exit_rules.py`. This was this doc's one
previously-unverified checklist item.

(Along the way: the `mcp` SDK had moved to 2.0.0, which dropped
`mcp.server.fastmcp` — unrelated to anything above, just an unpinned
dependency drifting. Pinned `mcp<2.0` in `pyproject.toml`.)

The Windows-side servers (`docgraph-trading-dashboard`, `docgraph-rl-stocks`)
and `db/docgraph-trading.db`'s rebuild status are unchanged by this session
— still open, see below.

## Open

### 1. V4's real decision: chunk-level detail view — still not resolved, still don't build it speculatively

Unchanged from before: does a chunk-level detail view for code files belong
in `serve.py` at all, or does V4's value stay entirely in `docgraph_context`
output? No audit has been done on whether anyone actually wants this. If the
answer turns out to be "yes, worth it," the natural extension is a
node-expand-on-click for `bucket='code'` nodes showing their chunks +
`symbol` edges as a small internal subgraph, reusing `serve.py`'s existing
task-box/highlight machinery rather than a new page.

A related, separate decision this doesn't resolve either: whether to
surface `code_ref` edges *themselves* in the file-level graph (distinct
from adding chunk-level nodes) — that's its own feature with its own audit,
not a reason to hold open the `bucket='code'` node-filter fix above.

### 2. The V2/V3/V4 validation gate — pre-registered kill criterion, not yet run

Every one of V2, V3, and V4 shipped with the identical caveat —
"implemented and fixture-tested, NOT yet validated in real use." V2's
original entry set an explicit decision gate (a week of real use, kill it
if inert) that was never actually run before V3 and V4 built on top of it.
Presence in a pack isn't evidence of usefulness on its own, and provenance
alone can't show what a link/code_ref/symbol tier displaced from the
budget — so before starting the week, the threshold and the counterfactual
both need to exist:

> **Kill criterion (write this down before the week starts, not after):**
> Over ≥20 real `docgraph_context` calls on rl-stocks, if fewer than 15% of
> packs contain a link/code_ref/symbol-provenance chunk that gets annotated
> — at the time, next to the log entry, not reconstructed later — as
> *actually used* (read, referenced, or acted on, not merely present), V2–V4
> retrieval is inert. Kill it: strip the three tiers back to V1's seed +
> colocation, keep the schema (no migration needed either way), stop
> building on top of it.
>
> The 20/15% numbers are a starting proposal, not sacred — the point is that
> *some* number is committed now, before the data exists to rationalize a
> threshold after the fact.

**Built, not yet run**: `context.retrieve()` now has an opt-in, append-only
JSONL query logger (`DOCGRAPH_QUERY_LOG` env var, off by default, never
breaks retrieval on a write failure, written outside any indexed repo).
Each entry captures selected chunks (`path`/`heading`/`provenance`/`via`/
`rank`/`token_est`) *and* the counterfactual: candidates that scored into
ranking but lost to the token budget, tagged the same way — this is what
makes "what did V2–V4 add vs. what would V1 alone have returned" computable
offline from the log, not just "was something with a fancy provenance tag
present." `*.jsonl` is gitignored.

**The one easy way to silently fail this**: `DOCGRAPH_QUERY_LOG` only
reaches the MCP server if passed via `-e` at `claude mcp add` registration
time — it's a process Claude Code spawns, not a child of your interactive
shell, so exporting it in a terminal does nothing for real MCP-tool use.
The `rl-stocks-docs` registration above includes it; **re-registering
without `-e` produces an empty log, not an error** — verify a few real
calls actually produce log lines before trusting a week of silence.

**Next**: run it for real on rl-stocks for a week (or however long it takes
to hit ≥20 calls), annotate usefulness in the log as each pack is actually
consulted, then apply the threshold above and record the kill-or-keep
decision in `docs/HANDOFF.md` with the same discipline as V2/V3/V4's own
entries — not left implicit.

### 3. MCP registration — `db/docgraph-trading.db` still not rebuilt

Unchanged from before this session. `docs/HANDOFF.md`'s live-index table
(Windows-side) lists:

| DB file | Registered MCP server name |
|---|---|
| `db/docgraph-trading.db` | `docgraph-trading-dashboard` |
| `db/docgraph.db` | `docgraph-rl-stocks` |

`db/docgraph-trading.db` (trading-dashboard) still reflects V3's whole-file
code inclusion, even though the Phase 0 audit found it has a
chunking-candidate file too (`backend/indicators/engine.py`, 16 chunks).

**Open questions, not yet resolved:**
- Should `db/docgraph-trading.db` be rebuilt now to get V4's benefit on
  `engine.py`, or left alone until there's a concrete task that would
  exercise it?
- `db/coinbase_rl_bot.db` and `db/document_parser.db` are indexed but not
  registered as MCP servers at all (per HANDOFF.md) — out of scope for V4
  specifically, noted here only so it isn't conflated with the item above.

## Verification checklist for whoever picks this up

- [x] Confirm `docgraph_context` via a registered MCP tool (not just the
      CLI) returns sliced code chunks. Done this session on macOS via
      `rl-stocks-docs`; the Windows-side `docgraph-rl-stocks` /
      `docgraph-trading-dashboard` registrations are unverified by this.
- [x] Decide file-level-vs-chunk-level scope for the *node-filter* bug —
      resolved as "filter code nodes out," see Resolved item 1. The
      *speculative feature* decision (a chunk-level detail view) is
      unchanged and still open, see Open item 1.
- [ ] If trading-dashboard gets rebuilt, re-run `tests/run_link_fixtures.py`
      after, same regression-check discipline used for rl-stocks.
- [ ] Run the kill-criterion week (Open item 2) and record the decision.
