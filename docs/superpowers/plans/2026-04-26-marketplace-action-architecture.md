# Marketplace Action Architecture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn `gearbox` into a development repository that can export a clean Marketplace-ready `gearbox-action` bundle.

**Architecture:** Add a local router action as the canonical dispatch layer, installable composite action runtime setup, and a CLI export path that writes the release repository layout to disk. Keep internal workflows/docs pointed at real local action paths and add a release workflow for sync.

**Tech Stack:** Python 3.10+, Click CLI, composite GitHub Actions, pytest

---

### Task 1: Capture export behavior in tests

**Files:**
- Create: `tests/test_release.py`
- Modify: `tests/test_cli.py`

- [ ] Add a failing CLI help test for a new `package-marketplace` command.
- [ ] Add a failing export test that expects a generated bundle with `action.yml`, `actions/audit/action.yml`, `src/gearbox/cli.py`, `pyproject.toml`, and `README.md`.
- [ ] Add a failing export test that checks the root action routes to `./actions/audit` and the setup action installs the package from the repository root.

### Task 2: Implement export and routing support

**Files:**
- Create: `src/gearbox/release.py`
- Modify: `src/gearbox/cli.py`
- Create: `actions/main/action.yml`

- [ ] Implement a bundle builder that copies the release-safe files into an output directory.
- [ ] Add the `package-marketplace` CLI command to call the bundle builder.
- [ ] Add the main router composite action that dispatches by `with.action`.

### Task 3: Fix composite action runtime assumptions

**Files:**
- Modify: `actions/_setup/action.yml`
- Modify: `actions/publish/action.yml`

- [ ] Update setup to install the Python package from the repository root.
- [ ] Normalize nested local action references so every action uses `./actions/_setup`.

### Task 4: Align internal workflows and docs

**Files:**
- Modify: `.github/workflows/audit.yml`
- Modify: `README.md`
- Modify: `docs/index.md`
- Modify: `docs/examples/example-workflow-minimal.yml`
- Modify: `docs/examples/example-workflow.yml`

- [ ] Point internal examples and workflows to `./actions/main` or the real `./actions/*` paths.
- [ ] Update docs so `gearbox` is described as the development repo and the exported bundle as the Marketplace artifact.

### Task 5: Add release sync automation

**Files:**
- Create: `.github/workflows/release-marketplace.yml`

- [ ] Add a workflow that packages the Marketplace bundle on tag push or manual dispatch.
- [ ] Add a sync step scaffold that pushes the generated bundle to a target repository using a token and repository input.

### Task 6: Verify

**Files:**
- Test: `tests/test_cli.py`
- Test: `tests/test_release.py`

- [ ] Run focused tests for CLI and release packaging.
- [ ] Run the full pytest suite.
- [ ] Report exact verification status and any remaining follow-up items.
