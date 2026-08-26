import json
from pathlib import Path

from docgraph.validation import (
    _call_id,
    pending_calls,
    render_summary,
    summarize,
)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def _entry(task: str, call_id: str | None = None, chunks=None, budget_cut=None) -> dict:
    row = {"task": task, "chunks": chunks or [], "budget_cut": budget_cut or []}
    if call_id is not None:
        row["call_id"] = call_id
    return row


def test_call_id_falls_back_to_legacy_line_number_when_absent():
    assert _call_id({"task": "x"}, 3) == "legacy-3"
    assert _call_id({"task": "x", "call_id": "abc"}, 3) == "abc"


def test_pending_calls_excludes_reviewed_call_ids(tmp_path):
    query_log = tmp_path / "log.jsonl"
    annotations = tmp_path / "log.annotations.jsonl"
    _write_jsonl(query_log, [_entry("a", "c1"), _entry("b", "c2")])
    _write_jsonl(annotations, [{"call_id": "c1"}])

    pending = pending_calls(query_log, annotations)

    assert [call_id for call_id, _ in pending] == ["c2"]


def test_summarize_before_any_review_reports_collecting(tmp_path):
    query_log = tmp_path / "log.jsonl"
    annotations = tmp_path / "log.annotations.jsonl"
    _write_jsonl(query_log, [_entry("a", "c1")])

    result = summarize(query_log, annotations, min_calls=20)

    assert result["reviewed_calls"] == 0
    assert result["gate_ready"] is False
    assert result["decision"] == "collecting"


def test_summarize_computes_usefulness_rate_from_used_chunks_only(tmp_path):
    query_log = tmp_path / "log.jsonl"
    annotations = tmp_path / "log.annotations.jsonl"

    # Two calls: one has a selected code_ref chunk judged "used", the other
    # has a selected code_ref chunk judged "unused". Exposure is 2/2 but
    # usefulness should be 1/2 -- exposure and usefulness must not collapse
    # into the same number.
    chunk_used = {"path": "a.py", "heading": None, "provenance": "code_ref", "tier_detail": "filename"}
    chunk_unused = {"path": "b.py", "heading": None, "provenance": "code_ref", "tier_detail": "filename"}
    _write_jsonl(query_log, [
        _entry("task1", "c1", chunks=[chunk_used]),
        _entry("task2", "c2", chunks=[chunk_unused]),
    ])
    _write_jsonl(annotations, [
        {"call_id": "c1", "selected": [{**chunk_used, "assessment": "used"}], "budget_cut": []},
        {"call_id": "c2", "selected": [{**chunk_unused, "assessment": "unused"}], "budget_cut": []},
    ])

    result = summarize(query_log, annotations, min_calls=2, threshold=0.15)

    assert result["reviewed_calls"] == 2
    assert result["packs_with_used_advanced_context"] == 1
    assert result["usefulness_rate"] == 0.5
    assert result["gate_ready"] is True
    assert result["decision"] == "keep_or_tune"
    assert result["tiers"]["filename"]["selected_chunks"] == 2
    assert result["tiers"]["filename"]["used_chunks"] == 1


def test_summarize_kills_tier_below_threshold(tmp_path):
    query_log = tmp_path / "log.jsonl"
    annotations = tmp_path / "log.annotations.jsonl"
    chunk = {"path": "a.py", "heading": None, "provenance": "code_ref", "tier_detail": "filename"}
    _write_jsonl(query_log, [_entry("task1", "c1", chunks=[chunk])])
    _write_jsonl(annotations, [
        {"call_id": "c1", "selected": [{**chunk, "assessment": "unused"}], "budget_cut": []},
    ])

    result = summarize(query_log, annotations, min_calls=1, threshold=0.15)

    assert result["usefulness_rate"] == 0.0
    assert result["decision"] == "kill"


def test_summarize_tracks_useful_budget_cut_candidates_separately(tmp_path):
    query_log = tmp_path / "log.jsonl"
    annotations = tmp_path / "log.annotations.jsonl"
    cut = {"path": "missed.py", "heading": None, "provenance": "code_ref", "tier_detail": "filename"}
    _write_jsonl(query_log, [_entry("task1", "c1", budget_cut=[cut])])
    _write_jsonl(annotations, [
        {"call_id": "c1", "selected": [], "budget_cut": [{**cut, "assessment": "useful"}]},
    ])

    result = summarize(query_log, annotations, min_calls=1, threshold=0.15)

    # A useful budget-cut candidate must not be counted as "used" (it never
    # made it into a pack) -- it's tracked in a separate counter entirely.
    assert result["packs_with_used_advanced_context"] == 0
    assert result["budget_cut"]["useful"] == 1
    assert result["tiers"]["filename"]["budget_cut_useful"] == 1


def test_render_summary_includes_per_tier_table(tmp_path):
    summary = summarize(tmp_path / "missing.jsonl", tmp_path / "missing.annotations.jsonl", min_calls=1)
    text = render_summary(summary)
    assert "# DocGraph validation study" in text
    assert "| Tier |" in text
