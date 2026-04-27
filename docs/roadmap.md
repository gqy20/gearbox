# Roadmap

## 当前状态

Gearbox 已完成以下核心能力：

- **Audit**：仓库审计，生成改进建议 Issues，支持多实例并行和结果选优
- **Backlog**：Issue 分类（优先级/复杂度/标签），支持过期重新评估和源码分析
- **Dispatch**：从 ready-to-implement backlog 按优先级/复杂度选择 Issue，支持 dry-run
- **Review**：PR Code Review，评分 + inline comments
- **Implement**：Issue → 分支 → PR，支持 TDD 约束和 3 次失败停止
- **Publish**：将 issues.json 发布为 GitHub Issues
- **Marketplace**：完整 Action 发布仓，支持 `gqy20/gearbox-action@v1` 一行接入

## 剩余工作

### Phase 8: Review / Implement 内部入口对齐

review 和 implement 尚未拥有与 audit/backlog 对齐的独立 workflow 内部入口。
当前 review.yml 和 implement 调用外部 reusable workflow，未使用本仓库 inline matrix 编排。

- [ ] 实现 review 内部 workflow（`review.yml`），与 audit/backlog 矩阵编排体验对齐
- [ ] 实现 implement 内部 workflow（`implement.yml`），与 audit/backlog 矩阵编排体验对齐
- [ ] Review 支持与 audit 同样的并行选优机制
- [ ] Implement 支持与 backlog 同样的 artifact 聚合和选优

### 持续改进

- [ ] Audit 发现已有 open issue 时，引导 Agent 聚焦新问题（已实现）
- [ ] Backlog `since_days` 阈值可配置化（已实现 CLI，workflow_dispatch 可配）
- [ ] 完善集成测试覆盖关键 Agent 模块（issue #19）
- [ ] pydantic 依赖清理（issue #18）
- [ ] Scanner 对纯 Python 项目不跳过 semgrep（issue #17）

## 已完成里程碑

| 版本 | 内容 |
|------|------|
| v1.1.5 | dispatch、quiet planning、workflow-entry/matrix actions、backlog 分类过期重评、源码分析、open issues 摘要 |
| v1.1.4 | Marketplace 根 action 展示名修正 |
| v1.1.3 | CI 基线、audit 预扫描、Claude Agent SDK 可观测性、backlog 统一入口 |
| v1.1.2 | Marketplace 发布流程稳定化 |
| v1.1.1 | `setup-uv` 版本固定修复 |
| v1.1.0 | 首个 Marketplace `gearbox-action` 版本 |
