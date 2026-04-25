# Composite Action 设计调研

## Action 类型对比

| 维度 | Composite Actions | JavaScript Actions | Docker Actions |
|------|------------------|-------------------|----------------|
| **运行时** | Shell (bash/pwsh/python) | Node.js | 容器 |
| **速度** | 最快（无需编译） | 快（预编译） | 最慢（镜像拉取+构建） |
| **复杂度** | 低 | 中 | 高 |
| **可移植性** | 全平台 Runner | 全平台 Runner | 通常仅 Linux |
| **分发方式** | action.yml + 脚本 | action.yml + dist/ | action.yml + Dockerfile |
| **嵌套调用** | **可调用其他 Composite** | 不可 | 不可 |
| **适用场景** | 编排、包装、胶水逻辑 | 复杂逻辑 + npm 依赖 | 完全环境隔离 |

**Gearbox 选择 Composite Actions 的理由：**
1. 可以嵌套调用其他 Composite Action（编排核心能力）
2. 可以包装第三方 Action（如 `anthropics/claude-code-action`），添加护栏
3. 无需编译步骤 — 即时迭代
4. `claude-code-action` 本身就是 Composite Action，天然适配

## Monorepo 多 Action 目录布局

```
gearbox/
├── README.md                          # 套件级别文档
├── LICENSE
│
├── actions/                           # 发布的 Action（每个可通过 uses: 引用）
│   ├── triage/action.yml             # Issue 分类排序
│   ├── implement/action.yml          # Issue → 实现 → PR
│   ├── review/action.yml             # PR Code Review
│   ├── audit/action.yml              # 仓库审计
│   ├── auto-merge/action.yml         # 条件自动合并
│   ├── report/action.yml             # 定时健康报告
│   ├── setup/action.yml              # 一键初始化
│   └── flywheel/action.yml           # 主编排器
│
├── src/                               # 共享库（可选）
│   ├── config_loader.py              # 配置文件解析器
│   ├── audit_logger.py               # 审计日志写入器
│   ├── validators.py                 # 输入校验
│   └── guards.py                     # 安全护栏
│
├── templates/                         # 预设配置
│   ├── frontend.yaml                 # 前端项目默认值
│   ├── backend.yaml                  # 后端项目默认值
│   ├── monorepo.yaml                 # Monorepo 默认值
│   └── minimal.yaml                  # 最小安全默认值
│
├── schemas/                           # JSON Schema 校验
│   └── flywheel-config.schema.json
│
├── tests/                             # 测试
│   ├── test_actions/
│   └── integration/
│
└── examples/                          # 使用示例
    ├── basic-triage.yml
    └── full-flywheel.yml
```

**消费者引用语法：**
```yaml
# 单独引用某个 Action
- uses: gqy20/gearbox/actions/triage@v1
- uses: gqy20/gearbox/actions/review@v1

# 引用主编排器
- uses: gqy20/gearbox@v1
```

## 标准 action.yml 结构

以 Triage Action 为例：

