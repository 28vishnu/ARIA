def adjust_confidence(current_confidence: float, feedback: str) -> float:
    fb = feedback.lower()
    if any(w in fb for w in ["wrong", "incorrect", "false", "bad"]):
        return max(0.1, round(current_confidence - 0.2, 2))
    elif any(w in fb for w in ["correct", "right", "good", "exact"]):
        return min(0.99, round(current_confidence + 0.05, 2))
    return current_confidence
