import logging

logger = logging.getLogger("aria")


class ConfidenceRouter:
    """
    Centralized confidence-based routing policy for ARIA.

    The router does not execute actions itself.
    It only determines what the cognitive system should do
    with the current confidence level.

    High confidence:
        Execute/respond directly.

    Medium confidence:
        Retrieve additional evidence and reassess.

    Low confidence:
        Ask the user for clarification.
    """

    HIGH_CONFIDENCE = 0.90
    MEDIUM_CONFIDENCE = 0.70

    DIRECT_EXECUTE = "direct_execute"
    RETRIEVE_MORE = "retrieve_more"
    ASK_CLARIFICATION = "ask_clarification"

    @classmethod
    def route(cls, confidence: float) -> str:
        """
        Determine the next cognitive path from a confidence score.

        Confidence is normalized to the valid range [0.0, 1.0]
        so malformed upstream values cannot break routing.
        """

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            logger.warning(
                "[ConfidenceRouter] Invalid confidence value: %r",
                confidence,
            )
            confidence = 0.0

        confidence = max(0.0, min(1.0, confidence))

        if confidence >= cls.HIGH_CONFIDENCE:
            logger.info(
                "[ConfidenceRouter] High confidence %.2f -> %s",
                confidence,
                cls.DIRECT_EXECUTE,
            )
            return cls.DIRECT_EXECUTE

        if confidence >= cls.MEDIUM_CONFIDENCE:
            logger.info(
                "[ConfidenceRouter] Medium confidence %.2f -> %s",
                confidence,
                cls.RETRIEVE_MORE,
            )
            return cls.RETRIEVE_MORE

        logger.info(
            "[ConfidenceRouter] Low confidence %.2f -> %s",
            confidence,
            cls.ASK_CLARIFICATION,
        )
        return cls.ASK_CLARIFICATION