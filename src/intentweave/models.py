from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThreadRecord:
    """One stored assistant turn; keyed by response id."""

    response_id: str
    thread_id: str
    parent_response_id: str | None
    fingerprint: dict[str, Any]
    system: Any | None
    tools: Any | None
    messages: list[dict[str, Any]]
    model: str
    stop_reason: str
    assistant_message: dict[str, Any]
    continued: bool = False
    continue_in_flight: bool = False
    last_used_epoch: float = 0.0
    ttl_epoch: int = 0
    refused: bool = False
    paused: bool = False

    def to_item(self) -> dict[str, Any]:
        return {
            "response_id": self.response_id,
            "thread_id": self.thread_id,
            "parent_response_id": self.parent_response_id,
            "fingerprint_json": self.fingerprint,
            "system": self.system,
            "tools": self.tools,
            "messages": self.messages,
            "model": self.model,
            "stop_reason": self.stop_reason,
            "assistant_message": self.assistant_message,
            "continued": self.continued,
            "continue_in_flight": self.continue_in_flight,
            "last_used_epoch": self.last_used_epoch,
            "ttl": self.ttl_epoch,
            "refused": self.refused,
            "paused": self.paused,
        }

    @classmethod
    def from_item(cls, item: dict[str, Any]) -> "ThreadRecord":
        return cls(
            response_id=item["response_id"],
            thread_id=item["thread_id"],
            parent_response_id=item.get("parent_response_id"),
            fingerprint=item.get("fingerprint_json") or {},
            system=item.get("system"),
            tools=item.get("tools"),
            messages=item.get("messages") or [],
            model=item["model"],
            stop_reason=item.get("stop_reason", "end_turn"),
            assistant_message=item.get("assistant_message") or {},
            continued=bool(item.get("continued")),
            continue_in_flight=bool(item.get("continue_in_flight")),
            last_used_epoch=float(item.get("last_used_epoch", 0)),
            ttl_epoch=int(item.get("ttl", 0)),
            refused=bool(item.get("refused")),
            paused=bool(item.get("paused")),
        )


@dataclass
class ProviderResult:
    response_id: str
    model: str
    content: list[dict[str, Any]]
    stop_reason: str
    usage: dict[str, Any] = field(default_factory=dict)

    def as_message_dict(self) -> dict[str, Any]:
        return {
            "id": self.response_id,
            "type": "message",
            "role": "assistant",
            "model": self.model,
            "content": self.content,
            "stop_reason": self.stop_reason,
            "usage": self.usage,
        }
