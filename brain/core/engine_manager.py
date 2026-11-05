from typing import Dict, Any


class EngineManager:

    def __init__(self):
        self.engines: Dict[str, Any] = {}

    def register(self, name: str, engine: Any):
        self.engines[name] = engine

    def get(self, name: str):
        return self.engines.get(name)

    def has(self, name: str):
        return name in self.engines

    def list(self):
        return list(self.engines.keys())