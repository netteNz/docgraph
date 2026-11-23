"""Replay calls 7 and 10 from the v2 query log with a symbol-tier budget
reserve, to test whether a symbol_target chunk can outrank a filename
fallback when given room, without touching context.py.

Usage: python simulate_symbol_reserve.py docs/validation/rl-stocks_query_log_v2.jsonl

For each watched call: room = budget - non-code_ref selected tokens.
Reserve = reserve_frac * room, filled greedily (rank order) from symbol-group
candidates only (symbol_preamble/symbol_target/symbol_neighbor/symbol_fallback).
Remaining room is then filled greedily (rank order) from all not-yet-selected
code_ref candidates (symbol groups included), same as the real fill loop.
No DB access: everything comes from the log.
"""
import json
import sys

WATCH = {
    7: "_run_ensemble",
    10: "generate_rollback_guide",
}
RESERVES = (0.0, 0.2, 0.3, 0.5, 0.7, 1.0)
SYMBOL_DETAILS = {"symbol_preamble", "symbol_target", "symbol_neighbor", "symbol_fallback"}


def fill(cands, room):
    selected, total, ids = [], 0, set()
    for c in cands:
        if id(c) in ids:
            continue
        if total + c["token_est"] > room:
            continue
        selected.append(c)
        ids.add(id(c))
        total += c["token_est"]
    return selected, ids


def run_reserve(cands, room, reserve_frac):
    symbol_cands = [c for c in cands if c.get("tier_detail") in SYMBOL_DETAILS]
    reserve_room = room * reserve_frac
    sym_selected, sym_ids = fill(symbol_cands, reserve_room)
    remaining_room = room - sum(c["token_est"] for c in sym_selected)
    rest_cands = [c for c in cands if id(c) not in sym_ids]
    rest_selected, _ = fill(rest_cands, remaining_room)
    return sym_selected + rest_selected


def main(path):
    log = [json.loads(l) for l in open(path, encoding="utf-8")]
    print("call  room  " + "  ".join(f"reserve={r}" for r in RESERVES))
    for i, r in enumerate(log, 1):
        if i not in WATCH:
            continue
        want = WATCH[i]
        room = r["budget"] - sum(
            c["token_est"] for c in r["chunks"] if c["provenance"] != "code_ref"
        )
        cands = sorted(
            [c for c in r["chunks"] + r["budget_cut"] if c["provenance"] == "code_ref"],
            key=lambda c: c["rank"],
        )
        cols = []
        for rf in RESERVES:
            sel = run_reserve(cands, room, rf)
            hit = any(c["heading"] == want for c in sel)
            cols.append(f"{'hit' if hit else 'miss'}(n={len(sel)})")
        print(f"{i:>4}  {room:>4}  " + "  ".join(f"{c:>14}" for c in cols) + f"  <- {want}")


if __name__ == "__main__":
    main(sys.argv[1])
