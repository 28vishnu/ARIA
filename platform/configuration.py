import os
from dataclasses import dataclass

@dataclass
class AppConfig:
    environment: str = os.getenv("AR_ENVIRONMENT", "production")
    mongodb_uri: str = os.getenv("MONGODB_URI", "")
    groq_api_key: str = os.getenv("GROQ_API_KEY", "")
    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    tavily_api_key: str = os.getenv("TAVILY_API_KEY", "")
    telegram_token: str = os.getenv("TELEGRAM_TOKEN", "")
    vector_persist_path: str = os.getenv("RENDER_PERSISTENT_DIR", "./aria_vectors")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    timeout_seconds: float = float(os.getenv("AR_TIMEOUT", "15.0"))

def load_config() -> AppConfig:
    return AppConfig()
