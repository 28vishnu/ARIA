"""ARIA brain package.

Keep package import lightweight so offline knowledge maintenance commands do not
need to initialize unrelated AI, vision, or network integrations.
"""
from importlib import import_module

_EXPORTS = {
    "AriaBrain": ("brain.brain", "AriaBrain"),
    "BrainRequest": ("brain.models.request", "BrainRequest"),
    "EventBus": ("brain.events", "EventBus"),
    "GraphManager": ("brain.graph", "GraphManager"),
    "CacheManager": ("brain.cache", "CacheManager"),
    "DocumentIndex": ("brain.document_index", "DocumentIndex"),
    "RetrievalEngine": ("brain.retrieval", "RetrievalEngine"),
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value
