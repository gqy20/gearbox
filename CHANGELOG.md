# 变更日志

本文件记录 `gearbox` 开发仓中所有值得关注的版本变更。

版本号使用与发布流程一致的 `vX.Y.Z` tag。每次发布到
`gearbox-action` 时，会自动提取对应版本段落作为 Release Notes。

## [未发布]

### 变更

- 这里记录尚未发布到 `gearbox-action` 的后续改动。

## [v1.1.2] - 2026-04-26

### 变更

- 打磨 Marketplace 发布流程，让 tag 推送时能稳定同步
  `gearbox-action` 的 tags 和 Releases。
- 修正导出后的 `gearbox-action` README 示例，确保 `${{ ... }}` 片段渲染正确。
- 将发布 workflow 中的 artifact actions 升级到当前仓库使用的最新主版本。

## [v1.1.1] - 2026-04-26

### 修复

- 将 `astral-sh/setup-uv` 固定到真实存在的 `v8.1.0`，修复 Marketplace
  发布链路无法启动的问题。

## [v1.1.0] - 2026-04-26

### 新增

- 为 `audit`、`triage`、`review` 增加 reusable matrix workflows，
  让高级用户可以使用真正的 GitHub Actions 原生并行编排。

### 变更

- 拆分薄触发 workflow 和 reusable orchestrator，并重写主文档，明确轻量
  Action 用法与高级 workflow 用法的区别。
- 改进 Claude Agent SDK 的可观测性，补齐实时 flush、partial stream 和
  长任务 heartbeat 日志。
- 将 Agent 共享运行时代码收敛到 `src/gearbox/agents/shared`，删除旧的
  应用内伪并行执行路径。

## [v1.0.0] - 2026-04-26

### 新增

- 发布首个可用于 Marketplace 的 `gearbox-action` 版本，并提供统一的
  `action` 路由入口。
