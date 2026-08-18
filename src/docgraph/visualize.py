"""
Simple, deliberately unfancy graph visualization for a docgraph.db.

Nodes = files (docs table) — not chunks, that'd be too many nodes for a POC.
Edges = co-location relationships (edges table, kind='colocation').
Output = one self-contained HTML file (D3 via CDN, no build step, no server).

This is a POC, not the deferred "V1 web graph" — no search, no context-pack
panel, no click-to-inspect beyond a basic tooltip. Just: does the shape of
the corpus look right when you can see it.
"""
import json
import sqlite3
from pathlib import Path

BUCKET_COLORS = {
    "root": "#8b949e",
    "docs": "#58a6ff",
    "skills": "#bc8cff",
    "subdir-allcaps": "#3fb950",
}

TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>DocGraph — {title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<style>
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #0d1117; color: #c9d1d9; }}
  #legend {{ position: fixed; top: 12px; left: 12px; font-size: 13px; }}
  #legend div {{ display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }}
  #legend span.dot {{ width: 10px; height: 10px; border-radius: 50%; display: inline-block; }}
  #tooltip {{
    position: fixed; pointer-events: none; background: #161b22; border: 1px solid #30363d;
    padding: 6px 10px; border-radius: 6px; font-size: 12px; display: none; max-width: 320px;
  }}
  #stats {{ position: fixed; bottom: 12px; left: 12px; font-size: 12px; color: #8b949e; }}
</style>
</head>
<body>
<div id="legend"></div>
<div id="tooltip"></div>
<div id="stats">{node_count} files, {edge_count} co-location edges — drag nodes, scroll to zoom</div>
<svg id="graph" width="100%" height="100vh"></svg>
<script>
const data = {data_json};
const bucketColors = {colors_json};

const svg = d3.select("#graph");
const width = window.innerWidth, height = window.innerHeight;

const g = svg.append("g");
svg.call(d3.zoom().scaleExtent([0.2, 5]).on("zoom", (e) => g.attr("transform", e.transform)));

const sizeScale = d3.scaleSqrt().domain(d3.extent(data.nodes, d => d.tokens || 1)).range([4, 16]);

const sim = d3.forceSimulation(data.nodes)
  .force("link", d3.forceLink(data.links).id(d => d.id).distance(60).strength(0.3))
  .force("charge", d3.forceManyBody().strength(-120))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collide", d3.forceCollide(d => sizeScale(d.tokens || 1) + 4));

const link = g.append("g")
  .selectAll("line").data(data.links).join("line")
  .attr("stroke", "#30363d").attr("stroke-width", 1);

const node = g.append("g")
  .selectAll("circle").data(data.nodes).join("circle")
  .attr("r", d => sizeScale(d.tokens || 1))
  .attr("fill", d => bucketColors[d.bucket] || "#8b949e")
  .attr("stroke", "#0d1117").attr("stroke-width", 1)
  .call(d3.drag()
    .on("start", (e, d) => {{ if (!e.active) sim.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; }})
    .on("drag", (e, d) => {{ d.fx = e.x; d.fy = e.y; }})
    .on("end", (e, d) => {{ if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }}));

const tooltip = d3.select("#tooltip");
node.on("mouseover", (e, d) => {{
    tooltip.style("display", "block")
      .html(`<b>${{d.title}}</b><br>${{d.path}}<br>${{d.bucket}} · ~${{d.tokens}} tokens`);
  }})
  .on("mousemove", (e) => tooltip.style("left", (e.clientX + 14) + "px").style("top", (e.clientY + 10) + "px"))
  .on("mouseout", () => tooltip.style("display", "none"));

sim.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("cx", d => d.x).attr("cy", d => d.y);
}});

const legend = d3.select("#legend");
Object.entries(bucketColors).forEach(([bucket, color]) => {{
  const row = legend.append("div");
  row.append("span").attr("class", "dot").style("background", color);
  row.append("span").text(bucket);
}});
</script>
</body>
</html>
"""


def build_html(db_path: Path, title: str = "") -> str:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    docs = conn.execute("SELECT path, bucket, indexed_title, token_est FROM docs").fetchall()
    edges = conn.execute(
        "SELECT DISTINCT source, target FROM edges WHERE kind = 'colocation' AND source < target"
    ).fetchall()  # source < target dedupes the bidirectional pair back to one line per edge
    conn.close()

    nodes = [
        {"id": d["path"], "path": d["path"], "title": d["indexed_title"] or d["path"],
         "bucket": d["bucket"], "tokens": d["token_est"]}
        for d in docs
    ]
    links = [{"source": e["source"], "target": e["target"]} for e in edges]

    return TEMPLATE.format(
        title=title or db_path.stem,
        node_count=len(nodes),
        edge_count=len(links),
        data_json=json.dumps({"nodes": nodes, "links": links}),
        colors_json=json.dumps(BUCKET_COLORS),
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