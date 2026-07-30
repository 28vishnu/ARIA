from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional


@dataclass
class Decision:
    """
    Canonical execution decision produced by DecisionEngine.

    This is the single Decision contract used throughout ARIA.
    """

    # Primary execution route
    action: str
    confidence: float = 1.0

    # Additional routes that may run after the primary action
    secondary_actions: List[str] = field(
        default_factory=list
    )

    # Route-specific information
    data: Dict[str, Any] = field(
        default_factory=dict
    )

    # Executable action selected by the reasoning/decision layer.
    action_name: Optional[str] = None

    # Validated candidate parameters for that action.
    action_params: Dict[str, Any] = field(
        default_factory=dict
    )

    # Planning / execution metadata
    requires_planning: bool = False
    requires_execution: bool = False
    requires_response: bool = True

    # Selected capabilities
    selected_skills: List[str] = field(
        default_factory=list
    )
    selected_tools: List[str] = field(
        default_factory=list
    )
    selected_plugins: List[str] = field(
        default_factory=list
    )

    priority: str = "normal"

    # General extensible metadata
    metadata: Dict[str, Any] = field(
        default_factory=dict
    )

    timestamp: float = 0.0
