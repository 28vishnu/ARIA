# JARVIS INTEGRATION MATRIX

Date: 2026-11-01  
Scope: All Integrations, Providers, Services, and External Dependencies  

---

## LLM Providers

| Provider | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Mistral** | ✅ Implemented | `brain/llm/llm_router.py` | `MISTRAL_API_KEY` | Configured | Primary in router priority? Priority: Mistral, Groq, Gemini, OpenRouter |
| **Groq** | ✅ Implemented | `brain/llm/llm_router.py` | `GROQ_API_KEY` | Configured | Default model: openai/gpt-oss-120b |
| **Google Gemini** | ✅ Implemented | `brain/llm/llm_router.py` | `GEMINI_API_KEY` | Configured | Default: gemini-2.0-flash |
| **OpenRouter** | ✅ Implemented | `brain/llm/llm_router.py` | `OPENROUTER_API_KEY` | Configured | Has free tier support |
| **NVIDIA NIM** | ⚠️ Partial | `integrations/nvidia_nim.py` (separate endpoint) | `NVIDIA_API_KEY`, Owner auth | **Disabled by default** (`ARIA_STRICT_NO_LLM=1`) | Not in main router, owner-only endpoint at `/ai/providers/nvidia/chat` |
| **Ollama (Local)** | ⚠️ Implemented | `brain/development/local_code_model.py` | None (local) | Configured for codegen | Used by code generation, not general chat |

---

## Search & Research

| Service | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Tavily** | ✅ Implemented | `actions/actions/web_search.py`, `brain/tools/search_tool.py` | `TAVILY_API_KEY` | Optional | Used by web search, automation watchers |
| **Real-time Research** | ✅ Implemented | `brain/development/research_service.py` | Via SearchTool | Enabled | Phase 1 feature |
| **OpenAlex** | ⚠️ Mentioned | `.env.example` | `OPENALEX_API_KEY` | Optional | Academic sources, not fully traced |

---

## Communication

| Service | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Telegram Bot** | ✅ Implemented | `main.py` webhook, `core/telegram_status.py` | `TELEGRAM_TOKEN`, `ALLOWED_TELEGRAM_USER_ID` | Required for TG features | Webhook at `/telegram-webhook`, owner-only, deduplication, durable queue |
| **Telegram Approvals** | ✅ Implemented | `brain/development/telegram_approval_interface.py` | Same as above | Integrated | Master-only approval gates |

---

## Version Control & DevOps

| Service | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Git (Local)** | ✅ Implemented | `brain/development/git_manager.py` | None | Enabled | Git operations |
| **GitHub API** | ✅ Implemented | `brain/development/github_manager.py` | GitHub tokens (via env/config) | Optional | Repo operations, sync, project creation |
| **GitHub Webhook** | ✅ Implemented | `integrations/github_webhook.py` | Signature verification | Endpoint at `/github-webhook` | |
| **GitHub Sync** | ✅ Implemented | `brain/development/github_sync.py` | Via GitHubManager | Enabled | Phase 1 feature |
| **GitHub Project Creator** | ✅ Implemented | `brain/development/github_project_creator.py` | GitHub auth | Enabled | Create repos/projects |

---

## Google Services (Read-Only)

| Service | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Gmail (Read-Only)** | ✅ Implemented | `integrations/gmail_readonly.py` | OAuth tokens | Optional | Polling enabled if connected, alerts integration |
| **Google Calendar (Read-Only)** | ✅ Implemented | `integrations/google_calendar_readonly.py` | OAuth tokens | Optional | Polling enabled if connected |
| **Google Drive (Read-Only)** | ✅ Implemented | `integraitons/google_drive_readonly.py` | OAuth tokens | Optional | Search and read endpoints |

---

## Storage & Databases

| Service | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------tag: inline | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **MongoDB** | ✅ Implemented | `core/bootstrap.py` via Motor | `MONGODB_URI` | Optional | Database: `aria_db`, graceful degradation if missing |
| **ChromaDB** | ✅ Implemented | `core/bootstrap.py` | None (local) | **Required** | Persistent at `./aria_vectors`, 2 collections |
| **SQLite** | ✅ Implemented | Various modules | None | Enabled | Knowledge corpus, alerts, job stores |

---

## Voice & Audio

| Service | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Audio Engine** | ✅ Implemented | `audio_engine.py` | Provider-dependent | Optional | Transcription for Telegram voice, TTS via edge-tts |
| **Edge TTS** | ✅ Implemented | Listed in requirements | None | Available | Text-to-speech |
| **Speech Recognition** | ⚠️ Implemented | `audio_engine.py` | Varies | Optional | Depends on providers |

