"""
Build the DocGraph SQLite/FTS5 index from a repo's markdown corpus.

Schema decisions each trace to a specific finding from the audit phase
(three real corpora: trading-dashboard, veto-webapp, rl-stocks):

  - contentless FTS5 + porter stemming     -> the repo is the source of
    truth; re-read bodies from disk at pack-assembly time, don't store
    twice. Porter so "authenticate" matches "authentication" w/o embeddings.
  - title stored SEPARATELY from a disambiguated indexed_title -> rl-stocks
    had 26- and 31-way H1 title collisions on generated reports; when a
    title repeats within a project we append the path stem so FTS ranking
    can tell them apart.
  - edges table = parent-directory co-location, NOT frontmatter related:
    -> link_coverage_pct was ~0-7% across every repo, so explicit links
    are a dead signal. Co-location scoped to IMMEDIATE parent (results/
    stage2_h4/ is meaningful; all of results/ is not — the rl-stocks
    102-file sessions/ dir proved whole-top-level-dir is just noise).
  - content_hash + a >20 byte guard on dedupe -> empty files trivially
    share the empty-string hash; that was a false positive in rl-stocks.
"""
import hashlib
import re
import sqlite3
from pathlib import Path

import frontmatter  # python-frontmatter

from .discover import discover  # the validated 4-bucket rule
from .sections import is_chunking_candidate, split_sections, token_est as _token_est_shared

H1_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)
MIN_DEDUPE_BYTES = 20  # guard against empty/near-empty files trivially
                        # sharing the empty-string hash (real rl-stocks finding)


def _token_est(text: str) -> int:
    # Cheap heuristic, matches what the audit used. Swap for tiktoken later
    # if pack budgeting needs to be exact rather than approximate.
    return len(text) // 4


def _dedupe_by_hash(rows: list[dict]) -> tuple[list[dict], int]:
    # Same content at multiple paths (the .claude/ vs .agents/ skill mirror
    # is the concrete case that motivated this) previously got indexed and
    # chunked separately, so a context pack could return the identical text
    # twice — confirmed on real output, burning ~half the token budget on
    # zero new information. Keep one canonical copy (first path, sorted, for
    # determinism); drop the rest before they ever reach docs/chunks/FTS.
    by_hash: dict[str, list[dict]] = {}
    for r in rows:
        if r["bytes"] < MIN_DEDUPE_BYTES:
            by_hash.setdefault(f'unique:{r["path"]}', []).append(r)  # never dedupe trivial files against each other
        else:
            by_hash.setdefault(r["hash"], []).append(r)
    kept, dropped = [], 0
    for group in by_hash.values():
        group.sort(key=lambda r: r["path"])
        kept.append(group[0])
        dropped += len(group) - 1
    kept.sort(key=lambda r: r["path"])
    return kept, dropped


def _resolve_title(post: frontmatter.Post, body: str, path: Path) -> str:
    if "title" in post.metadata:
        return str(post.metadata["title"]).strip()
    m = H1_RE.search(body)
    return m.group(1).strip() if m else path.stem


def build(repo_root: Path, db_path: Path, exclude_buckets: set[str] | None = None) -> dict:
    repo_root = repo_root.resolve()
    conn = sqlite3.connect(db_path)
    conn.executescript(DROP + SCHEMA)  # always rebuild clean — no stale-state carryover

    discovered = discover(repo_root, exclude_buckets or set())
    rows = []
    for path, bucket in discovered:
        raw = path.read_text(encoding="utf-8", errors="replace")
        post = frontmatter.loads(raw)
        body = post.content
        rel = str(path.relative_to(repo_root))
        rows.append({
            "path": rel,
            "parent": str(Path(rel).parent),
            "bucket": bucket,
            "title": _resolve_title(post, body, path),
            "body": body,
            "hash": hashlib.sha256(raw.encode()).hexdigest()[:12],
            "bytes": len(raw),
            "token_est": _token_est(raw),
        })

    rows, dupes_dropped = _dedupe_by_hash(rows)

    _disambiguate_titles(rows)          # rl-stocks collision fix
    _insert(conn, rows)
    edge_result = _build_colocation_edges(conn, rows)  # decision B, parent-scoped, size-capped

    conn.commit()
    stats = {
        "files": len(rows), "edges": edge_result["edges"], "db": str(db_path),
        "duplicates_dropped": dupes_dropped,
        "colocation_groups_skipped": edge_result["skipped_groups"],
        "files_with_no_colocation_edges": edge_result["skipped_files"],
    }
    conn.close()
    return stats


def _disambiguate_titles(rows: list[dict]) -> None:
    # Within a (parent-dir) group, if a title repeats, append the stem so
    # the INDEXED title is unique even when the H1 isn't.
    seen: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r["parent"], r["title"])
        seen[key] = seen.get(key, 0) + 1
    for r in rows:
        key = (r["parent"], r["title"])
        if seen[key] > 1:
            r["indexed_title"] = f'{r["title"]} ({Path(r["path"]).stem})'
        else:
            r["indexed_title"] = r["title"]


