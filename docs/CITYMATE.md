# CityMate · 城市生活助手

源码核对日期：2026-10-20。本文中的可选配置说明仅代表代码入口存在；具体已执行的验证按日期列出，不能把配置步骤视为已验证成果。

CoursePilot 的 Python 本地生活演进版。前端仍为 Vue 3，业务服务为 FastAPI + SQLAlchemy + MySQL；Redis 承接登录、缓存、GEO、签到、关注、点赞、排行榜和 Streams 抢购订单。

首次了解改造后的功能、架构与核心业务流程，可先阅读 [CityMate 项目说明](项目说明.md)。本文侧重开发配置、启动和验收。

## 入口与目录

- API：`backend/citymate/app.py`；路由：`backend/citymate/routers/`；请求模型：`schemas.py`；鉴权依赖：`dependencies.py`。
- 后台消费者：`backend/citymate/worker.py`，AI 与政策检索位于同一个 `citymate/` 包。
- 前端：`frontend/src/App.vue`，共用请求客户端：`frontend/src/lib/http.js`；助手回复组件：`frontend/src/components/MarkdownMessage.vue`，Markdown 解析：`frontend/src/lib/markdown.js`。
- 运行、开发和可选 AI 依赖分别为 `requirements.txt`、`requirements-dev.txt`、`requirements-ai.txt`。
- 旧教育版入口已移出当前仓库；目录迁移和规范见 [代码结构与开发规范](代码结构与开发规范.md)。

## 一键容器启动

在仓库根目录执行：

```powershell
docker compose -p citymate up -d --build
```

默认是明确开启的本地演示环境：MySQL 8.4、Redis 7.4、Python 3.12、API、独立 worker、Nginx 前端。首次启动自动迁移数据库并导入演示资料；重复启动不会重置库存。

- 前端：<http://localhost:15173>
- API 文档：<http://localhost:18000/docs>
- 健康检查：<http://localhost:18000/health>
- MySQL 本地端口：13306；Redis 本地端口：16379。均仅绑定 127.0.0.1。

演示管理员手机号 `13900000000`，演示作者 `13900000001`，其他格式正确的手机号首次登录自动注册。演示模式点击获取验证码后，验证码直接显示在登录框；没有发送短信。管理员角色只能通过演示初始化或服务器 CLI 授予，不能在注册接口提交角色。

停用演示模式后，验证码签发接口会返回“短信服务尚未配置”，不会泄漏验证码。正式短信供应商接入不在本地演示内。默认数据库口令仅供本地演示；需要外部部署时替换配置。

登录使用 Cookie + 服务端 Session，验证码和登录用户保存在 Redis Session 中。前端自动携带 HttpOnly Cookie，刷新页面通过 `/me` 恢复用户；旧版 localStorage Token 不再用于登录，升级后需要重新登录。API 写请求需携带 `X-CityMate-Request: 1` 并保留服务端返回的 Cookie。HTTPS 部署设置 `CITYMATE_COOKIE_SECURE=true`。

## 本机开发

需要 Python 3.12、Node.js 22 以及独立 MySQL/Redis。Windows PowerShell：

```powershell
# 仓库根目录；为项目创建专用 Python 环境
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
docker compose -p citymate up -d mysql redis

# 后端终端
cd backend
$env:CITYMATE_DATABASE_URL='mysql+pymysql://citymate:citymate-local-only@127.0.0.1:13306/citymate?charset=utf8mb4'
$env:CITYMATE_REDIS_URL='redis://127.0.0.1:16379/0'
$env:CITYMATE_DEMO='true'
../.venv/Scripts/python.exe -m alembic upgrade head
../.venv/Scripts/python.exe -m citymate.cli seed
../.venv/Scripts/python.exe -m uvicorn citymate.app:app --host 127.0.0.1 --port 18000
```

另一个后端终端使用相同环境变量运行 `python -m citymate.worker`（使用项目虚拟环境解释器）。前端目录执行 `npm ci`、`npm run dev -- --host 127.0.0.1 --port 15173`。前端代理默认连接 18000。

