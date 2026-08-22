"""
The context broker: task string -> ranked, token-budgeted markdown pack.

Two fixes folded in here, both driven by a real failure case (task: write
ExitManager tests; got EXIT_SIGNAL_TODO.md at 43% of budget mostly-irrelevant
content, plus PHASE1_INFRASTRUCTURE.md — an unrelated Foundry telemetry doc
that only shares generic words like "reset"/"boundary" with the task):

  1. Chunk-level retrieval. Long catalog-style docs (chunking_candidate at
     index time) are indexed per-H2-section, not as one FTS row. A task
     that matches one section pulls just that section into the pack,
     not the surrounding 200 irrelevant lines.
  2. AND-first, OR-fallback query. A plain OR-of-all-words query means any
     doc sharing even one generic word with the task can seed the pack.
     Try requiring every significant word first (rare co-occurrence = high
     precision); only widen to OR if that's too strict to seed anything.
     This is also what makes neighbor expansion safe: a co-located neighbor
     only gets pulled in if it clears the SAME query bar as a real seed
     would, not just because it happens to share a directory.
"""
import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import frontmatter

from .code_chunks import extract_chunk as _extract_code_chunk
from .code_refs import CODE_EXTENSIONS, split_code_key
from .sections import extract_section

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
# Bare file extensions never carry topical content — they only ever show up
# in a task string because a target/reference filename was mentioned, and
# they can never appear in existing prose. Under AND-first this makes them
# an impossible-to-satisfy constraint that forces every such task into
# OR-fallback regardless of how well the rest of the words would've matched.
_EXTENSION_STOPWORDS = {
    "py", "js", "ts", "jsx", "tsx", "md", "json", "yaml", "yml",
    "txt", "sh", "toml", "cfg", "ini", "html", "css", "sql",
}


def _fts_words(task: str) -> list[str]:
    seen, out = set(), []
    for w in _WORD_RE.findall(task.lower()):
        if len(w) > 1 and w not in seen and w not in _EXTENSION_STOPWORDS:
            seen.add(w)
            out.append(w)
    return out


def _fts_query(words: list[str], mode: str) -> str:
    if not words:
        return '""'
    return (" AND " if mode == "AND" else " OR ").join(words)


_SEED_SQL = (
    "SELECT c.id, c.path, c.indexed_title, c.token_est, c.heading, bm25(docs_fts) AS score "
    "FROM docs_fts JOIN chunks c ON c.id = docs_fts.rowid "
    "WHERE docs_fts MATCH ? ORDER BY score LIMIT ?"
)
_NEIGHBOR_SQL = (
    "SELECT c.id, c.path, c.indexed_title, c.token_est, c.heading, bm25(docs_fts) AS score "
    "FROM docs_fts JOIN chunks c ON c.id = docs_fts.rowid "
    "WHERE docs_fts MATCH ? AND c.path = ? ORDER BY score LIMIT 1"
)
# No FTS gate — unconditional inclusion is the entire point of a link edge
# (V1's neighbor rule requires the SAME query bar every seed clears; a link
# recovers exactly the case where a relevant target shares no vocabulary
# with the task, so gating it on that vocabulary would defeat it). Takes
# the target doc's first chunk (document order) as a deterministic proxy
# for "where a reader following the link would land" — a known limitation
# for long multi-chunk targets, since there's no query to disambiguate
# which section is relevant when inclusion doesn't depend on one.
_LINK_SQL = (
    "SELECT c.id, c.path, c.indexed_title, c.token_est, c.heading, NULL AS score "
    "FROM chunks c WHERE c.path = ? ORDER BY c.id LIMIT 1"
)
MAX_LINK_NEIGHBORS_PER_SEED = 5
# Retrieve-time cap, independent of index.py's MAX_LINK_FANOUT: that one
# bounds what a hub doc contributes to the edges table at index time; this
# one bounds what any single retrieval pulls from it, and is tunable
# without reindexing.