def _insert(conn: sqlite3.Connection, rows: list[dict]) -> None:
    for r in rows:
        cur = conn.execute(
            "INSERT INTO docs(path,parent,bucket,title,indexed_title,hash,bytes,token_est) "
            "VALUES(?,?,?,?,?,?,?,?)",
            (r["path"], r["parent"], r["bucket"], r["title"],
             r["indexed_title"], r["hash"], r["bytes"], r["token_est"]),
        )
        doc_id = cur.lastrowid

        # Only actually split when it clears the same bar the audit used
        # (>2000 tokens AND >=2 H2s) — everything else stays one whole-file
        # chunk, unchanged from before this fix.
        sections = split_sections(r["body"]) if is_chunking_candidate(r["body"]) else [(None, r["body"])]

        for heading, text in sections:
            display_title = r["indexed_title"] if heading is None else f'{r["indexed_title"]} \u00a7 {heading}'
            # Matching title deliberately narrower than display title: a
            # section chunk matches on its OWN heading, not the file's
            # overall title — otherwise any query word that happens to hit
            # the file's title (e.g. "exit" matching "Exit Signal TODO
            # Plan") pulls back EVERY section of that file once OR-fallback
            # kicks in, defeating the whole point of chunking.
            fts_title = heading if heading is not None else r["indexed_title"]
            cc = conn.execute(
                "INSERT INTO chunks(doc_id,path,heading,indexed_title,token_est) VALUES(?,?,?,?,?)",
                (doc_id, r["path"], heading, display_title, _token_est_shared(text)),
            )
            conn.execute(
                "INSERT INTO docs_fts(rowid,indexed_title,body) VALUES(?,?,?)",
                (cc.lastrowid, fts_title, text),
            )


MAX_COLOCATION_GROUP = 10
# Above this, "same directory" stops being a meaningful relatedness signal
# and starts being noise — a 31-file docs/ folder isn't one relationship,
# it's 465 unrelated pairs. No edges beats wrong edges; these files still
# get found via FTS, they just don't get an artificial relevance boost
# from a neighbor that happens to share a folder.


def _build_colocation_edges(conn: sqlite3.Connection, rows: list[dict]) -> dict:
    by_parent: dict[str, list[str]] = {}
    for r in rows:
        by_parent.setdefault(r["parent"], []).append(r["path"])
    n, skipped_groups, skipped_files = 0, 0, 0
    for paths in by_parent.values():
        if len(paths) < 2:
            continue
        if len(paths) > MAX_COLOCATION_GROUP:
            skipped_groups += 1
            skipped_files += len(paths)
            continue
        for i, a in enumerate(paths):
            for b in paths[i + 1:]:
                conn.execute(
                    "INSERT OR IGNORE INTO edges(source,target,kind,weight) VALUES(?,?,?,?)",
                    (a, b, "colocation", 1.0),
                )
                conn.execute(
                    "INSERT OR IGNORE INTO edges(source,target,kind,weight) VALUES(?,?,?,?)",
                    (b, a, "colocation", 1.0),
                )
                n += 2
    return {"edges": n, "skipped_groups": skipped_groups, "skipped_files": skipped_files}


DROP = """
DROP TABLE IF EXISTS docs;
DROP TABLE IF EXISTS chunks;
DROP TABLE IF EXISTS edges;
DROP TABLE IF EXISTS docs_fts;
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    id            INTEGER PRIMARY KEY,
    path          TEXT UNIQUE NOT NULL,
    parent        TEXT NOT NULL,
    bucket        TEXT NOT NULL,
    title         TEXT,
    indexed_title TEXT,
    hash          TEXT NOT NULL,
    bytes         INTEGER,
    token_est     INTEGER
);
CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY,
    doc_id        INTEGER NOT NULL REFERENCES docs(id),
    path          TEXT NOT NULL,
    heading       TEXT,
    indexed_title TEXT,
    token_est     INTEGER
);
CREATE TABLE IF NOT EXISTS edges (
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    kind   TEXT NOT NULL,
    weight REAL DEFAULT 1.0,
    PRIMARY KEY (source, target, kind)
);
CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    indexed_title, body,
    content='', tokenize='porter'
);
"""

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Build the DocGraph SQLite/FTS5 index.")
    p.add_argument("repo_root", type=Path)
    p.add_argument("db_path", type=Path)
    p.add_argument("--exclude-bucket", action="append", default=[],
                    choices=["root", "docs", "skills", "subdir-allcaps"])
    args = p.parse_args()
    result = build(args.repo_root, args.db_path, set(args.exclude_bucket))
    print(f"Indexed {result['files']} files, {result['edges']} co-location edges -> {result['db']}")
    if result["duplicates_dropped"]:
        print(f"  ({result['duplicates_dropped']} byte-identical duplicate files skipped — "
              f"kept one canonical copy each)")
    if result["colocation_groups_skipped"]:
        print(f"  ({result['colocation_groups_skipped']} directories over "
              f"{MAX_COLOCATION_GROUP} files skipped for co-location — "
              f"{result['files_with_no_colocation_edges']} files get no "
              f"co-location edges, FTS-only retrieval still applies)")