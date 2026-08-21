"""
Def/class-boundary chunking for Python source, plus a same-pass intra-file
symbol table — mirrors sections.py's role for code, per V4
(docs/HANDOFF.md).

is_chunking_candidate/build_chunks (index time) and extract_chunk (render
time) must agree on the identical split, same load-bearing invariant
sections.py's docstring calls out for markdown: bodies aren't persisted, so
index.py and context.py each independently recompute this from disk, and if
they ever disagreed a chunk's stored heading would point at text that
doesn't match what gets rendered.

Scope: Python only (stdlib ast, no tree-sitter). A file with a SyntaxError
falls back to whole-file inclusion, never a crash (index.py may hit a file
edited into a temporarily-broken state; extract_chunk may hit a file that
changed since indexing).
"""
import ast
from dataclasses import dataclass, field

from .sections import CHUNKING_TOKEN_THRESHOLD, token_est

CODE_MIN_TOP_LEVEL_DEFS = 2
# Mirrors sections.CHUNKING_MIN_SUBHEADINGS's role: below this, one file is
# one chunk regardless of size.


@dataclass
class CodeChunk:
    heading: str | None  # None = preamble (docstring/imports/module consts
                          # before the first def/class); "name" for an
                          # unsplit top-level def/class; "Class > method"
                          # for a re-split class's methods (the class's own
                          # preamble --- docstring/class-body assignments
                          # before its first method --- keeps heading ==
                          # "Class", same as sections.split_sections keeping
                          # a subdivided section's intro under the parent
                          # heading).
    text: str
    token_est: int


def _is_getenv_call(value: ast.AST) -> bool:
    if not isinstance(value, ast.Call):
        return False
    func = value.func
    if isinstance(func, ast.Attribute) and func.attr == "getenv":
        return True
    if isinstance(func, ast.Name) and func.id == "getenv":
        return True
    return False


def _is_environ_access(value: ast.AST) -> bool:
    # os.environ[...] (Subscript) or os.environ.get(...) (Call on Attribute)
    if isinstance(value, ast.Subscript):
        target = value.value
        return isinstance(target, ast.Attribute) and target.attr == "environ"
    if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute):
        return isinstance(value.func.value, ast.Attribute) and value.func.value.attr == "environ"
    return False


def _module_bindings(tree: ast.Module) -> dict[str, str]:
    """name -> "const" | "func" | "class", module scope only.

    Deliberately excludes os.getenv()/os.environ-sourced assignments (an
    API_KEY-style secret isn't a structural connective tissue between two
    chunks the way a real shared constant is).
    """
    bindings: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings[node.name] = "func"
        elif isinstance(node, ast.ClassDef):
            bindings[node.name] = "class"
        elif isinstance(node, ast.Assign):
            if _is_getenv_call(node.value) or _is_environ_access(node.value):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = "const"
        elif isinstance(node, ast.AnnAssign):
            if node.value is not None and (_is_getenv_call(node.value) or _is_environ_access(node.value)):
                continue
            if isinstance(node.target, ast.Name):
                bindings[node.target.id] = "const"
    return bindings


def _locally_bound_names(node: ast.AST) -> set[str]:
    """Names that are structurally local to `node`: parameters, anything
    assigned/for-targeted/comprehension-targeted inside it, and nested
    def/class names. Computed via ast.walk so a param like `data` or `x` is
    excluded from "used module-level names" the moment it's a parameter,
    never via a stopword list."""
    local: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.arg):
            local.add(child.arg)
        elif isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
            local.add(child.id)
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and child is not node:
            local.add(child.name)
    return local


def _used_module_names(node: ast.AST, bindings: dict[str, str]) -> set[str]:
    local = _locally_bound_names(node)
    used: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            if child.id in bindings and child.id not in local:
                used.add(child.id)

    # Parameter-to-binding: a param `replay_buffer` matching a module-level
    # `ReplayBuffer` func/class is real signal even though it never appears
    # as a plain Name load inside the body. Case-normalized so snake_case
    # params match PascalCase bindings. Only params that resolve to a
    # module-level name create edges — this is the noise filter: `data`,
    # `x`, `model` with no matching binding are simply never added.
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        norm_bindings = {
            name.replace("_", "").lower(): name
            for name, kind in bindings.items()
            if kind in ("func", "class")
        }
        params = list(node.args.posonlyargs) + list(node.args.args) + list(node.args.kwonlyargs)
        for p in params:
            norm_p = p.arg.replace("_", "").lower()
            if norm_p in norm_bindings:
                used.add(norm_bindings[norm_p])
    return used


