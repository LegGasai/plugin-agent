# Frontend AGENTS.md

Guidance for agents working in `frontend/`.

## Scope

This subrepo is the React console for the pluginized Agent platform.

Important paths:

- `src/App.jsx`: global state and top-level navigation.
- `src/pages/`: plugin market, agent square, and workbench pages.
- `src/components/`: reusable panels such as plugin config and chat.
- `src/lib/`: API helpers and plugin metadata helpers.
- `src/styles.css`: fixed viewport console styling.

## UI Structure

Keep the global left side as navigation:

- 插件市场
- 智能体广场
- 智能体工作台

The workbench page may contain its own internal side-main layout:

- Left: current Agent plugin instance configuration.
- Right: chat runtime, including the Agent's session history rail and the active conversation.

Do not replace the global navigation with plugin configuration.

## Layout Rules

The console is a fixed viewport app:

- `html`, `body`, and `#root` must not scroll.
- Main page containers should use `overflow: hidden`.
- Lists and panels should scroll internally.

Internal scroll areas include:

- Plugin market list.
- Agent square body.
- Plugin config list.
- Session history list.
- Chat message list.
- Tool list.

## Text and Product Tone

Keep frontend UI text in Chinese unless the value is a protocol/API/model identifier.

Use dense operational UI. Do not turn the console into a landing page or marketing hero.

## API Usage

Use `src/lib/api.js` for backend calls. Keep raw fetch calls out of components unless there is a good reason. Streaming chat should use the API helper that consumes `/api/agents/{agent_id}/stream` SSE events, not a component-local fetch loop.

Agent chat sessions are loaded and mutated through `src/lib/api.js` helpers for `/api/agents/{agent_id}/sessions` and `/api/sessions/{session_id}/messages`. Components should not keep a separate persistence model for conversation history.

Plugin market tabs should keep installed and marketplace package sources distinct: installed/built-in packages come from `/api/installed-plugin-packages`, marketplace packages from `/api/marketplace/plugins`, installation from `/api/marketplace/install`, and uninstall from `DELETE /api/installed-plugin-packages/{package_id}`. The installed tab should render one active version per `package_id`; the marketplace tab may render multiple versions and should surface `installed_version`, `latest_version`, and `has_newer_version` when present.

Use `src/lib/plugins.js` for plugin labels, resource kind labels, redaction helpers, and package normalization.

Do not send `"********"` back as a real secret. Use `stripRedactedSecrets`.

Plugin instance configuration should be rendered from each package's `config_schema_ref` and `schemas` payload when available. Show schema-declared `x-secret` or `x-encrypted` fields as secret fields and keep configuration inside the Agent workbench rather than external environment variables.

Provider conflict resolution belongs in the Agent workbench runtime controls, not in plugin instance config forms. Use `src/lib/api.js` helpers for `/api/agents/{agent_id}/capability-bindings` and keep saved bindings in Agent-level `capability_bindings`.

## Verification

Run from `frontend/`:

```bash
yarn build
```

For local development:

```bash
yarn dev --host 127.0.0.1 --port 5173
```

If the backend is not on `127.0.0.1:8000`, set:

```bash
VITE_PLUGIN_AGENT_API=http://127.0.0.1:8000 yarn dev
```

Use Yarn for dependency management. Keep `yarn.lock` committed and do not add `package-lock.json`.
