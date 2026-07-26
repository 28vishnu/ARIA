class PersonalityEngine:
    @staticmethod
    def apply_persona(response_text: str, tone: str = "jarvis") -> str:
        """Enforces a consistent personal assistant tone across all generated output."""
        clean_res = response_text.strip()
        
        # Ensure polite, professional addressing if appropriate
        if not clean_res.endswith("Sir.") and not clean_res.endswith("Sir"):
            clean_res += ", Sir."
            
        return clean_res
