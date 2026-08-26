"""Annotate and summarize the real-use retrieval validation gate.

Query logs intentionally contain retrieval facts only.  This module writes
human judgments to a separate append-only JSONL file so the observed result
cannot rewrite the raw evidence that produced it.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ADVANCED_PROVENANCE = {"link", "code_ref"}
DEFAULT_MIN_CALLS = 20
DEFAULT_THRESHOLD = 0.15


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    records = []
    with path.open(encoding="utf-8") as stream:
        for line_no, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSON: {exc.msg}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"{path}:{line_no}: expected a JSON object")
            records.append(record)
    return records


def _call_id(entry: dict, line_no: int) -> str:
    """Support logs written before call_id was added without mutating them."""
    return str(entry.get("call_id") or f"legacy-{line_no}")


def _tier(chunk: dict) -> str:
    if chunk.get("provenance") == "link":
        return "link"
    return str(chunk.get("tier_detail") or chunk.get("provenance") or "unknown")


def _candidate(chunk: dict) -> dict:
    return {
        "path": chunk.get("path"),
        "heading": chunk.get("heading"),
        "provenance": chunk.get("provenance"),
        "tier_detail": chunk.get("tier_detail"),
    }


def _candidate_key(chunk: dict) -> tuple:
    return (
        chunk.get("path"),
        chunk.get("heading"),
        chunk.get("provenance"),
        chunk.get("tier_detail"),
    )


def pending_calls(query_log: Path, annotations: Path) -> list[tuple[str, dict]]:
    entries = _read_jsonl(query_log)
    reviewed = {str(row.get("call_id")) for row in _read_jsonl(annotations)}
    return [
        (_call_id(entry, line_no), entry)
        for line_no, entry in enumerate(entries, 1)
        if _call_id(entry, line_no) not in reviewed
    ]


def _prompt_choice(prompt: str, choices: dict[str, str]) -> str:
    while True:
        answer = input(prompt).strip().lower()
        if answer in choices:
            return choices[answer]
        print("Choose " + ", ".join(choices))


def _prompt_note() -> str:
    while True:
        note = input("One-line outcome note: ").strip()
        if note:
            return " ".join(note.splitlines())
        print("Record a short outcome note while the call is still fresh.")


def annotate_next(query_log: Path, annotations: Path) -> bool:
    pending = pending_calls(query_log, annotations)
    if not pending:
        print("No unreviewed calls.")
        return False

    call_id, entry = pending[0]
    print(f"Call {call_id}\nTask: {entry.get('task', '')}")
    selected = [c for c in entry.get("chunks", []) if c.get("provenance") in ADVANCED_PROVENANCE]
    cut = list(entry.get("budget_cut", []))

    selected_reviews = []
    for chunk in selected:
        label = f"{_tier(chunk)}: {chunk.get('path')}"
        if chunk.get("heading"):
            label += f" § {chunk['heading']}"
        assessment = _prompt_choice(
            f"Selected {label} — [u]sed, [n]ot used, [?] uncertain: ",
            {"u": "used", "n": "unused", "?": "uncertain"},
        )
        selected_reviews.append({**_candidate(chunk), "assessment": assessment})

    cut_reviews = []
    for chunk in cut:
        label = f"{_tier(chunk)}: {chunk.get('path')}"
        if chunk.get("heading"):
            label += f" § {chunk['heading']}"
        assessment = _prompt_choice(
            f"Budget-cut {label} — [u]seful, [n]ot useful, [?] uncertain: ",
            {"u": "useful", "n": "not_useful", "?": "uncertain"},
        )
        cut_reviews.append({**_candidate(chunk), "assessment": assessment})

    record = {
        "schema_version": 1,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "call_id": call_id,
        "note": _prompt_note() if selected or cut else "No selected advanced or budget-cut candidates.",
        "selected": selected_reviews,
        "budget_cut": cut_reviews,
    }
    annotations.parent.mkdir(parents=True, exist_ok=True)
    with annotations.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(record) + "\n")
    print(f"Recorded review in {annotations}")
    return True


def summarize(
    query_log: Path,
    annotations: Path,
    *,
    min_calls: int = DEFAULT_MIN_CALLS,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    entries = _read_jsonl(query_log)
    calls = {_call_id(entry, i): entry for i, entry in enumerate(entries, 1)}
    reviews = {str(row.get("call_id")): row for row in _read_jsonl(annotations)}
    reviewed_ids = set(calls) & set(reviews)

    tier_stats: dict[str, dict[str, int | float]] = defaultdict(
        lambda: {
            "exposed_packs": 0,
            "used_packs": 0,
            "selected_chunks": 0,
            "used_chunks": 0,
            "budget_cut_reviewed": 0,
            "budget_cut_useful": 0,
            "budget_cut_uncertain": 0,
        }
    )
    used_any = 0
    useful_cut = 0
    uncertain_cut = 0

    for call_id in reviewed_ids:
        entry = calls[call_id]
        review = reviews[call_id]
        selected_reviews = {_candidate_key(row): row for row in review.get("selected", [])}
        tiers_exposed: set[str] = set()
        tiers_used: set[str] = set()
        call_used = False
        for chunk in entry.get("chunks", []):
            if chunk.get("provenance") not in ADVANCED_PROVENANCE:
                continue
            tier = _tier(chunk)
            tiers_exposed.add(tier)
            tier_stats[tier]["selected_chunks"] += 1
            judgment = selected_reviews.get(_candidate_key(chunk), {}).get("assessment")
            if judgment == "used":
                call_used = True
                tiers_used.add(tier)
                tier_stats[tier]["used_chunks"] += 1
        if call_used:
            used_any += 1
        for tier in tiers_exposed:
            tier_stats[tier]["exposed_packs"] += 1
        for tier in tiers_used:
            tier_stats[tier]["used_packs"] += 1

        for row in review.get("budget_cut", []):
            tier = _tier(row)
            tier_stats[tier]["budget_cut_reviewed"] += 1
            if row.get("assessment") == "useful":
                useful_cut += 1
                tier_stats[tier]["budget_cut_useful"] += 1
            elif row.get("assessment") == "uncertain":
                uncertain_cut += 1
                tier_stats[tier]["budget_cut_uncertain"] += 1

    reviewed_count = len(reviewed_ids)
    usefulness_rate = used_any / reviewed_count if reviewed_count else 0.0
    gate_ready = reviewed_count >= min_calls
    decision = "collecting"
    if gate_ready:
        decision = "keep_or_tune" if usefulness_rate >= threshold else "kill"

    for stats in tier_stats.values():
        exposed = stats["exposed_packs"]
        stats["usefulness_rate_all_reviewed_packs"] = (
            stats["used_packs"] / reviewed_count if reviewed_count else 0.0
        )
        stats["precision_when_exposed"] = stats["used_packs"] / exposed if exposed else 0.0

    return {
        "logged_calls": len(calls),
        "reviewed_calls": reviewed_count,
        "pending_calls": len(calls) - reviewed_count,
        "minimum_calls": min_calls,
        "threshold": threshold,
        "packs_with_used_advanced_context": used_any,
        "usefulness_rate": usefulness_rate,
        "gate_ready": gate_ready,
        "decision": decision,
        "tiers": dict(sorted(tier_stats.items())),
        "budget_cut": {"useful": useful_cut, "uncertain": uncertain_cut},
    }


def render_summary(summary: dict) -> str:
    lines = [
        "# DocGraph validation study",
        "",
        f"- Calls: {summary['reviewed_calls']}/{summary['logged_calls']} reviewed "
        f"(minimum {summary['minimum_calls']})",
        f"- Packs with used advanced context: {summary['packs_with_used_advanced_context']} "
        f"({summary['usefulness_rate']:.1%})",
        f"- Pre-registered threshold: {summary['threshold']:.1%}",
        f"- Gate: {summary['decision']}",
        f"- Useful budget-cut candidates: {summary['budget_cut']['useful']} "
        f"({summary['budget_cut']['uncertain']} uncertain)",
        "",
        "| Tier | Exposed packs | Used packs | Precision | Selected/used chunks | Useful budget cuts |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for tier, stats in summary["tiers"].items():
        lines.append(
            f"| {tier} | {stats['exposed_packs']} | {stats['used_packs']} | "
            f"{stats['precision_when_exposed']:.1%} | "
            f"{stats['selected_chunks']}/{stats['used_chunks']} | "
            f"{stats['budget_cut_useful']}/{stats['budget_cut_reviewed']} |"
        )
    return "\n".join(lines)


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Annotate and summarize DocGraph's P1 validation gate.")
    sub = parser.add_subparsers(dest="command", required=True)

    annotate_parser = sub.add_parser("annotate", help="Review the next unannotated retrieval call")
    annotate_parser.add_argument("query_log", type=Path)
    annotate_parser.add_argument("--annotations", type=Path)

    report_parser = sub.add_parser("report", help="Summarize reviewed retrieval calls")
    report_parser.add_argument("query_log", type=Path)
    report_parser.add_argument("--annotations", type=Path)
    report_parser.add_argument("--min-calls", type=int, default=DEFAULT_MIN_CALLS)
    report_parser.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    report_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(list(argv) if argv is not None else None)
    annotations = args.annotations or args.query_log.with_suffix(".annotations.jsonl")
    if args.command == "annotate":
        annotate_next(args.query_log, annotations)
        return 0

    if args.min_calls < 1:
        parser.error("--min-calls must be at least 1")
    if not 0 <= args.threshold <= 1:
        parser.error("--threshold must be between 0 and 1")
    result = summarize(args.query_log, annotations, min_calls=args.min_calls, threshold=args.threshold)
    print(json.dumps(result, indent=2) if args.json else render_summary(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
