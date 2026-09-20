"""
Retrieval-accuracy regression harness (docs/RETRIEVAL_RANKING_PLAN.md Part 1).

Mirrors run_code_fixtures.py's shape exactly: a JSON case file, a
standalone _check(case) runner, and (in test_retrieval_fixtures.py) a thin
parametrized pytest wrapper.

Both cases reconstruct real documented ordering failures (see
docs/validation/RL_STOCKS_VALIDATION_NOTES.md) with a synthetic corpus, so
neither needs the original repo. They score, not just pass/fail: _check
returns the observed rank alongside the boolean, and main() prints a small
table showing how much better (or worse) a change made ranking, not just
whether it crossed a line.

Run: python tests/run_retrieval_fixtures.py
"""
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from docgraph.code_chunks import is_chunking_candidate  # noqa: E402
from docgraph.context import retrieve  # noqa: E402

from run_code_fixtures import _temp_index  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "retrieval_fixtures"
FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "retrieval_fixtures.json"


def _code_ref_chunks(result: dict) -> list[dict]:
    return [c for c in result["chunks"] if c["provenance"] == "code_ref"]


def _check(case: dict) -> tuple[bool, str]:
    check = case["check"]
    expect = case["expect"]

    if check == "rank_order":
        if expect.get("requires_chunking"):
            # Hard constraint (docs/RETRIEVAL_RANKING_PLAN.md): a fixture that
            # collapses into one whole-file chunk passes vacuously without
            # testing in-file ordering at all. Fail loudly instead if a
            # future edit shrinks the fixture below the chunking threshold.
            for source in case["sources"]:
                body = (FIXTURES_DIR / source).read_text(encoding="utf-8")
                if not is_chunking_candidate(body):
                    return False, (
                        f"{source} is no longer a chunking candidate — fixture "
                        "no longer exercises in-file ordering"
                    )

        repo_root, db_path = _temp_index(
            sources=case["sources"], doc_body=case["doc_body"], fixtures_dir=FIXTURES_DIR,
        )
        try:
            result = retrieve(repo_root, db_path, case["task"], max_tokens=case["max_tokens"])
            code_chunks = _code_ref_chunks(result)
            headings = [c["heading"] for c in code_chunks]
            before, after = expect["before"], expect["after"]
            if before not in headings:
                return False, f"{before!r} not selected at all; got headings={headings}"
            if after not in headings:
                return False, f"{after!r} not selected at all; got headings={headings}"
            rank_before = next(c["rank"] for c in code_chunks if c["heading"] == before)
            rank_after = next(c["rank"] for c in code_chunks if c["heading"] == after)
            if not rank_before < rank_after:
                return False, (
                    f"{before!r} (rank {rank_before}) does not outrank "
                    f"{after!r} (rank {rank_after})"
                )
            return True, f"{before!r} (rank {rank_before}) outranks {after!r} (rank {rank_after})"
        finally:
            shutil.rmtree(repo_root, ignore_errors=True)

    if check == "target_selected":
        repo_root, db_path = _temp_index(
            sources=case["sources"], doc_body=case["doc_body"], fixtures_dir=FIXTURES_DIR,
        )
        try:
            result = retrieve(repo_root, db_path, case["task"], max_tokens=case["max_tokens"])
            code_chunks = _code_ref_chunks(result)
            selected_paths = {c["path"] for c in code_chunks}
            target = expect["selected_path"]
            if target not in selected_paths:
                return False, f"{target!r} not among selected code paths: {sorted(selected_paths)}"
            return True, f"{target!r} selected among {len(selected_paths)} code paths"
        finally:
            shutil.rmtree(repo_root, ignore_errors=True)

    raise ValueError(f"unknown check type: {check!r}")


def main() -> int:
    cases = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        ok, detail = _check(case)
        results.append((case, ok, detail))

    passed = sum(1 for _c, ok, _d in results if ok)
    print(f"\n=== retrieval fixtures: {passed}/{len(results)} passed ===")
    overall_ok = True
    for case, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        print(f"  [{status}] {case['name']} -- {detail}")
        if not ok:
            overall_ok = False

    print()
    print("All fixtures passed." if overall_ok else "Some fixtures failed.")
    return 0 if overall_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
