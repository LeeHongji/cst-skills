# CST Skills

[![Verify distribution](https://github.com/LeeHongji/cst-skills/actions/workflows/verify.yml/badge.svg)](https://github.com/LeeHongji/cst-skills/actions/workflows/verify.yml) · [MIT](LICENSE) · [Releases](https://github.com/LeeHongji/cst-skills/releases)

English | [简体中文](README.md)

**An Agent toolkit for microwave research: from theory, CAD review, and CST simulation to optimization, evidence archiving, and reusable engineering knowledge.**

CST Skills provides ten research Skills, two public MCP services, and research workspace initialization. Researchers use conversation to define objectives, review models, and guide optimization. The Agent follows a consistent workflow to organize experiments, run CST, and preserve results that can be independently reviewed.

## Getting started as a researcher

### First use: ask your Agent to install the toolkit

Give the repository address to an Agent with command execution and workspace read/write access, then send:

> Follow this repository's README and Agent installation runbook to install the complete CST Skills and MCP toolkit and initialize an independent research workspace. I use Codex. Handle dependency checks, installation, configuration, and connection verification. Confirm where I want to save research data before initializing the workspace. This request is for installation only; do not run a solver. If I need to enable configuration or reconnect in the client, explain the specific action.

The Agent performs installation and initialization. Researchers do not need to open a terminal or edit configuration files. Project trust, MCP enablement, or reconnection may require confirmation in the client interface.

### After installation: describe your research task

For example:

> Use cst-research to start a 3 GHz filtering phase shifter study. First understand the paper and geometry I provide, then establish the operating band, phase-error tolerance, insertion-loss and return-loss targets, materials, and manufacturing constraints. Plan validation of the individual resonator, coupled resonator pair, feed, individual filter branch, and integrated phase shifter. Present the research plan and CAD review first. After approval, perform bounded optimization, independently confirm the selected design, and archive the results.

Different devices require validation appropriate to their physical behavior. When requirements are incomplete, the Agent identifies missing specifications and hypotheses to test rather than assuming the design already meets the paper's requirements.

You can guide the work directly:

> Preserve the current best model. Prioritize better in-band return loss while keeping the original phase-error requirement. Limit the first round to six solver runs and report back after three consecutive trials without improvement. Show comparison plots and the worst value of each required metric after every round.

> Resume this study. Read the current best result, recent iterations, and unresolved issues before explaining the next step.

See the [English guide](docs/QUICKSTART.en.md) and the detailed [researcher conversation guide (Chinese)](docs/QUICKSTART.md).

## Installation performed by the Agent

The full procedure is available through the [Agent setup entry (Chinese)](docs/AGENT_SETUP.md) and the [Agent installation and initialization runbook (English)](skills/cst-research/references/installation.md). The Agent runs the following commands in the research workspace selected by the user.

### Requirements

- Windows.
- Python 3.13.
- Node.js and npm.
- An Agent client supporting Skills, MCP, command execution, and workspace read/write access.
- A working CST Studio Suite installation and the appropriate license for live solver runs.
- Access to Python dependency sources during the first deployment.

### 1. Install all Skills

Repository: [LeeHongji/cst-skills](https://github.com/LeeHongji/cst-skills).

For Codex:

```powershell
npx skills add LeeHongji/cst-skills --skill '*' --agent codex --copy --yes
```

For Codex and Claude Code:

```powershell
npx skills add LeeHongji/cst-skills --skill '*' --agent codex claude-code --copy --yes
```

Installation follows the [official Skills CLI](https://github.com/vercel-labs/skills), and Skill formatting follows the [Agent Skills specification](https://agentskills.io/specification).

### 2. Initialize the research workspace and MCP

Codex example:

```powershell
py -3.13 .agents/skills/cst-research/scripts/bootstrap.py --workspace . --clients codex
```

For both clients, use `--clients codex claude-code`. For Claude Code alone, the Agent locates the bootstrap script in the installed entry Skill and uses `--clients claude-code`.

Bootstrap verifies the bundled runtime and its hashes, deploys a versioned execution environment, creates the research data layout, and generates workspace-level MCP configuration. It preserves existing research data and unrelated settings. It does not start a solver or create model approvals. Software runtime and research data are stored separately.

### 3. Verify and load the services in the client

The Agent uses the workspace deployment record to check the environment and MCP protocol, then guides the researcher through opening the research workspace, enabling the client configuration, and reconnecting.

Verify these states separately:

1. All ten Skills are installed, and their bundled resources are readable.
2. The runtime, research data layout, and configuration are initialized.
3. Both MCP services pass background connection checks.
4. The current Agent conversation can actually discover and use the tools.

A passing background check does not establish that the current conversation has loaded the tools. Initialization also does not establish successful solver execution or acceptance of the human approval interaction.

## Research workflow

**Define objectives → consult theory and knowledge → validate models in stages → review CAD and approve → optimize within bounds → independently confirm → archive evidence → retain reusable lessons.**

| Stage | What the researcher receives |
|---|---|
| Requirements and theory | Explicit targets, design rationale, hypotheses, experiment budget, and stopping conditions |
| Staged validation | Models and evidence for individual elements, coupling, feeds, and the complete device |
| CAD review | A rotatable, zoomable 3D model with materials, ports, dimensions, and geometric checks |
| Approval | A genuine approval record bound to the current model revision and allowed parameter ranges |
| Screening and optimization | Candidate curves, baseline comparisons, improvements, and tradeoffs |
| Independent confirmation | A fresh confirmation solve, convergence evidence, and evaluation across the entire specified band |
| Archiving and learning | Exported curves, reopenable models, experiment records, and evidence-backed lessons |

The researcher sets objectives and makes engineering tradeoffs. The Agent creates specification records and models, invokes tools, tracks progress, and organizes evidence. Execution completion, numerical acceptance, and successful knowledge publication are reported separately.

## Skills and MCP services

### Ten Skills

Normally, ask the Agent to use `cst-research`; the entry Skill coordinates the relevant specialist Skills.

| Skill | Responsibility |
|---|---|
| cst-research | Initialization, research workflow navigation, and resuming studies |
| cst-brain-query | Retrieval of grounded knowledge and engineering experience |
| cst-vba-modeling | Parameterized models, geometry, materials, ports, and settings |
| cst-simulation-workflow | Model review, approval, guarded simulation, and evidence verification |
| cst-experiment-orchestration | Budgeted screening, optimization, and independent confirmation |
| cst-result-plotting | Exported-curve analysis, plotting, and metric comparisons |
| cst-brain-ingest | Source ingestion and provenance recording |
| cst-trace-compile | Experiment trace and evidence compilation |
| cst-strategy-learning | Extraction of engineering lessons with explicit applicability limits |
| cst-brain-lint | Knowledge structure, reference, and evidence checks |

### Two public MCP services

| Service | Capabilities |
|---|---|
| cst-function | `cst_run(request)` submits tasks; `cst_get(ref)` retrieves progress and evidence; `cst_approve(attempt, ranges)` records and validates approval |
| cst-brain | Knowledge retrieval, source ingestion, cases, strategies, and knowledge maintenance |

CAD, experiment state management, Guardian, and solver adapters are internal execution components. All production modeling and solver requests are dispatched through the same Function entry point.

## Research data organization

```text
<research-workspace>/
├─ workspace.json
├─ AGENTS.md
├─ projects/<topic-id>/
│  ├─ topic.md
│  ├─ README.md
│  └─ designs/<design-id>/
│     ├─ design.md
│     ├─ model.py
│     └─ attempts/<attempt-id>/
│        ├─ attempt.json
│        ├─ iterations.jsonl
│        └─ evidence-revisions/
├─ brain/
├─ runtime/
└─ system/
```

A workspace can hold multiple research topics that share its Brain. Each topic can contain several designs and experiment attempts; previous iterations and evidence are retained. Separate workspaces isolate execution state, approvals, and knowledge. When resuming a topic, the Agent restores context from its specifications, records, and evidence.

## Capabilities and verification scope

Supported capabilities include workspace initialization, CAD/DRC review, modeling and solving through supported adapters, parameter screening, curve analysis and comparison, approval, evidence archiving, and knowledge retention.

Eigenmode analysis, field and far-field exports, arbitrary existing-project edits, and multiport integration depend on actual adapter coverage. The Agent must check support and report gaps. An alternative validation method must not be presented as completed eigenmode analysis or verification of every solver.

Recorded validation includes 789 automated tests and a two-port lowpass case covering baseline and modified-parameter solves, independent confirmation, export, archiving, cache-free reopening, and learning checks. Outstanding real-client loading and human approval acceptance items are documented in the [validation report (Chinese)](docs/ACCEPTANCE.md). These results do not establish coverage of every CST feature.

## Documentation and license

Documentation language is indicated where relevant:

- [English guide](docs/QUICKSTART.en.md)
- [Researcher conversation guide (Chinese)](docs/QUICKSTART.md)
- [Agent setup entry (Chinese)](docs/AGENT_SETUP.md)
- [Agent installation runbook (English)](skills/cst-research/references/installation.md)
- [Microwave research stages (English)](skills/cst-research/references/research-workflow.md)
- [Research workflow and Skill responsibilities (Chinese)](docs/RESEARCH_WORKFLOW.md)
- [Architecture and data layout (Chinese)](docs/ARCHITECTURE.md)
- [Capability scope (Chinese)](docs/CAPABILITIES.md)
- [Maintenance process (Chinese)](docs/MAINTENANCE.md)
- [Validation record (Chinese)](docs/ACCEPTANCE.md)

The project's code and Skills are licensed under the [MIT License](LICENSE). Third-party components retain their respective licenses; see [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES). CST software and its proprietary SDK are not distributed with this repository.
