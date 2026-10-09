# 维护、版本与软件开发流程

版本 0.1.0。安装来源为仓库地址；版本化运行时由入口 Skill 附带的构建归档部署。

源码来源记录为 docs/source-baseline.json：包含 Git 修订和实际文件哈希，覆盖已有未提交改动；docs/source-adaptations.json 说明分发版修改。纯验证辅助函数另有来源清单，历史驱动和私有课题数据不复制。

标准改动过程：明确问题及验收 → 修改源码/Skills 与文档 → 有针对性的回归 → 独立环境安装与协议测试 → 实机案例验收（涉及执行行为时）→ 更新验收报告 → 构建版本包。不要只改生成的 runtime.zip。

```powershell
& <runtime-python> -m pytest tests -q
& <runtime-python> scripts/run-core-tests.py --output <external-verification-dir>
py -3.13 scripts/build-release.py
py -3.13 scripts/verify-release.py
git add --all
py -3.13 scripts/write-source-manifest.py
git add docs/distribution-files.json
```

重新引入来源时 assemble-source.py 不覆盖已有 MCP 树；必须审查代码差异，而不是重新复制覆盖本包。prepare-public.py 是首版公开整理工具，只面向本分发源码，不能用于用户工作区。它会重新生成公开种子和部分辅助文件，维护者修改这些内容时应同步调整生成器。

运行时软件目录版本化。相同归档重复部署会核对源码哈希并复用环境；已部署源码被修改会拒绝复用。研究数据不因 Skills 更新被删除。新版本迁移需保留旧版本、无活动任务时检查 schema 兼容性并重新绑定配置；本首版不提供自动数据迁移或后台更新。

没有通过兼容迁移的旧 workspace 不应强行指向新版本。卸载 Skills 不删除研究数据或运行时；回收模型输出仍走已有 Lab GC。保留原始来源，不能删除 .lok 来绕过锁。

发布前核对：README 命令与官方 CLI 兼容、十个 Skills 可发现、归档清单与源码一致、第三方声明齐全、私有文件扫描通过、两种客户端验收有据、清洁安装报告及真实案例证据完整。发布仓库为 https://github.com/LeeHongji/cst-skills；每个版本应明确列出已通过验证及待验收能力。
