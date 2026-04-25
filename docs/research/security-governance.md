# 安全与治理

## 1. 防止无限循环（最重要！）

飞轮系统的最大风险是 Agent 生成的操作重新触发 Agent，形成死循环。

### 分支前缀隔离

**规则：** 所有 Agent 生成的分支必须有可识别的前缀。

```yaml
# 安全检查步骤（每个 Action 必须包含）
- name: Safety Check
  shell: bash
  run: |
    BRANCH="${{ github.head_ref || github.ref_name }}"
    if [[ "$BRANCH" == gearbox-* ]] || [[ "$BRANCH" == claude-* ]]; then
      echo "::warning::Skipping - auto-generated branch detected"
      echo "skip=true" >> $GITHUB_OUTPUT
      exit 0
    fi
    echo "skip=false" >> $GITHUB_OUTPUT
```

### 各 Action 的排除规则

| Action | 排除条件 | 原因 |
|--------|---------|------|
| Triage | 无需排除（只读+打标签） | 不创建分支 |
| Implement | 排除 `gearbox-*` 分支上的 Issue | 防止递归实现 |
| Review | 排除 `gearbox-*` 分支的 PR | 避免自我 review |
| CI Fix | 排除 `gearbox-*` 和 `claude-*` 分支 | **最关键**，防止修复→失败→再修复的死循环 |
| Auto-Merge | 排除 `gearbox-*` 分支的 PR | 人工审核 AI 产出 |
| Report | 无需排除（只读+创建 Issue） | 不修改代码 |

### CI Fix 死循环防护（完整示例）

```yaml
jobs:
  ci-fix:
    if: |
      github.event.workflow_run.conclusion == 'failure' &&
      github.event.workflow_run.pull_requests[0] &&
      !startsWith(github.event.workflow_run.head_branch, 'gearbox-') &&
      !startsWith(github.event.workflow_run.head_branch, 'claude-') &&
      !startsWith(github.event.workflow_run.head_branch, 'auto-fix-')
```

## 2. 成本控制

### 多层成本护栏

```
Layer 1: per-execution limit (action 级别)
Layer 2: daily budget limit (config 级别)
Layer 3: rate limiting (每小时最大次数)
Layer 4: model selection (常规用 Sonnet，复杂用 Opus)
```

### 实现

```yaml
# Layer 1: 单次执行限制
inputs:
  cost_limit_usd:
    description: '单次执行最大预估成本 (USD)'
    required: false
    default: '5.00'
  max_turns:
    description: '最大对话轮次'
    required: false
    default: '15'

# Layer 2: 日预算检查
- name: Check daily budget
  shell: bash
  env:
    DAILY_LIMIT: "${{ inputs.daily_limit_usd || '50.00' }}"
  run: |
    TODAY=$(date +%Y-%m-%d)
    SPENT=$(cat .github/flywheel-audit/${TODAY}*.json 2>/dev/null \
      | jq -r '[.[].cost_estimated_usd] | add // 0')
    
    if (( $(echo "$SPENT >= $DAILY_LIMIT" | bc -l) )); then
      echo "::error::Daily budget exceeded ($SPENT >= $DAILY_LIMIT)"
      exit 1
    fi
    echo "daily_spent=$SPENT" >> $GITHUB_OUTPUT

# Layer 3: 速率限制
- name: Rate limit check
  shell: bash
  run: |
    HOUR_AGO=$(date -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ)
    COUNT=$(gh run list \
      --workflow=flywheel.yml \
      --created ">=$HOUR_AGO" \
      --limit 100 \
      --json databaseId \
      | jq 'length')
    
    if [ "$COUNT" -ge 10 ]; then
      echo "::warning::Rate limit approached ($COUNT executions in last hour)"
      exit 1
    fi
```

### 成本参考

| 操作 | 推荐模型 | 预估成本/次 | 月频次(50PR团队) | 月成本 |
|------|---------|------------|---------------|-------|
| Triage | Sonnet 4.6 | $0.01-0.03 | ~100 | $1-3 |
| Review | Sonnet 4.6 | $0.02-0.05 | ~50 | $1-2.5 |
| Implement | Sonnet 4.6 | $0.05-0.20 | ~10 | $0.5-2 |
| CI Fix | Opus 4.7 | $0.10-0.30 | ~5 | $0.5-1.5 |
| Report | Sonnet 4.6 | $0.02-0.04 | ~30 | $0.6-1.2 |
| **合计** | | | | **~$4-10/月** |

## 3. 权限模型：最小权限原则

