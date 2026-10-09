# Agent installation runbook / Agent 安装与初始化规程

Audience: an Agent with workspace read/write access and command execution. Execute technical steps yourself. Ask the researcher only for missing decisions or unavoidable client UI actions; do not hand them shell instructions as the normal experience.

This reference ships with copied Skills. Read it from the repository before installation or from the installed `cst-research` Skill afterward.

## 1. Resolve inputs and scope

Repository: https://github.com/LeeHongji/cst-skills. Record the source revision, chosen research workspace and requested clients (`codex`, `claude-code`, or both).

If the workspace is not given, ask where to save research data. Keep research data separate from the installation source. If no topic is requested, initialize without topic arguments. Create the topic later when title, physics and source are known.

Setup includes the necessary Skill copies, versioned runtime and workspace configuration. It does not authorize solver runs, approvals, system-wide software installation, publication or migration. Honor existing session authorization; do not ask twice for routine setup already requested.

## 2. Inspect source, destination and prerequisites

- Read applicable instructions, root README if available, and entry Skill. Check `assets/runtime.zip` and `assets/runtime-release.json`. Use bootstrap's validation; do not disable checksums or edit its manifest to hide a failure.
- Require Windows and Python **3.13**. Discover `py`, `python`, `node`, `npm`, `npx` using host tools and confirm actual versions. A command name or another Python version is insufficient. First installation requires Python package-index access.
- Discover client and CST availability separately. CST is needed for live solves, not workspace initialization or offline CAD. Use supported executable/API discovery.
- For missing dependencies, report the exact component/version and use already-authorized installation methods if available. Do not silently install global applications. Deploy Python dependencies through this repository's pinned runtime environment. Missing Claude Code does not block Codex-only installation.
- Inspect existing deployment, Skill folders and client configs. Reuse a valid same-version deployment. Do not overwrite user-modified Skills or switch an active workspace to a new runtime as routine reinstall. Preserve conflicts and explain them before replacement.

Run the commands below in the **research workspace**, not the source repository. Prefer structured subprocess arguments, explicitly set cwd, and correctly quote paths with spaces/Chinese characters. Set Python child-process environment `PYTHONUTF8=1` when capturing Chinese-path output. Shell examples assume controlled literals. Never interpolate untrusted strings into executable shell syntax.

## 3. Copy all ten Skills

For Codex only:

```powershell
npx skills add LeeHongji/cst-skills --skill '*' --agent codex --copy --yes
```

For both requested clients:

```powershell
npx skills add LeeHongji/cst-skills --skill '*' --agent codex claude-code --copy --yes
```

A checked source directory is also supported by the official CLI. Create the destination if needed. `--yes` accepts installation prompts, not CAD approval or client trust.

Inspect CLI output and installed files. Expected Skills:

`cst-research`, `cst-brain-query`, `cst-brain-ingest`, `cst-brain-lint`, `cst-vba-modeling`, `cst-simulation-workflow`, `cst-experiment-orchestration`, `cst-result-plotting`, `cst-trace-compile`, `cst-strategy-learning`.

Codex normally uses workspace `.agents/skills/`; Claude Code normally uses `.claude/skills/`. Resolve the actual installed entry path from output/files instead of assuming the Codex path for every client. Check `SKILL.md`, LICENSEs, relative references, entry `scripts/bootstrap.py` and `assets/`. Do not assemble core source piecemeal or expose legacy native/CAD/Lab MCPs as alternate write services.

## 4. Bootstrap from the installed Skill

Run the actual installed script with Python 3.13. Codex empty-workspace example:

```powershell
py -3.13 ".agents/skills/cst-research/scripts/bootstrap.py" --workspace . --clients codex
```

When the user has specified a topic, use real metadata:

```powershell
py -3.13 ".agents/skills/cst-research/scripts/bootstrap.py" --workspace . --clients codex --topic microwave-study --title "微波研究" --physics "平面微带电路" --citation "用户定义的研究需求"
```

Claude-only uses its installed path and `--clients claude-code`; both use `--clients codex claude-code`. If `py` is absent but a verified Python 3.13 executable is available, use it. Bootstrap chooses a versioned per-user runtime directory by default. Optional `--runtime-home` must be outside the workspace tree.

Bootstrap validates the archive, deploys a versioned runtime, creates a venv, installs pinned dependencies/four components, runs `pip check`, and initializes data. It does not install CST, solve or grant approval. Use its locking/recovery; do not delete lock files or markers to make it pass.

