# Trace contract

Each native MCP event records:

- stable event and trace IDs, timestamp, sequence, stage, actor, tool;
- redacted arguments and parameter delta;
- concise decision/rationale fields;
- observation, status, latency, error;
- evidence artifact paths.

Large VBA/history bodies are stored separately with SHA256. A compiled run manifest records source/working projects, solver settings, parameters, metrics, artifacts with hashes, Skills used, status, and reproducibility.