SQLite 仅作为无 MySQL 时的单机开发/自动化测试选项，配置 `CITYMATE_DATABASE_URL=sqlite:///./citymate.sqlite3`，仍然必须有 Redis 和独立消费者；SQLite 测试不能证明 MySQL 行锁行为。

此机器镜像仓库不可用时，可选 `docker compose -p citymate-check -f docker-compose.yml -f compose.cached-infra.yml up -d mysql redis` 使用已缓存镜像。此覆盖文件的 MySQL 5.7 仅用于本地兼容验证，不是推荐生产版本，也不要将其旧数据卷直接用于 MySQL 8.4。

当前工作区已准备好 `.venv-citymate`（在仓库的上一级目录）。在数据库完成初始化后，可以直接在仓库根目录执行 `powershell -NoProfile -ExecutionPolicy Bypass -File ./start.ps1`，后台启动 API、消费者和前端；加 `-Action stop` 只停止该脚本记录的本地进程。日志位于 `backend/logs/citymate/`。该脚本使用本地演示连接配置，通过 `CITYMATE_MODEL_ENABLED=false` 默认关闭模型调用；需要使用环境或 `backend/.env` 中已配置的模型时加 `-EnableModel`。

## 完整体验路线

### 扩展示例数据

在后端目录、项目 Python 环境中，使用与应用相同的 MySQL/Redis 配置并设置 `CITYMATE_DEMO=true`，执行 `python -m citymate.cli seed-rich` 可追加丰富的模拟内容。该命令不重置已有库存、订单、用户资料或预约名额，也不会向真实用户账户中添加虚构订单。

2026-10-19 已在本机导入：16 家商户、16 个优惠、24 篇手记、12 位模拟作者、36 条关注关系、132 条点赞、114 条签到记录和 8 个预约审核样例；同时补充了未来 7 天的中午、下午和晚间时段。连同原数据，当前有 20 家商户、20 个优惠和 25 篇手记。

模拟账号为 `13910000001` 至 `13910000012`，昵称带“·模拟”。可以登录这些账户体验已有的关注流、签到和预约记录；普通用户仍需自行关注作者后才会在“关注”页看到动态。商户与探店内容均为虚构，并在资料中标注。

同一天重复导入不会新增重复记录；后续日期执行会补充新的预约时段和模拟用户签到记录。管理员修改过的商户、优惠库存和已有时段名额保持原值。新增的 `tests/test_demo_data.py` 验证重复导入、既有资料与名额保留，以及非演示模式和手机号冲突时拒绝导入。

### 页面操作

1. 获取验证码登录普通账户，打开商户详情，查看人均、营业时间和地址。
2. 选择“附近 10 km”查看上海演示位置附近商户，或主动授权浏览器定位。当前只有上海演示商户；其他城市返回空结果是正常行为。
3. 在限量好价领取体验券；返回受理编号后等待独立消费者生成订单。订单页可取消已生成的演示订单。
4. 在商户详情选择时段、人数，生成草稿后确认提交；切换管理员登录，在工作台批准或拒绝申请。
5. 发布图文手记；使用另一个普通账户点赞、关注作者、查看关注流和共同关注。
6. 签到获得积分，重复签到不会重复计分；个人空间查看连续天数与排行榜。
7. 管理员可编辑商户信息、观察缓存失效后的资料、查看 HyperLogLog 近似独立访客和消费者状态。
8. 向助手询问推荐、优惠、订单。未配置模型时明确显示“规则演示”；配置模型后使用角色限定的工具调用。

## 技术覆盖与边界