Check `workspace.json`, `AGENTS.md`, `system/deployment.json`, registry and Brain. Requested configs are `.codex/config.toml` and/or `.mcp.json`. They preserve unrelated settings and create rollback receipts. Public services are `cst-function` and `cst-brain`, bound to this workspace. All runtime scripts/subprocesses must resolve from the deployment record.

Repeated topic initialization needs matching title/physics/source. Never force different metadata over an existing topic. Empty project registry is valid when no topic was requested. CLI Skill installation alone is not MCP runtime deployment.

## 5. Check deployment and protocol without solving

Read `system/deployment.json`. Use its Python/runtime:

```powershell
$deployment = Get-Content ./system/deployment.json -Raw | ConvertFrom-Json
& $deployment.python (Join-Path $deployment.runtime_root 'scripts/cst-research.py') doctor --workspace .
& $deployment.python (Join-Path $deployment.runtime_root 'scripts/cst-research.py') protocol-check --workspace .
```

Inspect doctor checks, contracts and Brain lint. CST discovery is a separate field: doctor passing does not prove a working live solver. Protocol execution tools must be exactly `cst_run`, `cst_get`, `cst_approve`; Brain queries must use this workspace. These subprocess checks prove background connectivity, **not availability in the current Agent conversation**.

## 6. Load in the actual Agent client

Tell the user to open the research workspace root, complete project trust/MCP enable prompts and reconnect or reopen the conversation if needed. Give the real path and only the next necessary UI action; do not invent button names. Do not change global trust to bypass this step. A freshly installed MCP generally cannot be added to an already-fixed active tool catalog by writing config alone.

After reload, inspect the current conversation's exposed tools. Use its actual Brain search for a read-only query. If there is an existing valid job, inspect it with `cst_get`; in an empty workspace, do not submit a fake job merely to test the getter. Execution acceptance can occur during the first requested model audit. Report visible tool names. If absent, check disabled project config, wrong workspace, stale conversation, startup logs or missing dependencies. Never bypass the facade through direct native calls.

Setup does not test `cst_approve` automatically. Approval needs a real audit and real human decision. Use supported client elicitation in ordinary research. A scoped delegation can be recorded only through the existing authorized signing mechanism with accurate model/range binding and attribution. Do not create a signer/standing grant just because a chat reply says “continue.” If client elicitation is unavailable and no authorized valid delegation exists, stop before solving and name the limitation. Never type terminal `REVIEWED` for the user.

`verify-live.py` is an optional maintainer/operator acceptance fallback, not a mandatory non-terminal researcher step. `prepare` audits; `verify` requires valid approval. A live test must be separately within the requested scope.

## 7. Handoff and future topics

Report independently: (1) Skill files copied, (2) runtime/data initialized, (3) background protocol checked, (4) actual client tools loaded or waiting for a specific action. Also state live CST availability and untested approval interaction. Open/link the researcher guide if available or explain the next prompt using [researcher-dialogue.md](researcher-dialogue.md).

The researcher should now be able to say “使用 cst-research，新建一个微波课题，先读论文、整理指标和路线，再给我 CAD 审查。” Do not ask them to author `gates.json`, model IR or contracts.

In an already-bound workspace, new topics use the deployed CLI:

```powershell
& $deployment.python (Join-Path $deployment.runtime_root 'scripts/cst-research.py') init --workspace . --clients codex --topic another-study --title "另一课题" --physics "平面微带电路" --citation "用户定义的研究需求"
```

Match existing topic metadata exactly on resume; read contracts/history instead of reinitializing with guessed values. Create designs/attempts with the same bound CLI. Configure only the user's requested clients.

## 8. Recovery

- Source unavailable: report the actual repository access or source-validation failure and resolve that installation source before continuing.
- Interrupted install: inspect state and retry the same bootstrap. Do not clear user data, version directories or process-owned locks.
- Topic/name conflict: retain the original and ask whether a distinct design/topic is intended; never overwrite evidence.
- Config conflict: inspect backup receipt/user edits. `restore-config` rejects edits made after backup; do not bypass it.
- Client not enabled: report “waiting for client loading,” not “ready for live research.”
- Solver/unsupported feature failure: retain diagnostics and report separately from installation; do not broaden capability claims.

## Official sources

[Skills CLI](https://github.com/vercel-labs/skills) · [Agent Skills](https://agentskills.io/specification) · [Codex configuration](https://learn.chatgpt.com/docs/config-file/config-basic) · [Claude Code MCP](https://code.claude.com/docs/en/mcp). For changing client behavior, consult current official docs and observed config rather than guessing UI flows.
