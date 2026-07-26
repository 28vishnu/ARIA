class PersonalityEngine:
    def __init__(self, memory_engine=None):
        self.memory_engine = memory_engine

    async def apply_persona(self, raw_text: str, is_major_event: bool = False) -> str:
        """Applies a concise, confident JARVIS persona dynamically adapted to user preferences."""
        cleaned = raw_text.strip()
        
        # Retrieve dynamic address style from memory if available
        address_style = "Sir"
        if self.memory_engine and hasattr(self.memory_engine, "get_address_style"):
            address_style = await self.memory_engine.get_address_style()

        # Clean up any redundant trailing punctuation before appending salutation
        cleaned = cleaned.rstrip(".")
        
        # Format with preferred address style if not already present
        if address_style and address_style.lower() not in cleaned.lower():
            cleaned = f"{cleaned}, {address_style}."
        else:
            cleaned = f"{cleaned}."

        # Only append formal signatures for major events, system reports, or greetings
        if is_major_event:
            cleaned += "\n\n— ARIA Neural Core"
            
        return cleaned
