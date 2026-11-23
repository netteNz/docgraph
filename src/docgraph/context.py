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
import hashlib
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


class IndexStaleError(RuntimeError):
    """The repository no longer matches the content used to build an index."""


def _source_hash(raw: str) -> str:
    """Match index.py's persisted, truncated source hash exactly."""
    return hashlib.sha256(raw.encode()).hexdigest()[:12]


def _require_fresh_sources(conn: sqlite3.Connection, repo_root: Path) -> None:
    """Fail before ranking when indexed source content has changed or vanished.

    Chunk bodies are intentionally not stored in SQLite. Rendering against a
    changed working tree could otherwise silently select a different section
    or fall back to the entire file when an indexed heading disappears.
    """
    stale: list[str] = []
    unreadable: list[str] = []
    for row in conn.execute("SELECT path, hash FROM docs ORDER BY path"):
        try:
            raw = (repo_root / row["path"]).read_text(encoding="utf-8", errors="replace")
        except OSError:
            unreadable.append(row["path"])
            continue
        if _source_hash(raw) != row["hash"]:
            stale.append(row["path"])

    if stale or unreadable:
        details = []
        if stale:
            details.append("changed: " + ", ".join(stale[:3]))
        if unreadable:
            details.append("missing/unreadable: " + ", ".join(unreadable[:3]))
        extra = len(stale) + len(unreadable) - 3
        suffix = f" (+{extra} more)" if extra > 0 else ""
        raise IndexStaleError(
            "index is stale relative to the source repository ("
            + "; ".join(details)
            + suffix
            + "); rebuild it with `python -m docgraph.index <repo_root> <db_path>`"
        )

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

OVERSIZED_WHOLE_FILE_BUDGET_FRACTION = 0.25
# A *whole-file* code chunk (heading IS NULL) claiming more than this share of
# the entire token budget is an unsliceable script — `code_chunks.py`'s
# def/class slicer found no top-level structure, so the file is one indivisible
# blob (rl-stocks: `scripts/analyze_reward_divergence.py`, 444 lines, zero
# top-level defs, 4413 tokens = 55% of a default pack). Admitted first, it
# starves every other code target; there is no way to trim it, so it defers to
# the back of its own seed's code band instead.
#
# Expressed as a fraction of the budget rather than an absolute token count on
# purpose: the harm is "one chunk eats the pack", which is inherently relative,
# and a fixed constant would have to be tuned against whichever file we last
# looked at. Two things are deliberately exempt: a sliceable file's small
# preamble (heading IS NULL but tiny), and every symbol chunk (heading NOT
# NULL) — a large named function is often exactly the answer, so size alone
# is not grounds to demote it.


CODE_HEADING_RELEVANCE = True
# Retrieve-time, killable without reindexing. A code chunk whose heading (def /
# class name, e.g. "generate_rollback_guide", "TradingEnv > step") shares a word
# stem with the task is "relevant"; chunks are ordered by how many task stems
# their heading matches (more first, from any seed), then unmatched chunks;
# within each match-count group the breadth-first order, the oversized penalty
# and the seed bands are unchanged. Code ranks never drop below
# CODE_TIER_BASE, so seed/link tiers are untouched. Replaces corpus-wide
# in-degree demotion, which the 2026-11-23 replay refuted (useful chunks live in
# heavily-referenced files too).

_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
CODE_HEADING_NOISE = frozenset({"init", "self", "main", "get", "set", "run", "test"})
_TASK_STOPWORDS = frozenset({
    "how", "does", "what", "the", "for", "and", "this", "that", "with", "from",
    "into", "about", "when", "why", "which", "where", "are", "was", "has", "have",
    "can", "should", "explain", "work", "works", "change", "changed",
    # Generic function words: "one"/"two" in a task title matched run_one_multiplier
    # on a second corpus (coinbase-rl-bot) -- same failure as "data" in legacy-19.
    "one", "two", "all", "any", "new", "use", "used", "using", "per", "not", "but",
    "our", "its", "you", "your", "also", "than", "then", "them", "they", "out",
    # Generic task verbs ("write tests for X" matched _write_summary, "what does X
    # compute" matched compute_metrics): they name the request, not the code.
    "write", "show", "list", "find", "make", "build", "create", "add", "fix",
    "compute", "calculate", "describe", "tell", "give", "need", "want", "did",
})


