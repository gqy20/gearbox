# Gearbox Marketplace Action Architecture Design

**Date:** 2026-04-26

## Goal

Turn the current `gearbox` repository into a development source repository that can produce a clean Marketplace-ready `gearbox-action` artifact without forcing Marketplace constraints onto day-to-day development.

## Chosen Direction

- Keep `gearbox` as the development repository.
- Introduce a router action in this repository for local integration and export parity.
- Add a packaging/export command that builds a Marketplace-ready repository layout into an output directory.
- Add release automation that can sync the exported artifact to a dedicated `gearbox-action` repository.

## Repository Roles

### `gearbox`

- Source of truth for Python code, composite actions, tests, docs, and release automation.
- May contain internal workflows and research docs.
- Should not be treated as the Marketplace listing repository.

### `gearbox-action`

- Dedicated Marketplace-facing repository.
- Contains only the routed root `action.yml`, the composite actions, runtime source, minimal packaging metadata, and user-facing docs.
- Receives updates from `gearbox` through automated sync.

## Required Changes In `gearbox`

### 1. Router Layer

Create `actions/main/action.yml` as the canonical dispatcher for:

- `audit`
- `triage`
- `implement`
- `review`
- `publish`

This router is the source for the exported root `action.yml`.

### 2. Runtime Packaging

Fix action runtime assumptions so exported actions can execute on a fresh runner:

- `_setup` must install the project package from the repository root.
- nested actions must reference `./actions/_setup` consistently.
- exported artifact must include `src/`, `pyproject.toml`, and action metadata.

### 3. Export Command

Add a CLI command that writes a Marketplace-ready bundle to a target directory.

Expected output layout:

- `action.yml`
- `actions/`
- `src/`
- `pyproject.toml`
- `README.md`

### 4. Release Automation

Add a workflow in `gearbox` that:

- runs on tag push or manual dispatch
- builds the Marketplace artifact
- syncs it into the target release repository

## Non-Goals For This Change

- Creating the external `gearbox-action` repository automatically
- Publishing to Marketplace directly from this repository
- Implementing full flywheel orchestration in the root action

## Acceptance Criteria

- Local router action exists and can serve as the exported root action source.
- The repository can generate a Marketplace-ready artifact with one command.
- Internal docs and workflows reference real action paths.
- Release automation exists for syncing to a dedicated release repository.
