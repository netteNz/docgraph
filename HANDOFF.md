# DocGraph — Session Handoff

**Last updated**: 2026-08-17

## What this repo is

`docgraph` is a small local tool: it indexes a repo's markdown corpus into a
SQLite/FTS5 database (`docgraph.index`), serves token-budgeted context packs
from that index (`docgraph.context` / `docgraph.mcp_server`), and renders a
force-directed HTML graph of the corpus (`docgraph.visualize`).

Modules (`src/docgraph/`):
- `discover.py` — file discovery / bucket classification (root, docs, skills, subdir-allcaps)
- `index.py` — builds the SQLite/FTS5 index. Dedupes byte-identical files, keeping one canonical copy.
- `sections.py` — chunking logic (`is_chunking_candidate`, etc.)
- `context.py` — CLI + `build_pack()`: keyword-ranked, token-budgeted markdown context pack for a task string
- `mcp_server.py` — MCP server wrapping `context.py`'s `build_pack()` as a tool (`docgraph_context`)
- `visualize.py` — renders a self-contained D3 HTML graph (file nodes, co-location edges, colored by bucket, sized by token count)

## Two live indexes in this directory

| DB file | Source repo | Registered MCP server name |
|---|---|---|
| `docgraph-trading.db` | `D:\code\web-development\trading-dashboard` | `docgraph-trading-dashboard` |
| `docgraph.db` | `D:\code\agentic-development\reinforcement-learning-stocks` | `docgraph-rl-stocks` |

Both registered via `claude mcp add ... -s user -e PYTHONIOENCODING=utf-8 -- python -m docgraph.mcp_server <repo_root> <db_path>`. Check with `claude mcp list`.

## Rebuilding an index

Run from **this directory** (`D:\code\docgraph`), not from the target repo —
`index.py`/`context.py` take a relative db path, and running from the wrong
cwd silently creates/opens a second, empty db file instead of erroring.

```bash
cd /d/code/docgraph
python -m docgraph.index /d/code/web-development/trading-dashboard docgraph-trading.db
python -m docgraph.index /d/code/agentic-development/reinforcement-learning-stocks docgraph.db
```

## Querying context directly (outside the MCP tool)

```bash
cd /d/code/docgraph
PYTHONIOENCODING=utf-8 python -m docgraph.context /d/code/web-development/trading-dashboard docgraph-trading.db "<task description>" --max-tokens 8000
```

`PYTHONIOENCODING=utf-8` is required on this Windows/PowerShell console —
without it, output containing non-ASCII characters (em dashes, arrows) crashes
with `UnicodeEncodeError` on the default cp1252 codepage.

## Visualizing a graph

```bash
cd /d/code/docgraph
python -m docgraph.visualize docgraph-trading.db trading_graph.html --title "trading-dashboard"
python -m docgraph.visualize docgraph.db rl_stocks_graph.html --title "reinforcement-learning-stocks"
```

Open the `.html` output directly in a browser — no server needed. Nodes =
files (not chunks), colored by discovery bucket (gray=root, blue=docs,
purple=skills, green=subdir-allcaps), sized by token count, edges =
co-location relationships. Deliberately a structural/corpus-shape view, not a
retrieval view — doesn't show chunk-level (H2/H3) structure or FTS relevance.
Both `trading_graph.html` and `rl_stocks_graph.html` already exist in this
directory from the last run.

## Known gotchas (hit these already, don't re-debug them)

1. **Relative db path + wrong cwd** → `sqlite3.OperationalError: no such
   table: docs_fts`. sqlite3 silently creates an empty file rather than
   erroring on a missing path, so this manifests as a mysterious missing-table
   error, not a missing-file error. Fix: always run from `D:\code\docgraph`,
   or pass the full path to the db.
2. **UnicodeEncodeError on `→` / em-dashes** when running `context.py`'s CLI
   directly on this Windows console. Fix: `PYTHONIOENCODING=utf-8`. Not
   needed when going through the MCP server (already set in its registration).
3. **Don't index the tool's own output files.** Earlier, a snapshot of a
   `docgraph.context` run was saved as `docgraph-context.md` inside the
   *target* repo root (`trading-dashboard`). Re-running `docgraph.index`
   picked it up as a corpus file, and because it literally contained the next
   query's task string verbatim, it self-matched and dominated/degenerated
   the next context-pack result (1 chunk instead of ~10). Fixed by deleting it
   before reindexing. If you want to keep a saved snapshot like that around,
   keep it *outside* whatever directory `docgraph.index` points at, or
   gitignore + also exclude it from indexing manually.
4. **Byte-identical duplicate files** (e.g. a skill mirrored under both
   `.claude/skills/...` and `.agents/skills/...`) used to show up twice in
   context packs and as two identical nodes in the graph. `index.py` was
   patched this session to dedupe byte-identical files, keeping one canonical
   copy. Confirmed fixed via both `docgraph.context` (single copy of
   `indicator-combo-builder` content) and `docgraph.visualize` (single
   `skills` cluster in the graph, not two).

## State as of last run (trading-dashboard index)

7 files indexed, 7 co-location edges (post-dedup): `ARCHITECTURE.md`,
`CLAUDE.md`, `README.md`, `WIRING_TODO.md` (all `root` bucket), plus 3 files
under `.agents\skills\indicator-combo-builder\` (`skills` bucket:
`SKILL.md`, `references/combos.md`, `references/implementation.md`).
