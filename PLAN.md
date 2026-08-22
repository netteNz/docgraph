# DocGraph — Context Map & Next Steps

## Context

DocGraph is a repo-native markdown context broker: it indexes a repo's docs into
SQLite/FTS5, serves token-budgeted context packs over MCP (`docgraph_context`),
and renders a D3 force-directed corpus graph (static + live).

Four versions have shipped: V1 (index/retrieve/MCP/visualize) → V2 (`link` edges)
→ V3 (`code_ref` doc→code edges) → V4 (def/class code slicing + `symbol` edges).

Two things prompted this map:

1. **Every version V2–V4 shipped with the identical caveat** — *"implemented and
   fixture-tested, NOT yet validated in real use."* V2's HANDOFF entry set an
   explicit decision gate ("a week of actual `docgraph_context` use... if it's
   inert or noisy there, kill it before building the expensive parts"). That gate
   was never run. V3 and V4 were built on top of it instead. Three layers of
   retrieval logic now rest on a hypothesis nobody has tested.
2. **The V4 work isn't reachable from this machine.** All V2–V4 validation ran on
   Windows against `rl-stocks` / `trading-dashboard`. `*.db` is gitignored, so
   none of those indexes travelled. See "Runtime state" below.

`docs/V4_NEXT_STEPS.md` already tracks two open items. This map confirms one of
them is a non-issue as written, and identifies the real defect underneath it.

---

## Runtime state on this machine (verified, 2026-08-22)

| Fact | Status |
|---|---|
| `db/` contents | **only** `doordashboard.db` (Aug 18, V1-era) |
| That db's edge kinds | `colocation: 12` only — no `link`, no `code_ref`, no `symbol` |
| `db/docgraph.db` (rl-stocks, V4-rebuilt per HANDOFF) | **absent** |
| `db/docgraph-trading.db`, `coinbase_rl_bot.db`, `document_parser.db` | **absent** |
| Registered docgraph MCP servers (`claude mcp list`) | **none** |
| rl-stocks source repo locally | ✅ present — `~/Projects/agentic-dev/reinforcement-learning-stocks` |
| trading-dashboard source locally | ❌ only `~/Projects/trading-dashboard.zip` |

**Consequence:** V4_NEXT_STEPS item 2 ("does the registered server pick up the
rebuilt db?") is moot here — there is nothing registered and nothing rebuilt.
But rl-stocks *is* available, so V4 can be rebuilt and validated on macOS.

---

## Module map

`src/docgraph/` — 2,960 LOC total, no runtime deps beyond `frontmatter` + `mcp`.

| File | LOC | Purpose | Key symbols |
|---|---|---|---|
| `discover.py` | 40 | 4-bucket file discovery (root/docs/skills/subdir-allcaps) | `discover()` |
| `sections.py` | 109 | Markdown recursive H2→H4 chunking | `is_chunking_candidate`, `split_sections`, `extract_section` |
| `code_chunks.py` | 271 | **V4.** Python def/class slicing via stdlib `ast` + intra-file symbol table | `build_chunks`, `is_chunking_candidate`, `extract_chunk`, `CodeChunk` |
| `links.py` | 64 | **V2.** Markdown link extraction/resolution | `extract_links`, `resolve_link`, `MAX_LINK_FANOUT=10` |
| `code_refs.py` | 125 | **V3/V4.** Doc→code filename + symbol mention extraction | `extract_code_mentions`, `resolve_code_ref`, `extract_symbol_mentions`, `resolve_symbol_ref` |
| `index.py` | 502 | Builds the SQLite/FTS5 index + all four edge kinds | `build()`, `_build_colocation_edges`, `_build_link_edges`, `_build_code_edges`, `HUB_NAME_FANOUT=5` |
| `context.py` | 328 | `retrieve()` — 4-tier retrieval; `build_pack()` = `_render(retrieve(...))` | `MAX_LINK_NEIGHBORS_PER_SEED=5`, `MAX_CODE_NEIGHBORS_PER_SEED=5`, `MAX_SYMBOL_FANOUT=5` |
| `mcp_server.py` | 71 | stdio MCP server exposing one tool | `docgraph_context(task, max_tokens)` |
| `visualize.py` | 420 | Static self-contained D3 HTML | `graph_data()`, `add_structural_ties()`, `build_html()`, `BUCKET_COLORS` |
| `serve.py` | 582 | Live graph + task box + retrieval highlighting (stdlib `http.server`) | reuses `graph_data`, `BUCKET_COLORS` |

### Data model

Schema is stable across V2–V4 — **no migrations have ever been needed.**

- `docs(id, path, parent, bucket, title, indexed_title, hash, bytes, token_est)`
- `chunks(id, doc_id, path, heading, indexed_title, token_est)`
- `edges(source, target, kind, weight)` — `source`/`target` are `path` or the
  composite `f"{path}#{heading}"` (V4 reuses `#` as the existing path+location
  separator, which is why V4 needed no schema change)
- `docs_fts` — FTS5, porter stemming. **Code docs deliberately get no FTS row**,
  so code is only reachable via a `code_ref` edge, never via seeding.

Edge kinds: `colocation` (bidirectional, doc-level) · `link` (directional,
doc-level) · `code_ref` (directional, doc→code) · `symbol` (bidirectional,
chunk↔chunk, **intra-file only**).

Every fan-out cap is **skip-not-truncate** — a hub over the cap loses *all* its
edges rather than an arbitrary subset. This is a consistent, deliberate design
rule across `MAX_LINK_FANOUT`, `MAX_CODE_REFS_PER_DOC`, `MAX_COLOCATION_GROUP`,
`HUB_NAME_FANOUT`, `MAX_SYMBOL_FANOUT`.

### Tests & fixtures

| Runner | Coverage | Runs on macOS? |
|---|---|---|
| `tests/run_link_fixtures.py` (88 LOC) | 7 cases in `link_fixtures.json` — `organic` (3) / `hub` suppression (1) / V3 `code` (3). Drives real `retrieve()` against **real indexed repos**, because link value is an emergent corpus property. Buckets are reported separately and never averaged. | ❌ **No** — see below |
| `tests/run_code_fixtures.py` (232 LOC) | 10 assertions over 9 synthetic sources in `tests/fixtures/code_fixtures/`. Mostly pure-function tests against `code_chunks.py`; two cases (`index_symbol_edge`, `retrieve_group_size`) build a disposable temp repo and run the real `index.build` + `retrieve`. | ✅ Yes — fully self-contained |
| `scripts/link_audit.py` (128 LOC) | Phase-0 corpus audit tool, not a test. Imports `_fts_query`/`_fts_words` from `context` so the measurement can't drift from the real tokenizer. | needs a corpus |

**`run_link_fixtures.py` cannot pass on this checkout.** `link_fixtures.json` hardcodes
Windows `repo_root` values (`/d/code/agentic-development/reinforcement-learning-stocks`)
and expects backslash-separated paths (`docs\SENTIMENT_INTEGRATION.md`). This is a
symptom, not the bug — see the design finding below and Step 0.

No pytest — both runners are plain `python` scripts asserting against JSON specs
and returning exit codes.

Code fixtures: `happy_path.py` (chunking + bidirectional symbol edge),
`common_helper_trap.py` (HUB_NAME_FANOUT suppression), `param_binding.py`
(param↔class case-normalization + noise filter), `shared_locals_only.py`,
`sub_threshold.py`, `env_key_exclusion.py`, `broken_syntax.py`.

---

## Finding: a real V3 graph regression, mis-framed in V4_NEXT_STEPS

V4_NEXT_STEPS item 1 asks to confirm `graph_data()` doesn't "double-count or
drop anything now that `chunks` has multiple rows per code doc," and whether
intra-file `symbol` self-loops need filtering.

**Both concerns are already handled** (`visualize.py:371-391`):
- `graph_data` selects from `docs`, never `chunks` → chunk-level slicing cannot
  double-count. Structurally immune.
- Its edge query hard-filters `kind = 'colocation'` → `symbol`, `link`, and
  `code_ref` edges never reach the graph. Self-loops are already impossible.

**The actual defect is one level up, and it landed in V3, not V4.** Since V3,
`_build_code_edges` inserts referenced code files into `docs` with
`bucket='code'` (`index.py:370`). `graph_data`'s `SELECT ... FROM docs` has **no
bucket filter**, so every referenced code file becomes a file-level graph node:

1. **Uncolored.** `BUCKET_COLORS` has no `"code"` key, and both renderers fall
   back to `bucketColors[d.bucket] || "#8b949e"` (`visualize.py:250`,
   `serve.py:225`) — `#8b949e` is *the exact color of the `root` bucket*. Code
   files are visually indistinguishable from root markdown.
2. **Dangling glow filter.** Selection/hover applies `url(#glow-${d.bucket})`
   (`visualize.py:278`, `serve.py:310`), but glow filters are generated only by
   iterating `BUCKET_COLORS` — `#glow-code` is never defined. Browser handling of
   an unresolvable SVG filter ref varies; needs a visual check, not an assumption.
3. **No legend row** — the legend also iterates `BUCKET_COLORS`.
4. **Fabricated structural edges.** `_build_colocation_edges` runs only over
   discovered *markdown* rows, so code docs have **zero** colocation edges. They
   therefore all land in `add_structural_ties`'s orphan set, which hub-and-spokes
   them by directory — inventing `src/` code-file clusters that carry a different
   semantic than doc co-location and that no audit ever validated.

On rl-stocks this means ~37 code nodes joining 72 markdown nodes, gray, with
synthetic edges. Unverified locally only because the db is absent.

---

## Design finding: stored paths are OS-native, not portable — fix at the source

The Windows-only fixtures aren't the bug, they're the first visible symptom.
`docs.path` (and everything derived from it — `edges.source`/`target`,
`_discover_code_files`'s known-code-paths set) is written with `str(path)`,
and `pathlib.Path.__str__()` renders using the OS-native separator. So **the
same repo indexed on Windows vs. macOS produces a different database** —
backslash-joined paths on one, forward-slash on the other. Every fixture,
every JSON/MCP response, every filename-mention match downstream inherits
that split.

The codebase already half-knows this: `links.py::resolve_link`'s docstring
says storage "uses OS-native separators... normalize with `os.path`, not a
hardcoded `/`," and both `resolve_link` and `code_refs.py::resolve_code_ref`
patch around it locally with `os.path.normpath`/`os.path.join`. That's not a
fix — `os.path` is itself OS-native, so the Windows build still produces
backslash-joined output; it only prevents a same-platform join from breaking.

**The correct fix is one convention change at the handful of places a `Path`
becomes a stored string** — use `.as_posix()` instead of `str()`:

| Site | Current | Fix |
|---|---|---|
| `index.py:91` (`docs.path`) | `str(path.relative_to(repo_root))` | `.as_posix()` |
| `index.py:94` (`docs.parent`) | `str(Path(rel).parent)` | `Path(rel).parent.as_posix()` — `rel` is now a plain posix string, but `Path(rel).parent` still renders back OS-native on Windows unless forced |
| `index.py:251` (`_discover_code_files`) | `str(rel)` | `.as_posix()` |
| `index.py:372` (code doc's `parent`) | `str(Path(code_path).parent)` | same as above |

With storage canonically forward-slash on every platform, `resolve_link` and
`resolve_code_ref` can drop their `os.path` workarounds for `posixpath` (or a
plain manual join) — simpler *and* actually correct everywhere, not just
patched. And `link_fixtures.json` becomes one portable file: real audit
findings encoded once, valid on whichever machine runs them, no per-OS fork.

This is the honest place to spend the "make it Mac-compatible" effort — fix
the one write boundary, and every downstream consumer (fixtures, `code_refs`
matching, `serve.py`/`mcp_server.py` JSON output) is correct for free instead
of needing its own patch.

---

## Recommended next steps

**Chosen direction:** fix path portability at the source, then instrument and
use the retrieval pipeline for real, with the graph-node fix folded into the
rebuild rather than deferred. Run order:

```
0.1 (path fix)  →  run_code_fixtures.py (regression check)
  →  0.2 (rebuild, with Step 2's bucket='code' filter applied)
  →  0.3 (port link_fixtures.json, run it)
  →  0.4 (register MCP server, -e DOCGRAPH_QUERY_LOG=... included)
  →  0.5 (verify through the registered tool + graph)
  →  1.1 (write the kill threshold into V4_NEXT_STEPS.md)
  →  1.2 + 1.3 (counterfactual logging, built and gitignored together)
  →  1.4 (run for a week, then apply 1.1's threshold)
```

### Step 0 — Make stored paths portable, then rebuild *(blocking, do first)*

**0.1 — Apply the `.as_posix()` fix** at the four sites above in `index.py`.
Switch `resolve_link` (`links.py`) and `resolve_code_ref` (`code_refs.py`)
from `os.path.*` to `posixpath.*` (or equivalent manual join) now that the
inputs they operate on are guaranteed posix-separated, and drop the
docstring caveat in `resolve_link` that's now moot.

**0.2 — Rebuild against local rl-stocks.**
```bash
cd /Users/nettenz/Projects/docgraph
.venv/bin/python -m docgraph.index \
  ~/Projects/agentic-dev/reinforcement-learning-stocks db/docgraph.db
```
Expected from HANDOFF's Windows run: 72 files, 94 `code_ref`, 542 `symbol` edges.
A material divergence is a finding — the repo has moved since. **Note on
direction**: don't read an upward jump in `code_ref` count as evidence the
portability fix changed matching behavior. Checked empirically —
`ntpath.normpath`/`ntpath.basename` already treat `/` as a valid separator and
convert it, so `resolve_code_ref`'s Windows run matched forward-slash doc
mentions against backslash `known_code_paths` correctly; that specific path
was never actually broken. Any divergence here is corpus drift, not the fix
working.

Also apply the Step 2 graph fix now, in this same pass (see Step 2 below for
why it's decided rather than deferred): filter `bucket='code'` out of
`graph_data`'s query in `visualize.py` before rebuilding, so 0.5's visual
check (registered MCP tool + a look at the graph) validates the real
end-state in one pass instead of two.

**0.3 — Update `link_fixtures.json` to be genuinely portable**: repo-relative
paths with forward slashes, `repo_root` resolved via a CLI arg/env var rather
than hardcoded. This should now be a straight port (same audit findings, same
values, just no backslashes) rather than a workaround, since 0.1 makes
forward-slash the one true stored format on every platform.

**0.4 — Register the MCP server, including the query-log env var.** Per
README's `claude mcp add` recipe, macOS python path, **absolute** db path
(gotcha #1) — **and** `-e DOCGRAPH_QUERY_LOG=/abs/path.jsonl` in the same
`claude mcp add` invocation (see Step 1). The MCP server is a process Claude
Code spawns, not a child of your interactive shell — an env var exported in
the terminal never reaches it. Setting `DOCGRAPH_QUERY_LOG` in your shell and
registering without `-e` silently logs nothing from real MCP-tool use, which
is the only use Step 1 actually cares about. Add this coupling to the
README's registration recipe itself (not just this plan) so the Windows
machine's re-registration doesn't repeat the mistake. `claude mcp list`
currently shows no docgraph servers at all.

**0.5 — Verify through the registered tool, not just the CLI.** Confirm
`docgraph_context` returns *sliced* code chunks, and confirm the graph (0.2's
`bucket='code'` filter) renders only markdown nodes. This is the one check
V4_NEXT_STEPS explicitly flagged as never performed.

### Step 1 — Close the V2/V3/V4 validation gate *(the actually overdue work)*

Three HANDOFF entries ask the same unanswered question: *does a link- /
code_ref- / symbol-recovered chunk ever change what the agent does, and does
`via` ever surface something that should have been suppressed?* Answering that
from memory after a week won't work — it has to leave a trace. And a trace of
*presence* alone isn't enough either: this is the V2 lesson ("don't graduate
without a decision gate") applied to the gate's own design. A week of JSONL
saying "23 packs contained a link-provenance chunk" tells you nothing about
whether those 23 chunks did anything — and says nothing about what they
displaced. Both gaps need closing before the log is worth writing.

**1.1 — Pre-register the kill threshold, before the week starts, in
`V4_NEXT_STEPS.md`.** Concretely:

> Over ≥20 real `docgraph_context` calls on rl-stocks, if fewer than 15% of
> packs contain a link/code_ref/symbol-provenance chunk that you'd separately
> annotate (a one-line note next to the log entry, at the time, not
> reconstructed later) as *actually used* — read, referenced, or acted on,
> not merely present — V2–V4 retrieval is inert. Kill it: strip the three
> tiers back to V1's seed + colocation, keep the schema (no migration
> needed either way), stop building on top of it.

The exact numbers (20 calls, 15%) are a starting proposal, not sacred — the
point is that *some* number gets written down now, before the data exists to
rationalize it after the fact.

**1.2 — Log the counterfactual, not just the result.** Provenance on its own
can't show what V2–V4 cost: a link/code_ref/symbol chunk that fit the token
budget may have pushed out a colocation chunk the V1 baseline would have
returned instead. Extend `retrieve()`'s budget-trim step to also record the
candidates that were cut for budget, tagged with their own `provenance`. Then
"what did V2–V4 add vs. what would V1 alone have returned" is computable
offline from the log alone, without re-running anything — presence becomes
comparable to a baseline instead of being read in isolation.

**1.3 — Build the logger.** An **append-only JSONL query log** in
`context.retrieve()`, the right seam since it already returns every field
below as structured data — this is a write, not a computation — and covers
the MCP tool, the CLI, and `serve.py` in one place, since all three funnel
through it. Per call: timestamp, task string, `query_used` (AND or OR fired),
`total_tokens`. Per **selected** chunk: `path`, `heading`, `provenance`,
`via`, `rank`, `token_est`. Per **budget-cut** chunk (1.2): same fields, plus
why it was cut.

Design constraints (see Risk):
- Opt-in via env var `DOCGRAPH_QUERY_LOG=/abs/path.jsonl`, off by default —
  and see Step 0.4: this only reaches the MCP server if passed via `-e` at
  registration time, not set in your interactive shell.
- Wrapped so a failed write can never break retrieval.
- Written **outside** any indexed repo (gotcha #3) — a log inside rl-stocks
  would contain the next query's task string verbatim and self-match on
  reindex, exactly the `docgraph-context.md` failure HANDOFF already
  recorded once.
- Add `*.jsonl` to `.gitignore` **in the same commit** as the logging code,
  not as a follow-up — task strings can carry sensitive repo detail.

**1.4 — Run it for a week on rl-stocks, then apply 1.1's threshold to the
log**, annotating usefulness at the time each pack is actually consulted, not
retroactively. The output makes *kill* as available a conclusion as *keep* —
that's the whole point of pre-registering the number in 1.1 instead of
eyeballing the log afterward.

### Step 2 — Code-node graph regression *(decided now, not deferred: filter)*

Committing to **(a) — filter `bucket='code'` out of `graph_data`'s query** in
`visualize.py`, applied in Step 0.2 above rather than after a "look at it
first" pass. The look-first framing implied there was a real choice to make
by eyeballing the rendered graph; there isn't. `graph_data`'s edge query
already hard-filters to `kind = 'colocation'`, so a code node can *only* ever
appear with a fabricated `add_structural_ties` hub-and-spoke edge — there is
no rendering of the current code where a code node carries real signal to
look at. Option (b) (color + legend it properly) would be styling a node
whose only edge is invented; that's decoration, not a fix.

The two lines: `graph_data`'s `SELECT ... FROM docs` gets a `WHERE bucket !=
'code'`, in both the query and (if `visualize.py`/`serve.py` build the id set
separately anywhere) the corresponding node-id filter. `visualize.py` and
`serve.py` change together since they share `graph_data`/`BUCKET_COLORS`
precisely so they can't drift — one change touches both rendering paths.

**The one thing that would revisit this**: a later, separate decision to
surface `code_ref` edges themselves in the graph (not just suppress the
node). That's a different feature with its own audit — same discipline as
V4_NEXT_STEPS' explicit "don't build the chunk-level view speculatively" —
not a reason to hold this fix open now.

### Step 3 — Leave deferred

Per the project's own discipline, keep deferred: chunk-level detail view in
`serve.py` (V4_NEXT_STEPS explicitly says *"don't build it speculatively"*),
trading-dashboard rebuild (source isn't even unzipped here), prose/cross-file
symbol resolution, non-Python languages, embeddings, watch mode.

### Housekeeping — `CLAUDE.md` is missing *(self-inflicted, pick one now)*

`HANDOFF.md` repeatedly cites `CLAUDE.md`'s "Link edges" section as the full V2
rationale, but that file is both gitignored and absent from the working
tree — HANDOFF is supposed to be the source of truth and it's pointing at a
file that doesn't exist. Two fixes, pick one rather than leaving it open:
- **Un-ignore `CLAUDE.md`** and commit it, if its content was never actually
  meant to be private/local-only — restores the citation as-is.
- **Move the "Link edges" rationale into README's Design notes** (which
  already has a Design notes section covering the same ground) and fix
  HANDOFF's pointers to reference README instead. Keep `CLAUDE.md` gitignored
  if it's meant to stay a local/personal file.
Cheap either way — do it in the same pass as the housekeeping above, not as a
separate follow-up.

---

## Risk assessment

- [ ] **No public API breakage** in Steps 0–2. `build_pack()`'s signature and
      return type are unchanged; `mcp_server.py` and both CLIs are untouched.
- [ ] **No DB migration.** Schema has been stable since V1; `index.py` DROPs and
      rebuilds, so a reindex is the migration. Step 0.1's path-format change is a
      **content** change (existing `*.db` files hold OS-native paths), not a
      schema change — any `.db` built before this fix must be rebuilt, not read
      as-is. Not a concern here since the only local db (`doordashboard.db`) is
      gitignored and gets superseded by 0.2's rebuild anyway.
- [ ] **Step 0.1 touches `resolve_link`/`resolve_code_ref`.** Both are pure,
      fixture-covered functions — re-run `run_code_fixtures.py` and the ported
      `run_link_fixtures.py` (0.3) after the switch to `posixpath`, not just after
      the `index.py` change, since both files change together.
- [ ] **Step 2 changes rendered output** — `build_html` output is no longer
      byte-identical. Both renderers must change together; they share
      `graph_data`/`BUCKET_COLORS` precisely so they can't drift. Since it's now
      folded into 0.2, the graph node-count check in 0.5 doubles as its
      regression check — no separate pass needed.
- [ ] **Step 1.3 writes to disk on every retrieval.** Must be opt-in via env var,
      path-configurable, and must never break retrieval if the write fails.
      Task strings can contain sensitive repo detail — keep the log local and
      gitignored. `*.jsonl` must land in `.gitignore` in the **same commit** as
      the logging code (1.3), not after.
- [ ] **Gotcha #3 applies directly to Step 1.3**: a log written inside an indexed
      repo would contain the next query's task string verbatim, self-match on
      reindex, and degenerate the pack. This exact failure has already happened
      once with a saved `docgraph-context.md`. Write outside the repo.
- [ ] **Step 0.3 edits shared fixtures.** `link_fixtures.json` encodes real audit
      findings used by the Windows machine too — make it portable, don't fork it.
- [ ] **Step 0.4's `-e` coupling is easy to silently skip.** If the MCP server
      is re-registered without `DOCGRAPH_QUERY_LOG` passed via `-e`, Step 1
      logs nothing from real use and the week produces an empty file, not an
      error — the failure mode is silent, not loud. Worth a note in the
      README recipe itself, not just this plan, since the Windows machine
      will re-register independently.
- [ ] **1.1's threshold is a judgment call, not a derived constant.** 20 calls
      / 15% is a starting proposal; the risk isn't the specific numbers, it's
      skipping the pre-registration step and rationalizing a threshold after
      seeing the data — that's the exact failure this step exists to prevent.

## Verification

- **Step 0.1**: `run_code_fixtures.py` passes with `.as_posix()` applied and
  `resolve_link`/`resolve_code_ref` switched to `posixpath` — this is the
  regression check for the portability fix itself, before touching fixtures.
- **Step 0.2**: reindex rl-stocks, inspect `docs.path`/`edges.source` directly
  (`sqlite3 db/docgraph.db "select path from docs limit 5"`) and confirm every
  value uses `/`, never `\`.
- **Step 0.3**: `run_link_fixtures.py` passes on macOS using the ported,
  portable fixture file — the thing that was impossible before Step 0.1.
- **Step 0.5**: call `docgraph_context` through the *registered MCP tool*, not the
  CLI, and confirm the returned code content is a def/class slice rather than a
  whole file (rules out server-side staleness — V4_NEXT_STEPS' one never-done
  check), and reload `/` in `serve.py` to confirm node count now matches
  markdown-doc count only, with no gray/uncolored/unlegended code nodes and no
  dangling `#glow-code` filter reference on hover — this is Step 2's fix,
  applied in 0.2, verified here.
- **Step 1.3**: run a couple of real tasks through the *registered* MCP server
  first, and confirm the JSONL actually has entries — this is the check that
  catches Step 0.4's `-e` coupling being silently skipped. Then confirm each
  line has `provenance` values spanning `seed`/`colocation`/`link`/`code_ref`
  for selected chunks, plus a populated budget-cut list per 1.2. Confirm
  retrieval still succeeds with the env var unset, and with it pointed at an
  unwritable path.
- **Step 1.4**: after a week, confirm 1.1's threshold was applied against the
  annotated log — not eyeballed — and that the kill-or-keep call is written
  down as a decision (in HANDOFF.md, same discipline as V2/V3/V4's entries),
  not left implicit.
