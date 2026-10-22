# CityMate 前端

Vue 3 + Vite，统一入口 `src/App.vue`，样式为 `src/styles.css`，HTTP 客户端位于 `src/lib/http.js`。

```powershell
npm ci
npm run dev
```

默认开发端口为 15173，`/api` 和 `/uploads` 转发到 `http://localhost:18000`。可用环境变量 `CITYMATE_API_URL` 调整目标后端；已移除旧 Python/Java 双后端选择和代理。

登录使用 HttpOnly Cookie；HTTP 客户端统一处理同源凭证、CSRF 请求头、匿名刷新与错误消息。业务组件不直接保存或拼接登录 Token。

助手回复由 `src/components/MarkdownMessage.vue` 渲染，解析逻辑位于 `src/lib/markdown.js`。支持标题、列表、表格、引用、链接与代码块；宽表格可横向滚动。禁用原始 HTML，保留解析器的危险链接校验，不自动加载模型输出的远程图片；用户输入仍按纯文本显示。

助手布局位于 `src/styles.css`：大屏面板宽 420–560px，桌面高度随窗口调整，小屏为单列；回复和输入框字号为 14px。依赖更新后执行 `npm ci` 并重启开发服务，刷新页面加载新样式；容器部署需重新构建前端镜像。

```powershell
npm test
npm run build
npm run format:check
npm run format
```

测试覆盖 HTTP 客户端的登录请求、上传边界、401 行为与错误传播，以及 Markdown 排版、HTML 转义和危险链接过滤，不代表页面所有业务流程已有浏览器端自动化覆盖。

2026-10-19 展示优化验证：7 项测试通过（4 项 HTTP、3 项 Markdown），构建与格式检查通过，并在浏览器验证实际助手回复的标题、表格和加粗样式。

生产前端由本目录 `Dockerfile` 构建，`nginx.conf` 提供静态文件与 `/api` 代理。统一编排从 [项目根目录](../README.md) 的 `docker-compose.yml` 启动。
