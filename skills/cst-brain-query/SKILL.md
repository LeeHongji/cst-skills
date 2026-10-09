---
name: cst-brain-query
description: Retrieve grounded CST, electromagnetics, microwave-engineering, modeling, solver, optimization, failure, and case knowledge from the local second brain. Use before non-trivial CST work, when diagnosing a result, choosing a strategy, or answering a question that should be backed by local evidence and traces.
license: MIT
---

# CST Brain Query

Provider: use the separate `cst-brain` MCP configured in the current research workspace. Its tools read and curate that workspace Brain and do not control CST. If unavailable, use the runtime Python and root recorded in `system/deployment.json` to run `python -m cst_brain --brain-root <workspace>/brain`, or report the unavailable service. Do not invent a tool call.

Use the Brain as memory, not as unquestionable authority. Prefer validated pages, but preserve case-specific caveats.

## Workflow

1. Reformulate the task as a compact bilingual query when useful: component, CST operation, solver, metric, failure mode, and constraints.
2. Call `brain_context_pack_tool`:
   - `quick` for orientation.
   - `standard` before normal modeling or diagnosis.
   - `deep` before reconstruction, optimization, or architectural decisions.
3. Read the most relevant pages with `brain_read_page_tool`.
4. If a case is relevant, call `brain_get_case_tool` and `brain_get_trace_tool`.
5. Separate:
   - validated general knowledge,
   - case-specific evidence,
   - candidate hypotheses,
   - missing knowledge.
6. Pass only the relevant context into `$cst-simulation-workflow` or `$cst-vba-modeling`.

If retrieval is empty, continue with engineering fundamentals and authoritative sources, then add a candidate or ingest the source. Never invent a Brain citation.

See [retrieval-guide.md](references/retrieval-guide.md) for query patterns and status semantics.
