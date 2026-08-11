# ReproPilot 本地启动指南

## 环境要求

- Python 3.11+
- Node.js 20.19+ 或 22.12+
- Git
- Docker Engine 与 Docker Compose v2（真实隔离执行需要）

Backend 默认采用严格执行模式。没有模型密钥、真实仓库或 Sandbox 时，相应任务会明确失败。仅在检查 DAG、状态机和界面联调时才设置 `OFFLINE_DEMO_MODE=true`；演示产物不会作为论文、Benchmark 或 Claim-Evidence 的有效证据。

## 配置

在 `ReproPilot` 目录复制配置模板：

```powershell
Copy-Item backend.env.example backend.env
```

至少检查以下变量：

| 变量 | 用途 |
|---|---|
| `OPENAI_API_KEY` | OpenAI-compatible 模型密钥；严格模式下模型任务必需 |
| `OPENAI_BASE_URL` / `OPENAI_MODEL` | 模型服务地址和模型名 |
| `OFFLINE_DEMO_MODE` | 默认 `false`；仅显式启用不可验证的界面/DAG 演示 |
| `API_AUTH_TOKEN` | 可选的对外 API Bearer Token |
| `SANDBOX_API_TOKEN` | Backend 与 Sandbox 之间的内部 Token |
| `REPOSITORY_OPERATIONS_ENABLED` | 本地是否启用真实仓库克隆；Compose 默认启用 |
| `SANDBOX_DOCKER_GPUS` | `none`、`all` 或 `device=0,1` |

## 本地开发启动

先安装依赖：

```powershell
py -3.11 -m pip install -e ".\backend[dev]"
py -3.11 -m pip install -e ".\docker-sandbox[dev]"
Set-Location frontend
npm ci
Set-Location ..
```

分别在三个终端运行：

```powershell
.\scripts\windows\start-sandbox.ps1
.\scripts\windows\start-backend.ps1
.\scripts\windows\start-frontend.ps1
```

Linux/macOS 对应命令：

```bash
./scripts/unix/start-sandbox.sh
./scripts/unix/start-backend.sh
./scripts/unix/start-frontend.sh
```

服务地址：

| 服务 | 地址 |
|---|---|
| React 工作台 | `http://localhost:5173` |
| Backend | `http://localhost:8080` |
| OpenAPI | `http://localhost:8080/docs` |
| Backend 健康检查 | `http://localhost:8080/api/health` |
| Sandbox 健康检查 | `http://localhost:8082/api/v1/health` |

Backend 健康检查会真实请求 Sandbox。配置了 `SANDBOX_URL` 但 Docker 不可用时，顶层 `ok` 会返回 `false`，不会把“只配置了地址”误报为健康。

严格模式下，`REPOSITORY_OPERATIONS_ENABLED=false` 会使仓库准备节点失败；未配置可用 Sandbox 会使运行时创建、依赖安装和代码执行节点失败。演示模式下这些节点可继续 DAG，但输出包含 `evidence_status=unverified_demo`，未执行代码不返回伪造的成功退出码。

## Docker Compose

```powershell
docker compose up --build
```

Compose 会等待 Sandbox 通过健康检查后再启动 Backend，并使用 `/tmp/repropilot-workspaces` 作为 Backend 与宿主 Docker 共同可见的受限工作区。停止服务：

```powershell
docker compose down
```

## 验证

```powershell
Set-Location backend
py -3.11 -m pytest -q
Set-Location ..\docker-sandbox
py -3.11 -m pytest -q
Set-Location ..\frontend
npm run lint
npm run build
```

真实 Docker 验收还应创建 Sandbox、运行 Python、验证超时与输出截断、删除 Sandbox，并执行一次包含仓库准备和实验节点的完整 DAG。

## 常见问题

- Backend 可启动但健康检查为 `ok=false`：检查 Docker daemon、`SANDBOX_URL` 和两端 `SANDBOX_API_TOKEN` 是否一致。
- 仓库准备失败：确认容器内存在 Git、网络可访问目标仓库，并检查 `REPOSITORY_WORKSPACE_ROOT` 是否在 Sandbox 挂载白名单内。
- 前端构建报 Node API 缺失：升级到 Node 20.19+ 或 22.12+。
- Windows 符号链接测试被跳过：当前账户没有创建 symlink 权限；其余安全测试仍会执行。
- Full reproduction 被阻止：先通过审批门禁，并确保资源探针满足 CPU、内存、磁盘和 GPU 要求。
