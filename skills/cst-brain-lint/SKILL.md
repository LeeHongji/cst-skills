---
name: cst-brain-lint
description: Audit the CST second brain for invalid frontmatter, duplicate IDs, broken wikilinks, unsupported validated claims, stale derived indexes, and structural drift. Use after ingestion, trace compilation, manual Obsidian edits, merges, or before relying on the Brain for important CST decisions.
license: MIT
---

# CST Brain Lint

Provider: use the separate `cst-brain` MCP configured in the current research workspace. Its tools read and curate that workspace Brain and do not control CST. If unavailable, use the runtime Python and root recorded in `system/deployment.json` to run `python -m cst_brain --brain-root <workspace>/brain`, or report the unavailable service. Do not invent a tool call.

Audit before repair. Canonical Markdown and raw evidence must not be silently rewritten.

## Workflow

1. Call `brain_lint_fix_tool` with `fix_safe=false`.
2. Group findings into errors and warnings.
3. Repair errors explicitly:
   - add required frontmatter,
   - make IDs unique,
   - attach evidence or demote unsupported validated pages,
   - fix link targets.
4. Call `brain_lint_fix_tool` with `fix_safe=true` only to rebuild safe derived indexes.
5. Re-run the audit and report remaining warnings with reasons.
6. Run the bound workspace doctor after data changes. Maintainers run the distribution and component tests after schemas, MCP code, or Skills change; no legacy repository harness is required.

Never delete raw sources or trace snapshots as a lint fix. Never manufacture evidence to clear an error.

See [lint-codes.md](references/lint-codes.md) for issue meanings.
