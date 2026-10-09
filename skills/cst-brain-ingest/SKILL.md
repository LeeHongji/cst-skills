---
name: cst-brain-ingest
description: Capture CST documents, scripts, reports, exported data, and other local engineering sources into the evidence-backed Obsidian Brain. Use when a new source should become searchable without changing the original, when importing references, or when recording source provenance before extracting claims.
license: MIT
---

# CST Brain Ingest

Provider: use the separate `cst-brain` MCP configured in the current research workspace. Its tools read and curate that workspace Brain and do not control CST. If unavailable, use the runtime Python and root recorded in `system/deployment.json` to run `python -m cst_brain --brain-root <workspace>/brain`, or report the unavailable service. Do not invent a tool call.

Ingest first; synthesize second. Preserve the original evidence and its SHA256.

## Workflow

1. Confirm the source path and classify it as `document`, `paper`, `dataset`, `script`, `report`, or `other`.
2. Call `brain_ingest_tool` with the local path, descriptive title, and source type.
3. Inspect the returned source page and immutable raw copy.
4. Extract explicit claims into candidate pages with `brain_create_candidate_tool`. Cite the captured `source://sha256/...` evidence.
5. Connect the candidates to existing foundations, CST behavior, cases, failures, or strategies.
6. Run `brain_lint_fix_tool` with `fix_safe=false`.

Do not copy binary contents into Markdown. Do not promote a source summary merely because ingestion succeeded. Use an appropriate PDF/document/data Skill to inspect non-text formats.

See [evidence-policy.md](references/evidence-policy.md) for source and promotion rules.
