import sqlite3
from pathlib import Path

import pytest

from docgraph.context import (
    CODE_TIER_CHUNK_STEP,
    MAX_CODE_NEIGHBORS_PER_SEED,
    IndexStaleError,
    _code_tier_rank,
    retrieve,
)
from docgraph.index import build
from docgraph.serve import SERVE_TEMPLATE
import docgraph.index as index_module


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def _build(tmp_path: Path) -> Path:
    db_path = tmp_path / "docgraph.db"
    build(tmp_path, db_path)
    return db_path


def test_read_failure_does_not_create_a_dangling_code_edge(tmp_path, monkeypatch):
    _write(tmp_path / "DOC.md", "# Deployment\n\nSee `src/worker.py`.\n")
    _write(tmp_path / "src" / "worker.py", "def run():\n    return 1\n")

    def unreadable(*_args, **_kwargs):
        raise OSError("simulated read failure")

    monkeypatch.setattr(index_module, "_code_chunks_for", unreadable)
    db_path = _build(tmp_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM edges WHERE kind = 'code_ref'").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM docs WHERE bucket = 'code'").fetchone()[0] == 0
    conn.close()


def test_retrieval_rejects_source_mutated_after_indexing(tmp_path):
    source = _write(tmp_path / "DOC.md", "# Original\n\nneedle content\n")
    db_path = _build(tmp_path)
    source.write_text("# Replacement\n\nchanged content\n", encoding="utf-8")

    with pytest.raises(IndexStaleError, match="changed: DOC.md"):
        retrieve(tmp_path, db_path, "needle")


def test_retrieval_rejects_source_deleted_after_indexing(tmp_path):
    source = _write(tmp_path / "DOC.md", "# Original\n\nneedle content\n")
    db_path = _build(tmp_path)
    source.unlink()

    with pytest.raises(IndexStaleError, match="missing/unreadable: DOC.md"):
        retrieve(tmp_path, db_path, "needle")


def test_ambiguous_code_basename_creates_no_edge(tmp_path):
    _write(tmp_path / "DOC.md", "# Plan\n\nSee `main.py`.\n")
    _write(tmp_path / "api" / "main.py", "def api():\n    pass\n")
    _write(tmp_path / "worker" / "main.py", "def worker():\n    pass\n")
    db_path = tmp_path / "docgraph.db"
    stats = build(tmp_path, db_path)

    assert stats["ambiguous_code_refs"] == 1
    assert stats["code_edges"] == 0


def test_filename_only_code_refs_are_labeled_for_validation(tmp_path):
    _write(tmp_path / "DOC.md", "# Deployment\n\nSee `src/worker.py`.\n")
    _write(tmp_path / "src" / "worker.py", "def run():\n    return 1\n")
    db_path = _build(tmp_path)

    result = retrieve(tmp_path, db_path, "deployment")
    code_chunks = [chunk for chunk in result["chunks"] if chunk["provenance"] == "code_ref"]
    assert code_chunks
    assert {chunk["tier_detail"] for chunk in code_chunks} == {"filename"}


def test_oversized_code_reference_hub_is_skipped_entirely(tmp_path):
    mentions = []
    for i in range(11):
        _write(tmp_path / "src" / f"module_{i}.py", f"def f_{i}():\n    return {i}\n")
        mentions.append(f"`src/module_{i}.py`")
    _write(tmp_path / "DOC.md", "# Catalogue\n\n" + "\n".join(mentions) + "\n")
    db_path = tmp_path / "docgraph.db"
    stats = build(tmp_path, db_path)

    assert stats["code_hub_docs_skipped"] == 1
    assert stats["code_edges"] == 0
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM docs WHERE bucket = 'code'").fetchone()[0] == 0
    conn.close()


def test_live_viewer_sanitizes_marked_output():
    assert "DOMPurify.sanitize(rendered)" in SERVE_TEMPLATE
    assert "<script src=\"https://cdnjs.cloudflare.com/ajax/libs/dompurify/" in SERVE_TEMPLATE


def test_code_tier_rank_nests_at_the_chunk_cap():
    # The k term must stay strictly below the j step of 1/100, or chunk k
    # of one target ties chunk 0 of the next and the tiers interleave.
    # Reads CODE_TIER_CHUNK_STEP and MAX_CODE_NEIGHBORS_PER_SEED rather
    # than restating the formula, so this goes red if either constant
    # moves past what the current denominator can support.
    last_k = CODE_TIER_CHUNK_STEP // 100 - 1
    assert _code_tier_rank(20, 0, 0, last_k) < _code_tier_rank(20, 0, 1, 0)
    assert _code_tier_rank(20, 0, MAX_CODE_NEIGHBORS_PER_SEED - 1, last_k) < _code_tier_rank(20, 1, 0, 0)