### 各 Action 的最小权限需求

```yaml
# Triage: 只读 + 打标签
permissions:
  contents: read
  issues: write          # labels + comments
  pull-requests: read

# Review: 只读 + 评论
permissions:
  contents: read
  pull-requests: write   # comments + reviews
  issues: read

# Implement: 写入 + 创建 PR
permissions:
  contents: write        # branch + commit + push
  pull-quests: write     # create PR
  issues: write          # update Issue status

# CI Fix: 写入 + 执行
permissions:
  contents: write
  pull-requests: write
  actions: read          # 读 CI 日志

# Report: 只读 + 创建 Issue
permissions:
  contents: read
  issues: write          # create Issue

# Auto-Merge: 合并权限
permissions:
  contents: write
  pull-requests: write
```

### 权限超限告警

```yaml
# 在 Action 内部检测权限是否过大
- name: Verify permissions
  shell: bash
  run: |
    # 如果有 admin 权限，发出警告（不阻断）
    TOKEN="${{ inputs.github_token || github.token }}"
    PERMS=$(curl -sf -H "Authorization: Bearer $TOKEN" \
      "${GITHUB_API_URL}/repos/${{ github.repository }}" \
      | jq '.permissions // {}')

    for FIELD in administration billing management; do
      if echo "$PERMS" | jq -e ".$FIELD == true" >/dev/null 2>&1; then
        echo "::warning::Action has $FIELD permission. Consider narrowing."
      fi
    done
```

## 4. OIDC 联邦认证（零 Secret 方案）

### 架构

```
Consumer Repo → Gearbox Action → OIDC Token Exchange → Cloud Provider → Claude API
                              （无需长期 Secret）
```

### AWS Bedrock 实现

```yaml
# 在你的 Composite Action 中
- name: Authenticate via OIDC
  id: auth
  uses: aws-actions/configure-aws-credentials@e88078ba6c4e06ef1a0a30a01ce28b74f777046
  with:
    role-to-assume: arn:aws:iam::ACCOUNT:role/GearboxClaudeRole
    aws-region: us-east-1
    # 无需 api_key！OIDC 自动处理
```

### IAM 信任关系

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {
      "Federated": "token.actions.githubusercontent.com"
    },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com",
        "token.actions.githubusercontent.com:sub": "repo:gqy20/gearbox:environment:production"
      },
      "StringLike": {
        "token.actions.githubusercontent.com:ref": "refs/tags/v*"
      }
    }
  }]
}
```

**优势：**
- 消费者仓库中无需存储任何长期 Secret
- 短期 Token（最长 1 小时）
- 绑定到特定仓库 + Tag + 环境
- 完整审计追踪

## 5. 审计日志

### 多层审计方案

```
Layer 1: GitHub Actions 日志（自动，每步 stdout/stderr）
Layer 2: 结构化 JSON 文件（Action 写入 .github/flywheel-audit/）
Layer 3: Artifact 上传（保留 90 天）
Layer 4: GitHub Summary（Actions UI 可见）
```

### 审计数据结构

```json
{
  "metadata": {
    "timestamp": "2026-04-25T10:30:00Z",
    "run_id": "1234567890",
    "run_url": "https://github.com/owner/repo/actions/runs/1234567890",
    "workflow": "AI Flywheel",
    "event": "issues",
    "actor": "gqy20",
    "repository": "owner/repo"
  },
  "execution": {
    "action_mode": "triage",
    "session_id": "sess_abc123",
    "model_used": "claude-sonnet-4-6",
    "max_turns": "5",
    "actual_turns": 3,
    "duration_seconds": 45,
    "exit_code": "success"
  },
  "context": {
    "issue_number": 42,
    "base_ref": "main",
    "head_ref": null
  },
  "outcomes": {
    "labels_applied": ["bug", "priority-high"],
    "comments_posted": 1,
    "result_summary": "Classified as bug, P1 priority"
  },
  "security": {
    "oidc_authenticated": true,
    "cost_estimated_usd": "0.02",
    "guardrails_triggered": []
  }
}
```

### 审计日志写入步骤

```yaml
- name: Write audit log
  if: always()
  shell: bash
  run: |
    mkdir -p .github/flywheel-audit
    cat > ".github/flywheel-audit/${{ github.run_id }}.json" << 'EOF'
    {
      "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
      "run_id": "${{ github.run_id }}",
      "action": "triage",
      "actor": "${{ github.actor }}",
      "status": "${{ job.status }}",
      "cost_estimated_usd": "0.00"
    }
    EOF

