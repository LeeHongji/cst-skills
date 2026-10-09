# Research through conversation / 研究者对话流程

Read when onboarding a researcher or presenting research progress. Researchers should not have to write shell commands, JSON contracts, IR, MCP calls or internal identifiers. Execute mechanics through the bound runtime and Skills; expose engineering decisions, models, results and necessary client actions.

## Start from the problem

Translate the user's paper, diagram and objectives into a topic/design/attempt. Retrieve Brain evidence and inspect references; ask only for consequential missing requirements. Present a short proposal with quantified bands/gates, units, stackup, manufacturing limits, port/phase references, solver capability, tunables, budget and stopping conditions. Do not infer numerical tolerances from “match the paper.” Preserve uncertainty and cite sources.

Example researcher request:

> 使用 cst-research，研究一种 3 GHz 方形开路谐振器滤波移相器。先读附件论文，按原指标列出设计与验证路线，然后生成模型给我审查。

Explain the next engineering question and reviewable artifact. Create contracts and deterministic model yourself. Use the deployed CLI's `design` and `attempt` scaffold APIs, implement `build(overrides=None)`, and submit audit via `cst_run`. File schemas are internal bookkeeping, not forms the researcher must complete.

## Stage the microwave evidence

Use [research-workflow.md](research-workflow.md) for technical stages. Single resonance, coupling and feed verification should answer specific questions before a complete filter/integrated phase shifter. Check eigenmode coverage before promising it; distinguish an unsupported eigenmode from a supported frequency-domain resonance test. For phase shifters establish usable filter branches first, then optimize bandwidth/phase slope with shared port reference planes. Retain a useful baseline when goals conflict. Do not impose filter synthesis on unrelated devices.

## Make CAD review usable

Open/link the actual WebGL audit revision and explain stackup, conductors, ground, feed gaps, bends and ports. Show dimensions and fixed versus adjustable parameters. If the researcher spots an intrusion or poor bend, inspect and revise the model, then re-audit. DRC success is geometric evidence, not EM acceptance.

Before approval present artifact identity, allowed ranges, fixed conditions and run budget in readable form. Use `cst_approve` for supported human elicitation or an already-authorized, current-workspace signed delegation. Read the returned record; no assumed approval. Follow [installation.md](installation.md) for unsupported client interaction. Changes to topology/model/settings may invalidate approval; enforce the real binding, not the last conversational “yes.”

## Optimize with visible decisions

“Keep phase flat and improve filter response” becomes simultaneous acceptance gates, not permission to weaken one target. Choose bounded screen candidates, preserve every outcome, query with `cst_get`, plot retained evidence and compare against the best validated baseline. Explain parameter changes and physical rationale briefly. Reports give stage, completed/new/cache solves, current best, failed metrics, budget and next decision. Publish available plots before an entire sweep finishes when requested.

Stop adding candidates when the user asks, budget ends or the agreed stagnation criterion is met. Distinguish halting submissions from cancelling an active solve; report actual cancellation support and preserve evidence. Never terminate unrelated CST processes. This package is not a task-board UI or a background scheduler and does not guarantee operation after client shutdown.

## Deliver and resume

A good-result screen is followed by fresh confirm. Report convergence, pointwise full-band gates, curve exports, clean project/companion reopen and evidence hashes. Show baseline/candidate/confirm plots and worst values with pass/fail. Exported evidence must survive cache removal; do not claim a saved `.cst` contains portable solver results.

Check job.learning independently. Preserve publication failures and repair evidence instead of calling solver success “learning complete.” Use knowledge Skills for source ingestion, cases, strategies and lint; candidates stay case-specific until justified promotion.

Update topic README with best validated model, remaining issues and next action. On “continue,” read contracts/evidence/history/Brain, summarize status and resume. Do not reinitialize with guessed metadata or overwrite the prior best. A new topic gets a separate package in the registry; shared Brain does not transfer approvals.
