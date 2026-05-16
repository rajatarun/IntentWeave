"""
IntentWeave — deterministic, state-machine-driven orchestration engine.

Public API:
    configure(context_weave, tool_weave)  — wire in external clients
    handle_user_message(session_id, user_message, ...)  — process one turn
"""
from intentweave.orchestrator import configure, handle_user_message

__all__ = ["configure", "handle_user_message"]