- name: Upload audit artifact
  if: always()
  uses: actions/upload-artifact@v4
  with:
    name: "gearbox-audit-${{ github.run_id }}"
    path: .github/flywheel-audit/
    retention-days: 90

- name: Generate summary
  if: always()
  shell: bash
  run: |
    echo "## Gearbox Execution Report" >> "$GITHUB_STEP_SUMMARY"
    echo "" >> "$GITHUB_STEP_SUMMARY"
    echo "| Field | Value |" >> "$GITHUB_STEP_SUMMARY"
    echo "|-------|-------|" >> "$GITHUB_STEP_SUMMARY"
    echo "| Mode | Triage |" >> "$GITHUB_STEP_SUMMARY"
    echo "| Actor | @${{ github.actor }} |" >> "$GITHUB_STEP_SUMMARY"
    echo "| Status | ${{ job.status }} |" >> "$GITHUB_STEP_SUMMARY"
    echo "| Duration | ${SECONDS}s |" >> "$GITHUB_STEP_SUMMARY"
```

## 6. 禁止路径与敏感数据保护

### 配置层面

```yaml
# .github/flywheel.yml 中的 guardrails
guardrails:
  forbidden_paths:
    - ".github/"           # 不改工作流配置
    - ".env*"              # 不碰环境变量
    - "credentials/**"     # 不碰凭证
    - "*.pem"              # 不碰私钥
    - "*.key"              # 不碰密钥
    - "secrets/"           # 不碰秘密目录
  
  block_secret_patterns: true   # 检测输出中是否包含疑似 secret
  
  require_confirmation_for:
    - deleting_files
    - modifying_ci_config
    - installing_packages
```

### 运行时检测

```yaml
# 在 Claude 执行前后检查
- name: Pre-execution safety scan
  shell: bash
  run: |
    # 检查即将修改的文件是否触及禁止路径
    FORBIDDEN=(".github/" ".env" "credentials/")
    for PATH in "${FORBIDDEN[@]}"; do
      if git diff --name-only | grep -q "^$PATH"; then
        echo "::error::Attempted to modify forbidden path: $PATH"
        exit 1
      fi
    done

- name: Post-execution secret scan
  if: always()
  shell: bash
  run: |
    # 扫描 Claude 输出中是否有疑似 secret 泄露
    PATTERNS=(
      "sk-ant-[a-zA-Z0-9]{20,}"
      "-----BEGIN (RSA |EC )?PRIVATE KEY-----"
      "password\s*=\s*[\"'][^\"']+[\"']"
      "api_key\s*[:=]\s*[\"'][^\"']{20,}[\"']"
    )
    # 对最近的 git diff 进行扫描...
```

## 7. 人类始终在环中

| 操作 | 人类介入点 | 无法绕过 |
|------|-----------|---------|
| Issue 创建 | 人或外部系统 | Agent 只能分类，不能凭空创建业务 Issue |
| Ready 标记 |人或 Claude 建议（需确认） | Implement 需要 `ready-to-implement` 标签 |
| Merge 决策 | 满足条件自动合并，但前提是有 approval | Auto-Merge 要求 ≥1 approval |
| 异常处理 | 人在 loop 中随时可干预 | 所有 Action 都支持手动禁用 |
| 配置变更 | 人编辑 `.github/flywheel.yml` | Agent 不能修改自己的配置 |

## Sources

- [Securing GitHub Actions Workflows - GitHub Well-Architected Framework](https://wellarchitected.github.io/library/application-security/recommendations/actions-security/)
- [Hardening GitHub Actions: Permissions, OIDC, and Pinned Actions (Mar 2026)](https://devopsil.com/articles/2026-03-22-github-actions-security-hardening)
- [Pinning GitHub Actions to Commit SHAs - Romain Lespinasse (Feb 2026)](https://www.romainlespinasse.dev/posts/github-actions-commit-sha-pinning/)
- [GitHub Actions Security Cheat Sheet - Adaptive Enforcement Lab](https://adaptive-enforcement-lab.com/secure/github-actions-security/cheat-sheet/)
- [Protect the Repository Hosting Your GitHub Action - Jesse Houwing](https://jessehouwing.net/protect-the-repository-hosting-your-github-action/)
- [MCP Audit Logging: Tracing AI Agent Actions - Tetrate](https://tetrate.io/learn/ai/mcp/mcp-audit-logging)
- [SafeDep Gryph - Security Layer for AI Coding Agents](https://github.com/safedep/gryph)
