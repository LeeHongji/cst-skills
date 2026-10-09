# CST Skills distribution

This repository distributes the verified CST Automation core; do not build a
second executor. Production Agent writes use only cst_run/cst_get/cst_approve.
Brain is a separate MCP; CAD/Lab/Guardian and the vendored runtime are internal.
Public Skill sources live in skills/. Runtime releases are generated from MCP/,
brain/, examples/ and the maintained scripts by scripts/build-release.py.
Never hand-edit the generated archive or change finalized evidence.
Keep origin hashes in docs/source-baseline.json and adaptations in
docs/source-adaptations.json. Do not copy real user data, papers, credentials,
approval records or solver caches into this repository.
Run tests and installation verification before rebuilding a final release.
Research source files and original repositories are not migration targets.