```yaml
name: 'Gearbox - Auto Triage'
description: 'AI 驱动的 Issue 自动分类、优先级排序和标签管理'
author: 'gqy20'
branding:
  icon: 'tag'
  color: 'purple'

inputs:
  # === 认证 ===
  anthropic_api_key:
    description: 'Anthropic API Key'
    required: false
  github_token:
    description: 'GitHub Token (默认 GITHUB_TOKEN)'
    required: false
    default: ${{ github.token }}

  # === 配置 ===
  config_file:
    description: '飞轮配置文件路径'
    required: false
    default: '.github/flywheel.yml'

  # === 智能默认值（可覆盖）===
  model:
    description: '使用的 Claude 模型'
    required: false
    default: 'claude-sonnet-4-6'
  max_turns:
    description: '最大对话轮次（成本护栏）'
    required: false
    default: '5'
  custom_prompt:
    description: '自定义 Prompt（覆盖默认模板）'
    required: false
    default: ''

  # === 功能开关 ===
  dry_run:
    description: '试运行模式（只输出不执行写操作）'
    required: false
    default: 'false'
  enable_audit_log:
    description: '是否写入审计日志'
    required: false
    default: 'true'

outputs:
  issue_type:
    description: '分类结果: bug/feature/docs/question/refactor'
    value: ${{ steps.main.outputs.issue_type }}
  priority:
    description: '优先级: P0/P1/P2/P3'
    value: ${{ steps.main.outputs.priority }}
  labels_added:
    description: '添加的标签列表'
    value: ${{ steps.main.outputs.labels_added }}
  should_implement:
    description: '是否建议进入实现阶段'
    value: ${{ steps.main.outputs.should_implement }}

runs:
  using: 'composite'
  steps:
    # ===== Step 1: 安全检查 — 防止无限循环 =====
    - name: '🛡️ Safety Check'
      shell: bash
      run: |
        BRANCH="${{ github.head_ref || github.ref_name }}"
        if [[ "$BRANCH" == gearbox-* || "$BRANCH" == claude-* ]]; then
          echo "::warning::Skipping - auto-generated branch detected"
          echo "skip=true" >> $GITHUB_OUTPUT
          exit 0
        fi
        echo "skip=false" >> $GITHUB_OUTPUT
      id: safety

    # ===== Step 2: 加载消费者配置 =====
    - name: '⚙️ Load Config'
      if: steps.safety.outputs.skip != 'true'
      shell: bash
      run: |
        CONFIG="${{ inputs.config_file }}"
        if [ -f "$CONFIG" ]; then
          echo "config_exists=true" >> $GITHUB_OUTPUT
          python3 -c "import yaml; yaml.safe_load(open('$CONFIG'))" || {
            echo "::error::Invalid YAML in $CONFIG"
            exit 1
          }
        else
          echo "config_exists=false" >> $GITHUB_OUTPUT
          echo "::notice::No flywheel.yml found, using defaults"
        fi
      id: config

    # ===== Step 3: 构建 Prompt =====
    - name: '📝 Build Prompt'
      if: steps.safety.outputs.skip != 'true'
      shell: bash
      env:
        ISSUE_URL: "${{ github.event.issue.html_url }}"
        CUSTOM_PROMPT: "${{ inputs.custom_prompt }}"
        DRY_RUN: "${{ inputs.dry_run }}"
      run: |
        if [ -n "$CUSTOM_PROMPT" ]; then
          PROMPT="$CUSTOM_PROMPT"
        else
          PROMPT=$(cat <<'PROMPT_EOF'
          你是 Issue 分类专家。分析以下 Issue 并执行：

          ## 分析维度
          1. **类型判断**: bug / feature / docs / question / refactor
          2. **优先级**: P0(紧急生产故障) / P1(核心功能受损) / P2(一般) / P3(优化)
          3. **复杂度**: S(<1h实现) / M(1-3天) / L(>3天)
          4. **信息完整性**: 是否需要追问

          ## 执行操作
          - 用 gh api 添加对应 labels
          - 设置优先级标签
          - 如果信息不足，评论追问
          - 如果清晰且可自动化，标记 ready-to-implement

          ## Issue 上下文
          Issue URL: ${ISSUE_URL}
          ${DRY_RUN:+## ⚠️ 试运行模式：只输出计划，不执行写操作}
          PROMPT_EOF
          )
        fi
        echo "$PROMPT" > /tmp/claude-prompt.txt
        echo "prompt_file=/tmp/claude-prompt.txt" >> $GITHUB_OUTPUT
      id: prompt

    # ===== Step 4: 调用 Claude Code Action =====
    - name: '🤖 Run Claude Code'
      if: steps.safety.outputs.skip != 'true'
      uses: anthropics/claude-code-action@v1
      with:
        anthropic_api_key: ${{ inputs.anthropic_api_key }}
        prompt: ${{ steps.prompt.outputs.prompt_file }}
        claude_args: >
          --max-turns ${{ inputs.max_turns }}
          --model ${{ inputs.model }}
          --allowedTools 'Bash(gh:*),Read,Glob,Grep'

    # ===== Step 5: 审计日志 =====
    - name: '📊 Write Audit Log'
      if: always() && inputs.enable_audit_log == 'true'
      shell: bash
      run: |
        mkdir -p .github/flywheel-audit
        cat > ".github/flywheel-audit/triage-${{ github.run_id }}.json" << EOF
        {
          "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
          "run_id": "${{ github.run_id }}",
          "action": "triage",
          "issue_number": "${{ github.event.issue.number }}",
          "actor": "${{ github.actor }}",
          "status": "${{ job.status }}"
        }
        EOF
```

## Composite Action 嵌套/编排

Composite Action **可以**调用其他 Composite Action。这是 Gearbox 的核心架构能力：

