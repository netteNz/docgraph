# DocGraph — Session Handoff

**Last updated**: 2026-08-18

## 2026-08-18 — V2 link edges: added, decision gate still open

Added `kind='link'` edges (directional, doc-level, `MAX_LINK_FANOUT=10`
skip-not-truncate on hub docs) and unconditional one-hop link-neighbor
expansion in `retrieve()` (`MAX_LINK_NEIGHBORS_PER_SEED=5`, ranked below
every seed/co-location neighbor, `provenance="link"` + `via` field). Full
rationale in CLAUDE.md's "Link edges" section (local-only file, not in git
— see `.gitignore`) and README's Design notes.

**Phase 0 audit results** (`scripts/link_audit.py`, run against the three
corpora indexed below):
- trading-dashboard: 0 links in real docs (vendor dirs already excluded) —
  no signal possible.
- rl-stocks: 87 links found, 17 resolved (post-dedup), 13 disjoint — 12 of
  those from a single `docs/INDEX.md` hub (now fully suppressed by the
  fan-out cap), 1 organic.
- coinbase-rl-bot: 6 links, 4 resolved, 2 organic disjoint pairs.

**Status: implemented and fixture-tested, NOT yet validated in real use.**
`tests/run_link_fixtures.py` passes (3/3 organic, 1/1 hub-suppression), but
those fixtures were derived from the same audit that found the pairs — that
confirms the code implements the rule correctly, not that the rule is
useful independent of having been designed around these exact examples.
Decision: don't graduate to weights/hop-2/visualizer, and don't audit more
corpora yet either. Next step is to run this for real (a week of actual
`docgraph_context` use on rl-stocks or coinbase-rl-bot with `provenance`
visible) and watch for two things: does a link-recovered section ever
change what the agent actually does, and does `via` ever surface something
that should've been suppressed. If it's inert or noisy there, kill it
before building the expensive parts.

All three indexes below were already rebuilt this session (`docgraph.index`
rerun after the `links.py` change), so their `edges` tables already have
`kind='link'` rows — no reindex needed before picking this back up.

## What this repo is

`docgraph` is a small local tool: it indexes a repo's markdown corpus into a
SQLite/FTS5 database (`docgraph.index`), serves token-budgeted context packs
from that index (`docgraph.context` / `docgraph.mcp_server`), and renders a
force-directed HTML graph of the corpus — static (`docgraph.visualize`) or
live with retrieval-driven highlighting (`docgraph.serve`).

Modules (`src/docgraph/`):
- `discover.py` — file discovery / bucket classification (root, docs, skills, subdir-allcaps)
- `index.py` — builds the SQLite/FTS5 index. Dedupes byte-identical files, keeping one canonical copy.
- `sections.py` — chunking logic (`is_chunking_candidate`, etc.)
- `context.py` — `retrieve()`: runs FTS retrieval, returns structured per-chunk
  data (path, heading, score, seed/neighbor provenance, resolved body text).
  `build_pack()` is a thin wrapper — `_render(retrieve(...))` — kept for CLI/MCP
  backward compat, returns the same markdown string as before the refactor.
- `mcp_server.py` — MCP server wrapping `build_pack()` as a tool (`docgraph_context`)
- `visualize.py` — static, self-contained D3 HTML graph (file nodes, co-location
  edges, colored by bucket, sized by token count). `graph_data(db_path)` (node/edge
  query + `add_structural_ties`) is factored out and reused by `serve.py` so the two
  rendering paths can't drift on corpus-shape logic.
- `serve.py` (new) — stdlib `http.server` (no new dependency) serving the same
  graph live, plus a task box wired to `context.retrieve()`. Typing a task hits
  `GET /context?task=...&max_tokens=...`, highlights the selected file nodes
  (solid glow = seed match, dashed = co-location neighbor pulled in), and
  renders the pack as formatted markdown (via `marked`, CDN-loaded like D3) in
  a resizable side panel (drag the left edge, or click `⤢` to expand to 85vw).
  Binds `127.0.0.1` by default — local dev tool, no auth.

## Environment notes

This session's work happened on **macOS** (`/Users/nettenz/Projects/docgraph`),
a different machine/environment than the Windows session below (`D:\code\docgraph`).
Both sets of notes are kept — check which one matches your current environment
before reusing a path or command verbatim.

**macOS + Homebrew Python**: `pip install -e .` fails directly with a PEP 668
"externally-managed-environment" error (Homebrew blocks system-wide pip
installs). Use a venv:
```bash
cd /Users/nettenz/Projects/docgraph
python3 -m venv .venv
.venv/bin/pip install -e .
```
Then either `source .venv/bin/activate` first, or call `.venv/bin/python -m docgraph....` directly without activating.

## Live indexes in this directory

| DB file | Source repo | Environment | Registered MCP server name |
|---|---|---|---|
| `db/doordashboard.db` | `~/projects/doordashboard` | macOS | not registered |
| `db/docgraph-trading.db` | `D:\code\web-development\trading-dashboard` | Windows | `docgraph-trading-dashboard` |
| `db/docgraph.db` | `D:\code\agentic-development\reinforcement-learning-stocks` | Windows | `docgraph-rl-stocks` |
| `db/coinbase_rl_bot.db` | `D:\code\agentic-development\coinbase-rl-bot` | Windows | not registered |
| `db/document_parser.db` | `D:\code\microsoft\document_parser` | Windows | not registered |

