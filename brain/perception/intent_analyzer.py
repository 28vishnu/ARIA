import re
from brain.models.intent import Intent

GREETINGS = {"hi", "hello", "hey", "greetings", "good morning", "good evening", "good afternoon"}
SEARCH_KEYWORDS = {"search", "find", "look up", "locate"}
MEMORY_TRIGGER_WORDS = {"memory", "did i", "told you", "remember"}
DOCUMENT_TRIGGER_WORDS = {"pdf", "file", "document", "resume"}
DOCUMENT_KEYWORDS = {"summarize", "analyze", "review", "read"}
MEMORY_KEYWORDS = {"remember", "recall", "what did i"}

class IntentAnalyzer:
    def __init__(self):
        pass

    def normalize(self, query: str) -> str:
        """Strips whitespace, lowercases, and collapses multiple spaces."""
        cleaned = query.lower().strip()
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return cleaned

    def analyze(self, query: str) -> Intent:
        """Analyzes raw user text and converts it into a structured Intent object."""
        original_query = query
        normalized_query = self.normalize(query)
        
        intent_type = "conversation"
        confidence = 0.85
        requires_memory = False
        requires_documents = False
        requires_web = False
        requires_reasoning = False
        
        if normalized_query in GREETINGS or any(normalized_query.startswith(g + " ") for g in GREETINGS):
            intent_type = "greeting"
            confidence = 0.99
        elif normalized_query.endswith("?"):
            intent_type = "question"
            confidence = 0.90
            requires_reasoning = True
        elif any(w in normalized_query for w in SEARCH_KEYWORDS):
            intent_type = "search"
            confidence = 0.92
            if any(term in normalized_query for term in MEMORY_TRIGGER_WORDS):
                requires_memory = True
            if any(term in normalized_query for term in DOCUMENT_TRIGGER_WORDS):
                requires_documents = True
        elif any(w in normalized_query for w in DOCUMENT_KEYWORDS):
            intent_type = "document"
            confidence = 0.95
            requires_documents = True
            requires_reasoning = True
        elif any(w in normalized_query for w in MEMORY_KEYWORDS):
            intent_type = "memory"
            confidence = 0.94
            requires_memory = True
        else:
            intent_type = "conversation"
            confidence = 0.80

        return Intent(
            original_query=original_query,
            normalized_query=normalized_query,
            intent_type=intent_type,
            confidence=confidence,
            entities=[],
            requires_memory=requires_memory,
            requires_documents=requires_documents,
            requires_web=requires_web,
            requires_reasoning=requires_reasoning,
            metadata={},
            timestamp=0.0
        )
