# DocGraph — Session Handoff

**Last updated**: 2026-08-22

## 2026-08-22 — link fixtures actually run (not just skipped), stale dbs rebuilt

Context: user asked to move from "read the session log" to "actual testing."
Ran both test scripts fresh.

`tests/run_code_fixtures.py`: 10/10 pass, no external dependency (synthetic
fixtures).

`tests/run_link_fixtures.py`: all 7 fixtures were **skipping**, not
passing — `DOCGRAPH_FIXTURE_REPOS_DIR` wasn't set in this shell. On this
Windows machine both referenced repos live under one common parent:
```bash
export DOCGRAPH_FIXTURE_REPOS_DIR=/d/code/agentic-development
```
(contains both `reinforcement-learning-stocks` and `coinbase-rl-bot`).
Setting it unmasked real failures, not a clean pass: 4/7 fixtures failed
because `db/docgraph.db` (last built 2026-08-21) and
`db/coinbase_rl_bot.db` (last built 2026-08-18) were stale relative to
current repo state on disk — expected files
(`docs/SENTIMENT_INTEGRATION.md`, `scripts/analyze_reward_divergence.py`,
`agent-api/api/main.py`) all still exist in the source repos, confirming
this was index drift, not a code regression. Rebuilt both:
```bash
python -m docgraph.index /d/code/agentic-development/reinforcement-learning-stocks db/docgraph.db
python -m docgraph.index /d/code/agentic-development/coinbase-rl-bot db/coinbase_rl_bot.db
```
`db/docgraph.db`: 72 files, 104 co-location edges, 2 link edges, 91
code_ref edges, 37 code files, 542 symbol edges.
`db/coinbase_rl_bot.db`: 9 files, 26 co-location edges, 4 link edges, 21
code_ref edges, 10 code files, 160 symbol edges.
After rebuild: **7/7 link fixtures pass** (3 organic, 1 hub-suppression, 3
code). Takeaway for next session: always export
`DOCGRAPH_FIXTURE_REPOS_DIR` before trusting a "skip" result, and rebuild
`db/docgraph.db`/`db/coinbase_rl_bot.db` if it's been more than a day or
two since the last index run against those repos — they drift.

## 2026-08-22 — rl-stocks reindex driven through the live visualizer in Chrome

Context: after rebuilding `db/docgraph.db` (see the fixtures entry above),
user asked to actually exercise the visualizer against it rather than just
trust the fixture pass — this is the largest corpus the graph has been
rendered against yet (72 markdown files + 37 `code_ref`-referenced code
files = 109 nodes, 164 edges).

Served it live (`python -m docgraph.serve
/d/code/agentic-development/reinforcement-learning-stocks db/docgraph.db
--port 8765`) and drove it in Chrome (file:// URLs are blocked by the
extension — must use a real served URL). Checked three things:

1. **Rendering at scale**: all 109 nodes/164 edges draw correctly, code
   files colored by extension. At full zoom-out the graph reads as a dense
   tangle of long-range purple `code_ref` lines — legible once zoomed in or
   nodes dragged apart, not a bug, but a real UX ceiling: this corpus is
   already the densest tested and it only gets worse with size. Worth
   revisiting (e.g. edge bundling, collapsing code_ref lines, or a
   toggle to hide them) if a bigger corpus gets indexed next.
