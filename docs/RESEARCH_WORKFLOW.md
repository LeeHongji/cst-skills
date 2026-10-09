# 研究流程和 Skill 职责

| Skill | 负责什么 | 不负责什么 |
|---|---|---|
| cst-research | 初始化、流程导航、继续课题、收尾 | 第二套执行器或批准权限 |
| cst-brain-query | 检索有证据的上下文 | 自动相信检索到的经验 |
| cst-vba-modeling | 确定性模型、IR、材料/端口/设置适配 | 绕过 facade 直接写 CST |
| cst-simulation-workflow | 审查、批准、三工具执行、证据核验 | 任意 GUI/VBA 控制 |
| cst-experiment-orchestration | 候选、预算、停止条件、优化与确认 | 重复管理 Lab 生命周期 |
| cst-result-plotting | 导出曲线分析、绘图和指标解释 | 新求解或冒充实机结果 |
| cst-brain-ingest | 原始资料捕获及来源哈希 | 将摘要直接晋升为事实 |
| cst-trace-compile | 案例、trace 和证据修复/导入 | 重复编译已发布的 Function job |
| cst-strategy-learning | 有边界的经验与策略候选 | 将一个案例推广为通用定律 |
| cst-brain-lint | 知识结构、链接与证据检查 | 自动认定物理正确 |

课题先锁定目标、来源、频率与单位、材料、端口和相位参考面、验收线、可调参数、实验预算与停止条件。知识检索区分 validated、case-specific、candidate 和缺口。公开种子是 seed，不是已仿真的器件事实。

滤波器研究通常从单谐振器出发，继而分析双谐振器耦合、馈电外部耦合、完整滤波器，再集成移相器或其他器件。每一步写清楚回答什么问题、保留什么曲线和证据。不相关的阶段可以有依据地跳过；缺失的特征模适配需要明确报告，不应无限阻塞已支持的频域验证。

几何源通过 `build(overrides=None)` 返回 IR。离线 audit 生成真实 WebGL CAD 页、DRC 和封存证据。批准绑定当前文件、拓扑、模型和允许范围。筛选逐点调用 cst_run，每个候选保留成功、失败或阻断事实。预算耗尽、停滞或重大工程取舍需要用户指导。

最终候选必须 fresh confirm，检验真实收敛、全带指标、导出、设置与几何核对，以及独立无 Result 缓存重开。只要某个必需环节缺证，就应报告未完成；可接受的工程容差必须由用户明确决定，不能改变指标后宣称原目标通过。

仿真事实写入 append-only iterations.jsonl。永久证据在 topic package；runtime 依既有 retention.py 分类，不能一概删除。GC 仍默认 dry-run，执行需显式确认并保留清单，不能删除锁来强行回收。

最后核对 job.learning。发表失败与仿真结果分开报告，修复不重写历史。新经验先进 inbox，经独立证据或明确人工晋升后才改变知识状态。每次结束更新课题 README 的最佳验证结果、当前问题和下一步。
