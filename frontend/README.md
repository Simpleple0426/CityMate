# CoursePilot 课程与教务助手前端

Vue 前端默认连接 CoursePilot Python 教育版，提供课程咨询、选课规划、教务办理、费用与权益四类示例。Java 切换入口保留为旧版调试，未同步此次改造。

使用 `student_demo` 体验转班：查询可选班级、选择目标、生成草稿，再发送 `确认提交 <草稿ID>`。回复显示待教务审核申请编号，不代表真实转班、审批或扣款。详细说明见后端的 `wiki/四类Agent教务版说明.md`。

界面支持中文 Agent 标签、辅助 Agent 与路由原因展示、课程资料检索、讲义/通知导入以及教育评测。评测会调用真实模型并产生 API 用量。

教育版使用独立的浏览器设置键 `coursepilot.education.settings`，不会沿用旧版 Java 的会话。点击“新对话”会创建新会话 ID，保留学生 ID 和后端记忆；切换后端也会创建新会话。

运行 `npm test` 检查请求字段、教育版默认设置和错误处理，运行 `npm run build` 构建。启动方式见下文。内置课程目录为演示资料，学校考试安排需要导入真实通知。

## 功能

- 在页面中切换 Java / Python 后端。
- 统一适配 `/chat` 响应字段：
  - Python：`conv_id`、`agent_type`、`latency_ms`
  - Java：`conversation_id`、`agent_type`、`latency_ms`
- 支持聊天调试、健康检查、监控摘要、知识库检索、知识库文档导入、文件上传。
- 支持 Docker + Nginx 部署。

## 默认后端地址

| 后端 | 默认地址 |
|------|----------|
| Python | `http://localhost:8000` |
| Java | `http://localhost:8080` |

开发模式下，Vite 会代理：

| 前端路径 | 代理到 |
|----------|--------|
| `/api/python` | `http://localhost:8000` |
| `/api/java` | `http://localhost:8080` |

Docker 模式下，Nginx 会通过 `host.docker.internal` 访问宿主机上的 Python / Java 服务。

## 本地运行

安装依赖：

```bash
npm install
```

启动：

```bash
npm run dev
```

访问：

```text
http://localhost:5173
```

如果后端端口不是默认值，可以启动时覆盖：

```bash
VITE_PYTHON_API_URL=http://localhost:8000 \
VITE_JAVA_API_URL=http://localhost:8080 \
npm run dev
```

## Docker 部署

先构建前端静态文件：

```bash
npm run build
```

再构建并启动容器：

```bash
docker compose up -d --build
```

访问：

```text
http://localhost:5174
```

停止：

```bash
docker compose down
```

## 后端启动参考

Python 版默认：

```text
http://localhost:8000
```

Java 版默认：

```text
http://localhost:8080
```

两个后端不需要同时启动。前端页面里选择当前要调试的后端即可。
