# ReproPilot Workbench

React + TypeScript 工作台，用于创建科研计划、查看 DAG 状态、订阅 SSE、阅读 PDF，并展示节点日志、代码、指标和 Claim-to-Evidence Graph。

## 开发

需要 Node.js 20.19+ 或 22.12+。

```bash
npm ci
npm run dev
```

开发服务器默认在 `http://localhost:5173`，API 默认连接当前主机的 `8080` 端口。可通过 `VITE_API_BASE_URL` 覆盖。

## 验证

```bash
npm run lint
npm run build
```

生产镜像使用 Nginx 托管静态文件，并把 `/api/` 同源代理到 Backend；SSE 路由关闭代理缓冲。

## 主要模块

- `src/app/hooks/useReproPilotRuntime.ts`：计划执行、SSE 和节点状态同步
- `src/features/plan-graph`：DAG 布局与交互
- `src/features/execution`：日志、代码、指标和 Artifact 面板
- `src/features/claim-evidence`：Claim-to-Evidence Graph
- `src/features/pdf-viewer`：论文阅读与问答入口
- `src/services/api`：REST/SSE 客户端
