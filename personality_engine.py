class PersonalityEngine:
    @staticmethod
    def format_response(response_text: str, tone: str = "jarvis", celebration: bool = False, encouragement: bool = False) -> str:
        """Applies a consistent, sophisticated assistant persona with dynamic tone control."""
        clean_text = response_text.strip()
        
        # Add celebratory flair if a milestone or achievement is reached
        if celebration and not any(w in clean_text.lower() for w in ["congratulations", "excellent", "brilliant"]):
            clean_text = f"Outstanding work, Sir. {clean_text}"

        # Add motivational encouragement during complex tasks
        elif encouragement and not any(w in clean_w := clean_text.lower() for w in ["keep", "push", "steady"]):
            clean_text = f"We are making solid progress, Sir. {clean_text}"

        # Ensure a polished, professional signature ending if not already present
        if not clean_text.endswith("Sir.") and not clean_text.endswith("Sir"):
            # Check if it ends with punctuation
            if clean_text.endswith(('.', '!', '?')):
                clean_text += " Standing by, Sir."
            else:
                clean_text += ", Sir."

        return clean_text