# V4: one code file can now be multiple chunks (def/class-boundary sliced).
# _CODE_CHUNK_SQL fetches one specific chunk by (path, heading) — the
# symbol-resolved case; _CODE_FILE_CHUNKS_SQL fetches every chunk for a
# path in document order — the filename-only fallback, and (since a
# non-sliced file has exactly one chunk row) also what makes V3's old
# single-chunk behavior fall out unchanged for files that were never
# chunking candidates.
_CODE_CHUNK_SQL = (
    "SELECT c.id, c.path, c.indexed_title, c.token_est, c.heading, NULL AS score "
    "FROM chunks c WHERE c.path = ? AND c.heading IS ? ORDER BY c.id LIMIT 1"
)
_CODE_FILE_CHUNKS_SQL = (
    "SELECT c.id, c.path, c.indexed_title, c.token_est, c.heading, NULL AS score "
    "FROM chunks c WHERE c.path = ? ORDER BY c.id"
)
_SYMBOL_NEIGHBORS_SQL = "SELECT target FROM edges WHERE source = ? AND kind = 'symbol'"
MAX_CODE_NEIGHBORS_PER_SEED = 5
MAX_SYMBOL_FANOUT = 5
# Retrieve-time, tunable without reindexing (like MAX_CODE_NEIGHBORS_PER_SEED).
# Skip-not-truncate: if a symbol-resolved chunk's one-hop expansion (preamble
# + seed + same-name neighbors) would exceed this, the WHOLE expansion is
# discarded and degraded to the filename-only fallback (all chunks in the
# file, document order) rather than truncated to an arbitrary subset.


