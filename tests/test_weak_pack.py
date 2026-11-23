"""Weak-pack confidence signal (V5 WS3) + first test of _render's header text."""
from pathlib import Path

from docgraph.context import _assess_confidence, _render, build_pack
from docgraph.index import build


def _chunk(title, body, provenance="seed"):
    return {"indexed_title": title, "heading": None, "body": body, "provenance": provenance}


def test_low_coverage_flags_weak():
    c = _assess_confidence(["kubernetes", "ingress", "tls"], "OR", [1],
                           [_chunk("Resume", "certifications and skills")])
    assert c["weak"] and "low_coverage" in c["reasons"]


def test_covered_query_not_weak():
    c = _assess_confidence(["pot", "smoothing"], "AND", [1],
                           [_chunk("Pot Smoothing", "exponential smoothing of a pot")])
    assert not c["weak"]


def test_or_without_support_flags_even_when_covered():
    c = _assess_confidence(["alpha", "beta"], "OR", [1],
                           [_chunk("Doc", "alpha beta together")])
    assert c["weak"] and c["reasons"] == ["or_fallback_no_support"]


def test_no_seeds_is_weak():
    assert _assess_confidence(["x"], "OR", [], [])["reasons"] == ["no_match"]


def test_render_and_build_pack_show_warning(tmp_path: Path):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "cooking.md").write_text("# Cooking\n\npasta and tomato sauce recipes\n", encoding="utf-8")
    db = tmp_path / "t.db"
    build(root, db)
    weak = build_pack(root, db, "kubernetes ingress pasta", 2000)
    assert "WEAK PACK" in weak
    good = build_pack(root, db, "pasta tomato sauce", 2000)
    assert "WEAK PACK" not in good
    assert "WEAK PACK" not in _render({"task": "t", "chunks": [], "total_tokens": 0,
                                       "budget": 1, "query_used": "AND"})
