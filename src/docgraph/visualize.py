"""
Simple, deliberately unfancy graph visualization for a docgraph.db.

Nodes = files (docs table) — not chunks, that'd be too many nodes for a POC.
Edges = co-location relationships (edges table, kind='colocation').
Output = one self-contained HTML file (D3 via CDN, no build step, no server).

This is a POC, not the live "V1 web graph" — no search, no context-pack
panel, no click-to-inspect beyond a basic tooltip. Just: does the shape of
the corpus look right when you can see it. See serve.py for the live,
retrieval-driven version.
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

BUCKET_COLORS = {
    "root": {"fill": "#8b949e", "glow": "#8b949e"},
    "docs": {"fill": "#58a6ff", "glow": "#58a6ff"},
    "skills": {"fill": "#bc8cff", "glow": "#bc8cff"},
    "subdir-allcaps": {"fill": "#3fb950", "glow": "#3fb950"},
}

# Per-file-extension colors for bucket='code' nodes (V4: code files as real
# graph nodes, not just retrieval-time chunks). Keyed by the code_refs.py
# CODE_EXTENSIONS set. .py gets a two-tone gradient (Python's actual brand
# colors) since a blended single hex reads as muddy; everything else is a
# single fill/glow color pulled from each ecosystem's common convention.
CODE_EXT_COLORS = {
    "py": {"fill": "url(#grad-code-py)", "glow": "#4B8BBE"},
    "js": {"fill": "#f1e05a", "glow": "#f1e05a"},
    "ts": {"fill": "#3178c6", "glow": "#3178c6"},
    "jsx": {"fill": "#61dafb", "glow": "#61dafb"},
    "tsx": {"fill": "#61dafb", "glow": "#61dafb"},
    "go": {"fill": "#00ADD8", "glow": "#00ADD8"},
    "rs": {"fill": "#dea584", "glow": "#dea584"},
}
DEFAULT_CODE_COLOR = {"fill": "#8b949e", "glow": "#8b949e"}


def _code_bucket(path: str) -> str:
    """Synthetic per-extension bucket key for a bucket='code' doc row."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return f"code-{ext}" if ext else "code-other"


def bucket_colors_for(nodes: list[dict]) -> dict:
    """BUCKET_COLORS plus one CODE_EXT_COLORS entry per code-* bucket that's
    actually present in these nodes, so the legend/palette only ever lists
    extensions this repo's index actually has."""
    colors = dict(BUCKET_COLORS)
    for n in nodes:
        b = n["bucket"]
        if b.startswith("code-") and b not in colors:
            ext = b[len("code-"):]
            colors[b] = CODE_EXT_COLORS.get(ext, DEFAULT_CODE_COLOR)
    return colors

# Filename stems (no extension) that make a good "hub" for a directory of
# otherwise-unlinked docs, in priority order.
HUB_STEM_PRIORITY = ["readme", "index", "skill", "claude", "architecture"]


def _parent_dir(path: str) -> str:
    """Directory portion of a doc path, tolerant of '/' or '\\' separators."""
    sep = "\\" if "\\" in path else "/"
    parts = path.split(sep)
    return sep.join(parts[:-1])


def _dir_sep(path: str) -> str:
    return "\\" if "\\" in path else "/"


def _pick_hub(paths: list[str]) -> str:
    """Pick the most index-like file in a directory to act as the hub node.

    Tiers: exact filename stem match > stem starts with a priority word >
    stem contains a priority word > alphabetically first (deterministic
    fallback when nothing looks index-like).
    """
    def stem(p: str) -> str:
        base = p.rsplit(_dir_sep(p), 1)[-1]
        return base.lower().rsplit(".", 1)[0]

    stems = {p: stem(p) for p in paths}
    for name in HUB_STEM_PRIORITY:
        for p in sorted(stems):
            if stems[p] == name:
                return p
    for name in HUB_STEM_PRIORITY:
        for p in sorted(stems):
            if stems[p].startswith(name):
                return p
    for name in HUB_STEM_PRIORITY:
        for p in sorted(stems):
            if name in stems[p]:
                return p
    return sorted(paths)[0]


