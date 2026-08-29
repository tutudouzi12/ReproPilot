# fastText AG News 有界论文复现

这个案例复现 *Bag of Tricks for Efficient Text Classification*（arXiv `1607.01759`）Table 1 和 Section 3.1 中的一条明确主张：在 AG News 上，`h=10` 的 fastText 分类器加入 word bigram 后，测试准确率从 `91.5%` 提升到 `92.5%`。

它不是结构 Smoke，也不要求模型自己判断成功。运行器固定论文提交当天（2016-08-09）的官方源码 commit、数据哈希、容器镜像、训练参数、数据顺序和验收阈值；Docker 完成真实训练后，由 ReproPilot 的 Claim-to-Evidence 合约独立生成结论。

## 冻结验收标准

| Criterion | Paper | Pass condition |
|---|---:|---:|
| Bigram accuracy | `92.5%` | 三次运行均值与论文值相差不超过 `1.0` 个百分点 |
| Bigram gain | `+1.0 pp` | 三次 paired runs 的平均增益不低于 `0.5 pp` |

两项均通过才会得到 `verified`；偏差较小但未通过会标记为 `partially_reproduced`，方向相反或偏差超过边界会标记为 `contradicted`。

## 实际结果

2026-08-29 的冻结 Docker 运行使用 3 个固定 shuffle seed，共执行 6 次真实训练：

- unigram 平均准确率：`91.300%`；
- bigram 平均准确率：`92.433%`；
- 平均提升：`1.133 pp`；
- 最终结论：[`verified`](results/2026-08-29-docker/README.md)。

结果目录保留每次指标、论文对照、Claim-to-Evidence Graph、环境与哈希清单，不保留约 400 MB 的临时模型，也不重新分发数据集。

## 运行

需要 Docker Engine、Python 3.11+ 和 Git。首次运行会下载约 12 MB 的 AG News 压缩包，并从固定 commit 获取 fastText 源码；真正的实验容器使用 `--network none`。

```powershell
py -3.11 examples\paper-reproduction\fasttext-ag-news\run.py `
  --output-dir tmp\fasttext-ag-news-result
```

如果源码和数据已经在本地，可以显式传入并由运行器校验：

```powershell
py -3.11 examples\paper-reproduction\fasttext-ag-news\run.py `
  --output-dir tmp\fasttext-ag-news-result `
  --source-checkout D:\path\to\fastText `
  --dataset-archive D:\path\to\ag_news_csv.tgz
```

## 离线契约测试

```powershell
py -3.11 -m pytest -q examples\paper-reproduction\fasttext-ag-news\test_run.py
```

这些测试只检查冻结配置、预处理、指标解析和确定性裁决；它们不能替代上面的真实 Docker 实验。

## 证据边界

- 只复现一个 AG News bigram 消融主张，不代表整篇论文全部复现。
- 官方脚本采用未固定种子的 Perl shuffle；本案例固定 3 个 shuffle seed 以支持重放。
- 官方源码固定到论文提交当天，但 Debian 编译环境仍不同于作者原始环境，因此不验证论文的硬件相关训练时间。
- fastText 使用 4 个异步训练线程，结果允许在预先冻结的容差内波动。
- 数据集 readme 限定研究/非商业使用；仓库只保存哈希和指标，不提交原始数据。
