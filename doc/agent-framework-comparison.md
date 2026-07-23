# WorkBrain Agent 技术方案对比

## 当前结论

WorkBrain 的生产后端继续使用原生 Tool Calling。当前流程只有 Todo 和 IT 服务申请两个边界清晰的 Agent，并且组织隔离、工具参数校验、人工确认、幂等和审计已经由项目代码显式控制。现在迁移框架会增加依赖和回归风险，但不会直接增加用户价值。

本日只增加一个隔离的只读 MCP Demo，用来验证如何把 WorkBrain 服务目录提供给支持 MCP 的外部 AI Host。Demo 不接入生产 API，也不提供创建或审批能力。

## 方案对比

| 方案 | 主要解决的问题 | 优点 | 代价 | WorkBrain 当前判断 |
| --- | --- | --- | --- | --- |
| 原生 Tool Calling | 让模型按 JSON Schema 选择并调用应用函数 | 依赖少、执行边界直接、容易结合现有 RBAC 和审计 | Agent 循环、状态和 Trace 需要自己维护 | 继续作为生产方案 |
| OpenAI Agents SDK | 代码优先的 Agent、工具、handoff、guardrail、人工审批和 tracing | 常见 Agent 能力已有统一运行时 | 引入新的运行时抽象；当前项目主要使用 DeepSeek，迁移收益有限 | 暂不迁移；多 Agent 明显增加时再评估 |
| LangGraph | 长时间、有状态、可暂停和恢复的工作流编排 | 持久化、checkpoint、human-in-the-loop 和故障恢复能力强 | 图状态和节点设计增加复杂度 | 只有出现多阶段长流程或复杂审批时再采用 |
| MCP | 在 AI Host 与外部系统之间标准化暴露 Tools、Resources 和 Prompts | 工具可被不同 MCP Host 发现和调用，适合企业系统集成 | MCP 本身不负责业务权限、LLM 编排和审批安全 | 适合未来作为受控集成层，本日实现只读 Demo |

## MCP Demo 的安全边界

- 只注册 `list_active_it_services` 一个工具。
- 只返回启用的服务项目。
- 组织编号由 MCP Server 的 `WORKBRAIN_MCP_ORGANIZATION_ID` 环境变量固定，调用参数中没有组织编号。
- 工具声明为只读、非破坏、幂等、封闭世界操作。
- 不提供创建申请、批准、拒绝、用户查询或文档正文读取。
- 使用本地 stdio transport；没有新增公网端口。
- 这是学习实验，不是已完成身份认证的生产 MCP 服务。

## 运行方式

先在已有项目依赖之外安装 Demo 的可选依赖：

```bash
.venv/bin/python -m pip install -r requirements-mcp-demo.txt
```

设置组织范围并通过 stdio 启动：

```bash
WORKBRAIN_MCP_ORGANIZATION_ID=1 \
  .venv/bin/python -m experiments.mcp_service_catalog_server
```

## 采用其他方案的触发条件

- 出现多个专家 Agent，需要 handoff、统一 guardrail 和跨 Agent tracing：重新评估 Agents SDK。
- 出现跨小时或跨天运行、失败后从 checkpoint 恢复、多个暂停节点：重新评估 LangGraph。
- 需要让 IDE、ChatGPT App 或其他企业 AI Host 使用 WorkBrain 能力：继续完善 MCP，并增加正式身份认证、用户到组织的授权映射和远程传输安全。

## 官方资料

- [OpenAI Agents SDK](https://developers.openai.com/api/docs/guides/agents)
- [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
- [MCP architecture](https://modelcontextprotocol.io/docs/learn/architecture)
- [Official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
