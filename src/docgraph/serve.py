"""
DocGraph live web graph — the "V1" successor to visualize.py's static POC.

Serves the same force-directed corpus graph, plus a task box that calls real
FTS5 retrieval (context.retrieve) and highlights exactly which file nodes got
selected into the context pack for that task, with the rendered pack content
in a side panel.

stdlib-only (http.server) — no new dependency, matching the rest of the
project (python-frontmatter + mcp are the only two deps). Local dev tool,
no auth: binds 127.0.0.1 by default.

Usage:
    python -m docgraph.serve <repo_root> <db_path> [--port 8765] [--host 127.0.0.1]
"""
from __future__ import annotations

import json
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from .context import retrieve
from .visualize import BUCKET_COLORS, graph_data

SERVE_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>DocGraph — {title}</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.9.0/d3.min.js"></script>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: system-ui, sans-serif; background: #0d1117; color: #c9d1d9; overflow: hidden; }}

  #legend {{ position: fixed; top: 14px; left: 14px; font-size: 12px; z-index: 10; }}
  #legend div {{ display: flex; align-items: center; gap: 7px; margin-bottom: 5px; opacity: 0.85; }}
  #legend span.dot {{
    width: 10px; height: 10px; border-radius: 50%; display: inline-block;
    box-shadow: 0 0 6px currentColor;
  }}
  #legend .sectionTitle {{
    color: #6e7681; font-size: 10.5px; text-transform: uppercase;
    letter-spacing: 0.04em; margin: 10px 0 4px;
  }}
  #legend .sectionTitle:first-child {{ margin-top: 0; }}
  #provSection {{ display: none; }}

  #controls {{
    position: fixed; top: 14px; right: 14px; z-index: 20;
    background: rgba(22, 27, 34, 0.95); border: 1px solid #30363d;
    border-radius: 8px; padding: 10px 12px; width: 340px;
    backdrop-filter: blur(6px);
  }}
  #controls input, #controls button {{
    font-family: inherit; font-size: 12px; background: #0d1117; color: #c9d1d9;
    border: 1px solid #30363d; border-radius: 5px; padding: 6px 8px;
  }}
  #task {{ width: 100%; margin-bottom: 6px; }}
  #controlsRow {{ display: flex; gap: 6px; align-items: center; }}
  #maxTokens {{ width: 90px; }}
  #go {{ cursor: pointer; flex: 1; }}
  #go:hover {{ border-color: #58a6ff; }}
  #clear {{ cursor: pointer; flex: 0 0 auto; }}
  #clear:hover {{ border-color: #f85149; }}
  #status {{ font-size: 11px; color: #8b949e; margin-top: 6px; min-height: 14px; }}

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

  #pack {{
    position: fixed; top: 0; right: 0; bottom: 0; width: 420px;
    background: rgba(13, 17, 23, 0.97); border-left: 1px solid #30363d;
    padding: 90px 18px 18px 28px; overflow-y: auto; font-size: 12px;
    line-height: 1.6; display: none; z-index: 15;
  }}
  #packResize {{
    position: absolute; left: -4px; top: 0; bottom: 0; width: 8px;
    cursor: col-resize; z-index: 16;
  }}
  #packResize:hover, #packResize.dragging {{ background: rgba(88, 166, 255, 0.25); }}
  #packToggle {{
    position: absolute; top: 14px; left: 14px; z-index: 16;
    background: #0d1117; color: #8b949e; border: 1px solid #30363d;
    border-radius: 5px; width: 24px; height: 24px; font-size: 12px;
    cursor: pointer; line-height: 1;
  }}
  #packToggle:hover {{ border-color: #58a6ff; color: #c9d1d9; }}
  #pack h2 {{ font-size: 13px; color: #e6edf3; margin: 0 0 4px 0; }}
  #pack .packMeta {{ color: #8b949e; font-size: 11px; margin-bottom: 14px; }}
  #pack .chunk {{ margin-bottom: 18px; padding-bottom: 14px; border-bottom: 1px solid #21262d; }}
  #pack .chunk h3 {{ font-size: 12px; color: #58a6ff; margin: 0 0 2px 0; }}
  #pack .chunkSrc {{ color: #6e7681; font-size: 10.5px; margin-bottom: 6px; }}
  #pack .chunkBody {{ color: #c9d1d9; }}
  #pack .chunkBody :first-child {{ margin-top: 0; }}
  #pack .chunkBody :last-child {{ margin-bottom: 0; }}
  #pack .chunkBody h1, #pack .chunkBody h2, #pack .chunkBody h3,
  #pack .chunkBody h4, #pack .chunkBody h5 {{ color: #e6edf3; font-size: 12.5px; margin: 12px 0 4px; }}
  #pack .chunkBody p {{ margin: 6px 0; }}
  #pack .chunkBody a {{ color: #58a6ff; }}
  #pack .chunkBody code {{
    background: #161b22; border: 1px solid #30363d; border-radius: 4px;
    padding: 1px 4px; font-size: 11px; font-family: ui-monospace, SFMono-Regular, monospace;
  }}
  #pack .chunkBody pre {{
    background: #161b22; border: 1px solid #30363d; border-radius: 6px;
    padding: 8px 10px; overflow-x: auto;
  }}
  #pack .chunkBody pre code {{ background: none; border: none; padding: 0; }}
  #pack .chunkBody ul, #pack .chunkBody ol {{ margin: 6px 0; padding-left: 20px; }}
  #pack .chunkBody blockquote {{
    border-left: 2px solid #30363d; margin: 6px 0; padding: 2px 10px; color: #8b949e;
  }}
  #pack .chunkBody table {{ border-collapse: collapse; font-size: 11px; margin: 6px 0; }}
  #pack .chunkBody th, #pack .chunkBody td {{ border: 1px solid #30363d; padding: 3px 6px; }}
  #pack .badge {{
    display: inline-block; font-size: 10px; padding: 1px 6px; border-radius: 10px;
    margin-left: 4px; border: 1px solid #30363d;
  }}
  #pack .badge.seed {{ color: #3fb950; border-color: #3fb950; }}
  #pack .badge.neighbor {{ color: #d29922; border-color: #d29922; }}
  #pack .badge.link {{ color: #58a6ff; border-color: #58a6ff; }}
  #pack .badge.code_ref {{ color: #bc8cff; border-color: #bc8cff; }}

  #stats {{
    position: fixed; bottom: 14px; left: 14px; font-size: 11px; color: #484f58;
    letter-spacing: 0.02em;
  }}

  .node-circle {{ cursor: pointer; }}
