# Contributing

Use Windows and Python 3.13. Install `requirements-lock.txt`, then install the
four packages under `MCP/` with `pip install --no-deps -e <path>`. Run
`python -m pytest tests -q` and `python scripts/run-core-tests.py --output reports/core`.

Change the maintained source first, then regenerate the runtime with
`python scripts/build-release.py`. Include the archive and member manifest in
the same change. Never patch a deployed versioned runtime. Document adapter
coverage and attach exported evidence for any claim about new CST behavior.

Keep research data, private documents, credentials, approvals, CST projects,
solver caches and local configuration out of this repository. A fixture must
be self-contained and legally distributable. Preserve third-party notices.
Git preserves exact source bytes so the shipped archive remains reproducible
across clones. Write new text as UTF-8 with LF; rebuild after intentional edits.
Use issue reports that include the release hash, Python/CST version, operation,
expected behavior and a concise redacted log. Do not include private models.

All production simulation writes continue through the three-tool facade.
Do not add a convenience path that bypasses ownership, locking, CAD review,
approval, budget, exported results or evidence retention.
