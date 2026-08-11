# Attention 论文 Smoke 复现示例

这个示例通过公开 API 创建并执行一条完整的论文复现 DAG，固定使用 `harvardnlp/annotated-transformer`，以 smoke 模式验证仓库发现、依赖准备、隔离执行、Artifact 和事件历史。

```text
POST /api/plan
  -> Planner / FilePlanStore
  -> POST /api/plans/:id/execute
  -> asyncio DAG Scheduler
  -> Librarian / Coder / Research Coding / Sandbox / Data
  -> Docker Sandbox
  -> Artifacts / Claim Evidence / SSE history
```

## 前置条件

先根据根目录 README 启动完整服务。真实执行需要：

- Backend 健康检查返回 `ok=true`；
- Docker Sandbox 可用；
- 可访问目标 GitHub 仓库；
- `REPOSITORY_OPERATIONS_ENABLED=true`；
- 如需模型生成，配置 OpenAI-compatible API。

## 运行

```bash
cd ReproPilot
python3 examples/paper-reproduction/run.py \
  --output /tmp/attention-paper-reproduction.json
```

远端服务可以指定地址：

```bash
python3 examples/paper-reproduction/run.py \
  --base-url http://YOUR_SERVER:8080 \
  --output /tmp/attention-paper-reproduction.json
```

脚本只使用 Python 标准库，会检查：

- 意图类型是 `Paper_Reproduction`；
- 所有 DAG 节点进入 `completed`；
- 选择了指定仓库；
- `repo_url`、`run_metrics` 和 `comparison_report` 非空；
- 事件包含 `plan_started`、`artifact_created` 和 `plan_completed`。

成功后写出不包含密钥的 JSON 摘要。摘要是本次运行证据，不应使用仓库内预置数字替代。

## 离线客户端测试

```bash
python3 -m unittest discover \
  -s examples/paper-reproduction -p 'test_*.py'
```

这个测试只验证 API 客户端逻辑，不访问模型、网络或 Docker，不能证明真实论文链已经运行。

## 边界

该示例是结构级 smoke test，不下载 WMT14、不训练完整 Transformer，也不计算论文 BLEU。CPU 小张量延迟不能外推为 GPU 训练吞吐；只有脚本本次生成的 Artifact、事件和运行元数据可以作为执行证据。
