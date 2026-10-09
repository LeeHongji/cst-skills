# 目录、接口和数据归属

分发包保存一份可维护的核心源码和十个 Skills。`scripts/build-release.py` 从源码生成入口 Skill 的 runtime.zip 与逐文件 SHA-256 清单；该归档是构建产物，不是第二份手工维护的执行内核。

| 层 | 所在位置 | 职责 |
|---|---|---|
| 规则 | 安装后的 Skills | 指导 Agent 做研究、审查和解释 |
| 执行入口 | cst-function MCP | cst_run、cst_get、cst_approve |
| 几何/执行 | runtime 软件中的 CAD、Guardian、原生适配器 | IR、DRC、受守护求解与读回 |
| 实验状态 | 工作区 system/lab | 幂等任务、锁、预算、批准和证据索引 |
| 工程知识 | 工作区 brain，独立 MCP | 检索、原始来源、案例、经验候选 |
| 持久课题 | 工作区 projects/<topic-id> | 四合同、模型、精选曲线与可重开模型 |
| 暂存运行 | 工作区 runtime | 工作副本、traces 和分级保留的求解输出 |

工作区根目录 contains workspace.json、AGENTS.md、projects/、brain/、runtime/、system/、logs/、backups/。不需要 topics/<id>/projects/<id> 双层结构，也不要求平台的 topic Git 分支。软件版本与数据通过 marker 和 registry 绑定，未知、重复、链接或越界课题拒绝执行。

公开 MCP API 保持原合同：cst_run(request)、cst_get(ref)、cst_approve(attempt,ranges)。operation 包含 audit/analyze/compare/simulate；前三者 offline，simulate 使用 screen/confirm。request_id 负责幂等。model/attempt/design/source identities 和设置构成缓存及批准边界。新建课题由初始化 CLI 完成，cst_run 不从自然语言自动创建合同。

Brain 服务公开既有十二个知识工具；CAD/Lab 不配置为额外 Agent 执行服务。维护 CLI 管理初始化、验证、证据或回收，不替代三工具求解。

每个工作区生成自己的 MCP 配置，两个客户端启动相同绑定的 Python 服务。源码导入、Python 环境和学习子进程均来自工作区部署记录绑定的版本化运行时。软件与研究数据分别管理，工作区之间保持状态和知识隔离。

配置生成使用两个服务名称 cst-function、cst-brain，并保留其他配置。生产建模与求解通过三个函数工具进入统一执行生命周期。
