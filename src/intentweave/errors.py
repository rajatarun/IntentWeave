from dataclasses import dataclass, field
from typing import Any


@dataclass
class ThreadError(Exception):
    """Base class for thread routing errors."""

    http_status: int
    error_type: str
    message: str
    error_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def to_body(self) -> dict[str, Any]:
        body: dict[str, Any] = {
            "type": "error",
            "error": {
                "type": self.error_type,
                "message": self.message,
            },
        }
        if self.error_code or self.details:
            body["error"]["details"] = {"error_code": self.error_code, **self.details}
            if self.error_code:
                body["error"]["details"]["error_code"] = self.error_code
        return body


def thread_not_found(message: str = "Thread could not be continued.") -> ThreadError:
    return ThreadError(
        http_status=404,
        error_type="not_found_error",
        message=message,
        error_code="thread_not_found",
    )


def fingerprint_mismatch(fields: list[str]) -> ThreadError:
    joined = ", ".join(fields)
    return ThreadError(
        http_status=400,
        error_type="invalid_request_error",
        message=f"Fixed thread fields differ from create: {joined}",
        error_code="thread_fingerprint_mismatch",
        details={"mismatched_fields": fields},
    )


def already_continued() -> ThreadError:
    return ThreadError(
        http_status=400,
        error_type="invalid_request_error",
        message="This response id has already been continued.",
        error_code="thread_already_continued",
    )


def continue_in_flight() -> ThreadError:
    return ThreadError(
        http_status=400,
        error_type="invalid_request_error",
        message="A continue request from this response id is already in progress.",
        error_code="thread_continue_in_flight",
    )


def invalid_request(message: str) -> ThreadError:
    return ThreadError(
        http_status=400,
        error_type="invalid_request_error",
        message=message,
        error_code=None,
    )
