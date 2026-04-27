# 基本用法

## CLI 命令概览

```bash
# 查看帮助
uv run gearbox --help

# 审计仓库
uv run gearbox agent audit-repo --repo owner/repo --output-dir ./audit-output

# 发布审计结果为 GitHub Issues
uv run gearbox publish-issues --input ./audit-output/issues.json

# 打包 Marketplace Action
uv run gearbox package-marketplace --output-dir ./dist/gearbox-action

# 预览版本发布说明
uv run gearbox release-notes --version v1.1.2
```

## 审计示例

```bash
# 对目标仓库执行完整审计
uv run gearbox agent audit-repo \
  --repo owner/repo \
  --benchmarks github/copilot,sourcegraph/amp \
  --output-dir ./audit-output \
  --parallel-runs 3
```

审计完成后，`output-dir` 中会包含：

| 文件 | 说明 |
| --- | --- |
| `issues.json` | 结构化的审计发现 |
| `summary.md` | 审计摘要报告 |
| `result.json` | Agent 运行结果 |

## Marketplace 调用示例

### 最简调用

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: audit
    repo: owner/repo
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

### Backlog 分类

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: backlog
    repo: owner/repo
    issues: '2,5,6'
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

### PR Review

```yaml
- uses: gqy20/gearbox-action@v1
  with:
    action: review
    repo: owner/repo
    pr_number: 456
    anthropic_api_key: ${{ secrets.ANTHROPIC_AUTH_TOKEN }}
```

更多完整示例请参考 [examples/](../examples/) 目录。
