"""
DocGraph MCP server — single tool, stdio transport, same pattern as the
Obsidian vault server (FastMCP). Deliberately one tool: docgraph.context.
Resist adding search/get_node/neighbors as separate tools until context()
alone proves insufficient in real use.

Usage:
    python -m docgraph.mcp_server <repo_root> <db_path>

Register in Claude Code / claude_desktop_config.json the same way as any
other stdio MCP server, pointing "args" at this module and the two paths.
"""
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from .context import build_pack

mcp = FastMCP("docgraph")

# Bound at startup from argv rather than passed per-call — one server
# instance is scoped to one repo/index, matching how the Obsidian server
# is scoped to one vault. Point Claude Code at a different repo by running
# a second server instance with different args, not by parameterizing the tool.
_REPO_ROOT: Path
_DB_PATH: Path


@mcp.tool()
def docgraph_context(task: str, max_tokens: int = 8000) -> str:
    """
    Retrieve a token-budgeted markdown context pack relevant to a task,
    from this server's indexed repo. Use this instead of reading docs/**
    directly — it returns only what's relevant to the task description,
    ranked by keyword relevance plus one-hop directory-neighbor expansion.

    Args:
        task: Natural-language description of what you're trying to do.
              Be specific — this is used as a keyword search, not a
              semantic query, so include the actual terms your task
              involves (component names, feature names, error messages).
              Avoid including the name of a file you're ABOUT to create —
              e.g. prefer "write ExitManager boundary condition tests"
              over "write tests/test_exit_manager.py" — a target filename
              that doesn't exist yet can never match anything in the docs,
              which forces retrieval into a broader, less precise fallback
              mode even when the rest of the task string would have found
              an exact match on its own.
        max_tokens: Token budget for the returned pack. Default 8000.
    """
    return build_pack(_REPO_ROOT, _DB_PATH, task, max_tokens=max_tokens)


def main() -> None:
    global _REPO_ROOT, _DB_PATH
    if len(sys.argv) != 3:
        print("Usage: python -m docgraph.mcp_server <repo_root> <db_path>", file=sys.stderr)
        sys.exit(1)
    _REPO_ROOT = Path(sys.argv[1]).resolve()
    _DB_PATH = Path(sys.argv[2]).resolve()
    if not _DB_PATH.exists():
        print(
            f"No index at {_DB_PATH} — run `python -m docgraph.index "
            f"{_REPO_ROOT} {_DB_PATH}` first.", file=sys.stderr,
        )
        sys.exit(1)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()