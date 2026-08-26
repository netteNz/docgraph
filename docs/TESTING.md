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
