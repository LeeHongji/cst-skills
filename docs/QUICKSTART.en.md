# Independent CST research workspace

The technical commands below are intended for an Agent or operator. Researchers
can delegate installation by asking their Agent to read
[AGENT_SETUP.md](AGENT_SETUP.md). The self-contained installation runbook is
[installation.md](../skills/cst-research/references/installation.md), and the
researcher-facing conversational guide is available in [Chinese](QUICKSTART.md).
No terminal step is required in that normal researcher journey.

Trust the initialized workspace in your client and reconnect MCP. Codex skips
project-local configuration for an untrusted directory; initialization does not
alter global trust settings. Claude Code must also accept the project MCP
configuration. A protocol test does not establish client UI/elicitation acceptance.

Prerequisites: Windows, Python 3.13, Node.js/npm and an MCP-capable Agent.
Live solves need your own working CST installation. No proprietary SDK is
redistributed. First bootstrap requires Python package-index access.

In a new research directory:

```powershell
npx skills add LeeHongji/cst-skills --skill '*' --agent codex claude-code --copy
py -3.13 .agents/skills/cst-research/scripts/bootstrap.py --workspace . --topic microwave-study --title "Microwave study" --physics "Planar microstrip" --citation "User-defined research specification"
```

The source repository is [LeeHongji/cst-skills](https://github.com/LeeHongji/cst-skills). The official CLI
installs Skills; bootstrap verifies and deploys the bundled runtime separately
from them, then creates research data and project-scoped MCP configuration.
It does not start CST or create approvals. Open the WORKSPACE in your Agent,
trust it and reload MCP. Invoke cst-research to begin or resume a study.

Read system/deployment.json for the correct Python/runtime. Use the bound
cst-research.py doctor and protocol-check commands. The workspace contains
projects/<topic>/designs/<design>/attempts/<attempt>, brain, runtime and system.
Each workspace binds its own data and configuration to a versioned runtime.

The workflow is scope/theory → Brain context → staged modeling → offline CAD
and DRC → genuine artifact-bound approval → bounded screen/optimization →
fresh confirm → immutable evidence and cache-free reopen → learning receipt.
The public execution tools are cst_run, cst_get and cst_approve. Brain is a
separate MCP. Unsupported solver/field capabilities are reported explicitly.

The lowpass example is created with cst-research.py example. verify-live.py
--mode prepare audits it and verifies unapproved refusal. An actual human can
run --mode approve interactively, review the stated file and SHA-256, and type
REVIEWED for l3=13–15 mm, other parameters fixed. Agents must never supply this
response on a human's behalf. --mode verify then performs screen, variation,
fresh confirmation, exact-cache/refusal checks and offline comparison.

Uncertain retries reuse the same request ID; deliberate new experiments use
new IDs. Completed execution and passed numerical gates are separate. Check
convergence, exported curves, hashes, independent reopen and learning status.
The sample proves bounded case support, not complete CST solver coverage.

See the Agent installation runbook for setup, loading and recovery;
[maintenance](MAINTENANCE.md) documents explicit version-upgrade handling.
