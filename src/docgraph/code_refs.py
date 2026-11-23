"""
Doc->code filename-mention extraction/resolution — mirrors links.py's shape
(pure, no-I/O, reused by index.py at index time).

Filename mentions only (no import-statement parsing) and whole-file-or-
symbol-chunk resolution (no fuzzy/prose matching) — see docs/HANDOFF.md's
V3 entry for the original filename-only scope, and its V4 entry for the
symbol-mention extension added here.
"""
import posixpath
import re

CODE_EXTENSIONS = {"py", "js", "ts", "jsx", "tsx", "go", "rs"}
# Deliberately actual-code extensions only, not config/text files (.txt,
# .json, .yaml) — matches "actual code" from the original ask and naturally
# excludes stale non-code filename mentions without special-casing them.

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_FILENAME_RE = re.compile(
    r"[\w./\\-]+\.(?:" + "|".join(sorted(CODE_EXTENSIONS)) + r")\b"
)

MAX_CODE_REFS_PER_DOC = 10
# Same skip-entirely-not-truncate rule as MAX_LINK_FANOUT — no evidence yet
# for which N of a doc's code refs would matter more than others.


def split_code_key(key: str) -> tuple[str, str | None]:
    """Split a code_ref/symbol edge endpoint into (path, heading|None).

    '#' is this codebase's existing reserved separator for "path plus a
    location within it" — links.py already splits markdown anchors on '#'
    the same way. A bare path (V3's filename-only resolution, unchanged)
    has no '#' and comes back with heading=None.
    """
    if "#" in key:
        path, heading = key.split("#", 1)
        return path, heading
    return key, None


def extract_code_mentions(body: str) -> list[str]:
    """Return filename-shaped tokens from backtick spans and fenced code
    blocks. Skips plain unbacktick'd prose entirely (precision over recall,
    matching the rest of this codebase's bias)."""
    out = []
    for fence in _FENCE_RE.findall(body):
        out.extend(_FILENAME_RE.findall(fence))
    for span in _INLINE_CODE_RE.findall(_FENCE_RE.sub("", body)):
        out.extend(_FILENAME_RE.findall(span))
    return out


def _unique_shallowest(paths: list[str]) -> str | None:
    """The single path at minimum depth, or None if two or more tie there."""
    depth = min(p.count("/") for p in paths)
    shallowest = [p for p in paths if p.count("/") == depth]
    return shallowest[0] if len(shallowest) == 1 else None


