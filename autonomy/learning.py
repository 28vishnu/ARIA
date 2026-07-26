import logging
from typing import Dict
from autonomy.models import LearningRule

logger = logging.getLogger("aria")

class LearningEngine:
    def __init__(self):
        self.rules: Dict[str, LearningRule] = {}

    def store_behavioral_rule(self, key: str, directive: str, feedback: str):
        """Stores behavioral adaptation rules distinct from factual personal memory."""
        rule = LearningRule(rule_key=key, directive=directive, source_feedback=feedback)
        self.rules[key] = rule
        logger.info("[LearningEngine] Stored behavioral rule [%s]: %s", key, directive)

    def get_directive(self, key: str) -> str:
        rule = self.rules.get(key)
        return rule.directive if rule and rule.active else ""
