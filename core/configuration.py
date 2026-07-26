import os
from dataclasses import dataclass

@dataclass
class AppConfig:
    environment: str
    mongodb_uri: str
    groq_api_key: str
    gemini_api_key: str
    groq_model: str
    gemini_model: str
    tavily_api_key: str
    telegram_token: str
    vector_persist_path: str
    log_level: str
    timeout_seconds: float
    permission_mode: str

def load_config() -> AppConfig:
    return AppConfig(
        environment=os.getenv("AR_ENVIRONMENT", "production"),
        mongodb_uri=os.getenv("MONGODB_URI", ""),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
        groq_model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        gemini_model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        telegram_token=os.getenv("TELEGRAM_TOKEN", ""),
        vector_persist_path=os.getenv("RENDER_PERSISTENT_DIR", "./aria_vectors"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        timeout_seconds=float(os.getenv("AR_TIMEOUT", "15.0")),
        permission_mode=os.getenv("AR_PERMISSION_MODE", "autonomous")
    )
