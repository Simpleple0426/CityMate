# CoursePilot · 课航

面向培训机构学员的课程咨询与教务办理多 Agent 演示平台，覆盖课程咨询、选课规划、教务办理、费用与权益四类任务。

项目以转班业务为主要实践场景，将意图识别、知识检索、会话记忆和业务工具连接到同一条对话链路，支持从多轮需求澄清、候选筛选、政策资格核验，到生成草稿、用户确认和提交待审核申请的完整演示。

**技术栈：** Python 3.12 · FastAPI · OpenAI-compatible API · MCP · Redis · ChromaDB · SQLite · Vue 3 · Docker Compose · Prometheus

## 业务场景

面向培训机构的课程咨询与教务服务场景，通过多 Agent 协作完成需求理解、知识检索、业务查询和办理引导。以转班流程为例，支持多轮需求澄清、政策资格核验及用户确认后提交申请。

## 核心能力

| 能力 | 实现方式 |
| --- | --- |
| 多 Agent 协作 | 按意图选择主 Agent，按需调用只读辅助 Agent，返回路由原因及工具使用信息 |
| 多轮选班 | 按用户与会话持久化约束、版本和更新记录；先过滤硬性要求，再按偏好排序，无解时解释冲突 |
| 政策与事实联合判断 | 从人工维护的结构化政策提取事实依赖，通过白名单查询业务数据，输出逐条 pass / fail / unknown 与证据来源 |
| 可控的申请提交 | 模型调用工具生成草稿；明确确认后，由确定性处理器重新校验并提交，重复确认幂等返回 |
| 按需知识检索 | Agent 经 MCP stdio 服务检索 ChromaDB；工具层提供查询改写、缓存、熔断和重排 |
| 分层会话记忆 | Redis 保存工作记忆，ChromaDB 保存情景记忆与用户画像 |
| Skills 与可观测性 | 动态加载业务规则，提供监控、Prometheus 指标及按请求查询的工具轨迹 |

## 系统架构

意图识别包含 LLM、Embedding 与关键词融合逻辑，并结合教育业务的显式意图和任务续接规则。通用文档检索与结构化政策判断采用不同执行路径：前者用于资料问答，后者用于可追溯的业务条件核验。

## 快速开始

### 1. 配置环境

以下命令在包含本 README 的后端目录执行。需要 Docker 和 Docker Compose；本地 Python 开发推荐使用 Python 3.12。

```bash
cp .env.example .env
```

Windows PowerShell 使用 `Copy-Item .env.example .env`。编辑 `.env`，填写模型配置：

```dotenv
OPENAI_API_KEY=your_api_key
OPENAI_MODEL=your_chat_model
OPENAI_BASE_URL=
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
REDIS_PASSWORD=replace_with_your_password
```

官方服务的 `OPENAI_BASE_URL` 留空；兼容服务填写对应 API 地址。聊天与 Embedding 均有远端调用路径，请确认服务支持配置的模型和接口。其他容器配置保留示例值即可。真实模型调用会产生 API 费用。

### 2. 启动后端及依赖

```bash
docker compose up -d --build
docker compose ps
docker compose logs -f coursepilot
```

首次构建需要下载依赖、镜像和向量模型。Compose 启动 API、Redis、ChromaDB、Prometheus 和 Nginx；Vue 页面需要另外启动。

| 入口 | 地址 |
| --- | --- |
| Swagger 接口文档 | http://localhost:8000/docs |
| 健康检查 | http://localhost:8000/health |
| Nginx 反向代理 | http://localhost |
| Prometheus | http://localhost:9090 |

停止服务使用 `docker compose down`，默认保留业务目录和命名数据卷。

### 3. 启动前端（可选）

前端位于当前工作区的同级目录 `CoursePilotFrontend/`，不包含在本后端目录内。取得前端源码后，在前端目录执行：

```bash
npm install
npm run dev
```

访问 http://localhost:5173，学员 ID 使用 `student_demo`。Node.js 版本需满足前端 Vite 依赖要求。前端更多配置见其 README。

### 4. 体验转班流程

在同一会话中依次发送：

