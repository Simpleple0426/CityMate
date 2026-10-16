# CoursePilot 四类 Agent 教务版说明

| Agent | 职责 | 业务工具 |
|---|---|---|
| `course_consultation` | 课程和通用政策咨询 | `list_courses` |
| `course_planning` | 候选筛选和比较 | `list_courses`、`get_enrollment`、`check_transfer`、`advise_transfer` |
| `academic_service` | 转班草稿、申请查询与任务推进 | 上述工具及 `prepare_transfer`、`get_application_status`、`assess_free_transfer` |
| `fees_entitlements` | 剩余课时、差价和免费资格 | `get_enrollment`、`check_transfer`、`advise_transfer`、`assess_free_transfer` |

四类角色共享 `search_knowledge_base`；另有 `escalation` 人工交接出口。实际权限来自 `get_tools()`，模型没有 `submit_transfer` 工具。

## 7 Agent 角色与路由

**源码位置：** `agents/agent_orchestrator.py` 的 `AgentProfile`、四类 `EducationAgent` 子类、`AgentOrchestrator.__init__()`、`_route_decision()`、`run_collaboration()` 和 `_best_agent()`。

### 7.1 角色契约

`AgentProfile` 定义角色任务、工作流程、输入输出契约、工具范围以及模型参数。四个角色复用执行基类，但系统指令和实际工具集合不同。

| 角色 | 负责的结果 | 业务工具 |
|---|---|---|
| 课程咨询 | 课程和通用政策解释 | `list_courses` |
| 选课规划 | 候选班级和比较依据 | `list_courses`、`get_enrollment`、`check_transfer`、`advise_transfer` |
| 教务办理 | 生成转班草稿和查询申请 | 上述工具及 `prepare_transfer`、`get_application_status`、`assess_free_transfer` |
| 费用与权益 | 课时、差价和免费资格 | `get_enrollment`、`check_transfer`、`advise_transfer`、`assess_free_transfer` |

各角色还获得共享的知识检索工具。实际权限来自 `get_tools()` 返回的字典；`AgentProfile.tool_scope` 主要表达角色契约，不能只看它判断运行时权限。

### 7.2 如何选择负责人

`_route_decision()` 综合明确表达、识别意图、活动转班任务、当前任务焦点和要求更新。用户补充“改成晚上”时可继续原任务，明确询问新课程政策时可切换话题，避免一直被旧任务锁定。

主角色为教务办理时，日期或筛选表达可以引入选课规划角色，费用表达可以引入费用与权益角色。结果保存为 `RoutingDecision`，包含负责人、辅助角色、原因和置信度。

### 7.3 当前协作顺序

`run_collaboration()` 顺序执行辅助角色，把它们的结果放入结构化上下文，再执行主角色。主角色统一回答，办理前重新核验。辅助结果包含自然语言 findings、成功状态及工具列表，不是所有角色都返回严格 JSON Schema 的业务报告。

默认池每类只有一个实例。`_best_agent()` 可以按表现选择同类型实例，但当前监控降权不会自动把费用工作改派给课程咨询，也没有证明已实现生产级水平扩容。

## 8 模型工具调用循环

**源码位置：** `agents/agent_orchestrator.py` 的 `BaseAgent.handle()`、`_call_llm()`、`_validate_tool_input()`、`_build_system_prompt()`；工具定义位于 `agents/tools.py` 的 `AgentToolSpec`、`make_tool()`，业务工具集合位于 `agents/education_tools.py`。

### 8.1 循环过程

`_call_llm()` 先组织背景、实体、角色输入契约与用户消息，再把角色可用工具转换为 Function Calling 定义。模型返回普通文本时结束；返回 `tool_calls` 时，后端读取工具名和 JSON 参数，查询白名单，校验参数并执行 handler。

执行结果以 `role=tool` 消息写回，同时保留匹配的 `tool_call_id`。下一轮模型根据结果继续选择工具或生成回答。循环最多八轮，超过上限抛出错误。

```python
# 学习用简化流程，实际实现见 BaseAgent._call_llm
for turn in range(8):
    response = await model(messages, tools)
    if not response.tool_calls:
        return response.text
    messages.append(response.assistant_message)
    for call in response.tool_calls:
        spec = whitelist[call.name]
        validate(spec, call.arguments)
        result = await execute(spec, request, call.arguments)
        messages.append(tool_message(call.id, result))
```

### 8.2 身份与参数边界

工具 handler 接收 `Request` 和参数字典。查询当前报名时使用 `req.user_id`，不接受模型自行填写另一个学员 ID。JSON Schema 限制字段，执行器也有运行时校验；白名单中不存在的工具会返回失败结果。

这是工具层防止模型擅自扩大操作范围的设计，但无法替代 HTTP 层真实鉴权，因为 `req.user_id` 本身仍来自客户端。

### 8.3 轨迹与并发

轨迹记录角色、工具名、输入、执行状态、业务结果状态、耗时和错误等。工具调用成功与业务符合资格是两个概念：工具可以正常返回“不符合资格”，调用本身仍是成功的。

