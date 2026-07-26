from datetime import datetime, timezone, timedelta

def is_stale(expires_at: str) -> bool:
    """Checks if a knowledge entry has exceeded its freshness window."""
    if not expires_at:
        return False
    try:
        exp_dt = datetime.fromisoformat(expires_at)
        return datetime.now(timezone.utc) > exp_dt
    except Exception:
        return False

def calculate_expiration(knowledge_type: str) -> str | None:
    """Determines expiration timeline based on knowledge classification."""
    now = datetime.now(timezone.utc)
    if knowledge_type.upper() == "DYNAMIC":
        return (now + timedelta(days=1)).isoformat()  # Expires in 24 hours
    elif knowledge_type.upper() == "CODE":
        return (now + timedelta(days=180)).isoformat() # Expires in 6 months
    return None # STATIC / USER_MEMORY never expires automatically