def _identifier_stems(text: str | None) -> set[str]:
    """Word stems of an identifier or phrase: CamelCase and snake_case are split,
    tokens shorter than 3 chars dropped, then 5-char prefix (_stem_key)."""
    if not text:
        return set()
    spaced = _CAMEL_RE.sub(r"\1 \2", text)
    return {_stem_key(t) for t in re.findall(r"[A-Za-z0-9]+", spaced) if len(t) > 2}


def _task_stems(task: str) -> set[str]:
    # From the raw task, not _fts_words: that lowercases first, so "ExitManager"
    # would stay one token and never match an `exit_manager`-style heading.
    spaced = _CAMEL_RE.sub(r"\1 \2", task)
    return {
        _stem_key(t) for t in re.findall(r"[A-Za-z0-9]+", spaced)
        if len(t) > 2 and t.lower() not in _TASK_STOPWORDS
    } - CODE_HEADING_NOISE


def _heading_matches(heading: str | None, task_stems: set[str]) -> int:
    """How many distinct task stems the heading shares (0 = not relevant)."""
    return len((_identifier_stems(heading) - CODE_HEADING_NOISE) & task_stems)


def _heading_relevant(heading: str | None, task_stems: set[str]) -> bool:
    return _heading_matches(heading, task_stems) > 0


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
                  "tier_detail": "filename"|"symbol_target"|"symbol_neighbor"|...,
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
    try:
        _require_fresh_sources(conn, repo_root)
    except Exception:
        conn.close()
        raise

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
    tier_detail: dict[int, str] = {}
    via: dict[int, str] = {}
    relevant: set[int] = set()
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
    task_stems = _task_stems(task) if CODE_HEADING_RELEVANCE else set()
    for i, row in enumerate(seeds):
        code_targets = conn.execute(
            # NOTE: promoting symbol-resolved targets ("path#heading") ahead
            # of filename fallbacks was tried and reverted — it shifts every
            # later target down one slot, and on rl-stocks that pushed
            # `src/exit_manager.py` past MAX_CODE_NEIGHBORS_PER_SEED so it
            # stopped being a candidate at all. Any retry needs to widen the
            # LIMIT in the same change, not just reorder within it.
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
                group = []
                if preamble:
                    group.append((preamble, "symbol_preamble"))
                group.append((seed_chunk, "symbol_target"))
                group.extend((chunk, "symbol_neighbor") for chunk in neighbor_chunks)
                if len(group) > MAX_SYMBOL_FANOUT:
                    group = [
                        (chunk, "symbol_fallback")
                        for chunk in conn.execute(_CODE_FILE_CHUNKS_SQL, (code_path,)).fetchall()
                    ]
            else:
                # Filename-only: preamble + every chunk in the file, in
                # document order, budget-trimmed downstream same as V3's
                # whole-file inclusion — just now cut at def boundaries
                # instead of mid-function.
                group = [
                    (chunk, "filename")
                    for chunk in conn.execute(_CODE_FILE_CHUNKS_SQL, (code_path,)).fetchall()
                ]

            oversized = max_tokens * OVERSIZED_WHOLE_FILE_BUDGET_FRACTION
            for k, (cc, detail) in enumerate(group):
                if cc["id"] not in ranked:
                    # k is the MAJOR axis and j is minor (breadth-first): all
                    # targets' position-0 chunk (preamble, or first chunk in
                    # doc order) outrank any target's position-1 chunk, etc.
                    # Target-major (j major) was the bug behind the rollback
                    # gate failure — a same-seed doc that resolves two
                    # SEPARATE symbol targets in the same file (e.g. an
                    # earlier-defined `utc_now` and a later-defined
                    # `generate_rollback_guide`, each its own `code_targets`
                    # entry) would fully expand the alphabetically/lexically
                    # first target's whole group before the second target
                    # got a single chunk in, starving the on-topic one under
                    # a tight budget purely by document order. j stays
                    # bounded by MAX_CODE_NEIGHBORS_PER_SEED-1 (<=4) and k is
                    # assumed to stay under 100 per target (largest observed
                    # group in production data was 26 chunks) — if a target
                    # ever produces >=100 chunks, k/100 would collide with
                    # the next integer step of i; widen the divisor before
                    # that becomes possible.
                    penalty = 0.5 if (
                        cc["heading"] is None and cc["token_est"] > oversized
                    ) else 0.0
                    n_match = _heading_matches(cc["heading"], task_stems)
                    is_rel = n_match > 0
                    # Each task stem a heading FAILS to match shifts it one full
                    # seed band down: most-matched chunks (any seed) first, the
                    # unmatched last, each group keeping the breadth-first order
                    # above. Ordering by match count (not just matched/unmatched)
                    # keeps a heading hitting one generic stem ("data") from
                    # outranking one hitting several ("news", "features").
                    shift = seed_limit * (len(task_stems) - n_match)
                    ranked[cc["id"]] = (
                        CODE_TIER_BASE + shift + i + penalty + k / 100.0 + j / 10000.0
                    )
                    if is_rel:
                        relevant.add(cc["id"])
                    meta[cc["id"]] = cc
                    provenance[cc["id"]] = "code_ref"
                    tier_detail[cc["id"]] = detail
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
            "tier_detail": tier_detail.get(chunk_id),
            "via": via.get(chunk_id),
            "relevant": chunk_id in relevant,
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
            "tier_detail": tier_detail.get(chunk_id),
            "via": via.get(chunk_id),
            "relevant": chunk_id in relevant,
            "body": body,
        })

    conn.close()
    confidence = _assess_confidence(words, query_used, seeds, chunks)
    # Room the code tier actually had: budget minus everything non-code_ref
    # that was selected. The confound under every per-tier precision number
    # (V5 WS4) -- computed here, not in _log_query, so serve.py sees it too.
    code_tier_room = max_tokens - sum(
        c["token_est"] for c in chunks if c["provenance"] != "code_ref"
    )
    result = {
        "task": task,
        "query_used": query_used,
        "confidence": confidence,
        "budget": max_tokens,
        "code_tier_room": code_tier_room,
        "total_tokens": running,
        "chunks": chunks,
        "budget_cut": budget_cut,
    }
    _log_query(result)
    return result


