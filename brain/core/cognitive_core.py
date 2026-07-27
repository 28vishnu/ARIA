from typing import Dict, Any
from brain.perception.intent_analyzer import IntentAnalyzer
from brain.perception.context_builder import ContextBuilder
from brain.cognition.decision_engine import DecisionEngine
from brain.state.cognitive_state import CognitiveStateManager
from brain.memory.working_memory import WorkingMemory
from brain.memory.memory_router import MemoryRouter
from brain.core.cognitive_pipeline import CognitivePipeline
from brain.planning.planner import Planner
from brain.execution.executor import Executor

class CognitiveCore:
    """The central orchestrator of ARIA 2.0, unifying perception, cognition, planning, and execution."""
    def __init__(self):
        self.state_manager = CognitiveStateManager()
        self.working_memory = WorkingMemory()
        self.memory_router = MemoryRouter(self.working_memory)
        
        self.intent_analyzer = IntentAnalyzer()
        self.context_builder = ContextBuilder()
        self.decision_engine = DecisionEngine()
        
        self.pipeline = CognitivePipeline(
            intent_analyzer=self.intent_analyzer,
            context_builder=self.context_builder,
            decision_engine=self.decision_engine,
            state_manager=self.state_manager
        )
        
        self.planner = Planner(memory_router=self.memory_router)
        self.executor = Executor()

    def process(
        self,
        query: str,
        session_id: str = "",
        user_id: str = ""
    ) -> Dict[str, Any]:
        """Orchestrates the complete end-to-end cognitive loop from raw query to execution results."""
        # 1. Run perception and decision pipeline
        decision = self.pipeline.process(query=query, session_id=session_id, user_id=user_id)
        
        # Access the synchronized context from state manager
        context = self.state_manager.context
        
        # 2. Generate execution plan
        plan = self.planner.plan(decision=decision, context=context)
        self.state_manager.set_plan(plan)
        
        # 3. Execute plan tasks
        results = self.executor.execute(plan=plan)
        
        return {
            "decision": decision,
            "plan": plan,
            "results": results
        }
