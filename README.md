# CST Skills

[English](README.en.md) | 简体中文

**面向微波研究的 Agent 工具包：从理论设计、模型审查和 CST 仿真，到优化、结果归档与经验复用。**

CST Skills 提供十个研究 Skills、两个公开 MCP 服务，以及研究工作区初始化工具。研究者通过与 Agent 对话提出目标、审查模型和指导优化；Agent 按统一流程组织实验、调用 CST 并保存可复查的结果。

## 研究者如何开始

### 第一次使用：让 Agent 完成安装

将仓库地址提供给具有命令执行和工作区读写能力的 Agent，并发送：

> 请按照这个仓库的 README 和 Agent 安装规程，安装完整的 CST Skills 与 MCP，初始化一个独立研究工作区。我使用 Codex。请自行完成依赖检查、安装、配置和连接验证；研究数据保存位置先与我确认。这次只安装，不进行求解。需要我在客户端启用配置或重新连接时，告诉我具体步骤。

安装和初始化由 Agent 执行。研究者不需要打开终端或编辑配置。客户端的项目信任、MCP 启用或重新连接可能需要研究者在界面中确认。

### 安装后：直接提出研究需求

例如：

> 使用 cst-research 开展一个 3 GHz 滤波移相器课题。先理解我提供的论文和结构图，整理工作频带、移相误差、插损、回波、材料和制造要求。按照单谐振器、双谐振器耦合、馈电、单支路滤波器和移相器集成安排验证。先给我研究路线与 CAD 审查，批准后开展有界优化，最终独立确认并归档结果。

不同器件采用适合其物理问题的验证路线。指标不完整时，Agent 先整理缺项和待验证假设，不自行假定已经满足论文要求。

日常可以直接指导：

> 保留当前最佳模型，优先改善带内回波，同时维持原移相误差要求。第一轮最多求解六次，连续三次没有改善时向我汇报。每轮给我对比曲线和各项指标最差值。

> 继续这个课题。先读取当前最佳结果、最近迭代和未解决问题，再说明下一步准备做什么。

完整对话示例见 [研究者指南](docs/QUICKSTART.md)。

## Agent 如何安装

完整执行规程见 [Agent 安装入口](docs/AGENT_SETUP.md) 和 [安装与初始化规程](skills/cst-research/references/installation.md)。以下命令由 Agent 在用户选定的研究工作区中执行。

### 环境要求

- Windows。
- Python 3.13。
- Node.js 与 npm。
- 支持 Skills、MCP、命令执行和工作区读写的 Agent 客户端。
- 实际求解需要可用的 CST Studio Suite 及相应许可。
- 首次部署需要访问 Python 依赖源。

### 1. 安装全部 Skills