WEAK_COVERAGE_FLOOR = 0.5
# A pack is "weak" when even its best seed chunk contains fewer than this
# fraction of the task's significant words. Tunable without reindexing.


def _stem_key(word: str) -> str:
    return word.lower()[:5]  # crude prefix stem, only for coverage heuristics


def _assess_confidence(words: list[str], query_used: str, seeds, chunks: list[dict]) -> dict:
    """Honesty signal: does this pack plausibly answer the task, or is it
    whatever FTS could scrape together? Deliberately NOT based on query_used
    alone -- an AND match on one generic hub doc is weak too -- so it combines
    lexical coverage of the best seed chunk with absence of non-seed support."""
    seed_chunks = [c for c in chunks if c["provenance"] == "seed"]
    keys = {_stem_key(w) for w in words}
    best = 0.0
    for c in seed_chunks:
        text = " ".join((c["indexed_title"], c["heading"] or "", c["body"])).lower()
        toks = {t[:5] for t in re.findall(r"[a-z0-9]+", text)}
        if keys:
            best = max(best, len(keys & toks) / len(keys))
    support = any(c["provenance"] != "seed" for c in chunks)
    reasons = []
    if not seeds:
        reasons.append("no_match")
    else:
        if best < WEAK_COVERAGE_FLOOR:
            reasons.append("low_coverage")
        if query_used == "OR" and not support:
            reasons.append("or_fallback_no_support")
    return {
        "weak": bool(reasons),
        "reasons": reasons,
        "seed_count": len(seeds),
        "best_coverage": round(best, 2),
        "non_seed_support": support,
    }


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
            "code_tier_room": data.get("code_tier_room"),
            "total_tokens": data["total_tokens"],
            "chunks": [
                {
                    "path": c["path"], "heading": c["heading"],
                    "provenance": c["provenance"], "tier_detail": c["tier_detail"], "via": c["via"],
                    "rank": c["rank"], "token_est": c["token_est"], "relevant": c.get("relevant", False),
                }
                for c in data["chunks"]
            ],
            "budget_cut": data["budget_cut"],
            "confidence": data.get("confidence"),
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
    conf = data.get("confidence")
    if conf and conf["weak"]:
        out[-1:] = [
            f"> WEAK PACK ({', '.join(conf['reasons'])}): best chunk covers "
            f"{int(conf['best_coverage'] * 100)}% of the task's terms. The corpus may "
            f"not contain an answer -- treat this as a lead, not an answer, and "
            f"say so rather than citing it as authoritative.", ""]
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