| 黑马点评能力 | CityMate 实现 |
|---|---|
| Spring Boot / MyBatis-Plus | FastAPI 路由与依赖、SQLAlchemy ORM、Alembic 迁移 |
| 登录会话 | Cookie + Redis 服务端 Session、登录后更换会话 ID、续期、退出、验证码绑定会话且一次消费、尝试次数与频率限制 |
| 用户上下文 | 请求依赖从服务端会话读取身份；聊天和业务接口不接受可覆盖身份的 user_id |
| 热点缓存 | 空值缓存、互斥重建；`CITYMATE_CACHE_MODE=logical` 可启用逻辑过期与后台重建；写后失效 |
| 分布式锁 | redis-py 所有权令牌锁，串行化缓存/点赞/关注/签到操作；非 Redisson 自动看门狗 |
| 库存、秒杀 | Lua 原子检查活动时间、名额及重复领取；Redis 预扣，SQL 条件更新最终校验 |
| 异步订单 | Streams 消费组、正确 XACK、pending 重试、XAUTOCLAIM 接管，SQL 幂等订单 |
| 可靠事件 | 订单和 outbox 同事务提交；Redis 事件幂等，取消/失败补偿名额 |
| 全局 ID | UTC 秒时间戳 + Redis 日序列，字符串返回避免浏览器整数精度损失 |
| 社区 | 图文、真实图片解码重编码、点赞最早用户、关注与共同关注、动态收件箱 |
| Feed | Sorted Set，时间分数 + 同分偏移游标，支持相同毫秒多条动态 |
| 签到 / 榜单 | SQL 积分账本、月 Bitmap、跨月连续签到、Sorted Set 排行 |
| GEO / UV | GEOSEARCH 距离查询、登录用户 HyperLogLog 近似计数 |
| 可观测性 | 健康检查、消费者心跳、pending 数、管理员授权 Prometheus 指标 |

报名/优惠订单、预约采用不同状态机。领取优惠券不代表真实支付。预约待审核阶段不预占名额；批准时事务扣减人数。不支持真实支付、退款、短信发送、真实商户核销或已批准预约自动改期。

Redis 是抢购受理日志的一部分：Compose 配置了 AOF 与 always fsync，SQL/Outbox 提供已提交事件的重试路径。库存计数器缺失时，只有在 SQL 订单、Redis 买家关系或初始化标记至少一项仍存在的情况下，代码才会拒绝重新初始化。若三类证据都不存在，会按 SQL 库存初始化；尚未落库的预扣与 Redis 证据一起丢失时无法据此识别，不具备灾难场景零丢失保证。恢复前应暂停受理并核对记录，当前没有自动完成该核对的恢复工具。

社区 Redis 数据是查询加速层；签到、关注、点赞和笔记保存在 MySQL，读写操作可重建相应索引。动态流保留最近 500 条；列表按页读取。当前演示规模未实现海量粉丝分批推送。

## AI、记忆与检索

本地未配置密钥时，规则模式只做明确标注的目录筛选、优惠和订单查询；不会冒充 LLM。

配置 `OPENAI_API_KEY`、`OPENAI_MODEL`、可选 `OPENAI_BASE_URL` 后，启用推荐、预约、优惠、订单四类角色及有边界的工具调用。模型仅能查询当前用户订单和生成预约草稿；提交由完整确认口令处理器执行，模型无法调用抢购、取消、审核等操作。角色工具轨迹可在聊天回答下展开查看。

每个用户、每个会话的最近消息和明确预算/类别偏好保存在 Redis（24 小时）。当前没有自动长期画像或跨会话偏好推断。旧教育版的分层记忆模块已从当前源码移除。

2026-10-21 起，同一会话还保存最近成功处理的角色（24 小时）。没有新意图关键词的补充消息沿用角色，明确新话题可切换；这是关键词规则，不是完整语义分类。模型提示包含当前上海日期时间，并明确商户搜索不支持距离排序。接口新增 `model_calls`、`token_usage`、`usage_complete`，用于记录模型调用和服务商返回的用量。

Agent 专项程序测试在 `tests/test_agent.py`，真实模型评测在 `evals/run_agent.py`。在 `backend` 目录运行 `python -m evals.run_agent --live --repeat 2 --output logs/agent-eval.json`；需已配置模型，会产生调用费用。36 个场景均使用临时 SQLite/FakeRedis 和合成用户，不连接业务库。输出文件要求不存在，诊断子集可加 `--ids B01,B02`。测试结果、人工核查和局限见 [Agent 专项评测报告](Agent专项评测报告.md)。

前端刷新不自动恢复旧聊天记录；模型商户搜索工具只接受类别、关键词和预算，没有坐标参数。页面/API 的 GEO 附近查询不能算作助手已完成的距离排序能力。

政策源文件在 `backend/citymate/policies/`。默认词项检索使用查询的相邻两字符片段计分，缺少最低相关阈值，零命中时仍返回排序结果；修改文件需重启读取。它由模型的 `knowledge_search` 工具调用，规则模式不执行该检索。

