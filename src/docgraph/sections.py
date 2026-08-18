"""
Heading-based section splitting, shared between index.py (decides what to
index as a separate chunk) and context.py (re-derives the same split at
render time, since bodies aren't stored in the DB — the repo is re-read
from disk).

Using the identical function in both places is load-bearing: if index.py
and context.py ever disagreed on where a section starts/ends, a chunk's
indexed title would point at text that doesn't match what gets rendered.

Splitting is recursive and size-driven, not fixed-depth: split on H2; any
resulting section that is STILL over the chunking threshold and has 2+
subheadings at the next level gets split again (H3, then H4, hard stop).
Driven by real corpus variance — rl-stocks has files that are fine at H2
(GEMINI_CONTEXT.md, 22 H2s) and files with one catch-all H2 wrapping all
the real structure at H3 (EXIT_SIGNAL_TODO.md: single "## TODO LIST" over
"### PHASE 1..4"). A fixed depth is wrong for one of them whichever you
pick; the size test already in use decides per-section instead.
"""
import re

CHUNKING_TOKEN_THRESHOLD = 2000
CHUNKING_MIN_SUBHEADINGS = 2
MAX_HEADING_DEPTH = 4  # never split below ####


def _heading_re(level: int) -> re.Pattern:
    return re.compile(rf"^{'#' * level}\s+(.+)$", re.MULTILINE)


def token_est(text: str) -> int:
    return len(text) // 4


def is_chunking_candidate(body: str) -> bool:
    return (
        token_est(body) > CHUNKING_TOKEN_THRESHOLD
        and len(_heading_re(2).findall(body)) >= CHUNKING_MIN_SUBHEADINGS
    ) or (
        # single catch-all H2 (or none) but real structure at H3 —
        # the EXIT_SIGNAL_TODO.md shape. Still worth splitting.
        token_est(body) > CHUNKING_TOKEN_THRESHOLD
        and len(_heading_re(3).findall(body)) >= CHUNKING_MIN_SUBHEADINGS
    )


def _split_at_level(text: str, level: int) -> list[tuple[str | None, str]]:
    matches = list(_heading_re(level).finditer(text))
    if not matches:
        return [(None, text)]
    sections = []
    intro = text[: matches[0].start()].strip()
    if intro:
        sections.append((None, intro))
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((m.group(1).strip(), text[start:end].strip()))
    return sections


def split_sections(body: str, level: int = 2) -> list[tuple[str | None, str]]:
    """
    (heading_path, section_text) pairs. heading_path is None for content
    before the first heading, the heading text for a plain section, and
    "Parent > Child" when a too-large section was recursively subdivided.
    Always returns at least one entry.
    """
    out = []
    for heading, text in _split_at_level(body, level):
        oversized = token_est(text) > CHUNKING_TOKEN_THRESHOLD
        has_subs = (
            level < MAX_HEADING_DEPTH
            and len(_heading_re(level + 1).findall(text)) >= CHUNKING_MIN_SUBHEADINGS
        )
        if oversized and has_subs:
            for sub_heading, sub_text in split_sections(text, level + 1):
                if sub_heading is None:
                    # intro of the subdivided section keeps the parent name
                    out.append((heading, sub_text))
                else:
                    joined = f"{heading} > {sub_heading}" if heading else sub_heading
                    out.append((joined, sub_text))
        else:
            out.append((heading, text))
    return out


def extract_section(body: str, heading: str | None) -> str:
    """
    Re-derive the same split at render time and pull out one section.

    Critical: this must mirror index.py's is_chunking_candidate() check
    FIRST. Without it, heading=None is ambiguous — it means either "this
    chunk IS the whole file" (index-time non-candidate: never split) or
    "this is the intro before the first heading" (index-time candidate:
    was split, and this happens to be its first section). Calling
    split_sections() unconditionally on a small file that still contains
    real H2s silently returns just its intro, truncating everything after
    the first heading — confirmed bug, not hypothetical.
    """
    if not is_chunking_candidate(body):
        return body
    sections = split_sections(body)
    if len(sections) == 1:
        return sections[0][1]
    for h, text in sections:
        if h == heading:
            return text
    return body  # heading not found (file changed since indexing) — fail open