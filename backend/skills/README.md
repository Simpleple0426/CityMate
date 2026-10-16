# CoursePilot Skills 文档

CoursePilot 启动时会从 `COURSEPILOT_SKILLS_DIR` 读取 Skills，并在匹配用户请求时注入到对应 Agent 的 system prompt。Skills 适合维护业务处理规范、客服话术、技术排障 SOP、账单审核边界、升级规则和禁止事项。

当前教育业务使用 `course_services/SKILL.md`，旧版三类 Skills 保留兼容：

```text
skills/general_customer_service/SKILL.md  # 通用客服：接待、澄清、分流、投诉和转人工
skills/technical_support/SKILL.md         # 技术支持：故障排查、接口错误、部署配置和安全边界
skills/billing_support/SKILL.md           # 账单服务：扣款、退款、发票、订阅和财务审核
```

## Skill 文件格式

推荐每个 Skill 使用独立目录，并将主文件命名为 `SKILL.md`：

```text
skills/<skill_name>/SKILL.md
```

文件顶部使用简单 front matter：

```markdown
---
name: 技术支持处理规范
description: 适用于 TechnicalAgent 的故障排查和升级处理规范
keywords: 报错,错误,接口,API,部署,超时,500,401,日志
agents: technical
enabled: true
---
```

字段说明：

- `name`：Skill 展示名称，会出现在注入给模型的 prompt 中。
- `description`：简短说明，方便 `/skills` 接口排查。
- `keywords`：触发关键词，用户消息命中后才注入；多个关键词用英文逗号或中文逗号分隔均可。
- `agents`：适用 Agent，可填 `general`、`technical`、`billing`，多个值用逗号分隔。
- `enabled`：是否启用，支持 `true/false`。

## 编写要求

- 重要规则放在文档前半部分，因为过长内容会按 prompt 预算截断。
- 一类 Skill 只描述一类职责，不要把技术、账单、通用客服规则混在一个文件里。
- 必须包含“角色定位”“处理流程”“升级条件”“禁止事项”等稳定章节。
- 对用户隐私、支付、密码、验证码、API Key、Token 等敏感信息必须写明禁止收集或禁止公开。
- 对无法保证的事项使用保守措辞，例如“通常”“预计”“需要核验后确认”。
- 对需要人工、财务、二线技术处理的场景要明确写出升级条件。

## 任务包资源（CoursePilot 自定义运行时格式）

`course_services/resources.json` 声明参考资料和回复模板，每条记录包含：
`path`（包内 Markdown/文本相对路径）、`kind`（reference/template）、
`agents`（角色列表）、`keywords`（任一命中）、`required_tools`（全部依赖）。
省略角色或关键词列表表示不限制该维度。教务流程不设置关键词，以覆盖“下午的”等续办短句。

发现阶段读取入口和资源清单，资源正文在角色/关键词匹配且工具依赖满足后读取并注入。
Agent 将实际注册工具名称传入加载器；缺少依赖时不加载对应资源，返回缺失提示，不授予额外权限。
带 SKILL.md 的目录内，参考资料、模板和清单不再被发现为独立 Skill。
路径不得越出 Skill 目录；资源限 Markdown/文本且单份最多 6000 字符，不执行脚本。
组合内容超出剩余预算时退回入口说明，避免注入被截断的工作流或模板。

`/skills` 返回资源声明，`/skills/reload` 重载声明；参考正文按需读取最新文件。
知识库检索、结构化政策和实时业务数据仍由工具提供，参考资料只解释流程和字段，不复制政策事实。
模板是模型回复指导，确定性的草稿/资格处理分支仍由程序渲染。
这不是标准 MCP 接入，也不是任意平台 Skill 格式的兼容承诺。

验证：`python -m unittest discover -s tests -p test_skill_resources.py -v`。

## 热加载入口

修改 Skill 文件后，不需要重启服务，调用：

```bash
curl -X POST http://localhost:8000/skills/reload
```

查看加载结果和解析错误：

```bash
curl http://localhost:8000/skills
```