Windows entries registered via `claude mcp add ... -s user -e PYTHONIOENCODING=utf-8 -- python -m docgraph.mcp_server <repo_root> <db_path>`. Check with `claude mcp list`.

## Rebuilding an index

Run from **this directory** (`docgraph`'s own repo root — `D:\code\docgraph` on
Windows, `/Users/nettenz/Projects/docgraph` on macOS), not from the target repo —
`index.py`/`context.py` take a relative db path, and running from the wrong
cwd silently creates/opens a second, empty db file instead of erroring.

```bash
# macOS (this session)
cd /Users/nettenz/Projects/docgraph
.venv/bin/python -m docgraph.index ~/projects/doordashboard db/doordashboard.db

# Windows (prior session)
cd /d/code/docgraph
python -m docgraph.index /d/code/web-development/trading-dashboard db/docgraph-trading.db
python -m docgraph.index /d/code/agentic-development/reinforcement-learning-stocks db/docgraph.db
```

## Querying context directly (outside the MCP tool)

```bash
# macOS
.venv/bin/python -m docgraph.context ~/projects/doordashboard db/doordashboard.db "<task description>" --max-tokens 8000

# Windows — PYTHONIOENCODING=utf-8 required (see gotcha #2 below)
PYTHONIOENCODING=utf-8 python -m docgraph.context /d/code/web-development/trading-dashboard db/docgraph-trading.db "<task description>" --max-tokens 8000
```

## Visualizing a graph

Static (no server):
```bash
python -m docgraph.visualize db/docgraph-trading.db graphs/trading_graph.html --title "trading-dashboard"
```
Open the `.html` output directly in a browser. Nodes = files (not chunks),
colored by discovery bucket (gray=root, blue=docs, purple=skills,
green=subdir-allcaps), sized by token count, edges = co-location
relationships. Deliberately a structural/corpus-shape view, not a retrieval
view — doesn't show chunk-level (H2/H3) structure or FTS relevance.

Live (task-driven retrieval highlighting):
```bash
.venv/bin/python -m docgraph.serve ~/projects/doordashboard db/doordashboard.db --port 8765
```
Open `http://127.0.0.1:8765/` — same graph, plus a task box that runs real
retrieval and highlights the selected files, with the rendered pack in a
resizable side panel. This is the "V1 web graph" both README status notes and
prior versions of this handoff called out as not-yet-built.

## Known gotchas (hit these already, don't re-debug them)

0. **macOS + Homebrew Python: `pip install -e .` fails** with a PEP 668
   "externally-managed-environment" error. Fix: use a venv (`.venv/bin/pip
   install -e .`), see Environment notes above. macOS-specific.
1. **Relative db path + wrong cwd** → `sqlite3.OperationalError: no such
   table: docs_fts`. sqlite3 silently creates an empty file rather than
   erroring on a missing path, so this manifests as a mysterious missing-table
   error, not a missing-file error. Fix: always run from this repo's own
   root (`D:\code\docgraph` on Windows, `/Users/nettenz/Projects/docgraph` on
   macOS), or pass the full path to the db. Environment-agnostic.
2. **UnicodeEncodeError on `→` / em-dashes** when running `context.py`'s CLI
   directly on a Windows console. Fix: `PYTHONIOENCODING=utf-8`. Not needed
   when going through the MCP server (already set in its registration), and
   not observed on macOS. Windows-specific.
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

## State as of last run — Windows session (trading-dashboard index)

7 files indexed, 7 co-location edges (post-dedup): `ARCHITECTURE.md`,
`CLAUDE.md`, `README.md`, `WIRING_TODO.md` (all `root` bucket), plus 3 files
under `.agents\skills\indicator-combo-builder\` (`skills` bucket:
`SKILL.md`, `references/combos.md`, `references/implementation.md`).

## State as of last run — macOS session (doordashboard index)

5 files indexed, 12 co-location edges → `db/doordashboard.db`, source
`~/projects/doordashboard`. Verified end-to-end this session: `.venv`
install, `docgraph.index`, `docgraph.context` CLI, `docgraph.visualize`
(static), and `docgraph.serve` (live — `/`, `/context?task=...` including
missing-task 400, bad `max_tokens` 400, unknown-route 404, empty-match
graceful state, and concurrent-request safety all manually checked).
Not yet registered as an MCP server on this machine — only indexed/served
directly so far.

## Code changes made this session (macOS, refactor + new feature)

- `context.py`: extracted `retrieve(repo_root, db_path, task, max_tokens,
  seed_limit) -> dict` (structured chunks with path/heading/score/rank/
  provenance/body) out of `build_pack`. `build_pack` is now
  `_render(retrieve(...))` — same public signature/return type (`str`), so
  `mcp_server.py` and the CLI needed no changes.
- `visualize.py`: extracted `graph_data(db_path) -> dict` (node/edge query +
  `add_structural_ties`) out of `build_html`, pure refactor, output
  byte-identical. `serve.py` reuses it.
- `serve.py` (new): stdlib `http.server`-based live graph server — see module
  description above. Includes: retrieval highlighting (seed vs. neighbor
  provenance, visually distinct), markdown-rendered pack panel (`marked` via
  CDN), resizable/expandable panel (drag handle + `⤢` toggle).