### 可选分支配置（已完成隔离环境联调）

2026-10-21 已验证 Chroma 真实嵌入、MCP stdio 子进程及模型聊天链路，结果见 [知识检索联调报告](知识检索联调报告.md)。两项默认均不启用；中文检索排序仍需优化：

```powershell
# 本地 Python 环境
python -m pip install -r requirements-ai.txt
$env:CITYMATE_KNOWLEDGE_MODE='chroma'
$env:CITYMATE_KNOWLEDGE_TRANSPORT='mcp'
```

容器设置 `.env.example` 中的 `CITYMATE_AI_EXTRAS=true`、`CITYMATE_KNOWLEDGE_MODE=chroma`、`CITYMATE_KNOWLEDGE_TRANSPORT=mcp`，用 `--env-file` 指定文件并重新构建。Chroma 首次使用可能下载嵌入模型。分块知识集合为 `citymate_policy_chunks_v1`，旧文档级集合保留但不再查询；MCP 注册检索、统计和写入三个工具，但 `knowledge_add` 始终抛错，实际没有开放远程写入。完整容器部署及首次模型下载尚未验证。

分块配置为 `CITYMATE_KNOWLEDGE_CHUNK_SIZE=320`、`CITYMATE_KNOWLEDGE_CHUNK_OVERLAP=48`，单位是字符而非 Token，local 与 MCP 模式均生效。政策文件以 Markdown 标题和空行标出条款边界，长段落再按长度和重叠切分。修改文件或参数后重启，启动同步会清理当前分块集合中的旧块；不同实例必须使用相同政策快照。单元测试 `tests/test_knowledge.py` 不需要向量依赖；设置 `CITYMATE_TEST_KNOWLEDGE=true` 后，`tests/test_knowledge_integration.py` 验证真实向量、MCP、元数据和旧块清理。真实模型回答质量需另行运行 `evals.run_knowledge --live`，不能用脚本模型通过代替。

## 测试

最新真实服务结果见 [2026-10-20 并发与故障验证报告](并发与故障验证报告.md)：31 项原有回归与 10 项新增验证全部通过。新增测试覆盖并发领取、重复消费、消费者进程强制中断、事务回滚、Outbox 响应丢失重试及预约容量竞争。

在后端目录使用项目 Python：

```powershell
python -m pytest tests -q
```

默认 SQLite + fakeredis/Lua，覆盖并发预扣、重复消费、消费者接管、取消补偿、权限隔离、预约名额、签到、同分动态分页、文件校验和规则助手。

真实服务测试需专用 `citymate_test` 数据库，并设置 `CITYMATE_TEST_DATABASE_URL`、`CITYMATE_TEST_REDIS_URL`。测试明确拒绝非 `citymate_test` 的外部数据库；会清空专用测试表，每次使用独立 Redis 前缀。不要指向业务库。

前端：`npm run build`、`npm test` 与 `npm run format:check`。现有 Node 测试验证当前 HTTP 客户端的 Cookie、CSRF、上传、401 和错误行为，以及 Markdown 排版、HTML 转义、危险链接过滤和远程图片不加载；页面完整流程仍需浏览器检查。真实模型与 MCP/Chroma 本地链路已有独立验证记录；首次嵌入下载、浏览器全链路及完整容器部署仍不在该记录范围内。

## 本次验证记录（2026-10-18）

- SQLite + fakeredis：初始 17 项测试通过。
- 真实 MySQL 5.7 + Redis 7：最终 20 项测试全部通过，包括新增商户/优惠券权限、活动时间和模型工具越权拒绝。
- 并发验证：25 位用户争抢 10 个名额，接受 10 笔不同订单；重复领取返回原编号。
- 故障路径：重复消费、消费者退出后的 pending 接管、数据库拒单补偿、重复取消不重复恢复库存。
- 前端：生产构建成功；5 项保留的兼容模块测试通过。
- 浏览器：普通用户登录、优惠券异步成单、签到加分、规则助手读取本人订单、创建预约草稿并提交、管理员批准预约成功。
- 发现并修复：MySQL 默认字符集的中文写入错误、MySQL SUM 的 Decimal 到 Redis 分数转换问题。
- 未验证：默认 MySQL 8.4 完整容器构建（镜像仓库连接失败）；真实模型调用、Chroma 嵌入下载和 MCP 语义检索全链路；生产吞吐及高可用。

