# NexusOps 历史定位与 CoursePilot 当前项目

NexusOps 是早期企业运营方向的命名和包装方案。当前源码与简历统一采用 CoursePilot 课航，定位为培训机构的课程咨询与教务办理演示平台。本文件保留历史名称，防止旧链接失效；它不代表另一个已实现的企业运营产品。

## 名称与业务对应

| 历史表述 | 当前准确表述 |
|---|---|
| 企业智能运营协同中枢 | 课程咨询与教务办理多 Agent 演示平台 |
| 通用客服、技术支持、账单退款 | 课程咨询、选课规划、教务办理、费用与权益 |
| 企业跨系统自动操作 | 本地演示 SQLite 查询、草稿与待审核申请 |
| 并行角色输出与汇总 | 辅助角色顺序执行，主角色统一推进 |
| 生产级运营平台 | 有监控、工具治理和回归能力的演示后端 |

## 当前能力

```text
HTTP /chat → 读取记忆 → 意图识别 → 编排器业务控制与要求更新
→ 主角色与辅助角色选择 → 辅助角色顺序执行 → 主角色执行
→ 确定性规则或模型工具循环 → 回复与轨迹 → 写回消息与后台画像

共享 RAG 工具 → 查询改写与并行召回 → MCP stdio → ChromaDB → 重排
业务工具 → SQLite 与结构化政策 → 生成草稿 → 完整确认口令 → 复核提交
```

| Agent | 职责 | 业务工具 |
|---|---|---|
| `course_consultation` | 课程和通用政策咨询 | `list_courses` |
| `course_planning` | 候选筛选和比较 | `list_courses`、`get_enrollment`、`check_transfer`、`advise_transfer` |
| `academic_service` | 转班草稿、申请查询与任务推进 | 上述工具及 `prepare_transfer`、`get_application_status`、`assess_free_transfer` |
| `fees_entitlements` | 剩余课时、差价和免费资格 | `get_enrollment`、`check_transfer`、`advise_transfer`、`assess_free_transfer` |

四类角色共享 `search_knowledge_base`；另有 `escalation` 人工交接出口。实际权限来自 `get_tools()`，模型没有 `submit_transfer` 工具。

当前为 Python 教务演示后端。`user_id` 由客户端传入，只有 `student_demo` 有预置报名；没有真实登录、审批、支付或退款连接。提交结果为 `pending_review`，不修改报名、不占名额、不扣款。旧客服、作业辅导角色和 Java 描述不属于当前默认业务实现。

## 对外材料

项目介绍使用[当前定位](CoursePilot定位与技术亮点.md)，简历使用[推荐版本](简历包装.md)，数据使用[评测报告](真实模型联调与评测.md)。不将订单、物流、发票、真实退款、跨企业系统编排、Java 技术栈作为当前 Python 教务项目已完成能力。

企业运营方向可以作为未来复用思路：保留角色、工具、规则、状态和评测的分层设计，替换领域工具与鉴权、审批连接。任何新领域能力完成前均属于扩展设想。
