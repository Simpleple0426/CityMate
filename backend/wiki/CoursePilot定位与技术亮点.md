# CoursePilot 项目定位与技术亮点

CoursePilot 课航是面向培训机构的多 Agent 课程咨询与教务办理演示平台。重点是持续维护学员要求，查询真实演示数据，核验政策，生成草稿并经明确确认提交待审核申请。

## 业务问题

学员需求分散在多轮对话里，时间、预算和老师要求会变化。系统需要保留未被撤销的条件，说明候选的取舍，并避免模型把建议或草稿描述成已完成转班。

## 当前流程

```text
HTTP /chat → 读取记忆 → 意图识别 → 编排器业务控制与要求更新
→ 主角色与辅助角色选择 → 辅助角色顺序执行 → 主角色执行
→ 确定性规则或模型工具循环 → 回复与轨迹 → 写回消息与后台画像

共享 RAG 工具 → 查询改写与并行召回 → MCP stdio → ChromaDB → 重排
业务工具 → SQLite 与结构化政策 → 生成草稿 → 完整确认口令 → 复核提交
```

## 角色分工

| Agent | 职责 | 业务工具 |
|---|---|---|
| `course_consultation` | 课程和通用政策咨询 | `list_courses` |
| `course_planning` | 候选筛选和比较 | `list_courses`、`get_enrollment`、`check_transfer`、`advise_transfer` |
| `academic_service` | 转班草稿、申请查询与任务推进 | 上述工具及 `prepare_transfer`、`get_application_status`、`assess_free_transfer` |
| `fees_entitlements` | 剩余课时、差价和免费资格 | `get_enrollment`、`check_transfer`、`advise_transfer`、`assess_free_transfer` |

四类角色共享 `search_knowledge_base`；另有 `escalation` 人工交接出口。实际权限来自 `get_tools()`，模型没有 `submit_transfer` 工具。

## 技术能力与源码

| 能力 | 实现 |
|---|---|
| 意图与任务路由 | `core/intent_recognizer.py`、`agents/agent_orchestrator.py` |
| 多轮要求与冲突解释 | `core/transfer_requirements.py`、`agents/transfer_advisor.py` |
| 政策与数据库事实核验 | `core/policy_evidence.py`、`data/demo_docs/transfer_policies.json` |
| 确认、事务与幂等 | `agents/education_store.py` 的 `prepare()`、`submit()` |
| MCP 与 RAG | `integrations/`、`agents/tools.py` |
| 记忆、Skills 与监控 | `memory/`、`core/skill_loader.py`、`monitor/` |
| 回归与质量评测 | `evaluation/`、`tests/` |

意图识别先命中明确业务规则，其他表达才进入三路融合；主辅协作按依赖顺序执行；RAG 主要作为 Agent 工具按需调用。部分选班和资格判断直接执行确定性规则，不调用角色生成模型。

## 验证与范围

| 证据 | 保存结果 | 正确解释 |
|---|---|---|
| [full 30 场景报告](../data/eval/live-full-30.md)与[逐轮记录](../data/eval/live-full-30.json) | 29/30 | 一次真实模型后端全链路人工场景回归的程序检查通过情况 |
| [口语预算单独复测](../data/eval/live-colloquial-retest.md) | 3/3 | 修复失败项后的单独复测，未重新完整跑出 30/30 |
| [Skills 小样本对照](../data/eval/live-no-skills-5.md) | 启用 5/5，关闭 4/5 | 五场景一次对照，不证明稳定提高 20% |
| [多轮策略对照](../data/eval/transfer-strategies.json) | 最后一轮 2/6，持续维护 6/6 | 六个确定性人工案例，不是真实模型成功率 |

full 包含实际 `/chat`、Redis、本地 Chroma、MCP 子进程和隔离 SQLite，不包含浏览器、真实审批和支付。29/30 不是 LLM Judge 评分、意图准确率或线上成功率。

当前为 Python 教务演示后端。`user_id` 由客户端传入，只有 `student_demo` 有预置报名；没有真实登录、审批、支付或退款连接。提交结果为 `pending_review`，不修改报名、不占名额、不扣款。旧客服、作业辅导角色和 Java 描述不属于当前默认业务实现。

详细实现见[技术亮点](技术亮点.md)和[源码指南](后端架构与源码学习指南.md)。
