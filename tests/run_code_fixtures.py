"""
Evaluation harness for the V4 code-chunking + symbol-trace-expansion
hypothesis. Plain script, no pytest dependency, mirrors run_link_fixtures.py's
shape.

Unlike link_fixtures.json (which points at real indexed repos, since it
tests emergent corpus properties), code_fixtures.json points at small
hand-written .py sources under fixtures/code_fixtures/ -- V4's cases are
precise structural conditions, best tested directly against code_chunks.py's
pure functions. Two cases (index_symbol_edge, retrieve_group_size) build a
disposable temp repo + index to exercise index.py/context.py's integration,
since edge-building and retrieval expansion don't live in code_chunks.py.

Run: python tests/run_code_fixtures.py
"""
import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from docgraph.code_chunks import build_chunks, is_chunking_candidate, extract_chunk  # noqa: E402
from docgraph.context import retrieve  # noqa: E402
from docgraph.index import HUB_NAME_FANOUT, build as index_build  # noqa: E402

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "code_fixtures"
FIXTURES_PATH = Path(__file__).resolve().parent / "fixtures" / "code_fixtures.json"


def _load(source_file: str) -> str:
    return (FIXTURES_DIR / source_file).read_text(encoding="utf-8")


def _participants(source_file: str) -> dict[str, set[str]]:
    body = _load(source_file)
    _, used_names, defining_heading = build_chunks(body)
    participants: dict[str, set[str]] = {}
    for heading, names in used_names.items():
        for name in names:
            participants.setdefault(name, set()).add(heading)
    for name, heading in defining_heading.items():
        participants.setdefault(name, set()).add(heading)
    return participants


def _temp_index(source_file: str, mention_lines: list[str]) -> tuple[Path, Path]:
    """Build a disposable temp repo containing one fixture .py file plus a
    small doc that filename- and symbol-references it, then index it.
    Returns (repo_root, db_path); caller is responsible for cleanup."""
    tmp_dir = Path(tempfile.mkdtemp(prefix="docgraph_code_fixture_"))
    src_dir = tmp_dir / "src"
    src_dir.mkdir()
    shutil.copy(FIXTURES_DIR / source_file, src_dir / source_file)
    doc = tmp_dir / "DOC.md"
    doc.write_text(
        "# Fixture doc\n\n"
        f"See `src/{source_file}`.\n\n" + "\n".join(mention_lines) + "\n",
        encoding="utf-8",
    )
    db_path = tmp_dir / "fixture.db"
    index_build(tmp_dir, db_path)
    return tmp_dir, db_path


