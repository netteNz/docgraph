"""
Phase 3 evaluation for the V2 link-edge hypothesis. Plain script, no pytest
dependency (pyproject.toml only declares python-frontmatter and mcp; this is
a small, finite fixture list, not a growing regression suite yet).

Fixtures are split into two buckets, reported SEPARATELY and never averaged:

  organic — a link connects lexically-disjoint content with no hub doc in
    the way. This is the original V2 thesis in its cleanest form. Only ~3
    real examples exist across the audited corpora (Phase 0's finding), so
    this bucket gives a qualitative read on a handful of examples, not a
    statistically confident answer either way.

  hub     — traversal mediated by (or guarded against) a link-hub doc like
    an INDEX.md. Phase 0 found hub-driven pairs dominate raw disjoint counts
    (12 of 15 total), so this bucket answers a different question: does the
    fan-out cap actually keep a hub from leaking noise into retrieval.

Run: python tests/run_link_fixtures.py
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from docgraph.context import retrieve  # noqa: E402

FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "link_fixtures.json"


def _check(case: dict) -> tuple[bool, str]:
    chunks = retrieve(
        Path(case["repo_root"]), Path(case["db_path"]), case["task"]
    )["chunks"]

    if "expect_include" in case:
        want = case["expect_include"]
        for c in chunks:
            if c["path"] == want["path"] and c["provenance"] == want.get("provenance", c["provenance"]):
                return True, f"found {want['path']} with provenance={c['provenance']}"
        return False, f"expected {want['path']} (provenance={want.get('provenance')}) not found in results"

    if "expect_exclude" in case:
        want = case["expect_exclude"]
        for c in chunks:
            path_match = "path" not in want or c["path"] == want["path"]
            via_match = "via" not in want or c.get("via") == want["via"]
            if path_match and via_match and (
                "provenance" not in want or c["provenance"] == want["provenance"]
            ):
                return False, f"unexpectedly found excluded chunk: {c['path']} (via={c.get('via')})"
        return True, "no matching excluded chunk found"

    raise ValueError(f"fixture missing expect_include/expect_exclude: {case}")


def main() -> int:
    cases = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    by_bucket: dict[str, list[tuple[dict, bool, str]]] = {}
    for case in cases:
        ok, detail = _check(case)
        by_bucket.setdefault(case["bucket"], []).append((case, ok, detail))

    overall_ok = True
    for bucket, results in by_bucket.items():
        passed = sum(1 for _c, ok, _d in results if ok)
        print(f"\n=== {bucket} bucket: {passed}/{len(results)} passed ===")
        for case, ok, detail in results:
            status = "PASS" if ok else "FAIL"
            print(f"  [{status}] {case['task']!r} -- {detail}")
            if not ok:
                overall_ok = False

    print()
    if overall_ok:
        print("All fixtures passed.")
    else:
        print("Some fixtures failed.")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
