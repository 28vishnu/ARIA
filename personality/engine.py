import logging
from personality.profile import PersonalityProfile
from personality.response import SystemResponse
from personality.emotion import EmotionDetector
from personality.conversation import ConversationEngine
from personality.policies import PersonalityPolicyEnforcer

logger = logging.getLogger("aria")

class PersonalityEngine:
    def __init__(self, profile: PersonalityProfile = PersonalityProfile()):
        self.profile = profile
        self.emotion_detector = EmotionDetector()
        self.conversation_engine = ConversationEngine()
        self.policy_enforcer = PersonalityPolicyEnforcer()

    def apply_personality(self, session_id: str, user_query: str, response: SystemResponse) -> str:
        """Applies presentation layers based on profile and emotion without mutating underlying facts."""
        self.conversation_engine.record_turn(session_id, user_query)
        emotion = self.emotion_detector.detect(user_query)
        
        raw_data = response.data
        tone = self.profile.tone.lower()

        # Extract core text/data representation safely
        base_content = ""
        if isinstance(raw_data, dict):
            base_content = raw_data.get("result") or raw_data.get("content") or str(raw_data)
        else:
            base_content = str(raw_data or "Operation successful.")

        # Presentation Styling (Strictly formatting/tone changes only)
        styled = base_content
        if tone == "jarvis":
            if response.success:
                styled = f"Located, Sir.\n{base_content}"
            else:
                styled = f"Unsuccessful, Sir. {response.error}"
        elif tone == "friendly":
            if emotion == "Frustrated":
                styled = f"I understand this is frustrating. Let's look at this: {base_content}"
            else:
                styled = f"Here is what I found: {base_content}"
        elif tone == "minimal":
            styled = base_content

        # Enforce safety policies
        if not self.policy_enforcer.validate_presentation(raw_data, styled):
            return base_content

        return styled
