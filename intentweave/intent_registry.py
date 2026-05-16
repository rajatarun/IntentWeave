from __future__ import annotations

# Registry maps intent name → configuration.
# required_slots defines EXACTLY what slots are needed (ordered).
# needs_tool=False routes to PRESENT action (no ToolWeave call).
INTENT_REGISTRY: dict[str, dict] = {
    "book_flight": {
        "domain": "travel",
        "required_slots": ["origin", "destination", "date", "passengers"],
        "tool_name": "flight_booking",
        "needs_tool": True,
    },
    "book_hotel": {
        "domain": "travel",
        "required_slots": ["location", "check_in_date", "check_out_date", "guests"],
        "tool_name": "hotel_booking",
        "needs_tool": True,
    },
    "transfer_money": {
        "domain": "finance",
        "required_slots": ["amount", "currency", "recipient_account", "sender_account"],
        "tool_name": "payment_transfer",
        "needs_tool": True,
    },
    "get_balance": {
        "domain": "finance",
        "required_slots": ["account_id"],
        "tool_name": "account_balance",
        "needs_tool": True,
    },
    "get_weather": {
        "domain": "weather",
        "required_slots": ["location", "date"],
        "tool_name": None,
        "needs_tool": False,
    },
    "create_reminder": {
        "domain": "productivity",
        "required_slots": ["reminder_text", "reminder_datetime"],
        "tool_name": "reminder_create",
        "needs_tool": True,
    },
    "cancel_subscription": {
        "domain": "account",
        "required_slots": ["subscription_id", "reason"],
        "tool_name": "subscription_cancel",
        "needs_tool": True,
    },
    "order_product": {
        "domain": "ecommerce",
        "required_slots": ["product_id", "quantity", "shipping_address", "payment_method"],
        "tool_name": "product_order",
        "needs_tool": True,
    },
}

# Each intent maps to a list of keyword patterns.
# Routing picks the intent whose longest matching pattern appears in the message.
# Patterns must be lowercase; matching is case-insensitive.
_INTENT_PATTERNS: dict[str, list[str]] = {
    "book_flight": [
        "book a flight",
        "book flight",
        "fly to",
        "flight to",
        "plane ticket",
        "airline ticket",
        "book plane",
        "air travel",
    ],
    "book_hotel": [
        "book a hotel",
        "book hotel",
        "hotel reservation",
        "reserve hotel",
        "find a hotel",
        "find hotel",
        "stay at",
    ],
    "transfer_money": [
        "transfer money",
        "send money",
        "wire transfer",
        "bank transfer",
        "send funds",
        "money transfer",
    ],
    "get_balance": [
        "get balance",
        "check balance",
        "account balance",
        "how much in my account",
        "my balance",
        "check my balance",
    ],
    "get_weather": [
        "weather forecast",
        "get weather",
        "what is the weather",
        "weather in",
        "temperature in",
        "will it rain",
        "weather",
    ],
    "create_reminder": [
        "create a reminder",
        "create reminder",
        "set a reminder",
        "set reminder",
        "remind me",
        "set an alarm",
        "add reminder",
    ],
    "cancel_subscription": [
        "cancel subscription",
        "cancel my subscription",
        "unsubscribe",
        "cancel my plan",
        "stop subscription",
        "end my subscription",
    ],
    "order_product": [
        "order a product",
        "order product",
        "place an order",
        "place order",
        "i want to buy",
        "buy product",
        "purchase",
    ],
}


def route_intent(user_message: str) -> str | None:
    """
    Deterministic longest-pattern-wins keyword routing.
    Returns None when no pattern matches — caller must treat this as BLOCKED.
    """
    normalized = user_message.lower()
    best_intent: str | None = None
    best_length = 0

    for intent, patterns in _INTENT_PATTERNS.items():
        for pattern in patterns:
            if pattern in normalized and len(pattern) > best_length:
                best_intent = intent
                best_length = len(pattern)

    return best_intent


def get_intent_config(intent: str) -> dict:
    if intent not in INTENT_REGISTRY:
        raise KeyError(f"Unknown intent: {intent!r}")
    return INTENT_REGISTRY[intent]


def intent_needs_tool(intent: str) -> bool:
    return INTENT_REGISTRY.get(intent, {}).get("needs_tool", False)


def get_tool_name(intent: str) -> str | None:
    return INTENT_REGISTRY.get(intent, {}).get("tool_name")
