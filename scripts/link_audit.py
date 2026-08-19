"""
Phase 0 measurement for the V2 link-edge hypothesis: given the doc-doc
markdown links that actually exist in a corpus, how many connect content
that shares NO vocabulary with each other? That's the one case graph
traversal via links can recover that FTS retrieval structurally cannot.

V1 already measured raw link *coverage* (~0-7% across 3 corpora, see
index.py's module docstring) as the reason links were rejected as a
retrieval signal. This script asks the narrower question that number
doesn't answer: among the links that exist, how many are "disjoint" —
i.e. the target would NOT be reachable as an FTS seed using the source
chunk's own vocabulary. That resolved-and-disjoint percentage is the
actual go/no-go signal for the rest of the V2 plan.

extract_links()/resolve_link() now live in src/docgraph/links.py (moved
there verbatim once Phase 0 confirmed real, if hub-concentrated, disjoint
signal) — this script imports them rather than duplicating the logic.
"""
import argparse
import sqlite3
from pathlib import Path

import frontmatter

# Mirrors docgraph.context's tokenizer exactly (import so any future
# tuning there doesn't silently diverge from what this script measures).
from docgraph.context import _fts_query, _fts_words
from docgraph.links import extract_links, resolve_link


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def audit(repo_root: Path, db_path: Path) -> None:
    repo_root = repo_root.resolve()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    doc_rows = conn.execute("SELECT path, title FROM docs").fetchall()
    known_paths = {r["path"] for r in doc_rows}
    title_by_path = {r["path"]: r["title"] for r in doc_rows}

    total_links = 0
    dead_links = 0
    resolved_pairs: list[tuple[str, str]] = []

    for path in sorted(known_paths):
        raw = (repo_root / path).read_text(encoding="utf-8", errors="replace")
        body = frontmatter.loads(raw).content
        for raw_target, _anchor in extract_links(body):
            total_links += 1
            target = resolve_link(path, raw_target, known_paths)
            if target is None or target == path:
                if target != path:
                    dead_links += 1
                continue
            resolved_pairs.append((path, target))

    # A doc mentioning the same link target twice (once in a table of
    # contents, once inline) is one relationship, not two — dedupe before
    # any counting so a source's true distinct-target fan-out (the thing
    # that actually determines hub vs organic) isn't inflated by repeats.
    resolved_pairs = sorted(set(resolved_pairs))

    disjoint_pairs: list[tuple[str, str, float]] = []
    for source, target in resolved_pairs:
        # A real task string is a short human description, not every word in
        # the source document — AND-ing an entire doc's vocabulary against a
        # target is a degenerate test (virtually nothing would ever match,
        # regardless of the link's actual quality). The source doc's own
        # TITLE is a much closer proxy for "a task about this doc's topic":
        # it's short, and it's exactly the kind of phrase a real task string
        # asking about this content would resemble.
        title_words = _fts_words(title_by_path.get(source) or "")
        if not title_words:
            continue
        query = _fts_query(title_words, "AND")
        hit = conn.execute(
            "SELECT 1 FROM docs_fts JOIN chunks c ON c.id = docs_fts.rowid "
            "WHERE docs_fts MATCH ? AND c.path = ? LIMIT 1",
            (query, target),
        ).fetchone()
        if hit is None:
            source_body = frontmatter.loads(
                (repo_root / source).read_text(encoding="utf-8", errors="replace")
            ).content
            target_body = frontmatter.loads(
                (repo_root / target).read_text(encoding="utf-8", errors="replace")
            ).content
            jac = _jaccard(set(_fts_words(source_body)), set(_fts_words(target_body)))
            disjoint_pairs.append((source, target, jac))

    conn.close()

    resolved = len(resolved_pairs)
    disjoint = len(disjoint_pairs)
    pct = lambda n, d: f"{n} ({100 * n / d:.1f}%)" if d else f"{n} (n/a)"

    print(f"\n=== {db_path} ===")
    print(f"total links found:        {total_links}")
    print(f"dead (unresolved) links:  {pct(dead_links, total_links)}")
    print(f"resolved cross-doc links: {pct(resolved, total_links)}")
    print(f"resolved AND disjoint:    {pct(disjoint, resolved)}  <-- the go/no-go number")

    if disjoint_pairs:
        # A source is a "hub" for reporting purposes if it accounts for more
        # than one disjoint pair on its own — Phase 0 found a single
        # INDEX.md-style doc can dominate the whole sample, and hub-mediated
        # vs organic pairs are evaluated as separate buckets downstream
        # (Phase 3), never averaged together.
        from collections import Counter
        source_counts = Counter(s for s, _t, _j in disjoint_pairs)
        print(f"\nall {len(disjoint_pairs)} disjoint pairs (source -> target, jaccard, bucket):")
        for source, target, jac in sorted(disjoint_pairs, key=lambda p: (source_counts[p[0]] == 1, p[2])):
            bucket = "hub" if source_counts[source] > 1 else "organic"
            print(f"  [{bucket:7}] {source!r} -> {target!r}  "
                  f"({title_by_path.get(source)!r} -> {title_by_path.get(target)!r}, jaccard={jac:.2f})")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Phase 0: measure resolved-and-disjoint link percentage.")
    p.add_argument("repo_root", type=Path)
    p.add_argument("db_path", type=Path)
    args = p.parse_args()
    audit(args.repo_root, args.db_path)
