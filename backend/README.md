# CityMate 后端

统一运行入口为 `citymate.app:app`，后台消费者为 `python -m citymate.worker`。所有业务代码位于 `citymate/`，不再并存旧教育版 API。

## 开发

使用 Python 3.12，在项目虚拟环境中安装 `requirements-dev.txt`。手动开发可参考 [根目录环境示例](../.env.example)，将本地配置保存在不提交的 `.env` 中。`requirements-ai.txt` 用于 Chroma/MCP 可选分支；2026-10-21 已完成真实嵌入、MCP 子进程与模型聊天链路验证，仍需显式启用。首次安装可能编译本地依赖和下载嵌入模型，安装依赖不等于检索质量达标。结果见 [知识检索联调报告](../docs/知识检索联调报告.md)。

可选联调（在本目录使用项目虚拟环境）：

```powershell
python -m pip install -r requirements-ai.txt
$env:CITYMATE_TEST_KNOWLEDGE='true'
python -m pytest tests/test_knowledge_integration.py -q
# 使用隔离业务库，--live 会调用已配置的模型并产生费用。
python -m evals.run_knowledge --live --output logs/knowledge-new-run.json
```

```powershell
python -m pip install -r requirements-dev.txt
python -m alembic upgrade head
python -m citymate.cli seed
python -m uvicorn citymate.app:app --host 127.0.0.1 --port 18000
```

初始化演示数据要求 `CITYMATE_DEMO=true`。另开一个使用相同配置的终端运行 `python -m citymate.worker`。数据库、Redis、模型和部署细节见 [开发指南](../docs/CITYMATE.md)。

## 模块职责

- `app.py`：应用装配、资源生命周期、公共中间件。
- `schemas.py`：输入字段、类型、长度和格式校验。
- `dependencies.py`：请求级服务、当前用户和管理员权限。
- `routers/`：鉴权、商户、订单预约、社区、助手、系统状态六类接口。
- `service.py`、`commerce.py`、`social.py`：业务规则、SQL 事务和 Redis 操作。
- `knowledge_client.py`、`knowledge_server.py`：应用自身的 MCP 政策连接，不依赖旧项目目录。
- `tests/`：默认 SQLite + fakeredis 测试；真实服务测试使用隔离测试库。
- `evals/`：36 个 Agent 场景及真实模型评测入口，调用应用自身的 Assistant 与业务服务。

政策检索已改为标题/段落 Chunk，长段落默认最多 320 字符并重叠 48 字符。两种检索模式共享块及来源元数据；Chroma 使用 `citymate_policy_chunks_v1` 并在启动时同步、清理失效块。详细策略和配置见 [项目说明](../docs/项目说明.md)。历史文档级检索评测不能作为新版本成绩。

## 检查

```powershell
python -m pytest
python -m black --check citymate tests migrations evals
python -m black citymate tests migrations evals
```

新增接口放入对应路由模块，用户身份使用依赖注入，业务事务放在服务层。详细约定见 [开发规范](../docs/代码结构与开发规范.md)。

Agent 程序回归：`python -m pytest tests/test_agent.py`。真实模型评测：`python -m evals.run_agent --live --repeat 2 --output logs/agent-eval.json`。后者使用已配置的模型 Key，产生模型调用费用；业务数据固定使用临时 SQLite + FakeRedis，不连接配置中的业务数据库和 Redis。输出路径必须不存在，以保留历史证据；`--ids B01,B02` 可用于诊断子集，不能将子集结果当成全量结果。结果口径与限制见 [Agent 专项评测报告](../docs/Agent专项评测报告.md)。

真实并发与故障验证位于 `tests/test_real_reliability.py`，需同时设置 `CITYMATE_TEST_DATABASE_URL`（数据库名必须为 `citymate_test`）和 `CITYMATE_TEST_REDIS_URL`，否则这 10 项会跳过。测试会清理专用测试表并结束自己创建的消费者子进程，不能指向业务库或与另一测试任务共用该库。执行方法、41 项真实服务测试结果及边界见 [并发与故障验证报告](../docs/并发与故障验证报告.md)。

真实 HTTP 负载实验使用 `python -m evals.run_load`，另需一个全新的 `citymate_load_<12位十六进制>` 数据库、Redis DB 15，以及 `CITYMATE_LOAD_DATABASE_URL`、`CITYMATE_LOAD_REDIS_URL`。它会自行启动独立 API 与 Worker，保留测试数据，不复用上面的 `citymate_test` 清表夹具。`--live-agent` 会调用真实模型。参数、测量口径与结果见 [压力测试与容量验证报告](../docs/压力测试与容量验证报告.md)。
