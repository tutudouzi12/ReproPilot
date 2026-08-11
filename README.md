# ReproPilot

一个使用 Python 构建的科研工作流 Agent。系统把用户目标转换成可执行 DAG，通过多个专业 Agent 完成资料整理、实验代码生成和结果分析，并使用 SSE 将任务状态实时推送到 React 工作台。

> 当前定位：可本地运行、可恢复的单机 Agent 研究原型，不是生产级多租户平台。

## 核心链路

```text
React Workbench
      │ REST / SSE
      ▼
FastAPI ──► Rule Planner ──► asyncio DAG Scheduler
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
             Librarian Agent     Coder Agent       Data Agent
                    │                 │                 │
                    └──────► Research Coding ◄─────────┘
                                      │
                                      ▼
                               Docker Sandbox
```

系统目前实现：

- FastAPI、SSE、附件所有权、审批门禁和 OpenAI-compatible 模型调用
- 将论文复现、框架评测、代码执行和自有数据 Benchmark 拆成可执行 DAG
- 基于 `asyncio` 的并发调度、优先级、超时、重试、取消、预算和失败依赖阻断
- `execution_id + epoch + lease` 执行租约；任务转交或取消后丢弃迟到结果
- 原子状态快照、事件历史和服务重启后的中断任务恢复
- 仓库发现、候选回退、受限工作区准备、依赖分析与运行时修复
- Research Coding Agent 的最小补丁、策略校验、SHA-256 证据、失败回滚和重跑
- 自有数据 Benchmark 的数据契约、适配器生成、三轮预检、预测校验和指标重算
- 论文主张 Rubric、Claim-to-Evidence Graph 与预算受限的 ToT 消融设计
- 独立 Docker Sandbox 的镜像/挂载白名单、网络关闭、资源限制、GPU 请求和内部 Bearer Token
- 默认严格执行模式，以及显式开启且不可充当证据的离线演示模式

## 可复现实验与验证证据

- 可信离线运行镜像预装 `torch 2.13.0+cpu`；任务容器默认关闭网络，并限制为 512 MiB 内存、1 CPU、128 PIDs、`cap-drop ALL` 与 `no-new-privileges`。
- Docker smoke 覆盖鉴权、镜像/挂载白名单、真实 Python 执行、超时、输出截断，以及成功、失败、取消后的容器清理。
- Repository Preparation 已在真实 GitHub 仓库 `karpathy/minGPT` 的固定提交 `37baab71b9abea1b76ab957409a1cc2fbfba8a26` 上验证。
- Research Coding 隔离执行完成一次受限前向传播：输出形状 `[2, 7, 64]`、参数量 `167680`，且执行后无沙箱容器泄漏。
- Benchmark Harness 已完成 preflight、execution、validation，并从预测结果重新计算 `accuracy=0.5`、`macro_f1=0.3333333333333333`。
- 严格模式缺少模型或可信运行条件时会失败并保留错误证据；`OFFLINE_DEMO_MODE=true` 的结果会明确标记为 `unverified_demo`，不会计入有效论文或 Benchmark 证据。

## 技术栈

| 层 | 技术 |
|---|---|
| Frontend | React 19、TypeScript、React Flow、Vite |
| API | Python 3.11、FastAPI、Pydantic |
| Runtime | asyncio、自研 DAG Scheduler |
| LLM | OpenAI-compatible Chat Completions API |
| Persistence | JSON snapshot、atomic replace |
| Sandbox | docker-py、独立 FastAPI 服务 |
| Test | pytest、FastAPI TestClient |

## 项目结构

```text
ReproPilot/
├── backend/                 # FastAPI、Planner、Scheduler、Agents、Store、SSE
│   ├── app/
│   └── tests/
├── docker-sandbox/          # Python Docker 隔离执行服务
│   ├── app/
│   └── tests/
├── frontend/                # React 工作台
├── scripts/                 # Windows / Unix 启动脚本
├── backend.env.example
└── docker-compose.yml
```

## 本地启动

需要 Python 3.11+、Node.js 20+。如需真实沙箱执行，还需要 Docker。

```powershell
cd ReproPilot
Copy-Item backend.env.example backend.env

py -3.11 -m pip install -e ".\backend[dev]"
py -3.11 -m pip install -e ".\docker-sandbox[dev]"

.\scripts\windows\start-sandbox.ps1
.\scripts\windows\start-backend.ps1
.\scripts\windows\start-frontend.ps1
```

默认使用严格模式：缺少模型、真实仓库或 Sandbox 的执行节点会失败，不会伪造成功。只为界面与 DAG 联调时，可显式设置 `OFFLINE_DEMO_MODE=true`；演示产物会标记为 `unverified_demo`，代码未执行时 `exit_code` 为 `null`，并从 Evidence Graph 的有效证据中排除。

也可以使用 Docker Compose：

```powershell
cd ReproPilot
Copy-Item backend.env.example backend.env
docker compose up --build
```

服务地址：

- Web UI: `http://localhost:5173`
- Backend API: `http://localhost:8080`
- API 文档: `http://localhost:8080/docs`
- Sandbox health: `http://localhost:8082/api/v1/health`

## 测试

```powershell
cd ReproPilot\backend
py -3.11 -m pytest -q

cd ..\docker-sandbox
py -3.11 -m pytest -q
```

测试覆盖 API 端到端计划执行、Agent 路由、DAG 治理、租约与恢复、论文调试、Benchmark、Claim-Evidence、Sandbox 生命周期和安全边界。

Compose 启动后可执行真实 Docker 冒烟测试：

```powershell
cd ReproPilot
py -3.11 .\scripts\docker_smoke.py
```

该脚本验证三服务健康、Sandbox 鉴权、镜像与挂载白名单、网络关闭、CPU/内存/PID/权限限制、真实 Python 执行、超时、输出截断和容器清理。

## 设计边界

- Planner 使用可审计的确定性路由和图模板；Agent 内的生成步骤通过结构化契约接入模型。
- 持久化适合单机原型；多实例部署需要替换为 PostgreSQL/Redis 并实现分布式租约。
- Docker Socket 具备较高宿主机权限，只适合受控开发环境。
- 当前沙箱默认关闭网络、限制 CPU/内存/PID、丢弃 Linux capabilities，并启用 `no-new-privileges`。

## License

[MIT](LICENSE)