仓库地址：[LeeHongji/cst-skills](https://github.com/LeeHongji/cst-skills)。

Codex：

```powershell
npx skills add LeeHongji/cst-skills --skill '*' --agent codex --copy --yes
```

Codex 与 Claude Code：

```powershell
npx skills add LeeHongji/cst-skills --skill '*' --agent codex claude-code --copy --yes
```

安装方式遵循 [官方 Skills CLI](https://github.com/vercel-labs/skills)，Skill 格式遵循 [Agent Skills 规范](https://agentskills.io/specification)。

### 2. 初始化研究工作区和 MCP

Codex 示例：

```powershell
py -3.13 .agents/skills/cst-research/scripts/bootstrap.py --workspace . --clients codex
```

同时使用两种客户端时，将客户端参数改为 `--clients codex claude-code`。Claude Code 单独安装时，Agent 根据安装结果定位入口 Skill 的脚本，使用 `--clients claude-code`。

初始化工具校验附带运行时及其哈希，部署版本化运行环境，建立研究目录并生成工作区级 MCP 配置。它保留已有研究数据和无关配置，不启动求解，也不创建模型批准。软件运行环境与研究数据分别保存。

### 3. 检查并在客户端加载

Agent 根据工作区部署记录执行环境和 MCP 协议检查，再指导研究者打开研究工作区、完成客户端启用并重新连接。

安装应分别确认：

1. 十个 Skills 已安装，附带资源可读。
2. 运行时、研究目录和配置已初始化。
3. 两个 MCP 服务的后台连接检查通过。
4. 当前 Agent 对话实际能够发现并使用工具。

后台检查通过不代表当前对话已经加载工具。初始化本身也不等于模型求解或人工批准交互已验收。

## 研究流程

**明确目标 → 理论与知识检索 → 分层建模验证 → CAD 审查与批准 → 有界优化 → 独立确认 → 证据归档 → 经验沉淀。**

| 环节 | 交付给研究者的内容 |
|---|---|
| 需求与理论 | 明确的指标、设计依据、假设、实验预算和停止条件 |
| 分层验证 | 单元、耦合、馈电和完整器件各自的模型与验证结果 |
| CAD 审查 | 可旋转、缩放的三维模型，材料、端口、尺寸和几何检查 |
| 批准 | 对应当前模型版本及允许参数范围的真实批准记录 |
| 筛选与优化 | 候选曲线、基线对比、指标改善与代价 |
| 独立确认 | 新的确认求解、收敛证据和全频带指标判断 |
| 归档与学习 | 导出曲线、可重开模型、实验记录及有依据的经验 |

研究者决定目标和工程取舍；Agent 创建合同与模型、执行工具调用、跟踪进度并整理证据。求解完成、指标达标和经验成功入库分别报告。

## Skills 与 MCP

### 十个 Skills

通常只需要求 Agent 使用 `cst-research`，入口会协调相关专业 Skill。

| Skill | 职责 |
|---|---|
| cst-research | 初始化、研究流程导航和继续课题 |
| cst-brain-query | 检索有依据的知识与经验 |
| cst-vba-modeling | 参数化模型、几何、材料、端口与设置 |
| cst-simulation-workflow | 模型审查、批准、受守护仿真与结果核验 |
| cst-experiment-orchestration | 有预算的筛选、优化和独立确认 |
| cst-result-plotting | 导出曲线分析、绘图和指标比较 |
| cst-brain-ingest | 资料导入与来源记录 |
| cst-trace-compile | 实验记录与证据整理 |
| cst-strategy-learning | 提炼有适用边界的研究经验 |
| cst-brain-lint | 检查知识结构、引用与证据关系 |

### 两个公开 MCP 服务

| 服务 | 能力 |
|---|---|
| cst-function | `cst_run(request)` 发起任务；`cst_get(ref)` 查询进度与证据；`cst_approve(attempt, ranges)` 记录并校验批准 |
| cst-brain | 知识检索、资料导入、案例、策略与知识维护 |

CAD、实验状态管理、Guardian 和求解适配器属于内部执行组件。所有生产建模与求解请求通过同一个函数入口调度。

## 研究数据如何组织

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

一个工作区可容纳多个课题，共享该工作区的 Brain。每个课题可以有多个设计和实验尝试，旧迭代与证据保留；不同工作区的运行状态、批准和知识库隔离。重新打开课题时，Agent 根据合同、记录和证据恢复上下文。

## 能力与验证范围

已支持工作区初始化、CAD/DRC 审查、受支持适配器的建模求解、参数筛选、曲线分析比较、批准、归档与知识沉淀。

特征模、场图、远场、任意已有工程编辑及多端口集成等能力须以实际适配器覆盖为准。Agent 应先检查支持情况，明确缺口；不能把替代验证称为已经完成特征模或全部求解器验证。

当前验证记录包括 789 项自动测试，以及二端口低通案例的基准、改参、独立确认、导出、归档、无缓存重开和学习检查。真实客户端加载与人工确认的待验收项见 [验收报告](docs/ACCEPTANCE.md)。这些结果不代表全部 CST 功能已经覆盖。

## 文档与许可

- [研究者指南](docs/QUICKSTART.md)
- [Agent 安装入口](docs/AGENT_SETUP.md)
- [English guide](docs/QUICKSTART.en.md)
- [研究流程与 Skill 职责](docs/RESEARCH_WORKFLOW.md)
- [架构与目录](docs/ARCHITECTURE.md)
- [能力范围](docs/CAPABILITIES.md)
- [维护流程](docs/MAINTENANCE.md)
- [验证记录](docs/ACCEPTANCE.md)

代码与 Skills 采用 [MIT License](LICENSE)，第三方组件遵循各自许可，见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES)。CST 软件及其专有 SDK 不随仓库分发。
