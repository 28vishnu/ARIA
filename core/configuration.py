import os
from dataclasses import dataclass

APP_NAME = "JARVIS"
APP_FULL_NAME = "JUST A RATHER VERY INTELLIGENT SYSTEM"


def _setting(name: str, legacy_name: str | None = None, default: str = "") -> str:
    """Read the JARVIS setting first, retaining the previous name as fallback."""
    value = os.getenv(name)
    if value is None and legacy_name:
        value = os.getenv(legacy_name)
    return default if value is None else value


@dataclass
class AppConfig:
    environment: str
    mongodb_uri: str

    # LLM providers
    groq_api_key: str
    gemini_api_key: str
    openrouter_api_key: str
    mistral_api_key: str

    # LLM models
    groq_model: str
    gemini_model: str
    openrouter_model: str
    mistral_model: str

    # External services
    tavily_api_key: str
    telegram_token: str

    # Runtime
    vector_persist_path: str
    log_level: str
    timeout_seconds: float
    permission_mode: str


def load_config() -> AppConfig:
    return AppConfig(
        environment=_setting("JARVIS_ENVIRONMENT", "AR_ENVIRONMENT", "production"),

        mongodb_uri=os.getenv(
            "MONGODB_URI",
            ""
        ),

        # LLM API keys
        groq_api_key=os.getenv(
            "GROQ_API_KEY",
            ""
        ),

        gemini_api_key=os.getenv(
            "GEMINI_API_KEY",
            ""
        ),

        openrouter_api_key=os.getenv(
            "OPENROUTER_API_KEY",
            ""
        ),

        mistral_api_key=os.getenv(
            "MISTRAL_API_KEY",
            ""
        ),

        # LLM models
        groq_model=os.getenv(
            "GROQ_MODEL",
            "openai/gpt-oss-120b"
        ),

        gemini_model=os.getenv(
            "GEMINI_MODEL",
            "gemini-2.0-flash"
        ),

        openrouter_model=os.getenv(
            "OPENROUTER_MODEL",
            "openai/gpt-oss-20b:free"
        ),

        mistral_model=os.getenv(
            "MISTRAL_MODEL",
            "mistral-small-latest"
        ),

        # Other services
        tavily_api_key=os.getenv(
            "TAVILY_API_KEY",
            ""
        ),

        telegram_token=os.getenv(
            "TELEGRAM_TOKEN",
            ""
        ),

        # Runtime configuration
        vector_persist_path=_setting(
            "JARVIS_VECTOR_PERSIST_PATH", "RENDER_PERSISTENT_DIR", "./aria_vectors"
        ),

        log_level=os.getenv(
            "LOG_LEVEL",
            "INFO"
        ),

        timeout_seconds=float(_setting("JARVIS_TIMEOUT", "AR_TIMEOUT", "15.0")),

        permission_mode=_setting("JARVIS_PERMISSION_MODE", "AR_PERMISSION_MODE", "autonomous")
    )
