---
name: cst-research
description: Initialize and resume a CST microwave research workspace, coordinate modeling, CAD review, bounded simulation and optimization, and preserve reproducible results and reusable knowledge through Skills and MCP services.
license: MIT
metadata:
  version: "0.1.0"
  compatibility: Windows, Python 3.13 and a working CST installation for live solves. MCP-capable Agent required. Install all ten Skills for the complete research workflow.
---

# CST Research / CST 研究入口

Use this entry for a new study or to resume one. It coordinates the existing
nine professional Skills; it is not another solver or approval authority.

## First use

Read the Agent runbook [installation.md](references/installation.md). Execute
installation, initialization and diagnostics yourself; researchers should not
need a terminal, JSON contracts or MCP syntax. Run the installed Skill's
`scripts/bootstrap.py` with Python 3.13 and an explicit user-chosen workspace.
The bundled, checksum-verified runtime is deployed separately from installed
Skills. Initialization does not launch CST or create approvals.
Resolve execution components from the workspace's bound versioned runtime.
Distinguish copied Skills, deployed runtime, background protocol checks and
actual client tool loading. Tell the user only necessary client UI actions.
For onboarding and research guidance read
[researcher-dialogue.md](references/researcher-dialogue.md).

## Resume and plan

1. Read workspace `system/deployment.json`, `AGENTS.md`, topic `README.md` and
   `topic.md`, design `design.md`, attempt `attempt.json`, latest immutable
   evidence and append-only `iterations.jsonl`. Read through cst_get for jobs.
2. Use cst-brain-query for grounded context. State objective, units, stackup,
   port and phase references, pointwise acceptance gates, adjustable parameters,
   solver capabilities, budget and stopping conditions before live execution.
3. Use the scaffold CLI in the bound runtime to create topics, designs and
   attempts. Do not write fake IR or approval records to complete a scaffold.
4. Read [research-workflow.md](references/research-workflow.md) for relevant
   microwave stages and the Skill responsibilities. A missing eigenmode adapter
   must be reported; it is not permission to call legacy native tools.

## Execute and preserve

Use cst-vba-modeling for deterministic `build(overrides=None)` IR; use
cst-simulation-workflow for audit, actual human/scoped approval, screen and
independent confirm. Live operations use ONLY cst_run/cst_get/cst_approve.
Use cst-experiment-orchestration for bounded candidate selection; stop for
unresolved engineering tradeoffs, exhausted budgets or no improvement.
Use cst-result-plotting on retained curves, then inspect convergence, every
acceptance gate, content hashes and independent cache-free reopen.
Distinguish executed, accepted, cached and failed results in all reports.

Inspect job-bound learning publication. Use cst-trace-compile for import or
repair only when needed, cst-strategy-learning for evidence-backed candidates,
cst-brain-ingest for new references, and cst-brain-lint after changes.
Never declare knowledge publication from solver success alone.
Finish by updating the topic's best validated result and next action, leaving
an actionable failure/stop report if the requested physics was not achieved.
Do not rewrite old iterations or silently promote case-specific knowledge.
