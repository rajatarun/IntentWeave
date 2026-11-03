import json
import logging
import uuid
from typing import Any

from intentweave.errors import ThreadError
from intentweave.service import ThreadService

logger = logging.getLogger(__name__)


def lambda_handler(event: dict[str, Any], context: Any, service: ThreadService) -> dict[str, Any]:
    del context
    method = _method(event)
    path = _normalize_path(event)

    if method == "GET" and path.rstrip("/") == "/health":
        return _json_response(200, {"status": "ok"})

    if method == "POST" and path.rstrip("/") == "/v1/messages":
        return _handle_messages(event, service)

    return _json_response(404, {"message": "Not Found"})


def _handle_messages(event: dict[str, Any], service: ThreadService) -> dict[str, Any]:
    request_id = f"req_{uuid.uuid4().hex[:24]}"
    try:
        body = _parse_body(event)
        message = service.handle_messages(body)
        resp = _json_response(200, message)
        resp["headers"]["x-request-id"] = request_id
        return resp
    except ThreadError as exc:
        body = exc.to_body()
        body["request_id"] = request_id
        return _json_response(exc.http_status, body)
    except json.JSONDecodeError:
        return _json_response(
            400,
            {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "message": "Invalid JSON body.",
                },
                "request_id": request_id,
            },
        )
    except Exception:
        logger.exception("Unhandled error")
        return _json_response(
            500,
            {
                "type": "error",
                "error": {"type": "api_error", "message": "Internal server error."},
                "request_id": request_id,
            },
        )


def _parse_body(event: dict[str, Any]) -> dict[str, Any]:
    raw = event.get("body") or "{}"
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8")
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        from intentweave.errors import invalid_request

        raise invalid_request("Body must be a JSON object.")
    return parsed


def _normalize_path(event: dict[str, Any]) -> str:
    path = event.get("rawPath") or event.get("path") or "/"
    ctx = event.get("requestContext") or {}
    stage = ctx.get("stage")
    if not stage or stage == "$default":
        return path
    prefix = f"/{stage}"
    if path == prefix or path.startswith(prefix + "/"):
        return path[len(prefix) :] or "/"
    return path


def _method(event: dict[str, Any]) -> str:
    ctx = event.get("requestContext") or {}
    http = ctx.get("http") or {}
    return (http.get("method") or event.get("httpMethod") or "GET").upper()


def _json_response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