def add_structural_ties(nodes: list[dict], links: list[dict]) -> list[dict]:
    """Ensure every node has at least one edge.

    Co-location edges only get generated within directories small enough to
    pairwise-link without exploding into a hairball, so any directory above
    that size — or any file sitting alone in its own directory — ends up
    with zero edges even though it clearly belongs to the corpus. This adds
    two kinds of edges to close that gap, tagged kind="structural" so the
    renderer can style them apart from real co-location edges:

    1. Hub-and-spoke within a directory of otherwise-unlinked files, using
       the most index-like filename (README/INDEX/SKILL/etc.) as the hub.
    2. For files that are the *only* doc in their directory (so there's no
       one to spoke to), one bridging edge to the nearest already-connected
       node one level down (a subdirectory) or one level up (the parent),
       preferring down since an index-style file's natural children usually
       matter more than its parent.
    """
    ids = [n["id"] for n in nodes]
    connected = set()
    for l in links:
        connected.add(l["source"])
        connected.add(l["target"])
    orphans = [i for i in ids if i not in connected]
    if not orphans:
        return links

    by_dir_all = defaultdict(list)
    for n in nodes:
        by_dir_all[_parent_dir(n["id"])].append(n["id"])

    by_dir_orphans = defaultdict(list)
    for oid in orphans:
        by_dir_orphans[_parent_dir(oid)].append(oid)

    new_edges = []
    for group in by_dir_orphans.values():
        hub = _pick_hub(group)
        for oid in group:
            if oid != hub:
                new_edges.append((hub, oid))

    degree = Counter()
    for l in links:
        degree[l["source"]] += 1
        degree[l["target"]] += 1
    for a, b in new_edges:
        degree[a] += 1
        degree[b] += 1

    zero_degree = sorted(i for i in ids if degree[i] == 0)
    for h in zero_degree:
        d = _parent_dir(h)
        sep = _dir_sep(h) if h else "/"
        anchor = None

        child_dirs = sorted(
            k for k in by_dir_all
            if k.startswith(d + sep) and k.count(sep) == d.count(sep) + 1
        )
        for cd in child_dirs:
            for c in sorted(by_dir_all[cd]):
                if degree[c] > 0:
                    anchor = c
                    break
            if anchor:
                break

        if not anchor and d:
            parent = sep.join(d.split(sep)[:-1])
            for c in sorted(by_dir_all.get(parent, [])):
                if degree[c] > 0:
                    anchor = c
                    break

        if anchor:
            new_edges.append((anchor, h))
            degree[anchor] += 1
            degree[h] += 1
        # else: no directory relationship to tie to at all (shouldn't occur
        # in practice); leave it, rather than inventing an unrelated link.

    augmented = list(links)
    augmented += [{"source": a, "target": b, "kind": "structural"} for a, b in new_edges]
    return augmented

TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>DocGraph — {title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #0d1117; color: #c9d1d9; overflow: hidden; }}

  #legend {{ position: fixed; top: 14px; left: 14px; font-size: 12px; z-index: 10; }}
  #legend div {{ display: flex; align-items: center; gap: 7px; margin-bottom: 5px; opacity: 0.85; }}
  #legend span.dot {{
    width: 10px; height: 10px; border-radius: 50%; display: inline-block;
    box-shadow: 0 0 6px currentColor;
  }}

  #tooltip {{
    position: fixed; pointer-events: none;
    background: rgba(22, 27, 34, 0.95);
    border: 1px solid #30363d;
    padding: 8px 12px; border-radius: 8px; font-size: 12px;
    display: none; max-width: 320px;
    backdrop-filter: blur(6px);
    box-shadow: 0 4px 20px rgba(0,0,0,0.5);
    line-height: 1.6;
  }}
  #tooltip b {{ color: #e6edf3; }}
  #tooltip .meta {{ color: #8b949e; font-size: 11px; margin-top: 3px; }}

  #stats {{
    position: fixed; bottom: 14px; left: 14px; font-size: 11px; color: #484f58;
    letter-spacing: 0.02em;
  }}

  .node-circle {{ cursor: pointer; }}
</style>
</head>
<body>
<div id="legend"></div>
<div id="tooltip"></div>
<div id="stats">{node_count} files, {stats_label} — drag nodes, scroll to zoom</div>
<svg id="graph" width="100%" height="100vh"></svg>
<script>
const data = {data_json};
const bucketColors = {colors_json};

const svg = d3.select("#graph");
const width = window.innerWidth, height = window.innerHeight;

// ── defs: per-bucket glow filters + link glow ───────────────────────────────
const defs = svg.append("defs");

const pyGrad = defs.append("linearGradient").attr("id", "grad-code-py")
  .attr("x1", "0%").attr("y1", "0%").attr("x2", "100%").attr("y2", "100%");
pyGrad.append("stop").attr("offset", "0%").attr("stop-color", "#306998");
pyGrad.append("stop").attr("offset", "100%").attr("stop-color", "#FFD43B");

Object.entries(bucketColors).forEach(([bucket, color]) => {{
  const filter = defs.append("filter")
    .attr("id", `glow-${{bucket}}`)
    .attr("x", "-50%").attr("y", "-50%")
    .attr("width", "200%").attr("height", "200%");
  filter.append("feGaussianBlur").attr("stdDeviation", "4").attr("result", "blur");
  const merge = filter.append("feMerge");
  merge.append("feMergeNode").attr("in", "blur");
  merge.append("feMergeNode").attr("in", "SourceGraphic");
}});