`_execute()` 为每次请求创建 worker，避免多个会话共享 `_last_tools_used` 和 `_last_tool_traces` 等可变字段；统计对象仍共享。该处理减少轨迹串扰，不等于已经解决所有同会话并发和多进程一致性问题。

### 8.4 确定性执行分支

`_execute()` 在部分免费核验或要求更新场景直接调用 `assess_free_transfer` 或 `advise_transfer`，通过固定渲染函数生成回复，不进入模型工具循环。模型与规则混合执行是当前架构的实际特点。

教务角色成功生成草稿后，后端还会用数据库草稿生成规范回复，明确显示班级、差价、状态与确认口令，避免模型漏掉关键办理信息。

## 9 SQLite 业务数据与状态

**源码位置：** `agents/education_store.py` 的 `__init__()`、`connection()`、`catalog()`、`enrollment()`、`_quote()`、`prepare()` 和 `submit()`。

| 表 | 保存内容 | 关键关联 |
|---|---|---|
| `classes` | 班级日期、时段、进度、名额、价格 | 班级 ID |
| `enrollments` | 当前用户报名、已付金额、剩余课时 | 用户 ID 与班级 ID |
| `class_metadata` | 授课老师 | 班级 ID |
| `transfer_requirements` | slots、修改事件、歧义、版本 | 用户 ID 与会话 ID |
| `active_tasks` | 活动办理任务 | 用户 ID 与会话 ID |
| `transfer_focus` | 选班或免费资格核验焦点 | 用户 ID 与会话 ID |
| `drafts` | 目标班级、原因、差价、状态 | 草稿 ID 与会话 |
| `draft_evidence` | 需求版本和政策指纹 | 草稿 ID |
| `applications` | 待审核申请 | 唯一的 draft_id |

金额以整数分保存。默认已付金额 200000 分，即 2000 元；目标晚班 220000 分，即 2200 元，补差 20000 分，即 200 元。差价计算来自业务代码，不能让模型凭印象计算。

SQLite 中的 `slots`、`events`、`ambiguities` 以 JSON 文本保存。会话记忆不承担这些业务状态的唯一存储责任。

`connection()` 创建连接、设置字典式行读取，并在上下文中管理提交与异常回滚，最后关闭连接。写草稿和提交使用 `BEGIN IMMEDIATE`，在当前 SQLite 范围内约束并发写入。

## 12 草稿与确认提交

**源码位置：** `EducationStore.prepare()`、`submit()`、`cancel()`、`invalidate_draft()`；编排器 `_business_control()`。

### 12.1 生成草稿

用户明确选择目标班级后，教务 Agent 可以调用 `prepare_transfer`。`prepare()` 重新查询报名、目标和费用，核验政策及当前要求，无歧义且满足条件才生成草稿。旧待确认草稿变为 superseded，新草稿变为 awaiting_confirmation，同时保存需求 revision 和政策 fingerprint。

准备草稿不创建待审核申请。模型获得的是草稿工具，没有提交工具。

### 12.2 确认提交

`_business_control()` 只接受完整匹配的 `确认提交 <12位小写十六进制草稿ID>`。用户只说“可以”“确认”“好的”时，会显示草稿或提示，不能直接提交。

`submit()` 在事务中依次检查草稿是否属于当前用户与会话、是否已有申请、是否仍待确认，再重新核验源班、目标、费用、需求版本和政策指纹。任何关键变化都使旧草稿失效，要求重新生成并确认。

```text
awaiting_confirmation
  ├─ 用户取消 → cancelled
  ├─ 新草稿或要求变更 → superseded
  ├─ 提交时发现数据变化 → invalidated
  └─ 明确确认且复核通过 → submitted → application.pending_review
```

### 12.3 幂等与事务分别解决什么

幂等防止重复确认创建重复申请：`applications.draft_id` 有唯一约束，提交前先查已存在申请并返回它。事务让同一次提交的校验与状态更新保持一致。

事务不会保证未来审批时仍有名额。本演示不扣减名额、不改变报名，后续真实审批还需要重新校验并完成资源分配。因此不能把这里称为完整名额锁定或支付事务系统。

## 演示步骤

1. 使用 `student_demo` 和新的 `conv_id`。
2. 发送“帮我转到周日班，不想补钱，老师最好不变”。
3. 查询候选后明确发送“帮我转到 PY-SUN-PM”。
4. 检查草稿显示的原班、目标、差价和状态。
5. 原样发送返回的完整确认口令。
6. 查询“我上次申请怎么样了”。

知识库使用 `education_services_v1`，默认资料来自 `data/demo_docs/education_services.json`；政策核验使用独立的 `transfer_policies.json`。业务状态、要求和草稿存在 SQLite；记忆摘要与画像存在 ChromaDB。

当前为 Python 教务演示后端。`user_id` 由客户端传入，只有 `student_demo` 有预置报名；没有真实登录、审批、支付或退款连接。提交结果为 `pending_review`，不修改报名、不占名额、不扣款。旧客服、作业辅导角色和 Java 描述不属于当前默认业务实现。

验证方式和已有报告见[真实模型评测](真实模型联调与评测.md)。
