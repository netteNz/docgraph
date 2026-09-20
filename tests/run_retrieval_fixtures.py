"""
Retrieval-accuracy regression harness (docs/RETRIEVAL_RANKING_PLAN.md Part 1).

Mirrors run_code_fixtures.py's shape exactly: a JSON case file, a
standalone _check(case) runner, and (in test_retrieval_fixtures.py) a thin
parametrized pytest wrapper.

Every case reconstructs a real documented ordering or budget failure (see
docs/validation/RL_STOCKS_VALIDATION_NOTES.md) with a synthetic corpus, so
none of them need the original repo. They score, not just pass/fail: _check
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
from docgraph.sections import is_chunking_candidate as is_doc_chunking_candidate  # noqa: E402
from docgraph.context import retrieve  # noqa: E402

from run_code_fixtures import _temp_index  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "retrieval_fixtures"
FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "retrieval_fixtures.json"


def _code_ref_chunks(result: dict) -> list[dict]:
    return [c for c in result["chunks"] if c["provenance"] == "code_ref"]


def _link_chunks(result: dict) -> list[dict]:
    return [c for c in result["chunks"] if c["provenance"] == "link"]


def _doc_body(case: dict) -> str:
    """Case docs come inline via `doc_body`, or from a fixture file via
    `doc_body_file` when they are too long to sit readably in JSON (the
    budget-starvation case needs a doc over the 2000-token markdown split
    threshold, or it indexes as a single seed and starves nothing)."""
    if "doc_body_file" in case:
        return (FIXTURES_DIR / case["doc_body_file"]).read_text(encoding="utf-8")
    return case["doc_body"]


def _check(case: dict) -> tuple[bool, str]:
    check = case["check"]
    expect = case["expect"]

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

    if expect.get("requires_doc_chunking"):
        # Same trap as requires_chunking, but for markdown link targets --
        # sections.is_chunking_candidate (H2/H3 + token floor), not
        # code_chunks.is_chunking_candidate (which additionally demands
        # top-level defs and is wrong for a doc).
        for dest in expect["requires_doc_chunking"]:
            filename = case["extra_docs"][dest]
            body = (FIXTURES_DIR / filename).read_text(encoding="utf-8")
            if not is_doc_chunking_candidate(body):
                return False, (
                    f"{dest} is no longer a chunking candidate — fixture "
                    "no longer exercises link-target chunk selection"
                )

    repo_root, db_path = _temp_index(
        sources=case["sources"],
        doc_body=_doc_body(case),
        fixtures_dir=FIXTURES_DIR,
        extra_docs=case.get("extra_docs"),
    )
    try:
        result = retrieve(repo_root, db_path, case["task"], max_tokens=case["max_tokens"])
        code_chunks = _code_ref_chunks(result)

        if check == "rank_order":
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

        if check == "target_selected":
            selected_paths = {c["path"] for c in code_chunks}
            target = expect["selected_path"]
            if target not in selected_paths:
                return False, f"{target!r} not among selected code paths: {sorted(selected_paths)}"
            return True, f"{target!r} selected among {len(selected_paths)} code paths"

        if check == "chunk_selected":
            # Budget starvation: the chunk is correctly *ranked* (code_fts
            # put it first in its tier) but the doc tier consumed the whole
            # budget before the code tier was reached. Assert on selection,
            # not on rank -- ranking already passes here and would hide the
            # defect entirely.
            heading = expect["heading"]
            headings = [c["heading"] for c in code_chunks]
            if heading in headings:
                rank = next(c["rank"] for c in code_chunks if c["heading"] == heading)
                return True, (
                    f"{heading!r} selected (rank {rank}); "
                    f"{len(code_chunks)} code chunks in {result['total_tokens']}/"
                    f"{result['budget']} tokens"
                )
            cut = [
                c for c in result["budget_cut"]
                if c["provenance"] == "code_ref" and c["heading"] == heading
            ]
            seed_tokens = sum(
                c["token_est"] for c in result["chunks"] if c["provenance"] == "seed"
            )
            why = (
                f"budget-cut at rank {cut[0]['rank']} ({cut[0]['token_est']} tok)"
                if cut else "not a candidate at all"
            )
            return False, (
                f"{heading!r} {why}; {seed_tokens} of {result['budget']} tokens went to "
                f"seeds, leaving {len(code_chunks)} code chunks: {headings}"
            )

        if check == "link_chunk_selected":
            # Which chunk of an already-included link target wins the one
            # slot. Assert on the chunk *for that path* specifically, not
            # merely that some link chunk exists -- a mode regression (AND
            # instead of OR) and an ordering regression (still picking the
            # first chunk) produce different wrong headings, and reporting
            # query_used lets the two be told apart from the failure alone.
            path = expect["path"]
            link_chunks = _link_chunks(result)
            by_path = [c for c in link_chunks if c["path"] == path]
            if not by_path:
                paths = sorted({c["path"] for c in link_chunks})
                return False, (
                    f"{path!r} not among link chunks (query_used={result['query_used']!r}); "
                    f"link paths present: {paths}"
                )
            got = by_path[0]
            expected_heading = expect["heading"]
            expected_via = expect.get("via")
            expected_mode = expect.get("query_used")
            if expected_mode is not None and result["query_used"] != expected_mode:
                return False, (
                    f"query_used={result['query_used']!r}, expected {expected_mode!r} "
                    f"(got heading {got['heading']!r} for {path!r})"
                )
            if expected_via is not None and got.get("via") != expected_via:
                return False, (
                    f"{path!r} link chunk came via {got.get('via')!r}, expected "
                    f"{expected_via!r} (heading={got['heading']!r})"
                )
            if got["heading"] != expected_heading:
                return False, (
                    f"{path!r} link chunk heading={got['heading']!r}, expected "
                    f"{expected_heading!r} (query_used={result['query_used']!r})"
                )
            return True, (
                f"{path!r} link chunk heading={got['heading']!r} "
                f"(query_used={result['query_used']!r})"
            )

        raise ValueError(f"unknown check type: {check!r}")
    finally:
        shutil.rmtree(repo_root, ignore_errors=True)


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
