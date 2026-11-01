# JARVIS feature inventory

This is a source-level inventory of the supplied archive, not a claim that every
feature is enabled or production-verified.

| Capability | Source areas | Evidence / limitation |
| --- | --- | --- |
| HTTP API and owner sign-in | `main.py`, `core/` | FastAPI, `/health`, `/ready`, signed owner sessions; runtime not launched here |
| Knowledge retrieval and ingestion | `brain/knowledge/` (30 files), `knowledge_engine.py` | Includes planning, evidence, freshness, structured data, graph and import modules |
| Memory and conversation | `memory_engine.py`, `conversation_manager.py`, `brain/` | Mongo/vector components are configuration-dependent |
| Planning and reasoning | `planner.py`, `reasoner.py`, `reasoning_engine.py`, `cognitive/`, `brain/` | Modules exist; end-to-end runtime verification pending |
| Actions and plugins | `actions/`, `skills/`, `plugins/` | Permission and validation components present |
| Autonomous engineering | `brain/development/`, `core/phase7_runtime.py`, `autonomy/` | Includes sandbox, approval and durable job components; live account flow unverified |
| Telegram | `main.py`, `workers.py`, `brain/telegram/` | Requires Telegram token and webhook configuration |
| Google/GitHub integrations | `integrations/` | Google modules are explicitly read-only; credentials and OAuth callback testing unavailable |
| Voice and multimodal | `audio_engine.py`, `voice_engine.py`, `multimodal/` | Optional native/model dependencies; no hardware test performed |
| Android app | `android/` | Native and embedded-web clients, sign-in/chat, notifications and voice bridge; build unavailable in this environment |
| Health and readiness | `main.py`, `core/health.py` | Separate liveness/readiness endpoints present |
| Deployment | `Dockerfile`, `.github/workflows/` | CI and Docker source present; workflow execution not available |

## Existing verification coverage

The source archive contains 84 test files. Their names cover knowledge ingestion/retrieval,
evidence handling, memory, action safety, integration routes, readiness, durable jobs,
and workflows. Tests were not deleted or modified to hide failures. Execution could
not start because the Windows `python.exe` entry resolves to an unavailable Microsoft
Store alias in this environment.
