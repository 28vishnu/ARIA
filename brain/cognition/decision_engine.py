from brain.models.intent import Intent
from brain.models.context import Context
from brain.models.decision import Decision

class DecisionEngine:
    def __init__(self):
        pass

    def decide(self, intent: Intent, context: Context) -> Decision:
        """Determines the next execution strategy based solely on structured intent and context."""
        intent_type = intent.intent_type
        
        action = "chat"
        confidence = intent.confidence
        requires_planning = False
        requires_execution = False
        requires_response = True
        selected_skills = []
        selected_tools = []
        selected_plugins = []
        priority = "normal"

        if intent_type == "greeting":
            action = "respond"
            requires_planning = False
            requires_execution = False
        elif intent_type == "question":
            action = "answer"
            requires_planning = False
            requires_execution = True
            selected_skills = ["reasoning"]
        elif intent_type == "document":
            action = "summarize_document"
            requires_planning = True
            requires_execution = True
            selected_skills = ["document_parser"]
        elif intent_type == "memory":
            action = "recall_memory"
            requires_planning = False
            requires_execution = True
            selected_skills = ["memory_engine"]
        elif intent_type == "search":
            action = "search_documents"
            requires_planning = False
            requires_execution = True
            if intent.requires_memory:
                selected_skills.append("memory_engine")
            if intent.requires_documents:
                selected_skills.append("document_parser")
        else:
            action = "chat"
            requires_planning = False
            requires_execution = False

        return Decision(
            action=action,
            confidence=confidence,
            requires_planning=requires_planning,
            requires_execution=requires_execution,
            requires_response=requires_response,
            selected_skills=selected_skills,
            selected_tools=selected_tools,
            selected_plugins=selected_plugins,
            priority=priority,
            metadata={
                "intent_type": intent_type,
                "requires_memory": intent.requires_memory,
                "requires_documents": intent.requires_documents,
                "requires_web": intent.requires_web,
                "requires_reasoning": intent.requires_reasoning
            },
            timestamp=0.0
        )
