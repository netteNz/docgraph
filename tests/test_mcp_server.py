from pathlib import Path

from docgraph import mcp_server
from docgraph.index import build


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_docgraph_context_returns_pack_from_bound_repo(tmp_path, monkeypatch):
    _write(tmp_path / "DOC.md", "# Deployment\n\nSee `src/worker.py` for the entrypoint.\n")
    _write(tmp_path / "src" / "worker.py", "def run():\n    return 1\n")
    db_path = tmp_path / "docgraph.db"
    build(tmp_path, db_path)

    monkeypatch.setattr(mcp_server, "_REPO_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(mcp_server, "_DB_PATH", db_path, raising=False)

    result = mcp_server.docgraph_context("deployment entrypoint")

    assert "DocGraph context pack" in result
    assert "DOC.md" in result


def test_docgraph_context_respects_max_tokens_budget(tmp_path, monkeypatch):
    _write(tmp_path / "DOC.md", "# Deployment\n\n" + ("word " * 500) + "\n")
    db_path = tmp_path / "docgraph.db"
    build(tmp_path, db_path)

    monkeypatch.setattr(mcp_server, "_REPO_ROOT", tmp_path, raising=False)
    monkeypatch.setattr(mcp_server, "_DB_PATH", db_path, raising=False)

    small = mcp_server.docgraph_context("deployment", max_tokens=50)
    large = mcp_server.docgraph_context("deployment", max_tokens=8000)

    assert len(small) < len(large)
