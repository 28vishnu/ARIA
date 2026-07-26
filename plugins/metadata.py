from dataclasses import dataclass, field
from typing import List, Dict, Any

@dataclass
class PluginManifest:
    id: str
    name: str
    version: str
    author: str
    capabilities: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    permissions: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