const linkFilter = defs.append("filter").attr("id", "link-glow");
linkFilter.append("feGaussianBlur").attr("stdDeviation", "2").attr("result", "blur");
const lm = linkFilter.append("feMerge");
lm.append("feMergeNode").attr("in", "blur");
lm.append("feMergeNode").attr("in", "SourceGraphic");

const g = svg.append("g");
svg.call(d3.zoom().scaleExtent([0.2, 5]).on("zoom", (e) => g.attr("transform", e.transform)));

const sizeScale = d3.scaleSqrt().domain(d3.extent(data.nodes, d => d.tokens || 1)).range([4, 18]);

const sim = d3.forceSimulation(data.nodes)
  .force("link", d3.forceLink(data.links).id(d => d.id).distance(70).strength(0.3))
  .force("charge", d3.forceManyBody().strength(-140))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collide", d3.forceCollide(d => sizeScale(d.tokens || 1) + 5));

// ── Links ────────────────────────────────────────────────────────────────────
const linkG = g.append("g").attr("class", "links");
const link = linkG.selectAll("line").data(data.links).join("line")
  .attr("stroke", d => d.kind === "code_ref" ? "#bc8cff" : "#21262d")
  .attr("stroke-width", 1)
  .attr("stroke-opacity", d => d.kind === "code_ref" ? 0.55 : 0.7)
  .attr("stroke-dasharray", d => d.kind === "structural" ? "3,3" : null);

