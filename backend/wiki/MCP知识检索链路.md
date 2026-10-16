# MCP 知识检索链路

默认 `COURSEPILOT_KNOWLEDGE_TRANSPORT=mcp`：

```text
Agent search_knowledge_base / HTTP search
→ 查询改写、缓存、熔断
→ KnowledgeMCPClient
→ 官方 SDK ClientSession：initialize → tools/list → tools/call
→ stdio 知识服务子进程
→ 原 ChromaDB KnowledgeBase
→ 合并、去重、重排
```

API lifespan 持有一个 MCP 会话，支持并发请求，退出时关闭会话和子进程。
协议请求超时为 20 秒，工具管理层超时为 30 秒；工具错误转为管理层降级结果。
服务启动或发现工具失败会阻止启动，不静默改成本地直连。进程运行中断后返回降级结果，当前需重启 API 恢复连接，未实现自动重连。
SDK 固定为 1.9.4，使用其 v1 API；未声称使用最新 SDK。

服务提供 knowledge_search、knowledge_stats、knowledge_add。只将检索工具注册到聊天 Agent；
导入和统计供原 HTTP 管理接口使用，避免从绑定函数反查知识库实例。
导入后清空检索缓存。上传管理接口仍沿用演示系统的身份边界；stdio 服务不开放网络端口。
子进程只接收必要的运行环境和 Chroma 配置，不接收 LLM API Key。

原 mcp/ 下的代码迁到 integrations/，避免遮蔽官方 SDK。原 MCPToolManager 类名为兼容保留，
它本身仍是内部工具管理层，真正的 MCP 通信由 knowledge_client.py 和 knowledge_server.py 完成。
转班写操作、Skills、数据库校验不走 MCP。

## 运行

使用 Python 3.12，安装 `pip install -r requirements.txt`，按原方式启动 API。
API 自动启动知识服务，不需要手工另开窗口。Docker 已使用 Python 3.12，重新构建即可。
单独接入其他本地 MCP 客户端时，工作目录设为 CoursePilot，命令为
`python -m integrations.knowledge_server`，并传入 CHROMA_HOST、CHROMA_PORT 和 CHROMA_PERSIST_DIRECTORY。
该命令的 stdout 专用于协议，日志在 stderr。

如需对照旧路径，显式设置 `COURSEPILOT_KNOWLEDGE_TRANSPORT=local`；默认仍为 mcp。
知识服务需要可用的 Chroma 服务，或可用的本地数据目录和 embedding 模型缓存。

## 验证

```sh
python -m unittest discover -s tests -p test_mcp_knowledge.py -v
python -m unittest discover -s tests -v
```

协议测试启动真实 MCP 子进程，使用确定性的内存检索后端，覆盖工具发现、查询、导入、统计、
并发请求、参数拒绝、工具异常、超时清理和 Agent RAG 适配层。
这些测试不下载 embedding 模型，不调用真实 LLM，也不证明完整 Chroma/Redis/LLM 联调成功。

实现参考：[官方 SDK v1.9.4](https://github.com/modelcontextprotocol/python-sdk/tree/v1.9.4)。

## 对应源码与当前业务范围

客户端为 `integrations/knowledge_client.py`，服务端为 `integrations/knowledge_server.py`，传输选择为 `integrations/knowledge_backend.py`，检索治理为 `integrations/tool_manager.py`。共享工具由 `agents/tools.py` 注册。

当前 `/chat` 通过 Agent 工具按需检索，不预先执行 `_build_knowledge_context()`。真实后端 full 联调结果见[评测说明](真实模型联调与评测.md)，MCP 协议单测与全链路报告需分别解读。
