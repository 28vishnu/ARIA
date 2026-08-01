"""
ARIA Global Event Types

This file contains every event that can occur inside ARIA.

All subsystems communicate only through these events.
Never hardcode event names anywhere else.
"""

# ==========================================================
# Workflow Events
# ==========================================================

WORKFLOW_STARTED = "workflow_started"
WORKFLOW_COMPLETED = "workflow_completed"
WORKFLOW_PAUSED = "workflow_paused"
WORKFLOW_RESUMED = "workflow_resumed"
WORKFLOW_CANCELLED = "workflow_cancelled"

# ==========================================================
# Task Events
# ==========================================================

TASK_STARTED = "task_started"
TASK_COMPLETED = "task_completed"
TASK_FAILED = "task_failed"
TASK_RETRY = "task_retry"
TASK_SKIPPED = "task_skipped"

# ==========================================================
# Chat Events
# ==========================================================

CHAT_STARTED = "chat_started"
CHAT_COMPLETED = "chat_completed"

USER_MESSAGE_RECEIVED = "user_message_received"
ASSISTANT_MESSAGE_GENERATED = "assistant_message_generated"

RESPONSE_GENERATED = "response_generated"

# ==========================================================
# Memory Events
# ==========================================================

MEMORY_CREATED = "memory_created"
MEMORY_UPDATED = "memory_updated"
MEMORY_DELETED = "memory_deleted"
MEMORY_RETRIEVED = "memory_retrieved"

# ==========================================================
# Knowledge Events
# ==========================================================

KNOWLEDGE_ADDED = "knowledge_added"
KNOWLEDGE_UPDATED = "knowledge_updated"
KNOWLEDGE_DELETED = "knowledge_deleted"

FACT_LEARNED = "fact_learned"
FACT_UPDATED = "fact_updated"

# ==========================================================
# Knowledge Graph Events
# ==========================================================

GRAPH_ENTITY_CREATED = "graph_entity_created"
GRAPH_ENTITY_UPDATED = "graph_entity_updated"

GRAPH_FACT_CREATED = "graph_fact_created"
GRAPH_FACT_UPDATED = "graph_fact_updated"

GRAPH_REBUILT = "graph_rebuilt"

# ==========================================================
# Document Events
# ==========================================================

DOCUMENT_UPLOADED = "document_uploaded"
DOCUMENT_INDEXED = "document_indexed"
DOCUMENT_PROCESSED = "document_processed"
DOCUMENT_SUMMARIZED = "document_summarized"
DOCUMENT_DELETED = "document_deleted"

# ==========================================================
# World Model Events
# ==========================================================

WORLD_UPDATED = "world_updated"

PERSON_ADDED = "person_added"
PROJECT_ADDED = "project_added"
GOAL_ADDED = "goal_added"
TASK_ADDED = "task_added"

# ==========================================================
# Learning Events
# ==========================================================

LEARNING_STARTED = "learning_started"
LEARNING_COMPLETED = "learning_completed"

AUTONOMOUS_LEARNING = "autonomous_learning"

# ==========================================================
# Reflection Events
# ==========================================================

REFLECTION_STARTED = "reflection_started"
REFLECTION_COMPLETED = "reflection_completed"

KNOWLEDGE_GAP_FOUND = "knowledge_gap_found"

# ==========================================================
# Skill Events
# ==========================================================

SKILL_STARTED = "skill_started"
SKILL_COMPLETED = "skill_completed"
SKILL_FAILED = "skill_failed"

# ==========================================================
# Planner Events
# ==========================================================

PLAN_CREATED = "plan_created"
PLAN_UPDATED = "plan_updated"
PLAN_COMPLETED = "plan_completed"

# ==========================================================
# Action Events
# ==========================================================

ACTION_STARTED = "action_started"
ACTION_COMPLETED = "action_completed"
ACTION_FAILED = "action_failed"

# ==========================================================
# System Events
# ==========================================================

SYSTEM_STARTED = "system_started"
SYSTEM_READY = "system_ready"
SYSTEM_SHUTDOWN = "system_shutdown"

ERROR_OCCURRED = "error_occurred"
WARNING_OCCURRED = "warning_occurred"
