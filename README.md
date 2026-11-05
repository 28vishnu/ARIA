# JARVIS

**JUST A RATHER VERY INTELLIGENT SYSTEM**

JARVIS is the continued development of the ARIA assistant project. The repository
contains a FastAPI service, modular knowledge and reasoning components, integrations,
background jobs, and an Android client. Existing ARIA storage names, environment
variables, Android application ID, and service URLs remain compatible during the
branding transition.

## Run locally

Use Python 3.11 or newer, install `requirements.txt`, then start the API from this
directory with `uvicorn main:app --host 127.0.0.1 --port 8000`. Optional integrations
require their provider credentials as environment variables. Keep secrets out of
source control. The `/health` endpoint reports liveness; `/ready` reports service
readiness after application startup.

## Android

Open the `android` directory in Android Studio. The legacy application ID
`com.aria.assistant` is intentionally retained so existing installs can receive
compatible updates. Release signing continues to use the existing `ARIA_*` keystore
environment variables.

See `JARVIS_ARCHITECTURE.md`, `JARVIS_FEATURE_INVENTORY.md`, and
`JARVIS_IMPLEMENTATION_STATUS.md` for the audited project map and verified status.
For knowledge operations, see `JARVIS_KNOWLEDGE_ARCHITECTURE.md`,
`JARVIS_KNOWLEDGE_DOMAINS.md`, `JARVIS_KNOWLEDGE_SOURCES.md`,
`JARVIS_KNOWLEDGE_DATABASE.md`, `JARVIS_INGESTION_GUIDE.md`,
`JARVIS_RETRIEVAL_GUIDE.md`, `JARVIS_KNOWLEDGE_EVALUATION.md`, and
`JARVIS_KNOWLEDGE_STATUS.md`.
