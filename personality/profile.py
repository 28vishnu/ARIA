from dataclasses import dataclass

@dataclass
class PersonalityProfile:
    name: str = "JARVIS"
    tone: str = "confident"  # professional, friendly, developer, jarvis, minimal
    verbosity: str = "concise"  # concise, detailed, verbose
    humour: float = 0.1
    empathy: float = 0.5
    emoji_level: int = 0  # 0: none, 1: low, 2: high
    greeting_style: str = "formal"
    response_style: str = "fragmented_data"
