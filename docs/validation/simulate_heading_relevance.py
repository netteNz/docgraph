"""Replay the code-tier fill with heading-relevance ordering (context.py Part B).

Usage:
  python docs/validation/simulate_heading_relevance.py docs/validation/rl-stocks_query_log_v3.jsonl

Imports the real helpers from docgraph.context (so replay == implementation).
Per call: code-tier room = budget - non-code_ref selected tokens; candidates =
code_ref chunks (selected + budget_cut). Baseline refills in logged rank order
(greedy skip-if-it-doesn't-fit, as simulate_target_cap.py). Variant moves chunks
whose heading shares a stem with the task ahead of all others (stable).

Variants: "binary" (the approved plan: relevant chunks first) and "count"
(relevant chunks ordered by number of matched task stems, more first). "count"
was added AFTER binary failed bar 1 on legacy-19 -- a post-hoc refinement
informed by this very log, so its replay is not out-of-sample; only the live
rerun is. Bars below were fixed before the first (binary) run.

Pre-registered bars (written before the first run, 2026-11-23):
  1. Used chunks kept >= 7/8, and every lost used chunk must be displaced by a
     heading-matched chunk of the SAME file (reported, judged by eye).
  2. Useful budget-cut chunks gained >= 1 (legacy-11 generate_rollback_guide).
  3. Advisory only: unreviewed newly-selected chunks have unknown value, so a
     pass licenses a live rerun + annotation, not a claim of improvement.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from docgraph.context import _heading_matches, _heading_relevant, _task_stems  # noqa: E402


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


VARIANTS = {
    "binary": lambda c, st: (not _heading_relevant(c["heading"], st), c["rank"]),
    "count": lambda c, st: (-_heading_matches(c["heading"], st), c["rank"]),
}


def main(log_path):
    log = [json.loads(l) for l in open(log_path, encoding="utf-8")]
    ann_path = Path(log_path).with_suffix(".annotations.jsonl")
    ann = {a["call_id"]: a for a in map(json.loads, open(ann_path, encoding="utf-8"))}
    agree = 0
    for name, keyfn in VARIANTS.items():
        kept = gained = new_unrev = changed = 0
        lines = []
        for i, r in enumerate(log, 1):
            a = ann[f"legacy-{i}"]
            stems = _task_stems(r["task"])
            used = {key(c) for c in a["selected"] if c["assessment"] == "used"}
            useful = {key(c) for c in a["budget_cut"] if c["assessment"] == "useful"}
            reviewed = {key(c) for c in a["selected"] + a["budget_cut"]}
            room = r["budget"] - sum(c["token_est"] for c in r["chunks"] if c["provenance"] != "code_ref")
            cands = sorted([c for c in r["chunks"] + r["budget_cut"] if c["provenance"] == "code_ref"],
                           key=lambda c: c["rank"])
            logged = {key(c) for c in r["chunks"] if c["provenance"] == "code_ref"}
            base = {key(c) for c in fill(cands, room)}
            if name == "binary":
                agree += base == logged
            sel_chunks = fill(sorted(cands, key=lambda c: keyfn(c, stems)), room)
            sel = {key(c) for c in sel_chunks}
            kept += len(used & sel)
            gained += len(useful & sel)
            changed += sel != base
            new_unrev += len(sel - base - reviewed)
            rel_sel = [key(c) for c in sel_chunks if _heading_relevant(c["heading"], stems)]
            for u in sorted(used - sel, key=str):
                same_file = [k for k in rel_sel if k[0] == u[0] and k not in base]
                lines.append(f"  LOST   legacy-{i}: {u}  displaced-by same-file relevant: {same_file or 'NONE'}")
            for u in sorted(useful & sel, key=str):
                lines.append(f"  GAINED legacy-{i}: {u}")
        print(f"[{name}] used kept {kept}/8 | useful cuts gained {gained}/5 | calls changed "
              f"{changed}/{len(log)} | newly selected unreviewed {new_unrev}")
        print("\n".join(lines))
    print(f"baseline replay reproduces logged selection in {agree}/{len(log)} calls")


if __name__ == "__main__":
    main(sys.argv[1])
