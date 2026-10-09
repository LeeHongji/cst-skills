"""Prepare portable instructions, public seed knowledge and source change receipts."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def write(name,content):
    path=ROOT/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content.strip()+'\n',encoding='utf-8')


def main():
    p=argparse.ArgumentParser();p.add_argument('--portable',type=Path,required=True);args=p.parse_args()
    requirements=(args.portable/'requirements-lock.txt').read_text().replace('pytest==9.1.1','pytest==8.4.2')
    write('requirements-lock.txt',requirements)
    write('requirements-dev.txt','-r requirements-lock.txt')
    helpers=[('prepare_resonator.py',['analytic'],'import math'),
             ('verify_resonator_physics.py',['notch','compare'],'import csv, math\nfrom pathlib import Path'),
             ('verify_fourport_results.py',['crosscheck_csv'],'import csv, math\nfrom pathlib import Path'),
             ('verify_brain_manifests.py',['validate'],'import json, jsonschema'),
             ('prepare_visual_cases.py',['primitives','multilayer','failed_spacing'],'from cst_cad.dsl import ModelBuilder')]
    helper_origins=[]
    for filename,names,imports in helpers:
        original=args.portable/'scripts/validation'/filename;content=original.read_text(encoding='utf-8')
        functions=[ast.get_source_segment(content,node) for node in ast.parse(content).body if isinstance(node,ast.FunctionDef) and node.name in names]
        if len(functions)!=len(names):raise ValueError('Required neutral verification helper missing')
        write('scripts/validation/'+filename,'"""Public pure verification helpers; historical drivers and data are excluded."""\n'+imports+'\n\n'+'\n\n'.join(functions))
        helper_origins.append(dict(path='scripts/validation/'+filename,source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),retained_functions=names))
    original=args.portable/'scripts/plot-cst-filter-response.py';content=original.read_text(encoding='utf-8')
    function=next(ast.get_source_segment(content,node) for node in ast.parse(content).body if isinstance(node,ast.FunctionDef) and node.name=='sample_window')
    write('scripts/validation/sample_window.py','"""Retained float32 band-edge verification helper; no live CST reader."""\nimport numpy as np\n\n'+function)
    helper_origins.append(dict(path='scripts/validation/sample_window.py',source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),retained_functions=['sample_window']))
    write('docs/verification-helper-origins.json',json.dumps(helper_origins,indent=2))
    write('MCP/CST-CAD/tests/test_visual_cases.py','''from pathlib import Path
import sys
import pytest
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT/'scripts/validation'),str(ROOT/'MCP/CST-CAD/src')]
from cst_cad import drc,ir
from prepare_visual_cases import primitives,multilayer,failed_spacing

def test_geometric_visual_controls_include_a_real_negative_case():
    for doc in (primitives(),multilayer(),failed_spacing()):
        assert ir.validate(doc)==[]
    assert drc.run(primitives())['status']=='pass'
    assert drc.run(multilayer())['status']=='pass'
    failure=drc.run(failed_spacing())
    assert failure['status']=='fail'
    assert failure['checks'][0]['measured']==pytest.approx(.1)
    assert failure['checks'][0]['violations']
''')
    write('LICENSE','''MIT License

Copyright (c) 2026 CST Skills contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.''')
    write('THIRD_PARTY_NOTICES','''# Third-party notices

The CST Automation-derived code and original Skills are distributed under the
root MIT license. Source byte provenance is in docs/source-baseline.json.

- cst-runtime-cli: Copyright (c) 2026 bbl21, MIT.
  Source: https://github.com/bbl21/cst-runtime-cli
  Preserved license: MCP/CST/vendor/cst-runtime-cli/LICENSE.
  Only necessary runtime scripts are included; these are internal dependencies.
- Three.js: Copyright 2010-2025 three.js authors, MIT.
  Source: https://github.com/mrdoob/three.js
  Preserved license: MCP/CST-CAD/src/cst_cad/assets/THREE-LICENSE.txt.
- Python packages are installed separately from requirements-lock.txt and retain
  their respective licenses; Python and Node runtimes are not redistributed.
- CST Studio Suite, its binaries, proprietary Python APIs and licenses are not
  included. Users supply their own working CST installation.

No private papers, historical research packages, approval keys or databases
are part of this release. The lowpass example is an internally specified
verification fixture; it is not a reproduced paper figure or paper result.''')
    write('MCP/CST/README.md','''# CST execution core

This component is an internal execution dependency of the CST Skills package.
Install and use the distribution from its root README.md and docs/QUICKSTART.md.
The public Agent server is agent_mcp_server.py and exposes exactly cst_run,
cst_get and cst_approve. mcp_server.py and the vendored CLI are internal/legacy
compatibility interfaces, not alternative production Agent write paths.
Configure this server for one initialized research workspace; never restore
historical native-tool configuration to bypass ownership or approval checks.
''')
    write('MCP/CST/README.zh-CN.md','''# CST 执行内核

本模块是 CST Skills 分发包的内部执行依赖。安装及使用说明见分发包根级
README.md 和 docs/QUICKSTART.md。公开 Agent 服务为 agent_mcp_server.py，
只提供 cst_run、cst_get、cst_approve。旧原生 MCP 和 vendor CLI 保留为内部
兼容实现，不是另一条生产写入路径。每个部署明确绑定研究工作区。
''')
    write('.gitignore',''' .venv/
__pycache__/
*.pyc
*.egg-info/
.pytest_cache/
.env
.codex/config.toml
.mcp.json
verification/local/
dist/
build/
node_modules/
reports/
verification workspace/
cst_runs/
runtime/
system/
projects/
output/
tmp/
'''.replace(' .venv/','.venv/'))
    write('AGENTS.md','''# CST Skills distribution

This repository distributes the verified CST Automation core; do not build a
second executor. Production Agent writes use only cst_run/cst_get/cst_approve.
Brain is a separate MCP; CAD/Lab/Guardian and the vendored runtime are internal.
Public Skill sources live in skills/. Runtime releases are generated from MCP/,
brain/, examples/ and the maintained scripts by scripts/build-release.py.
Never hand-edit the generated archive or change finalized evidence.
Keep origin hashes in docs/source-baseline.json and adaptations in
docs/source-adaptations.json. Do not copy real user data, papers, credentials,
approval records or solver caches into this repository.
Run tests and installation verification before rebuilding a final release.
Research source files and original repositories are not migration targets.
''')
    provider=('Provider: use the separate `cst-brain` MCP configured in the current research workspace. '
              'Its tools read and curate that workspace Brain and do not control CST. '
              'If unavailable, use the runtime Python and root recorded in `system/deployment.json` '
              'to run `python -m cst_brain --brain-root <workspace>/brain`, or report the unavailable service. '
              'Do not invent a tool call.')
    for skill in (ROOT/'skills').iterdir():
        path=skill/'SKILL.md'
        if not path.exists():continue
        text=path.read_text(encoding='utf-8')
        if '\nlicense:' not in text.split('---',2)[1]:text=text.replace('\n---\n','\nlicense: MIT\n---\n',1)
        lines=text.splitlines()
        lines=[provider if line.startswith('Provider:') else line for line in lines]
        text='\n'.join(lines)+'\n'
        text=text.replace('the facade resolves the topic\'s registered worktree','the facade resolves the topic in the current workspace registry')
        text=text.replace('(`data/runtime` in CSTLab; `cst_runs` in legacy mode)','(`<workspace>/runtime` in this distribution)')
        text=text.replace('under cst_runs.','under the configured runtime root.')
        text=text.replace('Run the repository harness check when schemas, MCP code, or Skills changed.',
            'Run the bound workspace doctor after data changes. Maintainers run the distribution and component tests after schemas, MCP code, or Skills change; no legacy repository harness is required.')
        text=text.replace('`scripts/repair-function-learning.py --job <ref> --apply`','`<runtime>/scripts/repair-function-learning.py --workspace <workspace> --job <ref> --apply`')
        if skill.name=='cst-result-plotting' and '`scripts/plot-cst-filter-response.py`' in text:
            text=text[:text.index('`scripts/plot-cst-filter-response.py`')]+'Use `<runtime>/scripts/plot-review.py --source <export.s2p> --output <new-review-dir>` for derived plots. This reads exported data only. Do not alter finalized Function evidence; evaluate gates through the facade.\n'
        path.write_text(text,encoding='utf-8')
    for path in (ROOT/'skills').glob('*/references/*.md'):
        text=path.read_text(encoding='utf-8')
        text=text.replace('`cst_runs/<experiment>`','the workspace `runtime/` directory managed by the facade')
        text=text.replace('`cst_runs/<short_task>_<YYYYMMDD>`','workspace `runtime/`, allocated by the facade')
        if path.name in {'parameter-policy.md','templates.md'} and 'Engineering guidance only' not in text:
            lines=text.splitlines()
            lines[1:1]=['','Engineering guidance only: verify actual facade/adapter coverage before selecting a solver, monitor or output. Eigenmode, far-field and arbitrary existing-project editing are not implied capabilities of this release. Unsupported requests must stop or use a supported, explicitly stated alternative.','']
            text='\n'.join(lines)+'\n'
        path.write_text(text,encoding='utf-8')
    reference=ROOT/'skills/cst-simulation-workflow/references/workflow.md'
    reference.write_text(reference.read_text().replace('(or a legacy worktree in compatibility mode)','from this workspace\'s system/projects.json'),encoding='utf-8')
    write('skills/cst-research/SKILL.md','''---
name: cst-research
description: Initialize and resume an independent CST microwave research workspace, route modeling, CAD review, bounded simulation and optimization, and preserve results and reusable knowledge through the verified CST Automation Skills and MCP services.
license: MIT
metadata:
  version: "0.1.0"
  compatibility: Windows, Python 3.13 and a working CST installation for live solves. MCP-capable Agent required. Install all ten Skills for the complete research workflow.
---

# CST Research / CST 研究入口

Use this entry for a new study or to resume one. It coordinates the existing
nine professional Skills; it is not another solver or approval authority.

## First use

Read [installation.md](references/installation.md). Run this Skill's
`scripts/bootstrap.py` with Python 3.13 and an explicit user-chosen workspace.
The bundled, checksum-verified runtime is deployed separately from installed
Skills. Initialization does not launch CST or create approvals.
Do not search the user's machine for an old cst-automation checkout as fallback.

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
''')
    write('skills/cst-research/references/installation.md','''# Installation / 安装

Install the complete suite in a new research workspace with the official CLI:

```powershell
npx skills add "C:/CST skills" --skill '*' --agent codex claude-code --copy
py -3.13 .agents/skills/cst-research/scripts/bootstrap.py --workspace . --topic microwave-study --title "Microwave study" --physics "Planar microstrip" --citation "User-defined research specification"
```

Use the installed Skill's actual path if your client uses a different location.
Replace the local source with the public repository URL after publication.
The repository includes all necessary runtime source; no original CST
Automation or CSTLab checkout is required. Python dependencies require package
index access on first install. The optional --runtime-home chooses the versioned
runtime location; its default is LOCALAPPDATA/CSTSkills/runtimes.

Open the WORKSPACE in Codex/Claude Code, trust it and reconnect/restart MCP.
Codex config is workspace/.codex/config.toml; Claude config is workspace/.mcp.json.
Initialization preserves unrelated configuration and creates rollback receipts.
Use only the runtime Python/root listed in system/deployment.json thereafter.

```powershell
& <runtime-python> <runtime>/scripts/cst-research.py doctor --workspace <workspace>
& <runtime-python> <runtime>/scripts/cst-research.py protocol-check --workspace <workspace>
```

These checks do not solve a model or substitute for real client review/load
verification. Bootstrap never installs CST, inspects DLL company names, grants
approval, disables client trust checks or modifies global Agent configuration.

Official sources: https://github.com/vercel-labs/skills and
https://agentskills.io/specification.
''')
    write('skills/cst-research/references/research-workflow.md','''# Microwave research workflow / 微波研究流程

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
''')
    # Public, self-authored seed policies: no historical papers, outcomes or keys.
    seeds=[('execution-boundary','执行与证据边界 / Execution and evidence',
        'Rules live in Skills, facts in Brain, experiment state in Lab and events in traces. Production CST writes use cst_run/cst_get/cst_approve. Save before solve, export Touchstone/CSV, retain logs, hash evidence and verify independent cache-free reopen. This seed documents software policy; it is not simulated device evidence.'),
        ('microwave-research-stages','微波研究分层 / Microwave research stages',
        'A filter study can progress from an isolated resonator, pair coupling and feed validation to a filter and integrated phase shifter. Select relevant stages and quantify their conclusions. Eigenmode and field exports require an actual supported adapter. These are planning guidelines, not universal proof of a design.'),
        ('complex-s-parameters','复数 S 参数与验收 / Complex S parameters',
        'Compute magnitude with 20*log10(abs(S)). Keep frequency units, port order and phase references explicit. Gate evaluation includes both band edges and every in-band sample; never extrapolate. A good plot or successful tool call does not establish numerical acceptance.')]
    for identity,title,body in seeds:
        write('brain/wiki/foundations/'+identity+'.md',f'''---
id: seed-{identity}
type: concept
status: seed
title: "{title}"
created: '2026-10-09'
updated: '2026-10-09'
sources: []
evidence: []
tags: [public-seed]
---

{body}

Source: CST Automation procedures shipped under MIT in this distribution.
Versioned implementation provenance: docs/source-baseline.json.
''')
    for name,title,body in [('index','CST Brain Index','# CST Brain Index\n\n## Foundations\n\n## Cases\n\n## Strategies\n\n## Sources'),('log','CST Brain Operation Log','# Operation Log')]:
        write('brain/meta/'+name+'.md',f'''---
id: meta-{name}
type: meta
status: seed
title: {title}
created: '2026-10-09'
updated: '2026-10-09'
tags: [meta/{name}]
---

{body}
''')
    write('brain/raw/manifest.json',json.dumps(dict(schema_version=1,sources={},trace_snapshots={}),indent=2))
    write('brain/AGENTS.md','''# Public Brain

Seed pages describe software policy and research guidance, not simulated
measurements. New source material is ingested unchanged with hashes. Record
case facts and bounded lessons; candidates stay in inbox until evidence-backed
promotion. No hidden chain-of-thought. Use brain-query before CST decisions and
brain-lint after ingest/compile/curation. Never upgrade seed/candidate status
merely because it was shipped in a release.
''')
    write('examples/lowpass/README.md','''# Stepped-impedance lowpass / 阶梯阻抗低通

Internally specified two-port verification fixture, not a paper reproduction.
The source preserves the established neutral CST Automation model unchanged.
Length mm, frequency GHz; RO4003C er=3.55, h=0.813 mm, copper 0.035 mm.
TD/Hex solver, frequency 0–7.2 GHz, energy criterion -40 dB.
Acceptance: S21 > -1 dB throughout 0.1–1.5 GHz; S21 < -10 dB throughout
3.6–4.2 GHz. Adjustable parameter l3, proposed review range 13–15 mm; all
other dimensions fixed. These targets do not claim rigorous filter synthesis.

Create it with the bound runtime cst-research.py example --workspace ...
--topic ...; audit with verify-live.py --mode prepare. No approval is included.
''')
    from validation.public_contract_fixture import generate
    generate(ROOT)
    # Capture changes relative to the imported source snapshot.
    baseline=json.loads((ROOT/'docs/source-baseline.json').read_text())
    changed=[]
    for item in baseline['files']:
        path=ROOT/item['path'];current=hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if current!=item['portable_sha256']:
            reason='Portable Skill instructions and public licensing' if item['path'].startswith('skills/') else 'Packaging adaptation; see maintained source diff and tests'
            if 'test_repository_trial_scripts' in item['path']:reason='Historical direct-write scripts are not distributed; their three source-shape tests are excluded'
            if 'test_steps12_verification' in item['path']:reason='Replace personal historical evidence check with public fixture-equivalence test'
            changed.append(dict(path=item['path'],baseline_sha256=item['portable_sha256'],distribution_sha256=current,reason=reason))
    write('docs/source-adaptations.json',json.dumps(dict(schema_version=1,changes=changed),indent=2))
    # CLI copy installation carries only each Skill directory, so each copied
    # procedure/bootstrap must retain the full permission and copyright notice.
    for skill in (ROOT/'skills').iterdir():
        if (skill/'SKILL.md').is_file():
            (skill/'LICENSE').write_bytes((ROOT/'LICENSE').read_bytes())
    print(json.dumps(dict(seed_pages=len(seeds),source_adaptations=len(changed))))


if __name__=='__main__':main()
