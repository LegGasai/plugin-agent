---
name: maintain-project-docs
description: Maintain this plugin-agent project's README.md and AGENTS.md files as the codebase evolves. Use when Codex changes project structure, backend or frontend commands, dependency managers, plugin architecture, public SDK conventions, runtime behavior, tests, local development workflow, or any convention future agents need to know.
---

# Maintain Project Docs

## Purpose

Keep project documentation aligned with the current codebase after meaningful changes. Treat README files as user-facing onboarding and AGENTS files as working instructions for future agents.

## Workflow

1. Inspect the change surface with `git status --short`, targeted `rg`, and the files touched by the task.
2. Decide which docs are affected:
   - Root `README.md`: update product summary, repo structure, quickstart, verification, and links.
   - Root `AGENTS.md`: update monorepo boundaries, cross-project conventions, and required verification.
   - `backend/README.md`: update backend API, CLI, plugin/runtime behavior, or backend setup.
   - `backend/AGENTS.md`: update backend coding rules, SDK boundaries, tests, and plugin development conventions.
   - `frontend/AGENTS.md`: update frontend architecture, dependency manager, commands, API usage, and UI conventions.
   - `docker/README.md`: update container or compose workflows.
3. Edit only the docs whose facts changed. Avoid broad rewrites unless the existing document structure no longer fits.
4. Keep docs consistent with source of truth:
   - Commands must match `backend/pyproject.toml`, `frontend/package.json`, Docker files, and actual scripts.
   - Architecture notes must match implemented objects, APIs, directories, and plugin manifests.
   - Dependency-manager guidance must match committed lockfiles.
5. Run the smallest useful verification:
   - Backend command changes: `cd backend && uv run pytest -q`
   - Frontend command changes: `cd frontend && yarn build`
   - Skill changes: `python3 /Users/leggasai/.codex/skills/.system/skill-creator/scripts/quick_validate.py <skill-dir>`
6. In the final response, mention which docs changed and what verification ran.

## Writing Rules

- Use concise, stable prose. Do not document implementation guesses or future plans as completed facts.
- Prefer concrete commands and paths over vague descriptions.
- Keep root docs high level; put subsystem details in the matching subrepo doc.
- Preserve current project terms unless the code changed them: `PluginPackage`, `PluginInstance`, `Agent`, `Capability`, `Resource`, `plugin_agent_sdk`.
- When changing AGENTS files, write instructions for future agents, not end-user marketing copy.
- When changing README files, write for a developer trying to run or understand the project.

## Triggers To Check

Update docs when a task changes any of these:

- directory layout or file ownership
- backend CLI, API route, config, database, plugin package, plugin instance, or SDK behavior
- frontend package manager, scripts, build setup, API client, page structure, or local dev URL
- Docker or deployment commands
- test commands or required verification
- project conventions that future agents should follow
