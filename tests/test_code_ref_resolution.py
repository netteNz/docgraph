from docgraph.code_refs import resolve_code_ref, resolve_code_ref_detailed
from docgraph.index import build


def _write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_exact_relative_path():
    known = {"src/worker.py", "other/worker.py"}
    assert resolve_code_ref_detailed("DOC.md", "src/worker.py", known) == (
        "src/worker.py", "resolved", "exact", 1)


def test_unique_basename():
    known = {"src/worker.py"}
    path, status, method, _ = resolve_code_ref_detailed("docs/DOC.md", "worker.py", known)
    assert (path, status, method) == ("src/worker.py", "resolved", "basename")


def test_dead_when_no_basename_match():
    assert resolve_code_ref_detailed("DOC.md", "nope.py", {"src/a.py"}) == (None, "dead", None, 0)


def test_scoped_hit_stays_in_subtree():
    known = {"web/src/main.jsx", "viz/src/main.jsx", "app/main.jsx"}
    path, status, method, n = resolve_code_ref_detailed("web/FEATURES.md", "main.jsx", known)
    assert (path, status, method, n) == ("web/src/main.jsx", "resolved", "scoped", 3)


def test_scoped_multi_uses_depth_within_scope_only():
    # proj/ holds two copies (depth 2 vs 3); the root copy is shallower still
    # but belongs to another scope and must never win.
    known = {"proj/a/utils.py", "proj/b/x/utils.py", "utils.py"}
    path, status, method, _ = resolve_code_ref_detailed("proj/README.md", "utils.py", known)
    assert (path, status, method) == ("proj/a/utils.py", "resolved", "scoped")


def test_scoped_multi_tie_stays_ambiguous_and_does_not_escape():
    known = {"proj/a/utils.py", "proj/b/utils.py", "utils.py"}
    path, status, method, _ = resolve_code_ref_detailed("proj/README.md", "utils.py", known)
    assert (path, status, method) == (None, "ambiguous", None)


def test_depth_tiebreak_repo_wide():
    known = {"src/trading_env.py", "staging/src/trading_env.py"}
    path, status, method, _ = resolve_code_ref_detailed("docs/PLAN.md", "trading_env.py", known)
    assert (path, status, method) == ("src/trading_env.py", "resolved", "depth")


def test_tie_at_minimum_depth_stays_ambiguous():
    known = {"api/main.py", "worker/main.py", "x/y/main.py"}
    assert resolve_code_ref("docs/PLAN.md", "main.py", known) == (None, "ambiguous")


def test_root_doc_skips_scoping_and_uses_depth():
    known = {"api/main.py", "worker/main.py"}
    assert resolve_code_ref("DOC.md", "main.py", known) == (None, "ambiguous")
    known = {"src/main.py", "staging/src/main.py"}
    assert resolve_code_ref("DOC.md", "main.py", known) == ("src/main.py", "resolved")


def test_build_reports_resolution_counters_and_audit(tmp_path):
    import sqlite3

    _write(tmp_path / "DOC.md", "# Plan\n\nSee `trading_env.py` and `main.py`.\n")
    _write(tmp_path / "src" / "trading_env.py", "x = 1\n")
    _write(tmp_path / "staging" / "src" / "trading_env.py", "x = 2\n")
    _write(tmp_path / "api" / "main.py", "def a():\n    pass\n")
    _write(tmp_path / "worker" / "main.py", "def w():\n    pass\n")
    db_path = tmp_path / "docgraph.db"
    stats = build(tmp_path, db_path)

    assert stats["code_resolved_by_method"]["depth"] == 1
    assert stats["ambiguous_code_refs"] == 1
    assert stats["code_edges"] == 1

    conn = sqlite3.connect(db_path)
    rows = {r[0]: r[1:] for r in conn.execute(
        "SELECT mention, status, method, target FROM code_ref_audit")}
    assert rows["trading_env.py"] == ("resolved", "depth", "src/trading_env.py")
    assert rows["main.py"][0] == "ambiguous"


_EXPERIMENTS = {"src/experiments.py", "src/dashboard/pages/experiments.py"}


def test_qualified_mention_from_subdir_doc_resolves_rooted_not_depth():
    assert resolve_code_ref_detailed("docs/X.md", "src/experiments.py", _EXPERIMENTS) == (
        "src/experiments.py", "resolved", "rooted", 1)


def test_qualified_mention_of_the_nested_file_no_longer_mis_resolves():
    # Previously resolved to src/experiments.py via the depth tiebreak (wrong file).
    assert resolve_code_ref_detailed(
        "docs/X.md", "src/dashboard/pages/experiments.py", _EXPERIMENTS) == (
        "src/dashboard/pages/experiments.py", "resolved", "rooted", 1)


def test_partial_qualifier_resolves_by_suffix():
    assert resolve_code_ref_detailed("docs/X.md", "dashboard/pages/experiments.py", _EXPERIMENTS) == (
        "src/dashboard/pages/experiments.py", "resolved", "suffix", 1)


def test_dotdot_prefix_that_misses_the_exact_path_still_resolves():
    # docs/a/b/X.md + ../src/experiments.py -> docs/a/src/experiments.py (unknown)
    path, status, method, _ = resolve_code_ref_detailed(
        "docs/a/b/X.md", "../src/experiments.py", _EXPERIMENTS)
    assert (path, status, method) == ("src/experiments.py", "resolved", "rooted")


def test_stale_qualifier_is_dead_not_a_basename_fallback():
    assert resolve_code_ref_detailed("docs/X.md", "old/experiments.py", _EXPERIMENTS) == (
        None, "dead", None, 0)


def test_suffix_tie_stays_ambiguous():
    known = {"a/lib/util.py", "b/lib/util.py"}
    assert resolve_code_ref_detailed("X.md", "lib/util.py", known) == (None, "ambiguous", None, 2)


def test_bare_basename_behaviour_is_unchanged():
    assert resolve_code_ref_detailed("docs/X.md", "experiments.py", _EXPERIMENTS) == (
        "src/experiments.py", "resolved", "depth", 2)


def test_foreign_absolute_path_resolves_to_the_repo_file_it_ends_with():
    known = {"src/ensemble.py", "src/dashboard/pages/ensemble.py"}
    assert resolve_code_ref_detailed(
        "docs/archive/X.md", "/Users/someone/proj/src/ensemble.py", known) == (
        "src/ensemble.py", "resolved", "suffix", 1)
    assert resolve_code_ref_detailed(
        "docs/X.md", "C:/work/proj/src/dashboard/pages/ensemble.py", known)[0] == (
        "src/dashboard/pages/ensemble.py")


def test_foreign_path_never_resolves_to_a_top_level_single_segment_file():
    assert resolve_code_ref_detailed("docs/X.md", "backend/app.py", {"app.py"}) == (None, "dead", None, 0)
