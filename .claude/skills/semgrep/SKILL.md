---
name: semgrep
description: Static code analysis tool for finding bugs and security issues. Use when auditing code quality, detecting OWASP vulnerabilities, or running custom code pattern matching across Python, Go, TypeScript, and many other languages.
---

# semgrep — Static Analysis

## Basic Scan

```bash
# Scan current directory
semgrep scan

# Scan specific path
semgrep scan ./src

# Scan with a specific rule/pattern
semgrep --pattern "os.system($VAR)" .
```

## Rules and Rulesets

```bash
# Use a specific ruleset
semgrep scan --config=auto        # auto-detect language
semgrep scan --config=p/security   # security rules
semgrep scan --config=python      # Python rules
semgrep scan --config=go           # Go rules
semgrep scan --config=typescript  # TS/JS rules

# Multiple configs
semgrep scan --config=p/security --config=python --config=go
```

## Output

```bash
# JSON output (for parsing)
semgrep scan --config=auto --json --output=semgrep.json

# SARIF format (for GitHub Advanced Security)
semgrep scan --config=auto --sarif --output=semgrep.sarif

# Quiet mode (only findings)
semgrep scan --quiet
```

## When to Use

- Detect bug patterns (e.g., `TODO`, hardcoded credentials, SQL injection)
- Security audits (OWASP Top 10)
- Code quality checks (unused variables, incorrect API usage)
- Run before generating audit findings

## Examples

```bash
# Security-focused scan
semgrep scan --config=p/security --severity=ERROR --json -o findings.json

# Full scan all languages
semgrep scan --config=auto --json -o semgrep.json
```