def _decorated_start(node: ast.AST) -> int:
    lines = [node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])]
    return min(lines)


def is_chunking_candidate(body: str) -> bool:
    try:
        tree = ast.parse(body)
    except SyntaxError:
        return False
    if token_est(body) <= CHUNKING_TOKEN_THRESHOLD:
        return False
    top_defs = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    if len(top_defs) >= CODE_MIN_TOP_LEVEL_DEFS:
        return True
    # Single top-level class with real method substructure — mirrors
    # sections.is_chunking_candidate's "single catch-all H2, real H3
    # structure underneath" branch.
    if len(top_defs) == 1 and isinstance(top_defs[0], ast.ClassDef):
        methods = [
            m for m in top_defs[0].body
            if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        if len(methods) >= CODE_MIN_TOP_LEVEL_DEFS:
            return True
    return False


def build_chunks(
    body: str,
) -> tuple[list[CodeChunk], dict[str, set[str]], dict[str, str]]:
    """
    Single AST pass. Returns:
      chunks           -- ordered list, preamble first if non-empty
      used_names       -- heading -> set of module-level names that
                           chunk's body references
      defining_heading -- module-level func/class name -> the heading of
                           the chunk that DEFINES it (== the name itself
                           for an unsplit function/class; for a re-split
                           class, == the bare class name if it has a
                           non-empty preamble, else the first method's
                           heading as a deterministic stand-in)

    Caller contract: call is_chunking_candidate(body) first. This function
    assumes the caller already knows body parses and qualifies; it does not
    re-check the threshold itself (mirrors sections.split_sections, which
    likewise assumes its caller already gated on is_chunking_candidate).
    """
    lines = body.splitlines(keepends=True)
    tree = ast.parse(body)
    bindings = _module_bindings(tree)

    top_defs = [
        n for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    chunks: list[CodeChunk] = []
    used_names: dict[str, set[str]] = {}
    defining_heading: dict[str, str] = {}

    first_def_line = _decorated_start(top_defs[0]) if top_defs else None
    if first_def_line is not None and first_def_line > 1:
        preamble_text = "".join(lines[: first_def_line - 1]).strip()
        if preamble_text:
            chunks.append(CodeChunk(None, preamble_text, token_est(preamble_text)))

    def _node_text(node: ast.AST) -> str:
        start = _decorated_start(node) - 1
        end = node.end_lineno
        return "".join(lines[start:end]).strip()

    for node in top_defs:
        if isinstance(node, ast.ClassDef):
            methods = [
                m for m in node.body
                if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            if len(methods) >= CODE_MIN_TOP_LEVEL_DEFS:
                first_method_line = _decorated_start(methods[0])
                class_start = _decorated_start(node) - 1
                class_preamble_text = "".join(
                    lines[class_start: first_method_line - 1]
                ).strip()
                if class_preamble_text:
                    heading = node.name
                    chunks.append(CodeChunk(
                        heading, class_preamble_text, token_est(class_preamble_text),
                    ))
                    used_names[heading] = _used_module_names(node, bindings)
                    defining_heading[node.name] = heading
                else:
                    defining_heading[node.name] = f"{node.name} > {methods[0].name}"

                for m in methods:
                    heading = f"{node.name} > {m.name}"
                    text = _node_text(m)
                    chunks.append(CodeChunk(heading, text, token_est(text)))
                    used_names[heading] = _used_module_names(m, bindings)
                continue
            # Falls through: a class with <2 methods stays a single chunk.

        heading = node.name
        text = _node_text(node)
        chunks.append(CodeChunk(heading, text, token_est(text)))
        used_names[heading] = _used_module_names(node, bindings)
        defining_heading[node.name] = heading

    if not chunks:
        # No top-level defs at all (shouldn't happen if the caller already
        # checked is_chunking_candidate, but stay whole rather than return
        # an empty list).
        chunks.append(CodeChunk(None, body, token_est(body)))

    return chunks, used_names, defining_heading


def extract_chunk(body: str, heading: str | None) -> str:
    """
    Render-time re-derivation. Mirrors sections.extract_section: if the
    file isn't a chunking candidate (or has since become syntactically
    broken), return the whole body — heading is irrelevant. Otherwise
    rebuild the split and find the matching chunk; if the heading vanished
    (file changed since indexing), fail open to the whole body, same
    rationale as extract_section's last line.
    """
    if not is_chunking_candidate(body):
        return body
    chunks, _, _ = build_chunks(body)
    for c in chunks:
        if c.heading == heading:
            return c.text
    return body