def resolve_code_ref_detailed(
    source_path: str, raw_target: str, known_code_paths: set[str],
) -> tuple[str | None, str, str | None, int]:
    """Resolve a filename mention, reporting *how* it resolved.

    Returns (path, status, method, n_candidates). status is "resolved",
    "dead" (no basename match at all) or "ambiguous"; method is set only
    when resolved. First match wins:

    1. exact       — relative-path resolution (same normalization as
                     links.py::resolve_link).
    2. basename    — exactly one known code file has that basename.
    3. scoped      — 2+ basename matches, and exactly one shares the source
                     doc's top-level directory. With 2+ in that directory,
                     the shallowest-path tiebreak applies *within the scope
                     only* — never escaping into another subproject, since
                     a wrong edge is worse than none. Root-level docs have
                     no subtree and skip this step.
    4. depth       — 2+ basename matches, none inside the doc's subtree:
                     the single shallowest path wins (a canonical top-level
                     copy beats a nested one, e.g. src/x.py over
                     staging/src/x.py). A tie at minimum depth stays
                     ambiguous.

    Path-qualified mentions (containing "/") never reach the basename tiers:
    the qualifier is evidence, and ignoring it mis-resolved e.g.
    `src/dashboard/pages/experiments.py` (written from docs/) to
    src/experiments.py. They resolve by:

    1a. rooted     — the qualified path is itself a repo-root-relative path.
    1b. suffix     — known files whose path ends with "/<qualified path>";
                     unique, or unique-shallowest among several. Failing that,
                     the longest known multi-segment path the mention itself
                     ends with (foreign absolute paths into the repo).
    A qualified mention matching neither is dead (stale or foreign path), not
    a basename fallback.

    Ambiguous refs are tracked separately from dead ones: a tie could be
    made real by more evidence, a dead ref can't.
    """
    base = posixpath.dirname(source_path)
    normalized = posixpath.normpath(posixpath.join(base, raw_target)) if base else posixpath.normpath(raw_target)
    if normalized in known_code_paths:
        return normalized, "resolved", "exact", 1

    if "/" in raw_target:
        qualified = posixpath.normpath(raw_target)
        while qualified.startswith(("./", "../", "/")):
            qualified = qualified.split("/", 1)[1] if not qualified.startswith("/") else qualified[1:]
        if qualified in known_code_paths:
            return qualified, "resolved", "rooted", 1
        tail = "/" + qualified
        suffixed = [p for p in known_code_paths if p.endswith(tail)]
        if not suffixed:
            # A foreign absolute path (/Users/x/proj/src/a.py, C:/work/src/a.py)
            # *contains* a repo path: match the longest known multi-segment path
            # the mention ends with. Single-segment known paths are excluded --
            # "<anything>/app.py" must not resolve to a top-level app.py.
            contained = [p for p in known_code_paths if "/" in p and qualified.endswith("/" + p)]
            if contained:
                longest = max(len(p) for p in contained)
                best = [p for p in contained if len(p) == longest]
                if len(best) == 1:
                    return best[0], "resolved", "suffix", 1
                return None, "ambiguous", None, len(best)
            return None, "dead", None, 0
        if len(suffixed) == 1:
            return suffixed[0], "resolved", "suffix", 1
        winner = _unique_shallowest(suffixed)
        if winner is not None:
            return winner, "resolved", "suffix", len(suffixed)
        return None, "ambiguous", None, len(suffixed)

    target_name = posixpath.basename(raw_target)
    matches = [p for p in known_code_paths if posixpath.basename(p) == target_name]
    if not matches:
        return None, "dead", None, 0
    if len(matches) == 1:
        return matches[0], "resolved", "basename", 1

    top = source_path.split("/", 1)[0] if "/" in source_path else ""
    if top:
        scoped = [p for p in matches if "/" in p and p.split("/", 1)[0] == top]
        if len(scoped) == 1:
            return scoped[0], "resolved", "scoped", len(matches)
        if len(scoped) > 1:
            winner = _unique_shallowest(scoped)
            if winner is not None:
                return winner, "resolved", "scoped", len(matches)
            return None, "ambiguous", None, len(matches)

    winner = _unique_shallowest(matches)
    if winner is not None:
        return winner, "resolved", "depth", len(matches)
    return None, "ambiguous", None, len(matches)


def resolve_code_ref(source_path: str, raw_target: str, known_code_paths: set[str]) -> tuple[str | None, str]:
    """(path|None, status) view of resolve_code_ref_detailed — see there."""
    path, status, _method, _n = resolve_code_ref_detailed(source_path, raw_target, known_code_paths)
    return path, status


_SYMBOL_SHAPE_RE = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)(?:\.([A-Za-z_][A-Za-z0-9_]*))?(\(\))?$"
)


def extract_symbol_mentions(body: str) -> list[str]:
    """Return inline-backtick spans shaped like a bare identifier,
    `Class.method`, or a zero-arg call: `train_step()`, `ExitManager.check`,
    `ReplayBuffer`.

    Deliberately narrower than extract_code_mentions: fenced blocks are
    excluded entirely here, not just de-duplicated against. A fenced code
    example legitimately contains many real identifiers, almost none of
    which the doc author intends as "look at this specific chunk" — a bare
    filename token is unambiguous even inside a fenced CLI invocation, but
    a bare identifier is not. Precision over recall, same bias
    extract_code_mentions already documents for itself.
    """
    out = []
    stripped = _FENCE_RE.sub("", body)
    for span in _INLINE_CODE_RE.findall(stripped):
        if _SYMBOL_SHAPE_RE.match(span.strip()):
            out.append(span.strip())
    return out


def resolve_symbol_ref(raw_mention: str, chunk_headings: set[str]) -> str | None:
    """Resolve a backticked symbol mention to one file's chunk heading.

    Pure, no I/O, no cross-file knowledge — mirrors resolve_link/
    resolve_code_ref's shape but operates on one already-parsed file's
    heading set instead of a repo-wide path set. Exact match only: strips a
    trailing '()', splits 'Class.method' into 'Class > method' (the heading
    shape code_chunks.build_chunks produces for a re-split class's
    methods). No fuzzy matching, no case normalization here — that already
    happened inside code_chunks.py's parameter-to-binding pass at index
    time, which is what built the headings this function matches against.
    """
    mention = raw_mention.rstrip("()")
    if mention in chunk_headings:
        return mention
    if "." in mention:
        cls, _, meth = mention.partition(".")
        candidate = f"{cls} > {meth}"
        if candidate in chunk_headings:
            return candidate
    return None
