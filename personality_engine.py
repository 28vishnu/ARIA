import random

class PersonalityEngine:
    def __init__(self, memory_engine=None):
        self.memory_engine = memory_engine
        self.acknowledgments = [
            "Certainly.",
            "Certainly, {address}.",
            "Understood.",
            "Right away.",
            "I'll handle that.",
            "Done.",
            "Affirmative.",
            "Working on it."
        ]

    def get_system_prompt(self) -> str:
        """Returns the native elite AI-OS system behavior instructions for model generation."""
        return (
            "You are ARIA, an elite AI operating system. "
            "Speak with concise confidence. "
            "Never introduce yourself unless explicitly asked. "
            "Never sign messages. "
            "Never say 'I'm your assistant.' "
            "Avoid unnecessary apologies and excessive enthusiasm. "
            "Prioritize clarity, technical precision, and authority."
        )

    async def apply_persona(self, raw_text: str, is_major_event: bool = False) -> str:
        """Applies natural conversational variation instead of rigid repetitive suffixes."""
        cleaned = raw_text.strip()
        
        address_style = "Sir"
        if self.memory_engine and hasattr(self.memory_engine, "get_address_style"):
            address_style = await self.memory_engine.get_address_style()

        # For short or action-completion responses, optionally inject natural variety
        if len(cleaned.split()) < 4 and not cleaned.endswith((".", "!", "?")):
            template = random.choice(self.acknowledgments)
            cleaned = template.format(address=address_style)

        if is_major_event:
            cleaned += "\n\n— ARIA Neural Core"
            
        return cleaned
