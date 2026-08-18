"""Four-bucket discovery rule, ported verbatim from the validated audit skill."""
import re
from pathlib import Path

DEFAULT_EXCLUDES = {
    ".git", "node_modules", ".venv", "venv", "dist", "build", "__pycache__",
    ".next", "site-packages", ".github", "target", "vendor", ".terraform",
    "coverage", ".pytest_cache", ".cache", "out", "staticfiles",
}
ALLCAPS_STEM_RE = re.compile(r"^[A-Z0-9_]+$")
DOCS_DIR_NAMES = {"docs"}
SKILLS_DIR_NAMES = {"skills"}


def _excluded(path: Path, root: Path) -> bool:
    return any(part in DEFAULT_EXCLUDES for part in path.relative_to(root).parts)


def discover(root: Path, exclude_buckets: set[str]) -> list[tuple[Path, str]]:
    found: dict[Path, str] = {}
    if "root" not in exclude_buckets:
        for p in root.glob("*.md"):
            found[p] = "root"
    for p in root.rglob("*.md"):
        if p in found or _excluded(p, root):
            continue
        parts = p.relative_to(root).parts[:-1]
        if "docs" not in exclude_buckets and any(x in DOCS_DIR_NAMES for x in parts):
            found[p] = "docs"
        elif "skills" not in exclude_buckets and any(x in SKILLS_DIR_NAMES for x in parts):
            found[p] = "skills"
    if "subdir-allcaps" not in exclude_buckets:
        for child in root.iterdir():
            if not child.is_dir() or child.name in DEFAULT_EXCLUDES:
                continue
            if child.name in DOCS_DIR_NAMES or child.name in SKILLS_DIR_NAMES:
                continue
            for f in child.glob("*.md"):
                if f not in found and ALLCAPS_STEM_RE.match(f.stem):
                    found[f] = "subdir-allcaps"
    return list(found.items())