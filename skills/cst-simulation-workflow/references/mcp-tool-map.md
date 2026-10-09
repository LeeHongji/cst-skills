# Production tool map

| Need | Service / tool |
| --- | --- |
| CAD audit, analysis, comparison, simulation | cst-function / cst_run |
| Task, metrics, exported curves, logs and evidence | cst-function / cst_get |
| Artifact-bound approval | cst-function / cst_approve |
| Search, context, cases and traces | cst-brain / brain_search_tool, brain_context_pack_tool, brain_read_page_tool, brain_get_case_tool, brain_get_trace_tool |
| Source import and candidate knowledge | cst-brain / brain_ingest_tool, brain_compile_run_tool, brain_create_candidate_tool |
| Evidence-gated promotion and maintenance | cst-brain / brain_promote_claim_tool, brain_lint_fix_tool, brain_rebuild_index_tool, brain_list_strategies_tool |

CAD/Lab/Guardian are internal execution dependencies. Lab administrative CLI
remains available for maintenance such as artifact indexing and retention.
Neither the legacy CST MCP nor the runtime/toolbox catalog is a production
Agent write entry. Keep their implementation and regression tests for backend
compatibility; no production Skill should route execution through them.

The default installer exposes 3 execution tools plus 12 knowledge tools.
Knowledge tools do not add a second solver lifecycle. Inspect the live tool
list after configuration changes; a Skill file does not load an MCP server.