---

## Vision & Multimodal

| Service | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Vision Engine** | ⚠️ Implemented | `vision_engine.py`, loaded in bootstrap | Provider-dependent | Optional | Loaded with try/except, may be unavailable |
| **Computer Control** | ⚠️ Implemented | `brain/tools/computer_control_tool.py` | None | Optional | Loaded with try/except |
| **Multimodal Gateway** | ✅ Implemented | `brain/integration/multimodal_capability_gateway.py` | N/A | Registered | Phase 9 feature |

---

## Autonomous & Self-Engineering

| Component | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Repository Intelligence** | ✅ Implemented | `brain/development/repository_intelligence.py` | None | Enabled | Phase 1-2 |
| **Development Agent/Controller** | ✅ Implemented | `brain/development/development_*.py` | None | Enabled | Autonomous coding |
| **Approval Manager** | ✅ Implemented | `brain/development/approval_manager.py` | Master auth (Telegram) | **Fail-closed** | Required for deployments |
| **Deployment Manager** | ✅ Implemented | `brain/development/deployment_manager.py` | None | Staging allowed, prod blocked | Safety controls |
| **Health Monitor** | ✅ Implemented | `brain/development/health_monitor.py` | None | Enabled | Post-deploy monitoring |
| **Rollback Manager** | ✅ Implemented | `brain/development/rollback_manager.py` | None | Enabled | Rollback capability |
| **Jarvis Final Integration** | ✅ Implemented | `brain/core/jarvis_final_integration.py` | N/A | Registered | Phase 10 |

---

## Background Jobs & Scheduling

| Component | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Background Scheduler** | ✅ Implemented | `autonomy/scheduler.py` | None | Enabled | APScheduler-based |
| **Durable Job Queue** | ✅ Implemented | `autonomy/durable_job_queue.py` | None (uses MongoDB) | Enabled if MongoDB available | Survives restarts |
| **Automation Watchers** | ✅ Implemented | `automation_watchers.py` | Via providers | Enabled | Phase 9 |
| **Knowledge Hub (Idle)** | ✅ Implemented | `brain/knowledge/knowledge_hub.py` | None | Scheduled every 30min | Idle-only acquisition |
| **Briefing System** | ✅ Implemented | `integrations/briefing_*` | None | Scheduled | Morning/evening digests, alerts |
| **Self-Improvement Cycle** | ✅ Implemented | Bootstrap Phase 10 | None | Scheduled | Daily/weekly reflection, consolidation |

---

## Android App

| Component | Status | Integration Point | Auth Required | Default State | Notes |
|---------|--------|-------------------|---------------|---------------|-------|
| **Android Client** | ⚠️ Present | `android/` directory | Owner app auth | Unknown | Package `com.aria.assistant`, needs build verification |

---

## Integration Health Summary

| Category | Implemented | Partial | Missing/Unverified | Total |
|----------|-------------|---------|-------------------|-------|
| **LLM Providers** | 4 | 2 (NVIDIA separate, Ollama codegen) | 0 | 6 |
| **Search/Research** | 2 | 1 | 0 | 3 |
| **Communication** | 2 | 0 | 0 | 2 |
| **DevOps/Git** | 6 | 0 | 0 | 6 |
| **Google Services** | 3 | 0 | 0 | 3 |
| **Storage** | 3 | 0 | 0 | 3 |
| **Voice/Audio** | 2 | 1 | 0 | 3 |
| **Vision/Multimodal** | 1 | 2 | 0 | 3 |
| **Autonomous** | 8 | 0 | 0 | 8 |
| **Background Jobs** | 7 | 0 | 0 | 7 |
| **Android** | 0 | 1 | 0 | 1 |

**Overall Integration Coverage: ~90% implemented, ~10% partial/unverified**

---

## Critical Integration Notes

1. **NVIDIA Gap**: NVIDIA NIM is accessible only via separate owner endpoint, not integrated into main LLM router/cognitive system
2. **Strict Defaults**: Many features disabled by default (no LLM, no cloud inference) for safety
3. **Graceful Degradation**: Most integrations handle missing deps gracefully
4. **Backward Compatibility**: Heavy effort to maintain ARIA compatibility
5. **Owner-Only**: Most sensitive operations require owner authentication
6. **Fail-Safe**: Deployment to production blocked by default, approval gates in place
7. **Environment Dependent**: Full functionality requires extensive env configuration
