from typing import Dict, Any, Optional


class ContextBuilder:
    """
    Builds a unified context object for ARIA.

    Every component should receive the same context instead
    of collecting information independently.
    """

    async def build(
        self,
        query: str,
        session_id: str,
        user_id: str,
        base_context: Optional[Dict[str, Any]] = None,
        memory=None,
        state=None,
    ) -> Dict[str, Any]:

        ctx = dict(base_context or {})

        ctx.update({
            "query": query,
            "session_id": session_id,
            "user_id": user_id,
            "memory": memory or [],
            "state": state or {},
        })

        return ctx