</style>
</head>
<body>
<div id="legend"></div>
<div id="controls">
  <input id="task" placeholder="Describe a task... (e.g. write ExitManager tests)" autofocus>
  <div id="controlsRow">
    <input id="maxTokens" type="number" value="8000" min="500" step="500" title="max tokens">
    <button id="go">Retrieve</button>
    <button id="clear" title="Clear query and reset graph">Clear</button>
  </div>
  <div id="status"></div>
</div>
<div id="tooltip"></div>
<div id="pack">
  <div id="packResize" title="Drag to resize"></div>
  <button id="packToggle" title="Expand/collapse">⤢</button>
  <div id="packContent"></div>
</div>
<div id="stats">{node_count} files, {stats_label} — drag nodes, scroll to zoom</div>
<svg id="graph" width="100%" height="100vh"></svg>
<script>
const data = {data_json};
const bucketColors = {colors_json};
const provenanceColors = {{ seed: "#3fb950", neighbor: "#d29922", link: "#58a6ff", code_ref: "#bc8cff" }};

const svg = d3.select("#graph");
const width = window.innerWidth, height = window.innerHeight;

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

Object.entries(provenanceColors).forEach(([prov, color]) => {{
  const f = defs.append("filter").attr("id", `glow-prov-${{prov}}`)
    .attr("x", "-60%").attr("y", "-60%").attr("width", "220%").attr("height", "220%");
  f.append("feFlood").attr("flood-color", color).attr("result", "flood");
  f.append("feComposite").attr("in", "flood").attr("in2", "SourceAlpha").attr("operator", "in").attr("result", "colored");
  f.append("feGaussianBlur").attr("in", "colored").attr("stdDeviation", prov === "seed" ? 6 : 4.5).attr("result", "blur");
  const m = f.append("feMerge");
  m.append("feMergeNode").attr("in", "blur");
  m.append("feMergeNode").attr("in", "SourceGraphic");
}});

