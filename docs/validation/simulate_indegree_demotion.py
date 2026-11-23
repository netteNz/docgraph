"""Replay the code-tier fill with high in-degree code targets demoted.

Usage:
  python docs/validation/simulate_indegree_demotion.py \
      docs/validation/rl-stocks_query_log_v3.jsonl db/rl-stocks-v5.db

Hypothesis (V4_NEXT_STEPS pending decision (b)): a code file referenced by
many docs (src/experiments.py, in-degree 19) says little about whether it
matters to *this* task -- IDF, applied to code_ref targets. In the v3 log
the >=8 in-degree targets took 95 selected chunks / ~13.5k tokens with 0 used.

For each call: code-tier room = budget - non-code_ref selected tokens; the
candidates are the call's code_ref chunks (selected + budget_cut). Baseline
re-fills them in logged rank order (greedy, skip-if-it-doesn't-fit, as
simulate_target_cap.py). Variant N moves every chunk whose target has
in-degree >= N after all other candidates, order otherwise preserved.

Scored against the call's annotations (assistant-made, not user-reviewed):
  kept_used     annotated-"used" selected chunks still selected
  got_useful    annotated-"useful" budget_cut chunks now selected
  lost_useful   ... that were selected at baseline and aren't now (never, today)
  unreviewed_in chunks newly selected that nobody annotated -- unknown value
  hi_tokens     tokens spent on in-degree >= N targets

Pre-registered bars (written before the first run, 2026-11-23):
  1. kept_used must equal baseline (8/8) -- no used chunk may drop out.
  2. got_useful must be >= baseline; and legacy-7's TradingEnv > __init__
     (target in-degree 17) is reported explicitly: demotion is expected to
     make it *less* reachable, which counts against the variant.
  3. The result is advisory: unreviewed_in chunks have unknown value, so a
     pass here licenses a live rerun + annotation, not a shipped constant.
"""
import json
import sqlite3
import sys
from pathlib import Path

THRESHOLDS = (None, 4, 6, 8, 12)


def key(c):
    return (c["path"], c["heading"])


def fill(cands, room):
    total, sel = 0, []
    for c in cands:
        if total + c["token_est"] > room:
            continue
        total += c["token_est"]
        sel.append(c)
    return sel


def in_degree(db_path):
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT target, COUNT(DISTINCT source) FROM edges WHERE kind='code_ref' GROUP BY target"
    ).fetchall()
    conn.close()
    return dict(rows)


def main(log_path, db_path):
    log = [json.loads(l) for l in open(log_path, encoding="utf-8")]
    ann_path = Path(log_path).with_suffix(".annotations.jsonl")
    ann = {a["call_id"]: a for a in map(json.loads, open(ann_path, encoding="utf-8"))}
    deg = in_degree(db_path)

    agree = 0
    totals = {n: dict(kept_used=0, got_useful=0, lost_useful=0, unreviewed_in=0,
                      hi_tokens=0, changed=0) for n in THRESHOLDS}
    watch = []
    for i, r in enumerate(log, 1):
        a = ann.get(f"legacy-{i}", {})
        used = {key(c) for c in a.get("selected", []) if c["assessment"] == "used"}
        useful = {key(c) for c in a.get("budget_cut", []) if c["assessment"] == "useful"}
        reviewed = {key(c) for c in a.get("selected", []) + a.get("budget_cut", [])}
        room = r["budget"] - sum(c["token_est"] for c in r["chunks"] if c["provenance"] != "code_ref")
        cands = sorted([c for c in r["chunks"] + r["budget_cut"] if c["provenance"] == "code_ref"],
                       key=lambda c: c["rank"])
        logged = {key(c) for c in r["chunks"] if c["provenance"] == "code_ref"}
        base = {key(c) for c in fill(cands, room)}
        agree += base == logged
        for n in THRESHOLDS:
            hi = (lambda c: deg.get(c["path"], 0) >= n) if n else (lambda c: False)
            order = sorted(cands, key=lambda c: (hi(c), c["rank"]))
            sel_chunks = fill(order, room)
            sel = {key(c) for c in sel_chunks}
            t = totals[n]
            t["kept_used"] += len(used & sel)
            t["got_useful"] += len(useful & sel)
            t["lost_useful"] += len(useful & base - sel)
            t["unreviewed_in"] += len(sel - base - reviewed)
            t["hi_tokens"] += sum(c["token_est"] for c in sel_chunks if deg.get(c["path"], 0) >= (n or 8))
            t["changed"] += sel != base
            for u in sorted(useful, key=str):
                watch.append((i, n, u, u in sel, deg.get(u[0], 0)))

    print(f"baseline replay reproduces logged code_ref selection in {agree}/{len(log)} calls\n")
    print("variant   kept_used  got_useful  lost_useful  unreviewed_in  hi_tokens  calls_changed")
    for n, t in totals.items():
        name = "baseline" if n is None else f"deg>={n}"
        print(f"{name:8}  {t['kept_used']:>9}  {t['got_useful']:>10}  {t['lost_useful']:>11}  "
              f"{t['unreviewed_in']:>13}  {t['hi_tokens']:>9}  {t['changed']:>13}")
    print("\n(hi_tokens for baseline uses deg>=8)\n\nuseful budget-cut chunks:")
    for i, n, u, hit, d in watch:
        print(f"  legacy-{i:<3} {('baseline' if n is None else f'deg>={n}'):9} "
              f"{u[0]} > {u[1]} (in-degree {d}): {'SELECTED' if hit else 'cut'}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
