"""
Shared viewer UI for the static (visualize.py) and live (serve.py) graph pages.

Both templates are .format() strings, so these blocks are inserted as format
arguments (single braces here, never re-formatted). Everything below assumes
the host template has already defined: `data`, `bucketColors`, `svg`,
`zoomBehavior`, `width`, `height`, `sizeScale`, `defs`, `node`, `link`,
`legend`, `tooltip` — and calls `addArrowMarkers(defs)` once, uses `linkColor`
/ `linkOpacity` / `linkDash` / `linkMarker` / `nodeStroke` / `nodeStrokeWidth`
/ `nodeDash` when building links and nodes, `positionLinks(link)` in its tick
handler, and `addViewerLegend(legend, data)` then `initViewerUi()` after the
legend rows for buckets exist.
"""

RESOLUTION_CSS = """
  /* ── shared viewer UI ───────────────────────────────────────────────── */
  #legend { top: 52px; max-height: calc(100vh - 360px); overflow-y: auto; padding-right: 8px; }
  #legend div.toggle { cursor: pointer; user-select: none; }
  #legend div.toggle:hover { opacity: 1; }
  #legend div.toggle.off { opacity: 0.35; text-decoration: line-through; }

  /* `#legend div` (flex) outranks the plain #provSection rule: hide it until a query runs */
  #legend #provSection { display: none; }

  #searchBox { position: fixed; top: 14px; left: 14px; width: 250px; z-index: 12; }
  #searchBox input {
    width: 100%; font-family: inherit; font-size: 12px; background: #0d1117; color: #c9d1d9;
    border: 1px solid #30363d; border-radius: 6px; padding: 6px 9px;
  }
  #searchBox input:focus { outline: none; border-color: #58a6ff; }
  #searchResults {
    display: none; margin-top: 3px; background: rgba(22, 27, 34, 0.98);
    border: 1px solid #30363d; border-radius: 6px; max-height: 260px; overflow-y: auto;
    font-size: 11.5px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);
  }
  #searchResults .hit { padding: 5px 9px; cursor: pointer; color: #8b949e; word-break: break-all; }
  #searchResults .hit:hover, #searchResults .hit.active { background: #1f2630; color: #e6edf3; }
  #searchResults .hit .flag { color: #f85149; margin-left: 4px; }

  #detail {
    display: none; position: fixed; left: 14px; bottom: 36px; width: 330px;
    max-height: 42vh; overflow-y: auto; z-index: 11; font-size: 11.5px; line-height: 1.55;
    background: rgba(22, 27, 34, 0.97); border: 1px solid #30363d; border-radius: 8px;
    padding: 10px 12px; box-shadow: 0 4px 20px rgba(0,0,0,0.5);
  }
  #detail b.title { color: #e6edf3; font-size: 12.5px; padding-right: 18px; display: block; }
  #detail .meta { color: #8b949e; font-size: 11px; margin-bottom: 6px; word-break: break-all; }
  #detail .close {
    position: absolute; top: 6px; right: 8px; background: none; border: none;
    color: #8b949e; font-size: 16px; cursor: pointer; line-height: 1;
  }
  #detail .close:hover { color: #e6edf3; }
  #detail h4 {
    margin: 9px 0 3px; font-size: 10px; text-transform: uppercase;
    letter-spacing: 0.06em; color: #6e7681; font-weight: 600;
  }
  #detail .row { padding: 1px 0; word-break: break-all; color: #8b949e; }
  #detail .chip {
    display: inline-block; font-size: 9.5px; padding: 0 5px; border-radius: 8px;
    border: 1px solid currentColor; margin-right: 5px; line-height: 1.5;
  }
  #detail a[data-focus] { color: #58a6ff; cursor: pointer; text-decoration: none; }
  #detail a[data-focus]:hover { text-decoration: underline; }
  #detail details summary { cursor: pointer; color: #8b949e; }
  #detail .warn { color: #d29922; }
  #detail .bad { color: #f85149; }
"""

