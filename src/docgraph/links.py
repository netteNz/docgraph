"""
Markdown link extraction/resolution — pure, no-I/O so it's reusable both at
index time (index.py) and by the standalone audit script (scripts/link_audit.py).

Moved verbatim from scripts/link_audit.py's Phase 0 prototype once the audit
confirmed real (if thin, hub-concentrated) disjoint-link signal across the
rl-stocks and coinbase-rl-bot corpora.
"""
import posixpath
import re
from urllib.parse import unquote

_LINK_RE = re.compile(r"(!?)\[([^\]]*)\]\(([^)\s]+)\)")
_WIKILINK_RE = re.compile(r"(!?)\[\[([^\]\n]+?)\]\]")
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:")

MAX_LINK_FANOUT = 10
# Same instinct as index.py's MAX_COLOCATION_GROUP: a doc linking out to
# more than this many other docs (an INDEX.md / README hub) isn't a set of
# individually meaningful relationships anymore — Phase 0's audit found
# exactly this pattern (rl-stocks' docs/INDEX.md alone produced 17 of 20
# "disjoint" pairs). Skip the whole doc's link edges rather than truncate
# arbitrarily, matching _build_colocation_edges's skip-not-truncate rule.


def _strip_code(body: str) -> str:
    body = _FENCE_RE.sub("", body)
    body = _INLINE_CODE_RE.sub("", body)
    return body


def extract_links(body: str) -> list[tuple[str, str | None]]:
    """Return [(raw_target, anchor_or_None), ...] for real cross-doc links."""
    out = []
    for is_image, _text, target in _LINK_RE.findall(_strip_code(body)):
        if is_image:
            continue
        if target.startswith(_EXTERNAL_SCHEMES):
            continue
        if target.startswith("#"):
            continue  # same-doc self-reference, not a cross-doc edge
        raw_target, _, anchor = target.partition("#")
        if not raw_target:
            continue
        out.append((raw_target, anchor or None))
    return out


def resolve_link(source_path: str, raw_target: str, known_paths: set[str]) -> str | None:
    """Resolve a markdown link target to a docs.path, or None if unresolvable.

    docs.path is stored as path.relative_to(repo_root).as_posix() (index.py)
    -- canonically forward-slash on every platform -- so resolution uses
    posixpath, not os.path, to match regardless of what OS this runs on.
    """
    if raw_target.startswith("/"):
        base = ""
        target = raw_target.lstrip("/")
    else:
        base = posixpath.dirname(source_path)
        target = raw_target
    normalized = posixpath.normpath(posixpath.join(base, target)) if base else posixpath.normpath(target)
    if normalized in known_paths:
        return normalized
    decoded = unquote(normalized)  # Obsidian/Markdown editors emit %20 etc.
    return decoded if decoded in known_paths else None


def extract_wikilinks(body: str) -> list[str]:
    """Return raw [[Target]] names (alias and #heading/^block stripped)."""
    out = []
    for is_embed, inner in _WIKILINK_RE.findall(_strip_code(body)):
        name = inner.split("|", 1)[0].split("#", 1)[0].split("^", 1)[0].strip()
        if not name or (is_embed and not name.lower().endswith(".md") and "." in name):
            continue  # embedded image/pdf etc., not a note
        out.append(name)
    return out


def build_wikilink_index(known_paths: set[str]) -> dict[str, list[str]]:
    """Lowercased stem -> paths, shallowest first (Obsidian resolves by name)."""
    idx: dict[str, list[str]] = {}
    for p in sorted(known_paths, key=lambda x: (x.count("/"), x)):
        idx.setdefault(posixpath.splitext(posixpath.basename(p))[0].lower(), []).append(p)
    return idx


def resolve_wikilink(name: str, index: dict[str, list[str]]) -> str | None:
    """Resolve by path-or-stem; ambiguity resolved only by a unique shallowest
    match (same 'no edges beats wrong edges' rule as code refs)."""
    key = posixpath.splitext(name)[0].lower() if name.lower().endswith(".md") else name.lower()
    cands = index.get(posixpath.basename(key), [])
    if "/" in key:
        cands = [c for c in cands if posixpath.splitext(c)[0].lower().endswith(key)]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    d = [c.count("/") for c in cands]
    return cands[0] if d.count(d[0]) == 1 else None