const pulseFilter = defs.append("filter").attr("id", "glow-selected-pulse")
  .attr("x", "-70%").attr("y", "-70%").attr("width", "240%").attr("height", "240%");
pulseFilter.append("feGaussianBlur").attr("stdDeviation", "7").attr("result", "blur");
const pulseMerge = pulseFilter.append("feMerge");
pulseMerge.append("feMergeNode").attr("in", "blur");
pulseMerge.append("feMergeNode").attr("in", "SourceGraphic");

const g = svg.append("g");
const zoomBehavior = d3.zoom().scaleExtent([0.2, 5]).on("zoom", (e) => g.attr("transform", e.transform));
svg.call(zoomBehavior);

const sizeScale = d3.scaleSqrt().domain(d3.extent(data.nodes, d => d.tokens || 1)).range([4, 18]);

const sim = d3.forceSimulation(data.nodes)
  .force("link", d3.forceLink(data.links).id(d => d.id).distance(70).strength(0.3))
  .force("charge", d3.forceManyBody().strength(-140))
  .force("center", d3.forceCenter(width / 2, height / 2))
  .force("collide", d3.forceCollide(d => sizeScale(d.tokens || 1) + 5));

const linkG = g.append("g").attr("class", "links");
const link = linkG.selectAll("line").data(data.links).join("line")
  .attr("stroke", "#21262d")
  .attr("stroke-width", 1)
  .attr("stroke-opacity", 0.7)
  .attr("stroke-dasharray", d => d.kind === "structural" ? "3,3" : null);

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

const adjNodes = new Map(data.nodes.map(d => [d.id, new Set()]));
data.links.forEach(l => {{
  const sid = typeof l.source === "object" ? l.source.id : l.source;
  const tid = typeof l.target === "object" ? l.target.id : l.target;
  adjNodes.get(sid)?.add(tid);
  adjNodes.get(tid)?.add(sid);
}});

// ── Retrieval highlight state ───────────────────────────────────────────────
// selection: Map path -> "seed" | "neighbor" | "link" | "code_ref", empty = no active query
let selection = new Map();

function restingR(d) {{
  const sel = selection.get(d.id);
  return sizeScale(d.tokens || 1) * (selection.has(d.id) ? (sel === "seed" ? 1.4 : 1.15) : 1);
}}
function restingStroke(d) {{
  return selection.has(d.id) ? provenanceColors[selection.get(d.id)] : "#0d1117";
}}
function restingFilter(d) {{
  return selection.has(d.id) ? `url(#glow-prov-${{selection.get(d.id)}})` : null;
}}

function resetHighlight() {{
  selection = new Map();
  node.transition().duration(200)
    .attr("fill-opacity", 1).attr("filter", null)
    .attr("r", d => sizeScale(d.tokens || 1))
    .attr("stroke", "#0d1117").attr("stroke-width", 1.5);
  link.transition().duration(200).attr("stroke", "#21262d").attr("stroke-width", 1).attr("stroke-opacity", 0.7);
  provSectionEl.style.display = "none";
}}