def _check(case: dict) -> tuple[bool, str]:
    check = case["check"]
    expect = case["expect"]
    source_file = case["source_file"]

    if check == "candidate_and_chunks":
        body = _load(source_file)
        candidate = is_chunking_candidate(body)
        if candidate != expect["is_candidate"]:
            return False, f"is_chunking_candidate={candidate}, expected {expect['is_candidate']}"
        chunks, used_names, _ = build_chunks(body)
        headings = [c.heading for c in chunks]
        if headings != expect["headings"]:
            return False, f"headings={headings}, expected {expect['headings']}"
        name = expect["shared_name"]
        for h in expect["shared_by"]:
            if name not in used_names.get(h, set()):
                return False, f"{name!r} missing from used_names[{h!r}]={used_names.get(h)}"
        return True, f"candidate + headings + shared name {name!r} all match"

    if check == "index_symbol_edge":
        repo_root, db_path = _temp_index(source_file, [
            "Calls `train_step()` and `evaluate()`.",
        ])
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            h1, h2 = expect["edge_between"]
            fwd = conn.execute(
                "SELECT 1 FROM edges WHERE kind='symbol' AND source=? AND target=?",
                (f"src\\{source_file}#{h1}", f"src\\{source_file}#{h2}"),
            ).fetchone() or conn.execute(
                "SELECT 1 FROM edges WHERE kind='symbol' AND source=? AND target=?",
                (f"src/{source_file}#{h1}", f"src/{source_file}#{h2}"),
            ).fetchone()
            bwd = conn.execute(
                "SELECT 1 FROM edges WHERE kind='symbol' AND source=? AND target=?",
                (f"src\\{source_file}#{h2}", f"src\\{source_file}#{h1}"),
            ).fetchone() or conn.execute(
                "SELECT 1 FROM edges WHERE kind='symbol' AND source=? AND target=?",
                (f"src/{source_file}#{h2}", f"src/{source_file}#{h1}"),
            ).fetchone()
            conn.close()
            if not fwd or (expect.get("bidirectional") and not bwd):
                return False, f"symbol edge between {h1}/{h2} missing (fwd={bool(fwd)}, bwd={bool(bwd)})"
            return True, f"symbol edge between {h1} <-> {h2} confirmed bidirectional"
        finally:
            shutil.rmtree(repo_root, ignore_errors=True)

    if check == "hub_name_fanout":
        participants = _participants(source_file)
        name = expect["name"]
        count = len(participants.get(name, set()))
        if count != expect["participant_count"]:
            return False, f"participant_count={count}, expected {expect['participant_count']}"
        if expect["exceeds_hub_name_fanout"] and count <= HUB_NAME_FANOUT:
            return False, f"{count} does not exceed HUB_NAME_FANOUT={HUB_NAME_FANOUT}"
        repo_root, db_path = _temp_index(source_file, [f"Relies on `{name}()`."])
        try:
            import sqlite3
            conn = sqlite3.connect(db_path)
            n = conn.execute(
                "SELECT COUNT(*) FROM edges WHERE kind='symbol' AND "
                "(source LIKE ? OR target LIKE ?)",
                (f"%#{name}", f"%#{name}"),
            ).fetchone()[0]
            conn.close()
            if n != expect["symbol_edges_from_name"]:
                return False, f"{n} symbol edges from {name!r}, expected {expect['symbol_edges_from_name']}"
            return True, f"{name!r} shared by {count} chunks, correctly produced 0 symbol edges"
        finally:
            shutil.rmtree(repo_root, ignore_errors=True)

    if check == "retrieve_group_size":
        heading = expect["seed_heading"]
        repo_root, db_path = _temp_index(source_file, [f"Relies on `{heading}()`."])
        try:
            result = retrieve(repo_root, db_path, f"{heading} helper", max_tokens=8000)
            code_chunks = [c for c in result["chunks"] if c["provenance"] == "code_ref"]
            if len(code_chunks) > expect["max_group_size"]:
                return False, (
                    f"{len(code_chunks)} code_ref chunks returned, "
                    f"expected <= {expect['max_group_size']}"
                )
            return True, f"{len(code_chunks)} code_ref chunks returned (<= {expect['max_group_size']})"
        finally:
            shutil.rmtree(repo_root, ignore_errors=True)

    if check == "used_names_contains":
        _, used_names, _ = build_chunks(_load(source_file))
        heading = expect["heading"]
        contains = expect["contains"]
        if contains not in used_names.get(heading, set()):
            return False, f"{contains!r} missing from used_names[{heading!r}]={used_names.get(heading)}"
        return True, f"{contains!r} present in used_names[{heading!r}]"

    if check == "used_names_excludes_all_but":
        _, used_names, _ = build_chunks(_load(source_file))
        heading = expect["heading"]
        names = used_names.get(heading, set())
        only = set(expect["only"])
        if names != only:
            return False, f"used_names[{heading!r}]={names}, expected exactly {only}"
        return True, f"used_names[{heading!r}] == {only} exactly (no noise leaked in)"

    if check == "used_names_empty":
        _, used_names, _ = build_chunks(_load(source_file))
        for h in expect["headings"]:
            if used_names.get(h):
                return False, f"used_names[{h!r}]={used_names.get(h)}, expected empty"
        return True, f"used_names empty for {expect['headings']}"

    if check == "syntax_error_fallback":
        body = _load(source_file)
        candidate = is_chunking_candidate(body)
        if candidate != expect["is_candidate"]:
            return False, f"is_chunking_candidate={candidate}, expected {expect['is_candidate']}"
        extracted = extract_chunk(body, None)
        if (extracted == body) != expect["extract_returns_whole_body"]:
            return False, "extract_chunk did not return whole body on broken syntax"
        return True, "syntax error correctly falls back to whole-file, no crash"

    if check == "not_candidate":
        body = _load(source_file)
        candidate = is_chunking_candidate(body)
        if candidate != expect["is_candidate"]:
            return False, f"is_chunking_candidate={candidate}, expected {expect['is_candidate']}"
        return True, "sub-threshold file correctly never sliced"

    if check == "used_names_excludes":
        _, used_names, _ = build_chunks(_load(source_file))
        heading = expect["heading"]
        names = used_names.get(heading, set())
        for excluded in expect["excludes"]:
            if excluded in names:
                return False, f"{excluded!r} unexpectedly present in used_names[{heading!r}]"
        for included in expect["includes"]:
            if included not in names:
                return False, f"{included!r} missing from used_names[{heading!r}]"
        return True, f"env-key names excluded, real constant included, in used_names[{heading!r}]"

    raise ValueError(f"unknown check type: {check!r}")


def main() -> int:
    cases = json.loads(FIXTURES_PATH.read_text(encoding="utf-8"))
    results = []
    for case in cases:
        ok, detail = _check(case)
        results.append((case, ok, detail))

    passed = sum(1 for _c, ok, _d in results if ok)
    print(f"\n=== code fixtures: {passed}/{len(results)} passed ===")
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