def retrieve(
    repo_root: Path,
    db_path: Path,
    task: str,
    max_tokens: int = 8000,
    seed_limit: int = 10,
) -> dict:
    """Run retrieval and return structured data (no rendering).

    {
      "task": str, "query_used": "AND"|"OR", "budget": int, "total_tokens": int,
      "chunks": [{"id", "path", "indexed_title", "heading", "token_est",
                  "score", "rank", "provenance": "seed"|"neighbor"|"link"|"code_ref",
                  "via": str | None,  # seed path that pulled in a link/code chunk
                  "body"}, ...],
      "budget_cut": [{"path", "heading", "provenance", "via", "rank", "token_est"}, ...]
        # candidates that scored into `ranked` but lost to the token budget --
        # what V2/V3/V4 tiers cost against a V1 baseline is only computable
        # if this counterfactual is captured alongside what was selected.
    }
    """
    repo_root = repo_root.resolve()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    words = _fts_words(task)
    seeds = conn.execute(_SEED_SQL, (_fts_query(words, "AND"), seed_limit)).fetchall()
    query_used = "AND"
    if not seeds:
        # Only widen when AND found literally nothing — a small number of
        # AND hits is still higher-precision evidence than a larger OR set,
        # not weaker evidence. Requiring a minimum COUNT before trusting
        # the stricter query was backwards: it discarded exact single
        # matches in favor of noisier fallback results.
        seeds = conn.execute(_SEED_SQL, (_fts_query(words, "OR"), seed_limit)).fetchall()
        query_used = "OR"

    ranked: dict[int, float] = {}
    meta: dict[int, sqlite3.Row] = {}
    provenance: dict[int, str] = {}
    via: dict[int, str] = {}
    for i, row in enumerate(seeds):
        ranked[row["id"]] = float(i)
        meta[row["id"]] = row
        provenance[row["id"]] = "seed"

    seed_paths = {row["path"] for row in seeds}
    # Neighbor expansion is score-floored: a co-located file only enters the
    # pack if it ALSO matches the query on its own terms (same AND/OR mode
    # the seeds used) — co-location alone is no longer sufficient, which is
    # what stops an unrelated same-directory file from riding in for free.
    neighbor_query = _fts_query(words, query_used)
    for i, row in enumerate(seeds):
        neighbors = conn.execute(
            "SELECT target FROM edges WHERE source = ? AND kind = 'colocation'",
            (row["path"],),
        ).fetchall()
        for nb in neighbors:
            if nb["target"] in seed_paths:
                continue
            for nc in conn.execute(_NEIGHBOR_SQL, (neighbor_query, nb["target"])).fetchall():
                if nc["id"] not in ranked:
                    ranked[nc["id"]] = i + 0.5
                    meta[nc["id"]] = nc
                    provenance[nc["id"]] = "neighbor"

    # Link neighbors are unconditional (no FTS gate) — ranked strictly below
    # every seed and every co-location neighbor (seed_limit + i + j/100),
    # ordered within that tier by the originating seed's rank.
    for i, row in enumerate(seeds):
        link_targets = conn.execute(
            "SELECT target FROM edges WHERE source = ? AND kind = 'link' "
            "ORDER BY target LIMIT ?",
            (row["path"], MAX_LINK_NEIGHBORS_PER_SEED),
        ).fetchall()
        for j, lt in enumerate(link_targets):
            if lt["target"] in seed_paths:
                continue
            lc = conn.execute(_LINK_SQL, (lt["target"],)).fetchone()
            if lc and lc["id"] not in ranked:
                ranked[lc["id"]] = seed_limit + i + j / 100.0
                meta[lc["id"]] = lc
                provenance[lc["id"]] = "link"
                via[lc["id"]] = row["path"]

    # Code neighbors are unconditional too, ranked strictly below the entire
    # link tier (which occupies [seed_limit, seed_limit*2)) regardless of
    # seed_limit's value.
    CODE_TIER_BASE = seed_limit * 2
    for i, row in enumerate(seeds):
        code_targets = conn.execute(
            "SELECT target FROM edges WHERE source = ? AND kind = 'code_ref' "
            "ORDER BY target LIMIT ?",
            (row["path"], MAX_CODE_NEIGHBORS_PER_SEED),
        ).fetchall()
        for j, ct in enumerate(code_targets):
            code_path, heading = split_code_key(ct["target"])
            if code_path in seed_paths:
                continue

            if heading is not None:
                # Symbol-resolved: seed on that chunk, one-hop expand over
                # kind='symbol' edges within the same file, always prepend
                # the preamble. If the resulting group is too big, discard
                # the expansion and degrade to the filename-only group
                # below (skip-not-truncate, not an arbitrary partial slice).
                seed_chunk = conn.execute(_CODE_CHUNK_SQL, (code_path, heading)).fetchone()
                if seed_chunk is None:
                    continue  # heading vanished since indexing — fail open by skipping
                neighbor_rows = conn.execute(_SYMBOL_NEIGHBORS_SQL, (ct["target"],)).fetchall()
                neighbor_chunks = []
                for nr in neighbor_rows:
                    n_path, n_heading = split_code_key(nr["target"])
                    nc = conn.execute(_CODE_CHUNK_SQL, (n_path, n_heading)).fetchone()
                    if nc:
                        neighbor_chunks.append(nc)
                preamble = conn.execute(_CODE_CHUNK_SQL, (code_path, None)).fetchone()
                group = ([preamble] if preamble else []) + [seed_chunk] + neighbor_chunks
                if len(group) > MAX_SYMBOL_FANOUT:
                    group = conn.execute(_CODE_FILE_CHUNKS_SQL, (code_path,)).fetchall()
            else:
                # Filename-only: preamble + every chunk in the file, in
                # document order, budget-trimmed downstream same as V3's
                # whole-file inclusion — just now cut at def boundaries
                # instead of mid-function.
                group = conn.execute(_CODE_FILE_CHUNKS_SQL, (code_path,)).fetchall()

            for k, cc in enumerate(group):
                if cc["id"] not in ranked:
                    ranked[cc["id"]] = CODE_TIER_BASE + i + j / 100.0 + k / 10000.0
                    meta[cc["id"]] = cc
                    provenance[cc["id"]] = "code_ref"
                    via[cc["id"]] = row["path"]

    ordered = sorted(ranked.items(), key=lambda kv: kv[1])
    selected, running = [], 0
    selected_ids: set[int] = set()
    for chunk_id, _rank in ordered:
        m = meta[chunk_id]
        if running + m["token_est"] > max_tokens and selected:
            continue
        selected.append(m)
        selected_ids.add(chunk_id)
        running += m["token_est"]

    # Counterfactual: candidates that scored into `ranked` but the budget
    # trim above didn't select -- this is what a link/code_ref/symbol tier
    # (or a bigger seed set) may have displaced. Captured regardless of
    # whether the query log is enabled; it's cheap and belongs with the
    # rest of retrieve()'s structured output either way.
    budget_cut = [
        {
            "path": meta[chunk_id]["path"],
            "heading": meta[chunk_id]["heading"],
            "provenance": provenance[chunk_id],
            "via": via.get(chunk_id),
            "rank": rank,
            "token_est": meta[chunk_id]["token_est"],
        }
        for chunk_id, rank in ordered
        if chunk_id not in selected_ids
    ]

    chunks = []
    for m in selected:
        chunk_id = m["id"]
        try:
            raw = (repo_root / m["path"]).read_text(encoding="utf-8", errors="replace")
            full_body = frontmatter.loads(raw).content
            if Path(m["path"]).suffix.lstrip(".") in CODE_EXTENSIONS:
                # Code chunks have no markdown headings, so extract_section
                # would always short-circuit to the whole file — that was
                # coincidentally correct under V3's whole-file-only model
                # and stops being correct now that code files are sliced.
                body = _extract_code_chunk(full_body, m["heading"]).strip()
            else:
                body = extract_section(full_body, m["heading"]).strip()
        except OSError as e:
            body = f"[could not read source: {e}]"
        chunks.append({
            "id": chunk_id,
            "path": m["path"],
            "indexed_title": m["indexed_title"],
            "heading": m["heading"],
            "token_est": m["token_est"],
            "score": m["score"],
            "rank": ranked[chunk_id],
            "provenance": provenance[chunk_id],
            "via": via.get(chunk_id),
            "body": body,
        })

    conn.close()
    result = {
        "task": task,
        "query_used": query_used,
        "budget": max_tokens,
        "total_tokens": running,
        "chunks": chunks,
        "budget_cut": budget_cut,
    }
    _log_query(result)
    return result


