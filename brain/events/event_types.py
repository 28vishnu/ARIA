"""
All event names used inside ARIA.

Never hardcode strings anywhere else.
"""

# Chat

CHAT_RECEIVED = "chat_received"

CHAT_RESPONSE = "chat_response"

# Memory

MEMORY_CREATED = "memory_created"

MEMORY_UPDATED = "memory_updated"

MEMORY_DELETED = "memory_deleted"

MEMORY_RECALLED = "memory_recalled"

# Documents

DOCUMENT_UPLOADED = "document_uploaded"

DOCUMENT_SUMMARIZED = "document_summarized"

DOCUMENT_DELETED = "document_deleted"

DOCUMENT_ANSWERED = "document_answered"

# Knowledge

KNOWLEDGE_CREATED = "knowledge_created"

KNOWLEDGE_UPDATED = "knowledge_updated"

KNOWLEDGE_GRAPH_UPDATED = "knowledge_graph_updated"

# Web

WEB_SEARCH_STARTED = "web_search_started"

WEB_SEARCH_FINISHED = "web_search_finished"

# Planner

PLAN_CREATED = "plan_created"

PLAN_STARTED = "plan_started"

PLAN_FINISHED = "plan_finished"

# Skills

SKILL_EXECUTED = "skill_executed"

# Actions

ACTION_EXECUTED = "action_executed"

# Learning

LEARNING_COMPLETED = "learning_completed"

# Reflection

SELF_REFLECTION = "self_reflection"

# Error

ERROR = "error"

# Shutdown

SYSTEM_STARTUP = "system_startup"

SYSTEM_SHUTDOWN = "system_shutdown"