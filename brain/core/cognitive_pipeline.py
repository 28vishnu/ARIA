from typing import List, Dict, Any, Optional
from brain.perception.intent_analyzer import IntentAnalyzer
from brain.perception.context_builder import ContextBuilder
from brain.cognition.decision_engine import DecisionEngine
from brain.state.cognitive_state import CognitiveStateManager
from brain.models.decision import Decision

class CognitivePipeline:
    def __init__(
        self,
        intent_analyzer: IntentAnalyzer,
        context_builder: ContextBuilder,
        decision_engine: DecisionEngine,
        state_manager: CognitiveStateManager
    ):
        self.intent_analyzer = intent_analyzer
        self.context_builder = context_builder
        self.decision_engine = decision_engine
        self.state_manager = state_manager

    def process(
        self,
        query: str,
        session_id: str = "",
        user_id: str = "",
        conversation_history: Optional[List[Dict[str, Any]]] = None
    ) -> Decision:
        """Executes the complete perception and decision pipeline, synchronizing state without resetting multi-turn context."""
        # 1. Analyze intent
        intent = self.intent_analyzer.analyze(query)
        self.state_manager.set_intent(intent)

        # 2. Build context
        context = self.context_builder.build(
            intent=intent,
            session_id=session_id,
            user_id=user_id,
            conversation_history=conversation_history
        )
        self.state_manager.set_context(context)

        # 3. Make decision
        decision = self.decision_engine.decide(intent, context)
        self.state_manager.set_decision(decision)

        return decision
