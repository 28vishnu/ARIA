import logging
from typing import Any, Dict
from datetime import datetime, timezone
from multimodal.message import Message

logger = logging.getLogger("aria")

class InputManager:
    def normalize(self, session_id: str, modality: str, raw_content: Any, metadata: Optional[Dict[str, Any]] = None) -> Message:
        """Detects, validates, and normalizes incoming payloads into a unified Message object."""
        modality = modality.lower().strip()
        valid_modalities = {"text", "voice", "image", "document", "audio"}
        
        if modality not in valid_modalities:
            logger.warning("[InputManager] Unknown modality '%s' defaulted to text.", modality)
            modality = "text"

        metadata = metadata or {}
        logger.info("[InputManager] Normalized incoming message | Session: %s | Modality: %s", session_id, modality)
        
        return Message(
            session_id=session_id,
            modality=modality,
            content=raw_content,
            metadata=metadata,
            timestamp=datetime.now(timezone.utc)
        )
