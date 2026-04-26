---
name: gh
description: GitHub CLI operations. Use for querying repository info, searching repos, managing issues and PRs, and interacting with GitHub APIs. Invoke when auditing repos or performing GitHub operations.
---

# gh — GitHub CLI

## Repository Info

```bash
# View repo overview
gh repo view <owner/repo>

# Read file content via API
gh api /repos/<owner/repo>/contents/<path>
```

## Search

```bash
# Search repositories by language and stars
gh search repos --language python --stars ">1000"

# Search code
gh search code "function_name" --repo owner/repo
```

## Issues

```bash
# View issue
gh issue view <owner/repo>/<number>

# Create issue
gh issue create --title "title" --body "body" --repo <owner/repo>

# Add labels
gh issue edit <owner/repo>/<number> --add-label "bug,high-priority"
```

## Pull Requests

```bash
# View PR
gh pr view <owner/repo>/<number>

# Create PR
gh pr create --title "title" --body "body" --base main --head branch --repo <owner/repo>

# Post review
gh pr review <owner/repo>/<number> --body "LGTM" --event APPROVE
```

## Environment

Ensure `GITHUB_TOKEN` is set (available in CI, or via `gh auth login` locally).
