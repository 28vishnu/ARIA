import logging

logger = logging.getLogger("aria")

class ConfidenceRouter:
    @staticmethod
    route(confidence: float) -> str:
        """Determines execution path based on unified subsystem confidence scores."""
        if confidence >= 0.90:
            logger.info("[ConfidenceRouter] High confidence (%.2f) -> Direct Response / Action", confidence)
            return "direct_execute"
        elif 0.70 <= confidence < 0.90:
            logger.info("[ConfidenceRouter] Medium confidence (%.2f) -> Retrieve Evidence / Rerank", confidence)
            return "retrieve_more"
        else:
            logger.info("[ConfidenceRouter] Low confidence (%.2f) -> Request User Clarification", confidence)
            return "ask_clarification"