// ── Nodes ────────────────────────────────────────────────────────────────────
const nodeG = g.append("g").attr("class", "nodes");
const node = nodeG.selectAll("circle").data(data.nodes).join("circle")
  .attr("class", "node-circle")
  .attr("r", 0)
  .attr("fill", d => (bucketColors[d.bucket] || {{}}).fill || "#8b949e")
  .attr("stroke", "#0d1117")
  .attr("stroke-width", 1.5)
  .attr("fill-opacity", 0)
  .call(d3.drag()
    .on("start", (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on("drag",  (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on("end",   (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}));

// Adjacency map for hover-dim logic
const adjNodes = new Map(data.nodes.map(d => [d.id, new Set()]));
data.links.forEach(l => {{
  const sid = typeof l.source === "object" ? l.source.id : l.source;
  const tid = typeof l.target === "object" ? l.target.id : l.target;
  adjNodes.get(sid)?.add(tid);
  adjNodes.get(tid)?.add(sid);
}});

// ── Hover interactions ────────────────────────────────────────────────────────
const tooltip = d3.select("#tooltip");

node
  .on("mouseover", function(e, d) {{
    const r = sizeScale(d.tokens || 1);
    d3.select(this).raise()
      .transition().duration(180).ease(d3.easeCubicOut)
      .attr("r", r * 1.55)
      .attr("stroke-width", 2.5)
      .attr("filter", `url(#glow-${{d.bucket}})`);

    node.transition().duration(150)
      .attr("fill-opacity", n => {{
        if (n.id === d.id) return 1;
        return adjNodes.get(d.id)?.has(n.id) ? 0.9 : 0.15;
      }});

    link.transition().duration(150)
      .attr("stroke", l => {{
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        if (sid === d.id || tid === d.id) return (bucketColors[d.bucket] || {{}}).fill || "#8b949e";
        return l.kind === "code_ref" ? "#bc8cff" : "#21262d";
      }})
      .attr("stroke-width", l => {{
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        return (sid === d.id || tid === d.id) ? 2 : 1;
      }})
      .attr("stroke-opacity", l => {{
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        return (sid === d.id || tid === d.id) ? 0.85 : 0.15;
      }})
      .attr("filter", l => {{
        const sid = typeof l.source === "object" ? l.source.id : l.source;
        const tid = typeof l.target === "object" ? l.target.id : l.target;
        return (sid === d.id || tid === d.id) ? "url(#link-glow)" : null;
      }});

    const connCount = adjNodes.get(d.id)?.size || 0;
    tooltip.style("display", "block")
      .html(`<b>${{d.title}}</b><div class="meta">${{d.path}}<br>${{d.bucket}} · ~${{d.tokens.toLocaleString()}} tokens · ${{connCount}} connection${{connCount !== 1 ? "s" : ""}}</div>`);
  }})
  .on("mousemove", (e) => {{
    tooltip.style("left", (e.clientX + 16) + "px").style("top", (e.clientY + 12) + "px");
  }})
  .on("mouseout", function(e, d) {{
    const r = sizeScale(d.tokens || 1);
    d3.select(this).transition().duration(220).ease(d3.easeCubicOut)
      .attr("r", r).attr("stroke-width", 1.5).attr("filter", null);

    node.transition().duration(200).attr("fill-opacity", 1);
    link.transition().duration(200)
      .attr("stroke", l => l.kind === "code_ref" ? "#bc8cff" : "#21262d")
      .attr("stroke-width", 1)
      .attr("stroke-opacity", l => l.kind === "code_ref" ? 0.55 : 0.7)
      .attr("filter", null);

    tooltip.style("display", "none");
  }});

// ── Tick ──────────────────────────────────────────────────────────────────────
sim.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("cx", d => d.x).attr("cy", d => d.y);
}});

// ── Spawn animation: staggered pop-in once sim settles ────────────────────────
let spawned = false;
sim.on("tick.spawn", () => {{
  if (spawned || sim.alpha() > 0.15) return;
  spawned = true;

  node.each(function(d, i) {{
    const r = sizeScale(d.tokens || 1);
    d3.select(this).transition().delay(i * 6).duration(350).ease(d3.easeBackOut.overshoot(1.6))
      .attr("r", r).attr("fill-opacity", 1);
  }});

}});

// ── Legend ────────────────────────────────────────────────────────────────────
const legend = d3.select("#legend");
Object.entries(bucketColors).forEach(([bucket, c]) => {{
  const row = legend.append("div");
  row.append("span").attr("class", "dot").style("background", c.fill).style("box-shadow", `0 0 6px ${{c.glow}}55`);
  row.append("span").text(bucket).style("color", "#8b949e");
}});

if (data.links.some(l => l.kind === "structural")) {{
  const row = legend.append("div");
  row.append("span")
    .style("width", "14px").style("height", "0")
    .style("border-top", "1.5px dashed #6e7681")
    .style("display", "inline-block");
  row.append("span").text("structural tie (no direct co-location)").style("color", "#8b949e");
}}

if (data.links.some(l => l.kind === "code_ref")) {{
  const row = legend.append("div");
  row.append("span")
    .style("width", "14px").style("height", "0")
    .style("border-top", "1.5px solid #bc8cff")
    .style("display", "inline-block");
  row.append("span").text("doc → code reference").style("color", "#8b949e");
}}
</script>
</body>
</html>
"""


def graph_data(db_path: Path) -> dict:
    """File-level nodes (docs) + co-location edges, augmented with structural
    ties so every node has at least one edge. Shared by build_html and serve.py
    so both rendering paths stay on the same corpus-shape logic."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    docs = conn.execute("SELECT path, bucket, indexed_title, token_est FROM docs").fetchall()
    edges = conn.execute(
        "SELECT DISTINCT source, target FROM edges WHERE kind = 'colocation' AND source < target"
    ).fetchall()  # source < target dedupes the bidirectional pair back to one line per edge
    code_ref_edges = conn.execute(
        "SELECT source, target FROM edges WHERE kind = 'code_ref'"
    ).fetchall()
    conn.close()

    nodes = [
        {"id": d["path"], "path": d["path"], "title": d["indexed_title"] or d["path"],
         "bucket": _code_bucket(d["path"]) if d["bucket"] == "code" else d["bucket"],
         "tokens": d["token_est"]}
        for d in docs
    ]
    links = [{"source": e["source"], "target": e["target"], "kind": "colocation"} for e in edges]

    # code_ref targets may carry a chunk heading (path#Heading) for
    # symbol-level refs -- strip it to land on the file-level node id, and
    # de-dupe since two symbol refs into the same file would otherwise
    # produce parallel duplicate edges.
    seen_code_links = set()
    for e in code_ref_edges:
        target = e["target"].split("#", 1)[0]
        key = (e["source"], target)
        if key not in seen_code_links:
            seen_code_links.add(key)
            links.append({"source": e["source"], "target": target, "kind": "code_ref"})

    # code_ref links merged in first so code files with a real edge aren't
    # mistaken for orphans and given a fabricated structural tie.
    links = add_structural_ties(nodes, links)
    return {"nodes": nodes, "links": links}


def build_html(db_path: Path, title: str = "") -> str:
    data = graph_data(db_path)
    nodes, links = data["nodes"], data["links"]
    structural_count = sum(1 for l in links if l.get("kind") == "structural")

    stats_label = f"{len(links)} edges"
    if structural_count:
        stats_label += f" ({structural_count} structural)"

    return TEMPLATE.format(
        title=title or db_path.stem,
        node_count=len(nodes),
        stats_label=stats_label,
        data_json=json.dumps(data),
        colors_json=json.dumps(bucket_colors_for(nodes)),
    )


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Render a simple force-directed graph of a docgraph.db.")
    p.add_argument("db_path", type=Path)
    p.add_argument("output_html", type=Path)
    p.add_argument("--title", default="")
    args = p.parse_args()
    args.output_html.write_text(build_html(args.db_path, args.title), encoding="utf-8")
    print(f"Wrote {args.output_html}")
