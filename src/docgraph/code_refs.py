"""
Doc->code filename-mention extraction/resolution — mirrors links.py's shape
(pure, no-I/O, reused by index.py at index time).

Filename mentions only (no import-statement parsing, no symbol-name
resolution) and whole-file inclusion only (no def/class-boundary slicing) —
see docs/HANDOFF.md's V3 entry for why both are deliberately deferred.
"""
import os
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
    base = os.path.dirname(source_path)
    normalized = os.path.normpath(os.path.join(base, raw_target)) if base else os.path.normpath(raw_target)
    if normalized in known_code_paths:
        return normalized, "resolved"

    target_name = os.path.basename(raw_target)
    matches = [p for p in known_code_paths if os.path.basename(p) == target_name]
    if len(matches) == 1:
        return matches[0], "resolved"
    if len(matches) > 1:
        return None, "ambiguous"
    return None, "dead"
