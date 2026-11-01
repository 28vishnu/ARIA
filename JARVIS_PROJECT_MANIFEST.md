# JARVIS project manifest

## Source and audit basis

- Source archive: `ARIA-main.zip`, supplied by the user.
- Working deliverable: this directory; source archive was preserved unchanged.
- Inventory: 551 source files by recursive file listing (including hidden workflow
  files); 84 original files under `tests/`.
- Deletions: none. No repository metadata or production data was present in the archive.
- There is no Git history in the supplied archive, so no commit-level rollback point can be created here.

## Top-level map

| Path | Role |
| --- | --- |
| `main.py` | FastAPI application, middleware, lifespan and first-party endpoints |
| `core/` | Configuration, bootstrap, dependency injection, health and runtime checks |
| `brain/` | Knowledge retrieval, reasoning, memory, development and tool components |
| `integrations/` | Google read-only integrations, GitHub, alerts, workspace and provider APIs |
| `actions/`, `skills/`, `plugins/` | Permission-aware actions, skills and plugin lifecycle |
| `autonomy/`, `cognitive/` | Scheduling, proactive work, planning and orchestration |
| `personality/`, `multimodal/` | Response policy/rendering, voice, image and ingress components |
| `android/` | Gradle Android client and embedded glass-style web interface |
| `tests/` | 84 existing test files covering core, integration, knowledge and Android-adjacent behavior |
| `.github/workflows/` | Android APK workflow and knowledge audit workflow |

Detailed route and subsystem maps are in `JARVIS_ARCHITECTURE.md` and
`JARVIS_FEATURE_INVENTORY.md`. The deletion audit is in
`JARVIS_DELETION_REPORT.md`.