function applyHighlight() {{
  if (selection.size === 0) {{ resetHighlight(); return; }}
  node.transition().duration(200)
    .attr("fill-opacity", d => selection.has(d.id) ? 1 : 0.12)
    .attr("filter", d => restingFilter(d))
    .attr("r", d => restingR(d))
    .attr("stroke", d => restingStroke(d))
    .attr("stroke-width", d => selection.has(d.id) ? 2 : 1.5);
  link.transition().duration(200)
    .attr("stroke-opacity", 0.15);
  provSectionEl.style.display = "block";
}}

function pulseNode(path) {{
  const target = node.filter(d => d.id === path);
  if (target.empty()) return;
  const d = target.datum();

  target.raise()
    .transition().duration(150).ease(d3.easeCubicOut)
    .attr("r", restingR(d) * 1.8).attr("stroke", "#e6edf3").attr("stroke-width", 3.5)
    .attr("filter", "url(#glow-selected-pulse)")
    .transition().delay(250).duration(450).ease(d3.easeCubicInOut)
    .attr("r", restingR(d)).attr("stroke", restingStroke(d)).attr("stroke-width", selection.has(d.id) ? 2 : 1.5)
    .attr("filter", restingFilter(d));

  const k = d3.zoomTransform(svg.node()).k;
  svg.transition().duration(500).call(
    zoomBehavior.transform,
    d3.zoomIdentity.translate(width / 2 - d.x * k, height / 2 - d.y * k).scale(k)
  );
}}

// ── Hover interactions (unchanged from POC, dim-on-hover) ──────────────────
const tooltip = d3.select("#tooltip");

node
  .on("mouseover", function(e, d) {{
    const r = sizeScale(d.tokens || 1);
    d3.select(this).raise()
      .transition().duration(180).ease(d3.easeCubicOut)
      .attr("r", r * 1.55)
      .attr("stroke-width", 2.5)
      .attr("filter", `url(#glow-${{d.bucket}})`);

    const connCount = adjNodes.get(d.id)?.size || 0;
    const sel = selection.get(d.id);
    const selLine = sel ? `<br><span style="color:${{provenanceColors[sel]}}">${{sel}} in current pack</span>` : "";
    tooltip.style("display", "block")
      .html(`<b>${{d.title}}</b><div class="meta">${{d.path}}<br>${{d.bucket}} · ~${{d.tokens.toLocaleString()}} tokens · ${{connCount}} connection${{connCount !== 1 ? "s" : ""}}${{selLine}}</div>`);
  }})
  .on("mousemove", (e) => {{
    tooltip.style("left", (e.clientX + 16) + "px").style("top", (e.clientY + 12) + "px");
  }})
  .on("mouseout", function(e, d) {{
    d3.select(this).transition().duration(220).ease(d3.easeCubicOut)
      .attr("r", restingR(d)).attr("stroke-width", selection.has(d.id) ? 2 : 1.5)
      .attr("filter", restingFilter(d));
    tooltip.style("display", "none");
  }});

sim.on("tick", () => {{
  link.attr("x1", d => d.source.x).attr("y1", d => d.source.y)
      .attr("x2", d => d.target.x).attr("y2", d => d.target.y);
  node.attr("cx", d => d.x).attr("cy", d => d.y);
}});

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