## 模型接入验证记录（2026-10-19）

以下为历史接入记录。2026-10-21 当前本地模型已切换为 `Qwen/Qwen3-32B`，并重启服务；11 场景子集自动检查通过，仍有回复语义问题，详见 [Agent 专项评测报告](Agent专项评测报告.md)。

- 从原项目的本地配置中，仅复用了模型 Key、模型名称和接口地址，写入被 Git 忽略的 `backend/.env`；未复制旧数据库配置。
- 硅基流动接口与配置模型 `deepseek-ai/DeepSeek-V4-Flash` 的实际请求成功。
- 使用临时 SQLite 与 fakeredis 演示数据，通过 FastAPI 聊天入口验证模型调用 `search_shops`、`shop_details` 和 `knowledge_search`，完成预算推荐与带来源的政策解释；未修改既有业务库。
- 本次没有启动现有网站与 Docker 数据服务，不能将该验证视为当前业务库上的浏览器验收。启动数据服务后，使用 `powershell -NoProfile -ExecutionPolicy Bypass -File ./start.ps1 -EnableModel` 启用模型。
- 本次检索使用本地词项模式，Chroma 与 MCP 全链路仍待验证。

## 统一代码结构验收（2026-10-19）

旧教育版入口、配套模块和旧兼容测试已移出活动源码。当前测试入口为 `backend/tests/` 和 `frontend/tests/`，路径变化见 [开发规范](代码结构与开发规范.md)。

- 后端：31 项测试通过，默认 SQLite + fakeredis；覆盖整理后的路由和应用实例隔离。
- 前端：4 项当前 HTTP 客户端测试通过，覆盖 Cookie/CSRF、上传、401 和错误传播。
- 格式：35 个 Python 文件通过 Black 检查，前端通过 Prettier 检查。
- 构建与配置：前端生产构建通过，Compose 配置、启动脚本语法和文档链接检查通过。
- 本次未重新部署容器或连接外部模型/MCP，也未重复完整浏览器验收；上面的历史记录不等于本次重新执行。

## 助手展示与验收（2026-10-19）

助手大屏面板已加宽为 420–560px，桌面高度随窗口调整，小屏使用单列布局。回复与输入框字号为 14px。助手消息通过 `markdown-it` 渲染标题、加粗、列表、表格、引用、链接和代码块，用户输入保持纯文本；宽表格可横向滚动。原始 HTML 被转义，危险链接被过滤，远程图片只显示替代文字。代码流程见 [Redis 讲义第 14.6 节](CityMate-Redis实战项目讲义.md#146-助手回复如何变成排版后的内容)。

依赖更新后，在 `frontend` 目录执行 `npm ci`，再启动开发服务。开发环境刷新页面以加载更新后的组件和样式；容器环境需重新构建前端镜像，单纯刷新不会更新已部署的旧静态文件。

本阶段实际验证记录：

- 重启本机 API、Worker 和前端，健康接口正常、消费者在线，MySQL 与 Redis 健康，20 条商户数据加载成功；保留模型模式。
- 浏览器验证验证码登录、刷新后保持登录、“我的行程”页面，以及模型实际回复的标题、表格和加粗排版。
- 前端 7 项测试通过：4 项 HTTP 客户端、3 项 Markdown 渲染；生产构建与 Prettier 检查通过。
- 未重跑完整订单与预约浏览器流程、真实数据库集成测试、Chroma/MCP 全链路或生产并发测试；本次文档同步仅记录此前结果。

展示验收可发送：“推荐两家咖啡店，仅用标题、两列表格（店名、人均）和一句加粗建议回答。”检查标题层级、表格边框与加粗文字；遇到宽表格时确认可在表格内横向滚动。代码块只展示，不执行，也未提供语法高亮或数学公式渲染。

![CityMate 首页](citymate-home.png)
![管理员预约审批](citymate-admin.png)
