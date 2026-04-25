# Roadmap

## 现状

已完成重命名（repo-auditor → gearbox），具备：
- CLI 入口（audit / publish-issues / config）
- 4 个 MCP 工具（profile / benchmark / compare / issue）
- GitHub Actions workflow 骨架
- 基础测试覆盖

核心差距：仍是"一次性审计工具"，不是可复用的 Action 套件。

## Phase 1: 第一个 Composite Action — Triage

**目标**：消费者仓库能 `uses: gqy20/gearbox/triage@v1` 自动分类 Issue。

```
actions/
  triage/
    action.yml          # composite action 定义
    classify.py         # 分类逻辑（标签、优先级、指派）
```

**action.yml 要素**：
- inputs：`issue-number`、`repo`、`classification-rules`
- outputs：`labels`、`priority`、`assignees`
- steps：checkout → uv sync → run classify → gh api 更新 issue
- 复用现有 config/mcp 基础设施

**交付物**：
- [ ] `actions/triage/action.yml`
- [ ] `src/gearbox/tools/classify.py` + 注册到 MCP server
- [ ] `.github/workflows/triage.yml`（独立可触发 + 被 consumer 调用）
- [ ] 测试：mock gh API，验证分类输出格式
- [ ] 文档：consumer 接入示例

## Phase 2: 扩展工具链

在 Phase 1 的框架上新增 3 个工具：

| 工具 | 输入 | 输出 | 说明 |
|------|------|------|------|
| `implement.py` | issue body | diff patch | 基于 issue 描述生成代码变更 |
| `review.py` | PR diff | review comment | 自动 code review |
| `ci_fix.py` | CI log | fix commit | 解析 CI 失败并自动修复 |

每个工具遵循相同模式：`@tool()` 装饰器 → 返回 `{content, structured_output}`。

**交付物**：
- [ ] 3 个新 tool 文件 + 单元测试
- [ ] 对应的 composite action（`actions/implement/`, `actions/review/`, `actions/ci_fix/`）

## Phase 3: 配置系统

**目标**：消费者通过一份 YAML 配置接入，不需要 fork 改 workflow。

```yaml
# .github/flywheel.yml（消费者仓库）
project:
  type: backend
  language: typescript

triage: { enabled: true, auto_label: true }
review: { enabled: true, focus_areas: [security, testing] }
ci_fix: { enabled: true, max_retries: 3 }
report: { enabled: true, schedule: "weekly" }
```

**实现**：
- [ ] `src/gearbox/config/consumer.py` — 解析 flywheel.yml，合并默认值
- [ ] 各 action 读取配置决定是否执行、参数是什么
- [ ] `gearbox init` CLI 子命令 — 在消费者仓库生成模板文件

## Phase 4: 发布与治理

- [ ] Git tag + GitHub Release（语义化版本）
- [ ] Marketplace 发布（6 个 Action 分别上架）
- [ ] 成本控制：单次运行 token 上限 + 每月预算告警
- [ ] 安全护栏：禁止路径白名单、OIDC 认证替代 PAT、审计日志

## 优先级判断原则

1. **Triage 先行** — 它是飞轮入口，没有分类后面所有动作都缺乏上下文
2. **每个 Phase 可独立交付** — 不依赖后续阶段就能产生价值
3. **复用优先于新建** — config/mcp/CLI 基础设施已在，新 action 尽量复用
4. **测试先行** — 每个 tool 必须有对应的 mock 测试才能合入 main
