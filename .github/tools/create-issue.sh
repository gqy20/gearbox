#!/usr/bin/env bash
# GitHub Issue 创建工具
# 用法: create-issue.sh <repo> <title> <body> [labels]

set -e

REPO="$1"
TITLE="$2"
BODY="$3"
LABELS="${4:-}"

# 验证必需参数
if [[ -z "$REPO" || -z "$TITLE" || -z "$BODY" ]]; then
  echo "错误: 缺少必需参数" >&2
  echo "用法: create-issue.sh <repo> <title> <body> [labels]" >&2
  exit 1
fi

# 构建创建命令
CMD=("gh" "issue" "create" "--repo" "$REPO" "--title" "$TITLE" "--body" "$BODY")

# 添加标签（如果提供）
if [[ -n "$LABELS" ]]; then
  IFS=',' read -ra LABEL_ARRAY <<< "$LABELS"
  for label in "${LABEL_ARRAY[@]}"; do
    CMD+=("--label" "$label")
  done
fi

# 执行创建
echo "正在创建 Issue: $TITLE" >&2
"${CMD[@]}"