_QUERY_LOG_ENV = "DOCGRAPH_QUERY_LOG"
# Opt-in (unset by default). Set via `-e DOCGRAPH_QUERY_LOG=/abs/path.jsonl`
# on `claude mcp add` -- the MCP server is a process Claude Code spawns, not
# a child of your interactive shell, so exporting this in a terminal never
# reaches it. See docs/HANDOFF.md and README's registration recipe.


def _log_query(data: dict) -> None:
    """Append-only JSONL query log, closing the V2/V3/V4 validation gate
    (docs/V4_NEXT_STEPS.md): does a link/code_ref/symbol-provenance chunk
    ever get used, and what did it cost (budget_cut) against a V1 baseline.
    Never allowed to break retrieval -- any failure here is swallowed.
    """
    log_path = os.environ.get(_QUERY_LOG_ENV)
    if not log_path:
        return
    try:
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "task": data["task"],
            "query_used": data["query_used"],
            "budget": data["budget"],
            "total_tokens": data["total_tokens"],
            "chunks": [
                {
                    "path": c["path"], "heading": c["heading"],
                    "provenance": c["provenance"], "via": c["via"],
                    "rank": c["rank"], "token_est": c["token_est"],
                }
                for c in data["chunks"]
            ],
            "budget_cut": data["budget_cut"],
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def build_pack(
    repo_root: Path,
    db_path: Path,
    task: str,
    max_tokens: int = 8000,
    seed_limit: int = 10,
) -> str:
    return _render(retrieve(repo_root, db_path, task, max_tokens, seed_limit))


def _render(data: dict) -> str:
    out = ["# DocGraph context pack", "", f"Task: {data['task']}", "",
           f"{len(data['chunks'])} chunks, ~{data['total_tokens']} tokens "
           f"(budget {data['budget']}, {data['query_used']}-matched seeds)", ""]
    for c in data["chunks"]:
        out.append(f"## {c['indexed_title']}")
        loc = c["path"] + (f" § {c['heading']}" if c["heading"] else "")
        out.append(f"Source: {loc}")
        out.append("")
        if c["provenance"] == "code_ref":
            lang = Path(c["path"]).suffix.lstrip(".")
            out.append(f"```{lang}")
            out.append(c["body"])
            out.append("```")
        else:
            out.append(c["body"])
        out.append("")
    return "\n".join(out)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Generate a DocGraph context pack for a task.")
    p.add_argument("repo_root", type=Path)
    p.add_argument("db_path", type=Path)
    p.add_argument("task")
    p.add_argument("--max-tokens", type=int, default=8000)
    p.add_argument("--seed-limit", type=int, default=10)
    args = p.parse_args()
    print(build_pack(args.repo_root, args.db_path, args.task, args.max_tokens, args.seed_limit))
