import sqlite3
from pathlib import Path

import pytest

from docgraph.context import (
    OVERSIZED_WHOLE_FILE_BUDGET_FRACTION,
    IndexStaleError,
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


def _chunk_sizes(db_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    try:
        return {
            (path, heading): token_est
            for path, heading, token_est in conn.execute(
                "SELECT path, heading, token_est FROM chunks"
            )
        }
    finally:
        conn.close()


def test_oversized_whole_file_chunk_defers_to_a_smaller_code_target(tmp_path):
    """The rl-stocks `legacy-1` failure, reproduced in miniature.

    One doc references two code files. The alphabetically EARLIER one has no
    top-level def/class, so the slicer leaves it as a single indivisible
    whole-file chunk; the LATER one is the small file that answers the task.
    `ORDER BY target` used to hand the blob the first budget slot, where it
    consumed the pack and displaced the answer -- exactly how
    `scripts/analyze_reward_divergence.py` (4413 tokens, 0 top-level defs)
    displaced `src/exit_manager.py` (1419 tokens) in the validation gate.
    """
    blob = "\n".join(
        f"CONFIG_{i} = 'padding value number {i} to bulk out this module'"
        for i in range(60)
    )
    _write(tmp_path / "src" / "aaa_blob.py", blob + "\n")
    _write(tmp_path / "src" / "zzz_answer.py", "def answer():\n    return 1\n")
    _write(
        tmp_path / "DOC.md",
        "# Deployment\n\nSee `src/aaa_blob.py` and `src/zzz_answer.py`.\n",
    )
    db_path = _build(tmp_path)

    sizes = _chunk_sizes(db_path)
    blob_tokens = sizes[("src/aaa_blob.py", None)]
    answer_tokens = sizes[("src/zzz_answer.py", None)]
    doc_tokens = sizes[("DOC.md", None)]

    # Room for the doc plus exactly one of the two code targets, so the tier
    # ordering alone decides which one survives.
    budget = doc_tokens + blob_tokens + answer_tokens - 1
    assert blob_tokens > budget * OVERSIZED_WHOLE_FILE_BUDGET_FRACTION
    assert answer_tokens < budget * OVERSIZED_WHOLE_FILE_BUDGET_FRACTION

    result = retrieve(tmp_path, db_path, "deployment", max_tokens=budget)
    selected = {chunk["path"] for chunk in result["chunks"]}
    cut = {chunk["path"] for chunk in result["budget_cut"]}

    assert "src/zzz_answer.py" in selected
    assert "src/aaa_blob.py" not in selected
    assert "src/aaa_blob.py" in cut


def test_small_preamble_of_a_sliceable_file_is_not_deferred(tmp_path):
    """The size penalty keys on whole-file *blobs*, not on `heading IS NULL`.

    A chunked file's preamble also has a NULL heading, but it is small and is
    the natural landing point for a reader, so it must not be pushed behind
    the rest of its own group.
    """
    body = ["import os", "", "CONSTANT = 1", ""]
    for name in ("alpha", "beta"):
        body.append(f"def {name}():")
        body.extend(f"    value_{i} = 'padding padding padding padding'" for i in range(120))
        body.append("    return 1")
        body.append("")
    _write(tmp_path / "src" / "pipeline.py", "\n".join(body) + "\n")
    _write(tmp_path / "DOC.md", "# Pipeline\n\nSee `src/pipeline.py`.\n")
    db_path = _build(tmp_path)

    sizes = _chunk_sizes(db_path)
    assert ("src/pipeline.py", "alpha") in sizes, "fixture must be sliced by def"
    preamble = sizes[("src/pipeline.py", None)]

    result = retrieve(tmp_path, db_path, "pipeline", max_tokens=4000)
    code = [c for c in result["chunks"] if c["provenance"] == "code_ref"]
    assert code, "expected the referenced file to reach the pack"
    assert code[0]["heading"] is None, "preamble should lead its own group"
    assert preamble < 4000 * OVERSIZED_WHOLE_FILE_BUDGET_FRACTION


def test_code_target_expansion_is_breadth_first_not_target_major(tmp_path):
    """The rl-stocks `legacy-10` failure, reproduced in miniature.

    One doc references two code files: an alphabetically-earlier one with
    several chunks (a multi-def file), and an alphabetically-later one that
    is the actual answer. Target-major expansion (old `j/100 + k/10000`)
    would fully expand the earlier target's group -- preamble AND its first
    def -- before the later target's own first chunk got a look in, exactly
    how a same-file `utc_now()` (defined earlier) starved
    `generate_rollback_guide()` (defined later, the on-topic answer) out of
    the rl-stocks validation gate. Breadth-first expansion (`k/100 + j/10000`)
    gives every target's position-0 chunk priority over any target's
    position-1 chunk, so the answer survives a tight budget instead.
    """
    body = ["import os", "", "CONSTANT = 1", ""]
    for name in ("helper_one", "helper_two"):
        body.append(f"def {name}():")
        body.extend(f"    value_{i} = 'padding padding padding padding'" for i in range(120))
        body.append("    return 1")
        body.append("")
    _write(tmp_path / "src" / "aaa_utils.py", "\n".join(body) + "\n")
    _write(
        tmp_path / "src" / "zzz_rollback.py",
        "def generate_rollback_guide():\n    return 'rollback steps'\n",
    )
    _write(
        tmp_path / "DOC.md",
        "# Deployment\n\nSee `src/aaa_utils.py` and `src/zzz_rollback.py`.\n",
    )
    db_path = _build(tmp_path)

    sizes = _chunk_sizes(db_path)
    assert ("src/aaa_utils.py", "helper_one") in sizes, "fixture must be sliced by def"
    preamble_tokens = sizes[("src/aaa_utils.py", None)]
    helper_one_tokens = sizes[("src/aaa_utils.py", "helper_one")]
    answer_tokens = sizes[("src/zzz_rollback.py", None)]
    doc_tokens = sizes[("DOC.md", None)]

    # Room for the doc, aaa_utils's preamble, and exactly one more chunk --
    # either aaa_utils's second chunk (target-major) or zzz_rollback's
    # answer (breadth-first). Tier ordering alone decides which one wins.
    budget = doc_tokens + preamble_tokens + max(helper_one_tokens, answer_tokens)

    result = retrieve(tmp_path, db_path, "deployment", max_tokens=budget)
    selected = [(c["path"], c["heading"]) for c in result["chunks"]]
    cut = {(c["path"], c["heading"]) for c in result["budget_cut"]}

    assert ("src/zzz_rollback.py", None) in selected
    assert ("src/aaa_utils.py", "helper_one") in cut


def test_live_viewer_sanitizes_marked_output():
    assert "DOMPurify.sanitize(rendered)" in SERVE_TEMPLATE
    assert "<script src=\"https://cdnjs.cloudflare.com/ajax/libs/dompurify/" in SERVE_TEMPLATE
