# Microwave research workflow / 微波研究流程

| Stage | Deliverable | Skills / tools |
|---|---|---|
| Scope and synthesis | sources, theory, targets, bands, references, budget | brain-query, topic/design contracts |
| Single element | resonance/field expectations and parameter sensitivity | vba-modeling, simulation-workflow |
| Coupled pair | mode splitting/coupling vs spacing when supported | same guarded facade |
| Feed coupon | external coupling, port planes and mismatch | same guarded facade |
| Filter branch | poles, pointwise return/insertion loss and bandwidth | experiment-orchestration, result-plotting |
| Integrated device | differential phase, imbalance, isolation if applicable | compare, screen and confirm |
| Durable result | exported curves, settings, IR, DRC, logs, clean CST, hashes | cst_get evidence, learning receipt |
| Reuse | source capture, cases, candidates, lint | brain-ingest, trace-compile, strategy-learning, brain-lint |

Use stages that answer the actual research question. Explain evidence-backed
skips; do not force filter synthesis onto unrelated devices or stall forever
at one mode-reading feature. Full-wave result confirmation remains required.
This release does not claim general eigenmode/field/far-field export support.

Every live candidate uses the same three-tool lifecycle. Reuse request_id only
for an uncertain retry of the exact request; a deliberate new iteration gets a
new ID. An offline audit is not a solve. A screen cache hit cites its original
evidence. Confirm always performs a fresh guarded solve.

Approval is bound to the actual review artifact and allowed ranges. Topology,
model or settings changes may invalidate approval. No standing grant is seeded.
Unlisted independent parameters stay fixed. Copy sources; preserve all failed
attempts and append-only history. Never terminate unrelated CST processes.

Complex S magnitudes are 20*log10(abs(S)); phase comparisons require explicit
port ordering and identical reference planes. Mesh settings must remain
comparable before interpreting a parameter change as physical sensitivity.
Report acceptance and learning publication separately from job completion.
