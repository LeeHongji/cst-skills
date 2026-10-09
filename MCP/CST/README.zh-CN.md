# CST 执行内核

本模块是 CST Skills 分发包的内部执行依赖。安装及使用说明见分发包根级
README.md 和 docs/QUICKSTART.md。公开 Agent 服务为 agent_mcp_server.py，
只提供 cst_run、cst_get、cst_approve。旧原生 MCP 和 vendor CLI 保留为内部
兼容实现，不是另一条生产写入路径。每个部署明确绑定研究工作区。