2. **Live retrieval highlighting**: typed the task `"exit signal todo
   plan"` (same task as the `code` bucket's fixture) into the task box —
   correctly seeded `EXIT_SIGNAL_TODO.md`, rendered the markdown pack panel
   (13 chunks, ~8000 token budget), and highlighted matching nodes with
   distinct seed (green glow) vs. neighbor (gold ring) styling, matching
   what `run_link_fixtures.py` already asserted structurally.
3. **Console**: three `[EXCEPTION] "message channel closed..."` entries
   appeared — this is standard Chrome-extension messaging noise (from the
   automation extension itself), not an app error; nothing else logged.

**No functional bugs found.** Verified end-to-end: index rebuild → live
serve → real browser interaction → retrieval → visual highlight, all
correct on the largest corpus tested so far.

## 2026-08-22 — chunking-ui indexed + registered, code_ref semantics documented, code files added as extension-colored graph nodes

Context: user asked to index a new repo (`~/projects/azure-development/chunking-ui`,
a small RAG POC with Chainlit UI), then walked through how `code_ref` edges
work, then asked for that to be reflected visually — code files should be
real nodes on the graph, colored by extension, not invisible.

**Indexed and registered `chunking-ui`**: `db/chunking-ui.db` — 7 files, 18
co-location edges, 2 link edges, 4 `code_ref` edges, 3 code files indexed, 12
`symbol` edges. Registered as MCP server `chunking-ui-docs`; first
registration used a relative `.venv/bin/python` command (only resolves if
the MCP server happens to be spawned from `~/Projects/docgraph`'s cwd) —
removed and re-registered with the absolute interpreter path
(`/Users/nettenz/Projects/docgraph/.venv/bin/python`) to avoid a
launch-cwd-dependent failure. Spot-checked retrieval quality directly via
`docgraph.context` before trusting it: a specific query ("how does semantic
re-ranking work") correctly top-ranked `implementation_plan.md`; an
unrelated query ("kubernetes deployment yaml") correctly returned 0 chunks
(no false positives); an AND-matched query ("metadata filtering") correctly
preferred the doc that actually proposes that feature over a more tangential
concepts doc.

**Code files are now real graph nodes, colored by extension** — previously
`bucket='code'` doc rows were filtered out of `graph_data()` entirely (see
the 2026-08-22 entry above this one: that filter was a *fix* for a different
bug, fabricated structural edges onto code files that had no edges of their
own — but the side effect was code files never appearing as nodes at all,
even once they *did* have real `code_ref` edges from V3/V4). Changed
`visualize.py`'s `graph_data()` to include all `docs` rows again, derive a
synthetic per-extension bucket key (`code-py`, `code-js`, `code-tsx`, ...)
for `bucket='code'` rows, and pull in `kind='code_ref'` edges (stripping the
optional `#Heading` suffix V4 symbol-resolution can add, and de-duping the
result — two symbol-level refs into the same file previously would've
produced parallel duplicate edges) merged in *before* `add_structural_ties`
so code files with a real edge aren't mistaken for orphans.

New `bucket_colors_for(nodes)` builds the color map per-index (not a static
module constant) so only extensions actually present get a legend entry.
`.py` renders as a real SVG gradient (`#306998` → `#FFD43B`, Python's own
brand colors) rather than a single blended hex, which would've just read as
muddy; `.js`/`.ts`/`.jsx`/`.tsx`/`.go`/`.rs` get flat colors from each
ecosystem's common convention. `code_ref` edges render solid purple
(`#bc8cff`, matching the provenance-badge color `serve.py` already used for
`code_ref` chunks in the query-result panel, so the same edge kind reads the
same color everywhere in the tool). Both `visualize.py` and `serve.py` share
this logic through `bucket_colors_for`/`graph_data`, so the live server
picked it up with no separate implementation.

**Bug caught and fixed during implementation, not after**: both renderers'
link mouseout handlers hard-reset every edge's stroke to flat grey — that
would've silently wiped the new purple `code_ref` styling back to grey the
instant you moved the mouse off a node. Fixed to be `kind`-aware (`code_ref`
→ purple, else grey), the same pattern the existing dashed-vs-solid
`structural` styling already used.

Verified: `graph_data()` on `chunking-ui.db` returns exactly 3 `code-py`
nodes (`app.py`, `backend.py`, `Original_Work/rag_poc.py`) and 4 de-duped
`code_ref` edges (the `rag_poc.py#SimpleEnsembleRetriever` symbol-level ref
correctly collapsed to the file-level edge, not duplicated). Rendered and
visually confirmed. `tests/run_code_fixtures.py` (10/10) and
`run_link_fixtures.py` (all runnable fixtures) still pass — neither touches
`visualize.py`/`serve.py`, so this was a manual/visual verification, not a
fixture-covered one; no automated regression coverage exists yet for the
graph-rendering layer.

## 2026-08-22 — Path portability fix, code-node graph regression fixed, MCP re-registered on macOS, V2–V4 validation gate instrumented

Context: this session picked up from a context-map audit that found the
macOS checkout had none of the Windows-produced `*.db` files (`*.db` is
gitignored) and that `run_link_fixtures.py` couldn't pass here because
`link_fixtures.json` hardcoded Windows paths. Digging into *why* that
fixture was Windows-only surfaced the real bug underneath it.

**Root cause found**: `docs.path` (and everything derived from it —
`edges.source`/`target`, `_discover_code_files`'s known-code-paths set) was
stored via `str(path.relative_to(repo_root))`, which renders with the
OS-native separator — the same repo indexed on Windows vs. macOS produced a
genuinely different database (backslash- vs forward-slash-joined paths), not
just a differently-formatted one. `links.py::resolve_link`'s docstring had
already half-diagnosed this and patched around it locally with
`os.path.normpath` — which doesn't actually fix it, since `os.path` is
itself OS-native. **Fixed** at the four sites in `index.py` that turn a
`Path` into a stored string (`.as_posix()` / `PurePosixPath(...).as_posix()`
instead of `str(...)`), and switched `resolve_link`/`resolve_code_ref` from
`os.path` to `posixpath` now that their inputs are guaranteed forward-slash.
Empirically checked before assuming impact: `ntpath.normpath`/`.basename`
already treat `/` as a valid separator, so the Windows-run `code_ref`
matching specifically was never actually broken by this — the fix is a
genuine cross-platform-storage correctness fix, not a matching-accuracy fix.
`run_code_fixtures.py` (platform-clean, 10/10) re-verified after the change.

**`tests/fixtures/link_fixtures.json` ported to be genuinely portable**:
forward-slash expected paths, `repo_root` replaced with a short `repo` name
resolved against a `DOCGRAPH_FIXTURE_REPOS_DIR` env var at runtime (one file,
valid on any machine with the referenced repos checked out, no per-OS fork).
`run_link_fixtures.py` now skips — doesn't fail — a fixture whose repo/db
isn't present on the running machine. On this checkout: 5/7 fixtures pass
(1 organic, 1 hub, 3 code); 2 skip cleanly (`coinbase-rl-bot`'s repo and db
aren't present here). One fixture (the `code_ref` negative control) needed
tightening from "zero `code_ref` chunks in the pack" to "zero `code_ref`
chunks with `via=CLAUDE.md`" — real corpus drift added a `README.md` that
now co-seeds the same task and has its own unrelated, real `code_ref`
edges; `CLAUDE.md` itself still correctly has none. This is drift, not a
regression from the path fix.

**Rebuilt `db/docgraph.db` against rl-stocks on macOS**: 65 files (down from
72), 80 co-location edges, 2 link edges, 84 `code_ref` edges (down from 94),
542 `symbol` edges (unchanged — exact match). The file-count and code_ref-
count drops are corpus drift (rl-stocks has moved on since the Windows
session), confirmed via direct inspection, not investigated further since
that's outside this session's scope.

**Code-node graph regression, found and fixed**: `docs/V4_NEXT_STEPS.md`
item 1 asked whether `graph_data()` might double-count or mishandle
`symbol` self-loops post-V4 — neither was actually possible
(`graph_data` queries `docs` not `chunks`, and hard-filters
`kind='colocation'`). The real defect predates V4 — landed in V3, when
referenced code files started entering `docs` with `bucket='code'` with no
corresponding entry in `BUCKET_COLORS`, no colocation edges of their own,
and therefore only ever a fabricated `add_structural_ties` hub-and-spoke
edge. Fixed with a `WHERE bucket != 'code'` filter in `graph_data`'s query
(`visualize.py`); `serve.py` inherits it since it imports `graph_data`
directly. Verified: `graph_data()` on the rebuilt index returns 65 nodes
(exactly the markdown-doc count), zero `bucket='code'` nodes.

**MCP re-registered on macOS** as `rl-stocks-docs`, including
`-e DOCGRAPH_QUERY_LOG=...` at registration time (see gotcha #6 above for
why that has to be `-e`, not a shell export). Hit an unrelated environment
issue along the way: `mcp` had drifted to 2.0.0 (unpinned dependency),
which dropped `mcp.server.fastmcp` — pinned `mcp<2.0` (see gotcha #5).
Verified through the *registered* tool (not the CLI) via a real `claude -p`
call: `docgraph_context` returned real def/class-level sliced chunks (e.g. a
26-token `_active_news_cols` chunk selected over the 1235-token whole
`scripts/backtest_exit_rules.py`) — the one check `V4_NEXT_STEPS.md` had
flagged as never performed.

**V2–V4 validation gate, instrumented but not yet run**: every one of V2,
V3, V4 shipped with "NOT yet validated in real use," and V2's original kill
gate was never actually run before V3/V4 built on top of it. Before writing
any logging code, pre-registered a kill criterion in `docs/V4_NEXT_STEPS.md`
(≥20 real calls, <15% annotated-as-actually-used → kill) — the point being
that a threshold exists *before* the data does, not after. Then built
`context.retrieve()`'s opt-in JSONL query logger (`DOCGRAPH_QUERY_LOG`,
off by default, wrapped so a write failure can never break retrieval,
written outside any indexed repo per gotcha #3): each entry captures
selected chunks *and* the budget-cut counterfactual (candidates that scored
into ranking but lost to the token budget, same provenance/via/rank
fields) — the counterfactual is what makes "what did V2–V4 add vs. what did
it cost" computable from the log alone, not just "was a fancy-provenance
chunk present." `*.jsonl` added to `.gitignore` in the same commit as the
logging code. Verified: env var unset → retrieval succeeds, no log; env var
set → log populated with real provenance spanning seed/neighbor/code_ref and
a real budget_cut list; env var pointed at an unwritable path → retrieval
still succeeds. **Not yet run for real** — that's the actual next step, see
`docs/V4_NEXT_STEPS.md`.

**Housekeeping**: `HANDOFF.md` cited `CLAUDE.md`'s "Link edges" section as
V2's rationale, but `CLAUDE.md` is gitignored and was never actually
committed — `.gitignore` explicitly marks it as intentionally local-only, so
fixed the pointer to README's Design notes (which already has the full
writeup) instead of un-ignoring the file.

## 2026-08-21 — V4 def/class-boundary code slicing + symbol-trace expansion: added, evaluated against rl-stocks

Added `code_chunks.py` (new module, mirrors `sections.py`'s role for Python
source via stdlib `ast` — no tree-sitter): def/class-boundary chunking with
a preamble chunk, plus a same-pass intra-file symbol table (`used_names` per
chunk: constants, callees, case-normalized param↔class bindings, excluding
`os.getenv`/`os.environ`-sourced assignments and anything purely local).
`kind='symbol'` edges (chunk-to-chunk, intra-file, bidirectional) use a
composite `f"{path}#{heading}"` key in the existing `edges.source`/`target`
columns — no schema change (`#` was already the codebase's separator for
"path plus a location within it", per `links.py`'s anchor splitting).
`code_refs.py` gained `extract_symbol_mentions`/`resolve_symbol_ref`
(inline-backtick-only, exact match against one file's chunk headings — no
fenced-block scanning, no fuzzy/prose matching); a resolved symbol mention
sharpens a `code_ref` edge's target from a bare file path to `path#heading`.
`retrieve()`'s code-neighbor tier now does one-hop `symbol`-edge expansion
(preamble + seed + connected chunks) for symbol-resolved targets, capped by
`MAX_SYMBOL_FANOUT=5` (retrieve-time, skip-not-truncate: exceeding it
discards the expansion and degrades to the filename-only fallback — all
chunks in document order — rather than an arbitrary partial slice).

**Phase 0 audit (before writing any code)**: scripted a check of the three
already-indexed corpora using their existing V3 `code_ref` edges to scope
which files/mentions to check. 7 of 9 docs with a resolvable inline-backtick
symbol mention resolve specifically into a chunking-candidate file (real,
spot-checked matches — `IndicatorEngine` in trading-dashboard,
`ExitManager`/`reset()`/`should_exit()` in rl-stocks' `src/exit_manager.py`)
— comfortably clears the stated kill criterion (fewer than 3 → shelve).
Separately, 20/46 (43%) of all code_ref target files are chunking
candidates on their own, so the whole-file→sliced change benefits docs with
no symbol mention too.

**Follow-up hub-name audit (before finalizing the design)**: computed
per-name fanout across all 19 rl-stocks/trading-dashboard chunking-candidate
files and found the concern was real, not hypothetical — `agent-api/api/
main.py`'s module-level `app` object (a Flask-style singleton) is referenced
by 9/9 chunks, which would wire the entire file into one clique and make
`MAX_SYMBOL_FANOUT` trip on every seed touching it; `src/news_data.py`'s
`SentimentResult` dataclass similarly at 6/15. Fix: `HUB_NAME_FANOUT=5`
(index-time, in `index.py`) — a module-level name referenced by more than
this many chunks in one file gets **no** symbol edges from that name at
all, skip-not-truncate, same rule as `MAX_LINK_FANOUT`/
`MAX_CODE_REFS_PER_DOC`/`MAX_COLOCATION_GROUP`. Confirmed on the real
rebuilt index: `main.py` produces 0 symbol edges, `news_data.py` produces 0
from `SentimentResult` but 50 from its other, non-hub shared names.

**Rebuild stats** (`db/docgraph.db`, 72 files, rl-stocks): 94 `code_ref`
edges (unchanged from V3), 542 `symbol` edges, `ambiguous_code_refs` rose
from 203 to 204 (one new symbol-resolution ambiguity, folded into the same
counter V3 already reported — same semantic bucket, not a new one).

**Status: implemented and fixture-tested, NOT yet validated in real use**
— same caveat V2 and V3 shipped with. `tests/run_code_fixtures.py` (10
assertions across 9 fixture files under `tests/fixtures/code_fixtures/`,
synthetic sources rather than real-repo pointers — V4's cases are precise
structural conditions, not emergent corpus properties) all pass. All of
`tests/run_link_fixtures.py`'s existing buckets (organic, hub, V3's code)
still pass unchanged after reindexing. One fixture's expectation changed
from the original design during implementation: the "common helper trap"
case (a `log_metrics` helper called by 7 others) was expected to hit
`MAX_SYMBOL_FANOUT`'s retrieve-time fallback and return the whole file;
in practice `HUB_NAME_FANOUT` already suppresses `log_metrics`'s edges at
*index* time, so `retrieve()` never even reaches a neighbor to expand to
and returns just `[preamble, seed chunk]` — smaller and more precise than
the original expectation, not a bug, but worth knowing the two caps
overlap in coverage for this exact shape of hub.

Watch real `docgraph_context` use for the same open question V2/V3 have:
does a symbol-expanded chunk ever change what the agent does, and does a
sliced-but-unexpanded (filename-only fallback) pack read any better than
V3's whole-file inclusion did.

Deferred, same discipline as V2/V3: prose symbol resolution (no backticks),
cross-file symbol resolution (single-file scope only), non-Python
languages, and type inference/dataflow analysis.

## 2026-08-20 — V3 doc->code reference edges: added, evaluated against rl-stocks

Added `kind='code_ref'` edges (directional, doc-level filename mentions only
— backtick spans + fenced code blocks, no import-statement parsing, no
symbol resolution) and a third unconditional retrieval tier in `retrieve()`
below the entire link tier (`MAX_CODE_REFS_PER_DOC=10` index-time fan-out
cap, `MAX_CODE_NEIGHBORS_PER_SEED=5` retrieve-time cap, both skip-not-
truncate on hubs, `provenance="code_ref"`). New module `code_refs.py`
mirrors `links.py`'s shape. Referenced code files are inserted into
`docs`/`chunks` with `bucket='code'` but deliberately get **no `docs_fts`
row** — this is what keeps code out of FTS seeding/co-location entirely, so
a code chunk is only reachable through a `code_ref` edge. Whole-file
inclusion only (no def/class slicing); `context.py::_render()` wraps a
`code_ref` chunk's body in a fenced code block keyed off the file extension.

**Planning corpus switched from `document_parser` to rl-stocks mid-session**
(see plan at `wise-coalescing-fern.md`, written against document_parser) —
rl-stocks turned out to be a better fixture source: it has real positive
resolutions (`src/trading_agent.py`, `src/ensemble.py`, `src/trading_env.py`
referenced by name across multiple docs), a genuine basename-ambiguity case
(`experiments.py` bare-mentioned but resolves to both `src/experiments.py`
*and* `src/dashboard/pages/experiments.py`), and genuine dangling refs
(`HANDOFF.md` mentions `app.py`/`data/source.py`/`backend/indicators/
engine.py` — none exist in this repo, apparently copy-pasted from notes
about the trading-dashboard project).

**Rebuild stats** (`db/docgraph.db`, 72 files): 94 `code_ref` edges, 37 code
files indexed, 76 dead refs, 203 ambiguous refs (mostly `staging/` mirroring
`src/` — real duplication in this corpus, not a bug), 4 hub docs skipped
(over `MAX_CODE_REFS_PER_DOC`).

**Status: implemented and fixture-tested, NOT yet validated in real use** —
same caveat V2 shipped with. `tests/run_link_fixtures.py` now has a `code`
bucket (3/3: two positive resolutions incl. one basename-fallback case, one
negative control), but like V2's organic bucket these were derived by
looking at the same corpus survey that motivated the feature. Watch real
`docgraph_context` use for whether a `code_ref` chunk ever changes what the
agent does, same open question V2 has.

Deferred, same discipline as V2 deferring `link_section` anchor resolution:
symbol-name resolution (matching prose like "the `DocumentParser` class"
back to its file) and a def/class-boundary slicer for oversized code files.

## 2026-08-18 — V2 link edges: added, decision gate still open

Added `kind='link'` edges (directional, doc-level, `MAX_LINK_FANOUT=10`
skip-not-truncate on hub docs) and unconditional one-hop link-neighbor
expansion in `retrieve()` (`MAX_LINK_NEIGHBORS_PER_SEED=5`, ranked below
every seed/co-location neighbor, `provenance="link"` + `via` field). Full
rationale in README's Design notes ("Link edges (V2)") — that's the source
of truth for this; `CLAUDE.md` is a local-only file (see `.gitignore`) and
was never actually committed, so don't cite it as a reference here.

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
- `visualize.py` — static, self-contained D3 HTML graph (file nodes, co-location +
  `code_ref` edges, sized by token count). Nodes colored by discovery bucket, except
  `bucket='code'` files which are colored by extension (`code-py` gets a Python-brand
  blue→yellow gradient, others a flat per-ecosystem color) via `bucket_colors_for()`.
  `graph_data(db_path)` (node/edge query + `add_structural_ties`) is factored out and
  reused by `serve.py` so the two rendering paths can't drift on corpus-shape logic.
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
| `db/docgraph.db` | `~/Projects/agentic-dev/reinforcement-learning-stocks` | macOS | `rl-stocks-docs` (registered 2026-08-22, includes `-e DOCGRAPH_QUERY_LOG=...`) |
| `db/chunking-ui.db` | `~/projects/azure-development/chunking-ui` | macOS | `chunking-ui-docs` (registered 2026-08-22, absolute `.venv/bin/python` path) |
| `db/docgraph-trading.db` | `D:\code\web-development\trading-dashboard` | Windows | `docgraph-trading-dashboard` |
| `db/docgraph.db` (Windows copy) | `D:\code\agentic-development\reinforcement-learning-stocks` | Windows | `docgraph-rl-stocks` |
| `db/coinbase_rl_bot.db` | `D:\code\agentic-development\coinbase-rl-bot` | Windows | not registered |
| `db/document_parser.db` | `D:\code\microsoft\document_parser` | Windows | not registered |

`db/docgraph.db` is per-machine, not shared (gitignored) — the macOS and
Windows rows above both build from the rl-stocks repo but are separate
files that can drift out of sync (see 2026-08-22 entry: 65 files here vs.
72 on the Windows run).

Windows entries registered via `claude mcp add ... -s user -e PYTHONIOENCODING=utf-8 -- python -m docgraph.mcp_server <repo_root> <db_path>`. See README's registration recipe for the macOS command, including the `DOCGRAPH_QUERY_LOG` `-e` flag needed for the query logger. Check with `claude mcp list`.

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
green=subdir-allcaps) — except code files (`bucket='code'`, referenced via a
`code_ref` edge from a doc), which are colored by extension instead (Python
gets a blue→yellow gradient, others a flat per-ecosystem color), sized by
token count. Edges = co-location relationships (grey) plus doc→code
`code_ref` edges (purple). Deliberately a structural/corpus-shape view, not a
retrieval view — doesn't show chunk-level (H2/H3) structure or FTS relevance.

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
5. **`ModuleNotFoundError: No module named 'mcp.server.fastmcp'`** when
   running `mcp_server.py` — `pyproject.toml` declared a bare `mcp`
   dependency, and `mcp` 2.0.0 dropped the `fastmcp` submodule `mcp_server.py`
   uses. Fix: pinned `mcp<2.0` in `pyproject.toml`; `.venv/bin/pip install
   -e .` then resolves to 1.29.0, which still has it. Environment-agnostic —
   will hit on any fresh venv until this is either re-pinned or `mcp_server.py`
   is ported to whatever the 2.0 API's equivalent is.
6. **`DOCGRAPH_QUERY_LOG` set in your shell does nothing for the MCP
   server.** The server is a process Claude Code spawns, not a child of your
   terminal — the env var has to be passed via `-e` at `claude mcp add`
   registration time (see README's registration recipe). Re-registering
   without it produces an empty log file, not an error; verify a few real
   calls actually produce log lines before trusting a week of silence.

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
