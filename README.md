# DocGraph

Repo-native markdown context broker — an MCP tool that gives coding agents
task-relevant docs instead of dumping `docs/**`.

Point it at a repo, and Claude Code (or any MCP client) gets a single tool,
`docgraph_context(task, max_tokens)`, that turns a task description into a
ranked, token-budgeted markdown pack pulled from that repo's own
documentation — instead of reading whole files wholesale and hoping the
relevant part is in there somewhere.

## Why

Agent context windows are finite and doc trees aren't curated for retrieval.
"Read `docs/**`" either blows the budget on a big repo or silently misses
files outside `docs/`. DocGraph indexes what's actually documentation
(skills, monorepo subproject READMEs, loose root files — not just `docs/`),
splits long catalog-style files into their real sections, and serves back
only what a specific task needs.

No embeddings, no LLM calls in the retrieval path. Deterministic and
inspectable — you can always see *why* a doc made it into a pack.

## How it works

```plaintext
repo markdown
     │
     ▼
discover.py    4-bucket rule: root files, docs/, skills/, monorepo
     │         subproject READMEs (all-caps filename, one level deep)
     ▼
index.py       SQLite + FTS5 (porter stemming), recursive H2→H4 chunking
     │         for long catalog docs, content-hash dedup, size-capped
     │         co-location edges between files in the same directory
     ▼
db/docgraph.db
     │
     ▼
context.py     task → AND-first/OR-fallback FTS query → co-location
     │         neighbor expansion (score-floored) → token-budget trim
     ├─────────────────────────────┐
     ▼                             ▼
mcp_server.py                  serve.py       live web graph: task box ->
wraps it as one                real retrieval -> highlighted nodes +
MCP tool, stdio                rendered markdown pack panel
transport
```

## Install

```bash
pip install -e .
```

## Usage

```bash
# Build the index for a repo
python -m docgraph.index /path/to/repo db/my-repo.db

# Generate a context pack directly (useful for testing before wiring into an agent)
python -m docgraph.context /path/to/repo db/my-repo.db "task description" --max-tokens 8000

# Run as an MCP server (stdio) — point your MCP client's config at this
python -m docgraph.mcp_server /path/to/repo db/my-repo.db

# Simple graph visualization (file-level nodes, co-location edges) — static, no server
python -m docgraph.visualize db/my-repo.db graphs/my-repo_graph.html --title "my-repo"

# Live web graph: same corpus graph, plus a task box that runs real retrieval
# and highlights exactly which files were selected, with the rendered pack
# in a resizable side panel
python -m docgraph.serve /path/to/repo db/my-repo.db --port 8765
```

Task strings are used as keyword search, not semantic search — be specific,
and avoid naming a file you're about to create (it can't match anything
that doesn't exist yet).

### Registering with Claude Code

```bash
claude mcp add my-repo-docs -s user -e PYTHONIOENCODING=utf-8 -- \
  python -m docgraph.mcp_server /path/to/repo /full/path/to/db/my-repo.db
```

One server instance = one repo + one index. For multiple repos, register
multiple servers with distinct names and separate `.db` files.

## Live web graph (`serve.py`)

```bash
python -m docgraph.serve /path/to/repo db/my-repo.db --port 8765 [--host 127.0.0.1]
```

The same force-directed corpus graph as `visualize.py`, served locally
(stdlib `http.server`, no new dependency) with:

- A task box that calls real retrieval (`context.retrieve`) and highlights
  which file nodes were actually selected into the pack — solid glow for
  seed matches, dashed for co-location neighbors pulled in via expansion —
  dimming everything else.
- A resizable side panel rendering the selected pack as formatted markdown
  (headings, code blocks, tables — via `marked`, CDN-loaded like D3). Drag
  its left edge or click the `⤢` button to expand it.
- A status line under the box showing chunk count, and graceful empty-state
  when a task matches nothing.

`GET /context?task=...&max_tokens=...` is the underlying JSON endpoint if you
want to hit it directly. Local dev tool only — no auth, binds `127.0.0.1` by
default.

## Discovery rule

- **root** — loose `.md` files directly at repo root
- **docs** — anything under a directory named `docs`, any depth
- **skills** — same, for a directory named `skills` (catches
  `.claude/skills/` and `.agents/skills/`)
- **subdir-allcaps** — files exactly one level under root, in another
  subdirectory, whose filename stem is ALL-CAPS (`README`, `TODO`,
  `ARCHITECTURE`...) — covers monorepo subproject meta-docs

Any bucket can be excluded per-run with `--exclude-bucket`.

## Design notes

- **FTS5 with porter stemming, no embeddings.** Deterministic, cheap, and
  good enough — cross-document explicit links tested consistently near-zero
  across every real repo this was built against.
- **Co-location edges, not explicit links.** Files in the same directory
  get a weak "related" edge, since that's the signal that's actually
  present. Capped at 10 files per directory — past that, "same folder"
  stops being a meaningful relationship and starts being noise.
- **Recursive chunking, not fixed-depth.** Long docs split at H2; any
  section still oversized with real substructure splits again at H3, then
  H4. Some repos have flat catalogs of H2 sections, others have one
  catch-all H2 hiding the real structure at H3 — fixed depth is wrong for
  one of them either way.
- **AND-first, OR-fallback queries.** Try requiring every query word to
  co-occur first; only widen to OR if that finds nothing. A single precise
  match is better evidence than several noisy ones.
- **Content-hash dedup at index time.** Mirrored files (e.g. a skill
  duplicated under `.claude/` and `.agents/`) get indexed once, not twice.

## Status

MVP, validated against three real repos of different shapes (10, 8, and
72-file corpora) and in live use via Claude Code. The live web graph
(`serve.py`) closes the "real graph UI" gap — file-level highlighting only
for now, chunk/heading-level nodes deferred. Not built: embeddings, watch
mode, cross-repo search.

## License

Personal project, no license specified.
