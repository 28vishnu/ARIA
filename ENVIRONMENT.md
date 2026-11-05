# Environment variable reference

Provider integrations and secrets are optional until their feature is used. Set
secrets in the deployment secret manager; never commit real credentials.

| Variable | Purpose | Compatibility |
| --- | --- | --- |
| `MONGODB_URI` | MongoDB connection | Existing name retained |
| `GROQ_API_KEY`, `GEMINI_API_KEY`, `OPENROUTER_API_KEY`, `MISTRAL_API_KEY` | LLM provider credentials | Existing names retained |
| `GROQ_MODEL`, `GEMINI_MODEL`, `OPENROUTER_MODEL`, `MISTRAL_MODEL` | Provider model selection | Existing names retained |
| `TAVILY_API_KEY` | Web search | Existing name retained |
| `TELEGRAM_TOKEN` | Telegram bot | Existing name retained |
| `OPENALEX_API_KEY` | Optional higher allowance for live OpenAlex research queries | Optional; basic access does not require it according to current provider documentation |
| `JARVIS_ENVIRONMENT` | Runtime environment | Precedes legacy `AR_ENVIRONMENT` |
| `JARVIS_VECTOR_PERSIST_PATH` | Vector persistence path | Precedes legacy `RENDER_PERSISTENT_DIR` |
| `JARVIS_TIMEOUT` | Request timeout seconds | Precedes legacy `AR_TIMEOUT` |
| `JARVIS_PERMISSION_MODE` | Permission mode | Precedes legacy `AR_PERMISSION_MODE` |
| `ARIA_*` keys | Integration, scheduling, workspace, database and Android signing settings | Retained; see configuration reads in source |

Defaults and additional provider-specific variables are defined at their call sites;
this table does not replace those code-level settings.
