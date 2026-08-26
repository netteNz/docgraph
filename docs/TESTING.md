# Testing

```bash
python -m pip install -e ".[test]"
python -m pytest -ra
```

The suite includes pure code-chunk tests and disposable-repository integration
tests. External organic/hub/code fixtures require
`DOCGRAPH_FIXTURE_REPOS_DIR` to point to a directory holding their source
repositories and databases as described in `tests/fixtures/link_fixtures.json`.

A fixture reported as **skipped** is not a passed validation result. `-ra` is
configured locally and in CI to list every unavailable fixture explicitly.
Provision those repositories in a dedicated CI environment before making the
organic-fixture assertions a release gate.

## Real-use validation gate (P1)

`src/docgraph/validation.py` (`python -m docgraph.validation ...`) closes
the ≥20-call gate described in `docs/V4_NEXT_STEPS.md`: a query log records
retrieval facts only (what got selected, what got budget-cut), and a
separate append-only annotations file records human used/unused/uncertain
judgments against it, so the observed result can never rewrite the raw
evidence that produced it.

```bash
export DOCGRAPH_QUERY_LOG=/abs/path/to/query_log.jsonl   # opt-in, gitignored -- see .gitignore
python -m docgraph.context <repo_root> <db_path> "<task>"  # repeat for each call

python -m docgraph.validation annotate query_log.jsonl      # review one call at a time, interactively
python -m docgraph.validation report query_log.jsonl        # summarize once >= min-calls are reviewed
```

`report`'s `decision` is `collecting` until `--min-calls` (default 20) calls
are reviewed, then `keep_or_tune` or `kill` against `--threshold` (default
15% of reviewed calls with an actually-used advanced-tier chunk). Exposure
(a chunk got selected) is not usefulness (a chunk got used) -- `report`
only counts a pack as useful when a reviewed judgment says so; don't read
`tiers.<name>.exposed_packs` as a usefulness number.

Unit tests for the annotation/report logic: `tests/test_validation.py`. See
`docs/validation/RL_STOCKS_VALIDATION_NOTES.md` for a worked example (the
rl-stocks corpus run) and what its `budget_cut` review does and doesn't
cover.