```yaml
# actions/flywheel/action.yml — 主编排器
name: 'Gearbox - Flywheel Orchestrator'
description: '读取 .github/flywheel.yml 并调度对应的子 Action'

inputs:
  anthropic_api_key:
    required: false
  config_file:
    required: false
    default: '.github/flywheel.yml'

runs:
  using: 'composite'
  steps:
    # 检测事件类型，决定调用哪个子 Action
    - name: Detect mode
      id: detect
      shell: bash
      run: |
        EVENT="${{ github.event_name }}"
        ACTION="${{ github.event.action }}"
        
        case "$EVENT" in
          issues)
            if [ "$ACTION" = "opened" ]; then
              echo "mode=triage" >> $GITHUB_OUTPUT
            elif [ "$ACTION" = "labeled" ]; then
              echo "mode=implement" >> $GITHUB_OUTPUT
            fi
            ;;
          pull_request)
            echo "mode=review" >> $GITHUB_OUTPUT
            ;;
          schedule)
            echo "mode=audit" >> $GITHUB_OUTPUT
            ;;
          check_run)
            echo "mode=auto-merge" >> $GITHUB_OUTPUT
            ;;
        esac

    # 嵌套调用子 Action（同仓库内用相对路径）
    - name: Run Triage
      if: steps.detect.outputs.mode == 'triage'
      uses: ./actions/triage
      with:
        anthropic_api_key: ${{ inputs.anthropic_api_key }}
        config_file: ${{ inputs.config_file }}

    - name: Run Implement
      if: steps.detect.outputs.mode == 'implement'
      uses: ./actions/implement
      with:
        anthropic_api_key: ${{ inputs.anthropic_api_key }}
        config_file: ${{ inputs.config_file }}

    - name: Run Review
      if: steps.detect.outputs.mode == 'review'
      uses: ./actions/review
      with:
        anthropic_api_key: ${{ inputs.anthropic_api_key }}
        config_file: ${{ inputs.config_file }}

    # ... 其他模式
```

**关键约束：** 同仓库嵌套用相对路径 `./actions/triage`；外部消费者用 `gqy20/gearbox/actions/triage@v1`。

## 版本策略

| 策略 | 优点 | 缺点 | 推荐 |
|------|------|------|------|
| **语义版本号 (`v1.2.3`)** | 标准 semver，Dependabot 兼容 | 单 tag 覆盖所有 Action | **主要方案** |
| **分支 (`main`)** | 始终最新 | 无稳定性保证 | 仅开发阶段 |
| **Commit SHA** | 最安全，不可变 | 难以维护 | 用于内部 pin 第三方 Action |

**推荐做法：**
- 仓库级语义版本：`v1.0.0`, `v1.1.0`, `v2.0.0`
- MAJOR: Action 输入/输出的破坏性变更
- MINOR: 新功能、新增 Action
- PATCH: Bug 修复、安全更新
- 每个 git tag 同时版本化所有 Action

## 包装第三方 Action 的最佳实践

### Input/Output 透传原则

1. **Inputs 向内流动：** wrapper 的 input 要么直接透传给被包装 Action，要么经过处理/转换
2. **Outputs 向外流出：** 始终重新暴露被包装 Action 的 outputs + 添加自定义 outputs
3. **环境变量遮蔽：** Composite Action 中 step 的 `env:` 会遮蔽 job 级 env 变量，需显式传递

### SHA 固定（供应链安全）

```yaml
# ✅ 正确：SHA 固定（最安全）
- uses: actions/checkout@b4ffde65f46336ab88eb5be09b00dbb74f777046

# ⚠️ 可接受：不可变 tag（Dependabot 可更新）
- uses: actions/checkout@v4

# ❌ 错误：分支引用（可变，不安全）
- uses: actions/checkout@main
```

## Sources

- [Understanding and Using Composite Actions in GitHub - Earthly Blog](https://earthly.dev/blog/composite-actions-github/)
- [Using a monorepo for your custom Github Actions - Julian Burr](https://www.julianburr.de/til/using-a-monorepo-for-your-custom-github-actions)
- [Composite Actions ADR - GitHub Runner](https://github.com/actions/runner/blob/main/docs/adrs/1144-composite-actions.md)
- [Conditional Composite ADR - GitHub Runner](https://github.com/actions/runner/blob/main/docs/adrs/1438-conditional-composite.md)
- [References in GitHub Workflows and Composite Actions - RW Aight](https://rwaight.github.io/blog/2025/08/05/github-reusable-workflow-references/)
- [How to Build Composite Actions in GitHub Actions - OneUptime](https://oneuptime.com/blog/post/2026-01-25-github-actions-composite-actions/view)
