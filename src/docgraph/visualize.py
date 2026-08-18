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
<div id="stats">{node_count} files, {edge_count} co-location edges — drag nodes, scroll to zoom</div>
<svg id="graph" width="100%" height="100vh"></svg>
<script>
const data = {data_json};
const bucketColors = {colors_json};

const svg = d3.select("#graph");
const width = window.innerWidth, height = window.innerHeight;

// ── defs: per-bucket glow filters + link glow ───────────────────────────────
const defs = svg.append("defs");

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
  .attr("stroke", "#21262d")
  .attr("stroke-width", 1)
  .attr("stroke-opacity", 0.7);

// ── Nodes ────────────────────────────────────────────────────────────────────
const nodeG = g.append("g").attr("class", "nodes");
const node = nodeG.selectAll("circle").data(data.nodes).join("circle")
  .attr("class", "node-circle")
  .attr("r", 0)
  .attr("fill", d => bucketColors[d.bucket] || "#8b949e")
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
        return (sid === d.id || tid === d.id) ? (bucketColors[d.bucket] || "#8b949e") : "#21262d";
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
      .attr("stroke", "#21262d").attr("stroke-width", 1)
      .attr("stroke-opacity", 0.7).attr("filter", null);

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

  // Expanding pulse ring per node
  nodeG.selectAll(".pulse-ring")
    .data(data.nodes).join("circle")
    .attr("class", "pulse-ring")
    .attr("cx", d => d.x).attr("cy", d => d.y)
    .attr("r", d => sizeScale(d.tokens || 1))
    .attr("stroke", d => bucketColors[d.bucket] || "#8b949e")
    .attr("fill", "none").attr("stroke-opacity", 0.6)
    .each(function(d, i) {{
      d3.select(this).transition().delay(i * 6).duration(800).ease(d3.easeExpOut)
        .attr("r", d => sizeScale(d.tokens || 1) + 22)
        .attr("stroke-opacity", 0).remove();
    }});
}});

// ── Legend ────────────────────────────────────────────────────────────────────
const legend = d3.select("#legend");
Object.entries(bucketColors).forEach(([bucket, color]) => {{
  const row = legend.append("div");
  row.append("span").attr("class", "dot").style("background", color).style("box-shadow", `0 0 6px ${{color}}55`);
  row.append("span").text(bucket).style("color", "#8b949e");
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