from datetime import datetime, timezone, timedelta

def is_stale(expires_at: str) -> bool:
    if not expires_at: return False
    try:
        return datetime.now(timezone.utc) > datetime.fromisoformat(expires_at)
    except Exception:
        return False

def calculate_expiration(knowledge_type: str) -> str | None:
    now = datetime.now(timezone.utc)
    if knowledge_type.upper() == "DYNAMIC": return (now + timedelta(days=1)).isoformat()
    if knowledge_type.upper() == "CODE": return (now + timedelta(days=180)).isoformat()
    return None
