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


def resolve_code_ref(source_path: str, raw_target: str, known_code_paths: set[str]) -> tuple[str | None, str]:
    """Resolve a filename mention to a known code file's repo-relative path.

    Tries relative-path resolution first (same normalization as
    links.py::resolve_link), then falls back to a basename match: if exactly
    one known code file has that basename, use it. Returns (path, "resolved"),
    (None, "dead") for zero matches, or (None, "ambiguous") for 2+ basename
    matches — tracked separately since ambiguous refs could be made real by
    disambiguating, dead ones can't (no edges beats wrong edges either way).
    """
    base = posixpath.dirname(source_path)
    normalized = posixpath.normpath(posixpath.join(base, raw_target)) if base else posixpath.normpath(raw_target)
    if normalized in known_code_paths:
        return normalized, "resolved"

    target_name = posixpath.basename(raw_target)
    matches = [p for p in known_code_paths if posixpath.basename(p) == target_name]
    if len(matches) == 1:
        return matches[0], "resolved"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "dead"


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