RESOLUTION_JS = """
// ── shared viewer UI: resolution findings, toggles, search, detail panel ──────
const methodColors = {
  exact: "#bc8cff", rooted: "#d2a8ff", suffix: "#a5d6ff", basename: "#79c0ff", scoped: "#3fb950", depth: "#f0883e",
};
const methodLabels = {
  exact: "exact path", rooted: "repo-root path", suffix: "path-suffix match", basename: "unique basename",
  scoped: "scoped to doc's subtree", depth: "shallowest-path tiebreak",
};
const AMBIGUOUS_RING = "#f85149", HUB_RING = "#d29922", SUPPRESSED = "#6e7681";

const esc = s => String(s).replace(/[&<>"']/g, c => (
  {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
const nodeId = e => (typeof e === "object" ? e.id : e);
const LINK_COLOR = "#58a6ff";
const isCodeEdge = l => l.kind === "code_ref" || l.kind === "code_ref_suppressed" || l.kind === "link";

function linkColor(l) {
  if (l.kind === "code_ref") return methodColors[l.method] || "#bc8cff";
  if (l.kind === "code_ref_suppressed") return SUPPRESSED;
  if (l.kind === "link") return LINK_COLOR;
  return "#21262d";
}
function linkOpacity(l) {
  if (l.kind === "code_ref") return 0.6;
  if (l.kind === "link") return 0.8;
  return l.kind === "code_ref_suppressed" ? 0.45 : 0.7;
}
function linkDash(l) {
  if (l.kind === "structural") return "3,3";
  return l.kind === "code_ref_suppressed" ? "2,3" : null;
}
function linkMarker(l) {
  if (l.kind === "code_ref") return `url(#arrow-${l.method || "exact"})`;
  if (l.kind === "link") return "url(#arrow-link)";
  return l.kind === "code_ref_suppressed" ? "url(#arrow-suppressed)" : null;
}
function nodeStroke(d) {
  if (d.ambiguous > 0) return AMBIGUOUS_RING;
  return d.hub_refs > 0 ? HUB_RING : "#0d1117";
}
function nodeStrokeWidth(d) { return (d.ambiguous > 0 || d.hub_refs > 0) ? 2.5 : 1.5; }
function nodeDash(d) { return d.hub_refs > 0 ? "3,2" : null; }

// Directional (code_ref) edges get an arrowhead; the line is shortened to the
// target node's rim so the head isn't hidden under the circle.
function addArrowMarkers(defs) {
  const colors = Object.assign({}, methodColors, {suppressed: SUPPRESSED, link: LINK_COLOR});
  Object.entries(colors).forEach(([k, c]) => {
    defs.append("marker").attr("id", "arrow-" + k)
      .attr("viewBox", "0 0 10 10").attr("refX", 10).attr("refY", 5)
      .attr("markerWidth", 7).attr("markerHeight", 7)
      .attr("markerUnits", "userSpaceOnUse").attr("orient", "auto")
      .append("path").attr("d", "M0,1 L10,5 L0,9 z").attr("fill", c);
  });
}
function positionLinks(sel) {
  sel.each(function(l) {
    let x2 = l.target.x, y2 = l.target.y;
    if (isCodeEdge(l)) {
      const dx = x2 - l.source.x, dy = y2 - l.source.y, len = Math.hypot(dx, dy) || 1;
      const r = sizeScale(l.target.tokens || 1) + 2;
      x2 -= dx / len * r; y2 -= dy / len * r;
    }
    this.setAttribute("x1", l.source.x); this.setAttribute("y1", l.source.y);
    this.setAttribute("x2", x2); this.setAttribute("y2", y2);
  });
}

// ── visibility toggles (legend rows) ─────────────────────────────────────────
const hiddenKeys = new Set();
const edgeKey = l => (l.kind === "code_ref" ? "method:" + (l.method || "exact")
  : l.kind === "code_ref_suppressed" ? "suppressed" : l.kind);

function applyVisibility() {
  const byId = new Map(data.nodes.map(d => [d.id, d]));
  const nodeHidden = d => !d || hiddenKeys.has("bucket:" + d.bucket);
  node.attr("display", d => (nodeHidden(d) ? "none" : null));
  link.attr("display", l => (
    hiddenKeys.has(edgeKey(l)) || nodeHidden(byId.get(nodeId(l.source)))
      || nodeHidden(byId.get(nodeId(l.target))) ? "none" : null));
}
function makeToggle(sel, key) {
  sel.classed("toggle", true).attr("title", "click to show/hide").on("click", function() {
    if (hiddenKeys.has(key)) hiddenKeys.delete(key); else hiddenKeys.add(key);
    d3.select(this).classed("off", hiddenKeys.has(key));
    applyVisibility();
  });
}

function resolutionTooltip(d) {
  const parts = [];
  const res = d.resolved || {};
  const resBits = Object.keys(methodColors).filter(m => res[m])
    .map(m => `<span style="color:${methodColors[m]}">${res[m]} ${m}</span>`);
  if (resBits.length) parts.push("code refs: " + resBits.join(" · "));
  if (d.ambiguous > 0) {
    const ex = (d.ambiguous_samples || []).map(s => `${esc(s.mention)} (${s.candidates})`).join(", ");
    parts.push(`<span style="color:${AMBIGUOUS_RING}">${d.ambiguous} ambiguous, no edge</span>: ${ex}`);
  }
  if (d.dead > 0) parts.push(`${d.dead} dead (no such file)`);
  if (d.hub_refs > 0) {
    parts.push(`<span style="color:${HUB_RING}">hub-skipped: ${d.hub_refs} resolved refs dropped whole</span>`);
  }
  parts.push('<span style="color:#6e7681">click for details</span>');
  return "<br>" + parts.join("<br>");
}

function addViewerLegend(legend, data) {
  const present = new Set(data.links.filter(l => l.kind === "code_ref").map(l => l.method || "exact"));
  const hasSuppressed = data.links.some(l => l.kind === "code_ref_suppressed");
  const nAmb = data.nodes.filter(n => n.ambiguous > 0).length;
  const nHub = data.nodes.filter(n => n.hub_refs > 0).length;
  const count = f => data.links.filter(f).length;

  const line = (color, dash, text, key) => {
    const row = legend.append("div");
    row.append("span").style("width", "14px").style("height", "0")
      .style("border-top", `2px ${dash} ${color}`).style("display", "inline-block");
    row.append("span").text(text).style("color", "#8b949e");
    makeToggle(row, key);
  };
  const ring = (color, dash, text) => {
    const row = legend.append("div");
    row.append("span").style("width", "10px").style("height", "10px").style("border-radius", "50%")
      .style("display", "inline-block").style("border", `2px ${dash} ${color}`);
    row.append("span").text(text).style("color", "#8b949e");
  };

  legend.append("div").attr("class", "sectionTitle").text("edges");
  const nColoc = count(l => l.kind === "colocation");
  if (nColoc) line("#484f58", "solid", `same folder (${nColoc})`, "colocation");
  const nLink = count(l => l.kind === "link");
  if (nLink) line(LINK_COLOR, "solid", `doc link / [[wikilink]] (${nLink})`, "link");
  const nStruct = count(l => l.kind === "structural");
  if (nStruct) line("#6e7681", "dashed", `structural tie (${nStruct})`, "structural");

  if (!present.size && !hasSuppressed && !nAmb && !nHub) return;
  legend.append("div").attr("class", "sectionTitle").text("code ref resolution  →");
  Object.keys(methodColors).filter(m => present.has(m)).forEach(m => {
    const n = count(l => l.kind === "code_ref" && (l.method || "exact") === m);
    line(methodColors[m], "solid", `${methodLabels[m]} (${n})`, "method:" + m);
  });
  if (hasSuppressed) {
    line(SUPPRESSED, "dotted", `dropped by hub rule (${count(l => l.kind === "code_ref_suppressed")} shown)`, "suppressed");
  }
  if (nAmb) ring(AMBIGUOUS_RING, "solid", `doc w/ ambiguous refs (${nAmb})`);
  if (nHub) ring(HUB_RING, "dashed", `hub-skipped doc (${nHub})`);
}

// ── detail panel ─────────────────────────────────────────────────────────────
const detailEl = d3.select("body").append("div").attr("id", "detail");
function closeDetail() { detailEl.style("display", "none"); }

function chip(method) {
  const c = methodColors[method] || "#8b949e";
  return `<span class="chip" style="color:${c}">${esc(method)}</span>`;
}
function focusLink(path) {
  return data.nodes.some(n => n.id === path)
    ? `<a data-focus="${esc(path)}">${esc(path)}</a>` : esc(path);
}

function openDetail(d) {
  const refs = d.refs || [];
  const resolved = refs.filter(r => r.status === "resolved");
  const ambiguous = refs.filter(r => r.status === "ambiguous");
  const dead = refs.filter(r => r.status === "dead");
  const inbound = data.links.filter(l => l.kind === "code_ref" && nodeId(l.target) === d.id);
  const h = [];
  h.push(`<button class="close" title="close (Esc)">×</button>`);
  h.push(`<b class="title">${esc(d.title)}</b>`);
  h.push(`<div class="meta">${esc(d.path)}<br>${esc(d.bucket)} · ~${(d.tokens || 0).toLocaleString()} tokens</div>`);

  if (d.hub_refs > 0) {
    h.push(`<div class="warn">Hub-skipped: ${d.hub_refs} distinct resolved refs exceeded the per-doc cap, so none became edges.</div>`);
  }
  if (resolved.length) {
    h.push(`<h4>resolves to (${resolved.length})</h4>`);
    resolved.forEach(r => h.push(`<div class="row">${chip(r.method)}${esc(r.mention)} → ${focusLink(r.target)}</div>`));
  }
  if (ambiguous.length) {
    h.push(`<h4 class="bad">ambiguous — no edge (${ambiguous.length})</h4>`);
    ambiguous.forEach(r => h.push(`<div class="row"><span class="bad">${esc(r.mention)}</span> · ${r.candidates} same-name files, no unique winner</div>`));
  }
  if (dead.length) {
    h.push(`<details><summary>${dead.length} dead refs (no such file)</summary>`
      + dead.map(r => `<div class="row">${esc(r.mention)}</div>`).join("") + `</details>`);
  }
  if (inbound.length) {
    h.push(`<h4>referenced by (${inbound.length})</h4>`);
    inbound.forEach(l => h.push(`<div class="row">${chip(l.method || "exact")}${focusLink(nodeId(l.source))}</div>`));
  }
  if (!refs.length && !inbound.length && !(d.hub_refs > 0)) {
    h.push(`<div class="row">No code-reference findings for this file.</div>`);
  }
  detailEl.html(h.join("")).style("display", "block").node().scrollTop = 0;
}

detailEl.on("click", e => {
  if (e.target.closest(".close")) { closeDetail(); return; }
  const a = e.target.closest("[data-focus]");
  if (a) focusNode(a.dataset.focus);
});

function focusNode(id) {
  const d = data.nodes.find(n => n.id === id);
  if (!d || d.x === undefined) return;
  const k = Math.max(d3.zoomTransform(svg.node()).k, 1.2);
  svg.transition().duration(500).call(
    zoomBehavior.transform,
    d3.zoomIdentity.translate(width / 2 - d.x * k, height / 2 - d.y * k).scale(k));
  openDetail(d);
  const rest = typeof restingStroke === "function" ? restingStroke : nodeStroke;
  node.filter(n => n.id === id).raise()
    .transition().duration(200).attr("stroke", "#e6edf3").attr("stroke-width", 4)
    .transition().delay(700).duration(400)
    .attr("stroke", n => rest(n)).attr("stroke-width", n => nodeStrokeWidth(n));
}

// ── search + keyboard + click wiring ─────────────────────────────────────────
function initViewerUi() {
  const box = d3.select("body").append("div").attr("id", "searchBox");
  const input = box.append("input").attr("placeholder", "Find file…   ( / )").attr("spellcheck", "false");
  const results = box.append("div").attr("id", "searchResults");
  let hits = [], active = 0;

  const render = () => {
    results.html("");
    results.style("display", hits.length ? "block" : "none");
    hits.forEach((n, i) => {
      const row = results.append("div").attr("class", "hit" + (i === active ? " active" : ""));
      row.append("span").text(n.path);
      if (n.ambiguous > 0) row.append("span").attr("class", "flag").text("● ambiguous");
      row.on("click", () => pick(n));
    });
  };
  const pick = n => { results.style("display", "none"); input.property("value", ""); hits = []; focusNode(n.id); };

  input.on("input", () => {
    const q = input.property("value").trim().toLowerCase();
    hits = q ? data.nodes.filter(n => n.path.toLowerCase().includes(q)).slice(0, 12) : [];
    active = 0; render();
  });
  input.on("keydown", e => {
    if (e.key === "ArrowDown" && hits.length) { active = (active + 1) % hits.length; render(); e.preventDefault(); }
    else if (e.key === "ArrowUp" && hits.length) { active = (active - 1 + hits.length) % hits.length; render(); e.preventDefault(); }
    else if (e.key === "Enter" && hits[active]) pick(hits[active]);
    else if (e.key === "Escape") { input.property("value", ""); hits = []; render(); input.node().blur(); }
    e.stopPropagation();
  });

  document.addEventListener("keydown", e => {
    const tag = document.activeElement && document.activeElement.tagName;
    if (e.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA") { e.preventDefault(); input.node().focus(); }
    else if (e.key === "Escape" && tag !== "INPUT") closeDetail();
  });

  node.on("click", (e, d) => { e.stopPropagation(); openDetail(d); });
  svg.on("click", () => closeDetail());
}
"""