```text
帮我转到周日班，不想补钱，老师最好不变
下午不行，只能晚上
最多补两百元也可以
帮我转到 PY-SUN-EVE
确认提交 <回复中实际返回的草稿ID>
```

第二轮无完全匹配方案时，系统应解释时间与费用冲突；用户放宽费用后才允许新的候选。提交成功后返回待教务审核申请，不代表完成转班或扣款。

也可在 Swagger 调用 `POST /chat`：

```json
{
  "message": "我是否符合免费转班条件？",
  "user_id": "student_demo",
  "conv_id": "demo-transfer-001"
}
```

后续请求沿用相同的 `user_id` 和 `conv_id`。目标班级未知时先补充信息，例如继续发送 `PY-SUN-PM`。

## API 概览

| 接口 | 用途 |
| --- | --- |
| `POST /chat` | 对话、Agent 路由与业务工具调用 |
| `POST /search` | 知识检索 |
| `POST /knowledge/add`、`POST /knowledge/upload` | 文本与文件导入 |
| `GET /knowledge/stats` | 知识库统计 |
| `GET /skills`、`POST /skills/reload` | Skills 查看与重载 |
| `GET /trace/tool/{request_id}`、`GET /trace/tools` | 工具调用轨迹 |
| `GET /monitor`、`GET /metrics` | 运行监控与 Prometheus 指标 |
| `POST /eval/run` | 内置评测入口 |

对话响应提供请求与会话 ID、意图、主 Agent、辅助 Agent、路由原因、工具列表及耗时。完整字段以 `/docs` 为准。

## 代码导航

```text
api/main.py                      FastAPI 入口与生命周期管理
agents/agent_orchestrator.py      角色路由、工具循环与确认提交
agents/education_store.py         SQLite 业务状态与约束持久化
agents/transfer_advisor.py        候选筛选、排序与冲突解释
core/intent_recognizer.py         意图识别
core/transfer_requirements.py     多轮约束增量解析
core/policy_evidence.py           政策匹配、事实依赖与逐条核验
core/skill_loader.py              Skills 加载
integrations/knowledge_client.py  MCP 客户端
integrations/knowledge_server.py  MCP stdio 服务端
integrations/tool_manager.py      检索治理与工具管理
memory/conversation_memory.py     工作记忆、情景记忆与画像
monitor/                         监控与指标
evaluation/                      离线对照、真实模型联调与评测
tests/                           自动化测试
skills/                          业务规则与参考资源
data/demo_docs/                   演示资料与政策
wiki/                            设计说明与源码阅读指南
```

建议先阅读 [Agent 编排](agents/agent_orchestrator.py)、[多轮约束解析](core/transfer_requirements.py) 和 [政策事实核验](core/policy_evidence.py)，再结合[后端架构与源码学习指南](wiki/后端架构与源码学习指南.md)了解完整链路。

## 测试与评测

安装后端依赖后，在后端目录执行：

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
python -m evaluation.transfer_benchmark --output data/eval/transfer-strategies.json
```

已有评测记录如下，具体运行方式与统计限制见[真实模型联调与评测](wiki/真实模型联调与评测.md)：

| 评测 | 已有记录 | 范围与解释 |
| --- | --- | --- |
| 多轮策略对照 | 只用最后一轮 2/6；持续维护 6/6 | 6 个人工确定性案例，不是真实模型成功率 |
| 真实模型 full 联调 | 29/30 | 覆盖实际 `/chat`、Redis、ChromaDB、MCP 与隔离 SQLite 的人工场景程序检查 |
| 失败项修复后单独复测 | 3/3 | 单独复测结果，未重新完整跑出 30/30 |

`core` 模式仅覆盖模型、意图、Skills 与隔离业务数据库；`full` 增加后端完整链路，仍不包含浏览器操作、真实审批与支付。上述结果不代表线上成功率或统计显著的泛化结论。

评测输出位于 `data/eval/`，默认被 Git 忽略，新克隆仓库不保证包含本地历史报告，可按文档重新生成。本 README 引用已有记录，本次文档修改未重新运行模型评测。
