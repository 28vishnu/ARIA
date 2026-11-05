import logging

logger = logging.getLogger("aria")

class EmotionDetector:
    def detect(self, user_text: str) -> str:
        """Lightweight heuristic emotion detector based strictly on current user text."""
        lower = user_text.lower()
        if any(w in lower for w in ["awesome", "great", "thanks", "fantastic", "wonderful"]):
            return "Celebrating"
        if any(w in lower for w in ["urgent", "hurry", "quick", "asap", "fast"]):
            return "Urgent"
        if any(w in lower for w in ["wrong", "error", "fail", "broken", "frustrated"]):
            return "Frustrated"
        if any(w in lower for w in ["confused", "what", "how", "why", "unclear"]):
            return "Confused"
        return "Neutral"
