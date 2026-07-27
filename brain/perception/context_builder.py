from typing import List, Dict, Any, Optional
from brain.models.intent import Intent
from brain.models.context import Context

class ContextBuilder:
    def __init__(self):
        pass

    def build(
        self,
        intent: Optional[Intent] = None,
        session_id: str = "",
        user_id: str = "",
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        working_memory: Optional[Dict[str, Any]] = None,
        documents: Optional[List[Dict[str, Any]]] = None,
        profile: Optional[Dict[str, Any]] = None,
        environment: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        timestamp: float = 0.0
    ) -> Context:
        """Assembles available state and parameters into a unified Context object."""
        return Context(
            intent=intent,
            session_id=session_id,
            user_id=user_id,
            conversation_history=conversation_history if conversation_history is not None else [],
            working_memory=working_memory if working_memory is not None else {},
            documents=documents if documents is not None else [],
            profile=profile if profile is not None else {},
            environment=environment if environment is not None else {},
            metadata=metadata if metadata is not None else {},
            timestamp=timestamp
        )