const legend = d3.select("#legend");
legend.append("div").attr("class", "sectionTitle").text("file buckets");
Object.entries(bucketColors).forEach(([bucket, color]) => {{
  const row = legend.append("div");
  row.append("span").attr("class", "dot").style("background", color).style("box-shadow", `0 0 6px ${{color}}55`);
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

const provSection = legend.append("div").attr("id", "provSection");
const provSectionEl = document.getElementById("provSection");
provSection.append("div").attr("class", "sectionTitle").text("retrieval provenance");
Object.entries(provenanceColors).forEach(([prov, color]) => {{
  const row = provSection.append("div");
  row.append("span").attr("class", "dot").style("background", color).style("box-shadow", `0 0 6px ${{color}}55`);
  row.append("span").text(prov).style("color", "#8b949e");
}});

// ── Retrieval box ────────────────────────────────────────────────────────────
const taskInput = document.getElementById("task");
const maxTokensInput = document.getElementById("maxTokens");
const statusEl = document.getElementById("status");
const packEl = document.getElementById("pack");
const packContentEl = document.getElementById("packContent");
const packResizeEl = document.getElementById("packResize");
const packToggleEl = document.getElementById("packToggle");

function escapeHtml(s) {{
  return s.replace(/[&<>"']/g, c => ({{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}})[c]);
}}

function clearQuery() {{
  taskInput.value = "";
  resetHighlight();
  packEl.style.display = "none";
  packContentEl.innerHTML = "";
  statusEl.textContent = "";
  taskInput.focus();
}}

function renderPack(json) {{
  if (json.chunks.length === 0) {{
    packEl.style.display = "block";
    packContentEl.innerHTML = `<h2>${{escapeHtml(json.task)}}</h2><div class="packMeta">0 chunks matched — try a more specific or different task string.</div>`;
    return;
  }}
  let html = `<h2>${{escapeHtml(json.task)}}</h2>`;
  html += `<div class="packMeta">${{json.chunks.length}} chunks, ~${{json.total_tokens}} tokens (budget ${{json.budget}}, ${{json.query_used}}-matched seeds)</div>`;
  for (const c of json.chunks) {{
    const loc = c.path + (c.heading ? ` § ${{c.heading}}` : "");
    // code_ref chunks are raw source, not markdown — fence them before
    // handing to marked, same as context.py::_render() does for the
    // CLI/MCP text output, so decorators/indentation/docstrings don't get
    // mangled by markdown parsing.
    const rendered = c.provenance === "code_ref"
      ? marked.parse("```" + (c.path.split(".").pop() || "") + "\\n" + c.body + "\\n```")
      : marked.parse(c.body);
    html += `<div class="chunk" data-path="${{escapeHtml(c.path)}}">
      <h3>${{escapeHtml(c.indexed_title)}}<span class="badge ${{c.provenance}}">${{c.provenance}}</span></h3>
      <div class="chunkSrc">${{escapeHtml(loc)}}</div>
      <div class="chunkBody">${{rendered}}</div>
    </div>`;
  }}
  packContentEl.innerHTML = html;
  packEl.style.display = "block";
}}

// ── Pack panel resize (drag) + expand toggle ────────────────────────────────
let packWidth = 420;
let packExpanded = false;

function setPackWidth(w) {{
  packWidth = Math.max(320, Math.min(w, window.innerWidth * 0.9));
  packEl.style.width = packWidth + "px";
}}

packResizeEl.addEventListener("mousedown", (e) => {{
  e.preventDefault();
  const startX = e.clientX, startW = packWidth;
  packResizeEl.classList.add("dragging");
  function onMove(ev) {{ setPackWidth(startW - (ev.clientX - startX)); }}
  function onUp() {{
    packResizeEl.classList.remove("dragging");
    document.removeEventListener("mousemove", onMove);
    document.removeEventListener("mouseup", onUp);
  }}
  document.addEventListener("mousemove", onMove);
  document.addEventListener("mouseup", onUp);
}});

packToggleEl.addEventListener("click", () => {{
  packExpanded = !packExpanded;
  setPackWidth(packExpanded ? window.innerWidth * 0.85 : 420);
  packToggleEl.textContent = packExpanded ? "⤡" : "⤢";
}});

async function runQuery() {{
  const task = taskInput.value.trim();
  if (!task) {{ clearQuery(); return; }}
  const maxTokens = parseInt(maxTokensInput.value, 10) || 8000;
  statusEl.textContent = "retrieving...";
  try {{
    const res = await fetch(`/context?task=${{encodeURIComponent(task)}}&max_tokens=${{maxTokens}}`);
    if (!res.ok) {{
      const err = await res.json().catch(() => ({{error: res.statusText}}));
      statusEl.textContent = `error: ${{err.error || res.statusText}}`;
      return;
    }}
    const json = await res.json();
    // path -> best provenance, seed > neighbor > link > code_ref (mirrors context.py's retrieval tiers)
    const provPriority = {{ seed: 0, neighbor: 1, link: 2, code_ref: 3 }};
    const sel = new Map();
    for (const c of json.chunks) {{
      const cur = sel.get(c.path);
      if (!cur || provPriority[c.provenance] < provPriority[cur]) sel.set(c.path, c.provenance);
    }}
    selection = sel;
    applyHighlight();
    renderPack(json);
    statusEl.textContent = `${{json.chunks.length}} chunks selected`;
  }} catch (e) {{
    statusEl.textContent = `error: ${{e}}`;
  }} finally {{
    taskInput.focus();
  }}
}}

document.getElementById("go").addEventListener("click", runQuery);
document.getElementById("clear").addEventListener("click", clearQuery);
taskInput.addEventListener("keydown", (e) => {{ if (e.key === "Enter") runQuery(); }});
packContentEl.addEventListener("click", (e) => {{
  const chunkEl = e.target.closest(".chunk");
  if (!chunkEl) return;
  pulseNode(chunkEl.dataset.path);
}});
</script>
</body>
</html>
"""


def _page_html(db_path: Path, title: str) -> str:
    data = graph_data(db_path)
    structural_count = sum(1 for l in data["links"] if l.get("kind") == "structural")
    stats_label = f"{len(data['links'])} edges"
    if structural_count:
        stats_label += f" ({structural_count} structural)"
    return SERVE_TEMPLATE.format(
        title=title or db_path.stem,
        node_count=len(data["nodes"]),
        stats_label=stats_label,
        data_json=json.dumps(data),
        colors_json=json.dumps(BUCKET_COLORS),
    )


class Handler(BaseHTTPRequestHandler):
    def __init__(self, *args, repo_root: Path, db_path: Path, title: str, **kwargs):
        self._repo_root = repo_root
        self._db_path = db_path
        self._title = title
        super().__init__(*args, **kwargs)

    def _send_json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 (stdlib method name)
        parsed = urlparse(self.path)

        if parsed.path == "/":
            body = _page_html(self._db_path, self._title).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/context":
            qs = parse_qs(parsed.query)
            task = (qs.get("task", [""])[0]).strip()
            if not task:
                self._send_json(400, {"error": "missing 'task' query param"})
                return
            try:
                max_tokens = int(qs.get("max_tokens", ["8000"])[0])
            except ValueError:
                self._send_json(400, {"error": "max_tokens must be an integer"})
                return
            try:
                data = retrieve(self._repo_root, self._db_path, task, max_tokens=max_tokens)
            except Exception as e:  # defensive: shouldn't trigger post-startup
                self._send_json(500, {"error": str(e)})
                return
            data["selected_paths"] = sorted({c["path"] for c in data["chunks"]})
            self._send_json(200, data)
            return

        self._send_json(404, {"error": "not found"})

    def log_message(self, fmt: str, *args) -> None:  # quieter default logging
        print(f"{self.address_string()} - {fmt % args}")


def serve(repo_root: Path, db_path: Path, host: str = "127.0.0.1", port: int = 8765, title: str = "") -> None:
    handler = partial(Handler, repo_root=repo_root.resolve(), db_path=db_path, title=title)
    httpd = ThreadingHTTPServer((host, port), handler)
    print(f"Serving DocGraph on http://{host}:{port}  (repo: {repo_root}, db: {db_path})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="Serve a live DocGraph web graph with real-time context retrieval.")
    p.add_argument("repo_root", type=Path)
    p.add_argument("db_path", type=Path)
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--title", default="")
    args = p.parse_args()
    serve(args.repo_root, args.db_path, host=args.host, port=args.port, title=args.title)
