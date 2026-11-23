"""Replay the code-tier fill from a query log under a per-target budget cap.

Usage: python simulate_target_cap.py docs/validation/rl-stocks_query_log_v2.jsonl

For each call, reconstructs the code-tier room (budget minus non-code_ref
selected tokens), then greedily refills the code_ref candidates
(selected + budget_cut, in rank order) under CODE_TARGET_BUDGET_SHARE caps.
Reports whether a named heading survives. Also replays target-major order
for comparison. No DB access: everything comes from the log.
"""
import json
import sys
from collections import defaultdict

WATCH = {
    10: "generate_rollback_guide",
    11: "generate_rollback_guide",
    19: "SentimentResult",
}
CAPS = (None, 0.5, 0.35, 0.25, 0.2)


def fill(cands, room, cap):
    used, total, sel = defaultdict(int), 0, []
    for c in cands:
        t = c["token_est"]
        if total + t > room:
            continue
        if cap is not None and used[c["path"]] + t > cap:
            continue
        used[c["path"]] += t
        total += t
        sel.append(c)
    return sel


def target_major_key(order):
    idx = {p: i for i, p in enumerate(order)}
    return lambda c: (int(c["rank"]), idx[c["path"]], round((c["rank"] % 1) * 100))


def main(path):
    log = [json.loads(l) for l in open(path, encoding="utf-8")]
    print("call  room  " + "  ".join(f"cap={c}" for c in CAPS) + "  target-major")
    for i, r in enumerate(log, 1):
        room = r["budget"] - sum(
            c["token_est"] for c in r["chunks"] if c["provenance"] != "code_ref"
        )
        cands = sorted(
            [c for c in r["chunks"] + r["budget_cut"] if c["provenance"] == "code_ref"],
            key=lambda c: c["rank"],
        )
        want = WATCH.get(i)
        cols = []
        for cap in CAPS:
            sel = fill(cands, room, None if cap is None else cap * room)
            cols.append("hit" if want and any(c["heading"] == want for c in sel) else f"n={len(sel)}")
        order = sorted({c["path"] for c in cands})
        sel = fill(sorted(cands, key=target_major_key(order)), room, None)
        tm = "hit" if want and any(c["heading"] == want for c in sel) else f"n={len(sel)}"
        flag = f"  <- {want}" if want else ""
        print(f"{i:>4}  {room:>4}  " + "  ".join(f"{c:>8}" for c in cols) + f"  {tm:>12}{flag}")


if __name__ == "__main__":
    main(sys.argv[1])
