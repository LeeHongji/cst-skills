# CST execution core

This component is an internal execution dependency of the CST Skills package.
Install and use the distribution from its root README.md and docs/QUICKSTART.md.
The public Agent server is agent_mcp_server.py and exposes exactly cst_run,
cst_get and cst_approve. mcp_server.py and the vendored CLI are internal/legacy
compatibility interfaces, not alternative production Agent write paths.
Configure this server for one initialized research workspace; never restore
historical native-tool configuration to bypass ownership or approval checks.
