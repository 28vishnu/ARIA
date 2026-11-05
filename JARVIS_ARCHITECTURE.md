# JARVIS architecture

## Runtime flow

`main.py` builds the FastAPI application and wires routers and lifespan-managed
services. `core/bootstrap.py` initializes persistent providers, the dependency
registry and background jobs. HTTP routes call into integrations, actions, skills,
memory, knowledge and reasoning components. The Android application calls the
configured backend and includes an embedded web UI plus native sign-in, voice and
notification bridges.

## HTTP surface

First-party `main.py` routes include `/`, `/health`, `/ready`, `/telegram-webhook`,
`/app/login`, `/app/change-password`, `/app/notifications`, and chat endpoints
registered in the application (including `/chat`). Included routers provide:

- `/upload`
- `/execute`, `/runs`
- `/integrations/status`, `/alerts/test`
- `/overview`, `/projects`, `/notes`, `/tasks`, `/workflows`, `/research-reports`, `/workflow-runs`
- `/ai/providers/status`, `/ai/providers/nvidia/chat`
- `/jarvis/status`
- `/drive/connect`, `/drive/oauth/callback`, `/drive/status`, `/drive/search`, `/drive/file/{file_id}/text`
- `/calendar/connect`, `/calendar/oauth/callback`, `/calendar/status`
- `/gmail/connect`, `/gmail/oauth/callback`, `/gmail/status`
- `/github-webhook`
- `/account/status`, `/repositories`, `/repositories/{owner}/{repo}/workflow-runs`

The exact method and auth policy are defined at the route decorators and middleware;
this map is an orientation aid, not a replacement for those definitions. Private app
routes are protected by owner-session middleware, while explicitly public health,
sign-in, and webhook paths have separate handling.

## Persistence

- MongoDB via Motor is initialized in `core/bootstrap.py`; existing database name
  `aria_db` and collection identifiers are retained for data compatibility.
- ChromaDB uses persistent storage and legacy collections including `aria_memory`;
  the configured persistent vector path defaults to `./aria_vectors`.
- Knowledge corpus ingestion and refresh use SQLite, with default paths such as
  `data/aria_open_knowledge.sqlite3`; refresh code supports resumable run records.
- Alerts, proactive jobs and other local stores use SQLite under existing ARIA-named
  paths. These paths are intentionally not renamed in place.

No production database was included or opened during this transformation. Schema
changes and data migrations were not applied.

## Android compatibility

The package namespace and application ID remain `com.aria.assistant` to preserve the
upgrade path for existing installations. Shared-preference keys, notification IDs,
backend URLs, release URL, and signing environment variables also remain stable.
Only visible app branding was updated where applied.

## Background work and integrations

Bootstrap starts scheduled knowledge refresh and other opt-in/background services.
The `autonomy/` and `integrations/` packages contain durable job stores, alert and
briefing schedulers, read-only Google integrations, GitHub operations, and workspace
automation. External credentials and service availability are required to verify
live behavior.
