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
import re
import sqlite3
from pathlib import Path

import frontmatter

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
                  "score", "rank", "provenance": "seed"|"neighbor", "body"}, ...]
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

    ordered = sorted(ranked.items(), key=lambda kv: kv[1])
    selected, running = [], 0
    for chunk_id, _rank in ordered:
        m = meta[chunk_id]
        if running + m["token_est"] > max_tokens and selected:
            continue
        selected.append(m)
        running += m["token_est"]

    chunks = []
    for m in selected:
        chunk_id = m["id"]
        try:
            raw = (repo_root / m["path"]).read_text(encoding="utf-8", errors="replace")
            full_body = frontmatter.loads(raw).content
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
            "body": body,
        })

    conn.close()
    return {
        "task": task,
        "query_used": query_used,
        "budget": max_tokens,
        "total_tokens": running,
        "chunks": chunks,
    }


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
