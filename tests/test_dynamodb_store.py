"""
Unit tests for DynamoDBSessionStore.

All DynamoDB calls are intercepted via unittest.mock — no real AWS account
or moto library required.  The tests cover:

  - Serialisation/deserialisation round-trips
  - Session get/save/delete lifecycle
  - Metadata buffer (populated by get, flushed by save, no extra WCU)
  - TTL attribute written on every save
  - Decimal ↔ int/float coercion
  - Missing-item (new session) path
"""
from __future__ import annotations

import decimal
import time
from unittest.mock import MagicMock, patch, call

import pytest

from intentweave.dynamodb_store import (
    DynamoDBSessionStore,
    _from_dynamo,
    _to_dynamo,
    _item_to_session,
    _session_to_item,
)
from intentweave.states import State
from tests.conftest import make_session


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_store(table_mock: MagicMock) -> DynamoDBSessionStore:
    """Return a DynamoDBSessionStore whose DynamoDB table is fully mocked."""
    with patch("intentweave.dynamodb_store.boto3") as mock_boto3:
        mock_boto3.resource.return_value.Table.return_value = table_mock
        store = DynamoDBSessionStore(table_name="test-table", ttl_days=7)
    return store


def _dynamo_item(session, metadata=None) -> dict:
    item = _session_to_item(session)
    if metadata:
        from intentweave.dynamodb_store import _to_dynamo
        item["metadata"] = _to_dynamo(metadata)
    return item


# ---------------------------------------------------------------------------
# Type coercion helpers
# ---------------------------------------------------------------------------

class TestToDynamo:
    def test_int_becomes_decimal(self):
        assert _to_dynamo(42) == decimal.Decimal(42)

    def test_float_becomes_decimal(self):
        assert _to_dynamo(3.14) == decimal.Decimal("3.14")

    def test_bool_preserved(self):
        assert _to_dynamo(True) is True
        assert _to_dynamo(False) is False

    def test_string_unchanged(self):
        assert _to_dynamo("hello") == "hello"

    def test_none_unchanged(self):
        assert _to_dynamo(None) is None

    def test_dict_recursive(self):
        result = _to_dynamo({"count": 5, "label": "x"})
        assert result == {"count": decimal.Decimal(5), "label": "x"}

    def test_list_recursive(self):
        result = _to_dynamo([1, 2.5, "a"])
        assert result == [decimal.Decimal(1), decimal.Decimal("2.5"), "a"]


class TestFromDynamo:
    def test_integral_decimal_to_int(self):
        assert _from_dynamo(decimal.Decimal("7")) == 7
        assert isinstance(_from_dynamo(decimal.Decimal("7")), int)

    def test_fractional_decimal_to_float(self):
        assert _from_dynamo(decimal.Decimal("3.14")) == pytest.approx(3.14)
        assert isinstance(_from_dynamo(decimal.Decimal("3.14")), float)

    def test_string_unchanged(self):
        assert _from_dynamo("hello") == "hello"

    def test_dict_recursive(self):
        result = _from_dynamo({"n": decimal.Decimal("10"), "s": "ok"})
        assert result == {"n": 10, "s": "ok"}

    def test_list_recursive(self):
        result = _from_dynamo([decimal.Decimal("1"), decimal.Decimal("2")])
        assert result == [1, 2]


# ---------------------------------------------------------------------------
# Serialisation round-trips
# ---------------------------------------------------------------------------

class TestSerialisation:
    def test_full_session_round_trip(self):
        original = make_session(
            session_id="s1",
            user_id="u1",
            state=State.CLARIFYING,
            intent="book_flight",
            domain="travel",
            required_slots=["origin", "destination", "date", "passengers"],
            filled_slots={"origin": "NYC", "passengers": 2},
            missing_slots=["destination", "date"],
            iteration_count=3,
            persona="EXECUTIVE",
        )
        item = _session_to_item(original)
        restored = _item_to_session(item)

        assert restored.session_id == original.session_id
        assert restored.user_id == original.user_id
        assert restored.intent == original.intent
        assert restored.domain == original.domain
        assert restored.state == original.state
        assert restored.iteration_count == original.iteration_count
        assert restored.required_slots == original.required_slots
        assert restored.filled_slots == original.filled_slots
        assert restored.missing_slots == original.missing_slots
        assert restored.persona == original.persona

    def test_none_intent_and_domain_omitted(self):
        s = make_session(intent=None, domain=None)
        s.intent = None
        s.domain = None
        item = _session_to_item(s)
        assert "intent" not in item
        assert "domain" not in item

    def test_none_intent_restored_as_none(self):
        s = make_session()
        s.intent = None
        s.domain = None
        item = _session_to_item(s)
        restored = _item_to_session(item)
        assert restored.intent is None
        assert restored.domain is None

    def test_iteration_count_as_decimal_in_item(self):
        s = make_session(iteration_count=5)
        item = _session_to_item(s)
        assert item["iteration_count"] == decimal.Decimal(5)

    def test_numeric_filled_slot_survives_round_trip(self):
        s = make_session(filled_slots={"passengers": 3, "amount": 99.5})
        item = _session_to_item(s)
        restored = _item_to_session(item)
        assert restored.filled_slots["passengers"] == 3
        assert restored.filled_slots["amount"] == pytest.approx(99.5)


# ---------------------------------------------------------------------------
# DynamoDBSessionStore — get
# ---------------------------------------------------------------------------

class TestGet:
    def test_returns_none_for_missing_session(self):
        table = MagicMock()
        table.get_item.return_value = {}          # no "Item" key
        store = _make_store(table)

        result = store.get("nonexistent")
        assert result is None
        table.get_item.assert_called_once_with(Key={"session_id": "nonexistent"})

    def test_returns_session_for_existing_item(self):
        session = make_session(session_id="s1", intent="book_flight")
        item = _dynamo_item(session)
        # Simulate DynamoDB returning Decimal for iteration_count
        item["iteration_count"] = decimal.Decimal(0)

        table = MagicMock()
        table.get_item.return_value = {"Item": item}
        store = _make_store(table)

        result = store.get("s1")
        assert result is not None
        assert result.session_id == "s1"
        assert result.intent == "book_flight"

    def test_get_warms_metadata_buffer(self):
        session = make_session(session_id="s1")
        item = _dynamo_item(session, metadata={"consecutive_empty_updates": decimal.Decimal(2)})

        table = MagicMock()
        table.get_item.return_value = {"Item": item}
        store = _make_store(table)

        store.get("s1")
        meta = store.get_metadata("s1")
        assert meta["consecutive_empty_updates"] == 2


# ---------------------------------------------------------------------------
# DynamoDBSessionStore — save
# ---------------------------------------------------------------------------

class TestSave:
    def test_put_item_called_with_session_data(self):
        table = MagicMock()
        store = _make_store(table)
        session = make_session(session_id="s1", intent="book_flight")

        store.save(session)

        table.put_item.assert_called_once()
        item = table.put_item.call_args.kwargs["Item"]
        assert item["session_id"] == "s1"
        assert item["intent"] == "book_flight"

    def test_ttl_written_on_save(self):
        table = MagicMock()
        store = _make_store(table)
        session = make_session(session_id="s1")

        before = int(time.time())
        store.save(session)
        after = int(time.time())

        item = table.put_item.call_args.kwargs["Item"]
        assert "ttl" in item
        ttl = int(item["ttl"])
        expected_lower = before + 7 * 86400
        expected_upper = after + 7 * 86400
        assert expected_lower <= ttl <= expected_upper

    def test_metadata_buffer_flushed_into_item(self):
        table = MagicMock()
        store = _make_store(table)
        session = make_session(session_id="s1")

        store.set_metadata("s1", "consecutive_empty_updates", 3)
        store.save(session)

        item = table.put_item.call_args.kwargs["Item"]
        assert "metadata" in item
        assert int(item["metadata"]["consecutive_empty_updates"]) == 3

    def test_empty_metadata_not_written(self):
        table = MagicMock()
        store = _make_store(table)
        session = make_session(session_id="s1")

        store.save(session)  # no metadata set

        item = table.put_item.call_args.kwargs["Item"]
        assert "metadata" not in item

    def test_single_dynamodb_write_per_save(self):
        table = MagicMock()
        store = _make_store(table)
        session = make_session(session_id="s1")

        store.set_metadata("s1", "k1", 1)
        store.set_metadata("s1", "k2", 2)
        store.save(session)

        assert table.put_item.call_count == 1


# ---------------------------------------------------------------------------
# DynamoDBSessionStore — delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete_item_called(self):
        table = MagicMock()
        store = _make_store(table)

        store.delete("s1")

        table.delete_item.assert_called_once_with(Key={"session_id": "s1"})

    def test_delete_clears_metadata_buffer(self):
        table = MagicMock()
        store = _make_store(table)

        store.set_metadata("s1", "k", 1)
        store.delete("s1")

        assert store.get_metadata("s1") == {}


# ---------------------------------------------------------------------------
# DynamoDBSessionStore — metadata buffer
# ---------------------------------------------------------------------------

class TestMetadataBuffer:
    def test_set_and_get_metadata(self):
        table = MagicMock()
        store = _make_store(table)

        store.set_metadata("s1", "consecutive_empty_updates", 1)
        assert store.get_metadata("s1") == {"consecutive_empty_updates": 1}

    def test_update_metadata_key(self):
        table = MagicMock()
        store = _make_store(table)

        store.set_metadata("s1", "k", 0)
        store.set_metadata("s1", "k", 5)
        assert store.get_metadata("s1")["k"] == 5

    def test_get_metadata_returns_empty_dict_for_unknown_session(self):
        table = MagicMock()
        store = _make_store(table)
        assert store.get_metadata("ghost") == {}

    def test_get_metadata_returns_copy(self):
        table = MagicMock()
        store = _make_store(table)
        store.set_metadata("s1", "k", 1)

        copy = store.get_metadata("s1")
        copy["k"] = 999
        assert store.get_metadata("s1")["k"] == 1  # original unaffected

    def test_no_extra_dynamo_calls_for_metadata_ops(self):
        table = MagicMock()
        store = _make_store(table)

        store.set_metadata("s1", "a", 1)
        store.set_metadata("s1", "b", 2)
        _ = store.get_metadata("s1")

        # All metadata ops should be in-memory only
        table.update_item.assert_not_called()
        table.get_item.assert_not_called()


# ---------------------------------------------------------------------------
# Full get → process → save cycle
# ---------------------------------------------------------------------------

class TestFullCycle:
    def test_metadata_survives_get_set_save_cycle(self):
        """
        Simulates one Lambda invocation:
        get() warms buffer, set_metadata() updates it, save() flushes it.
        """
        session = make_session(session_id="s1", iteration_count=1)
        item = _dynamo_item(session, metadata={"consecutive_empty_updates": decimal.Decimal(1)})

        table = MagicMock()
        table.get_item.return_value = {"Item": item}
        store = _make_store(table)

        # get — warms buffer from DynamoDB item
        fetched = store.get("s1")
        assert store.get_metadata("s1")["consecutive_empty_updates"] == 1

        # orchestrator increments the counter
        store.set_metadata("s1", "consecutive_empty_updates", 2)

        # save — flushes updated metadata into same DynamoDB item
        store.save(fetched)

        saved_item = table.put_item.call_args.kwargs["Item"]
        assert int(saved_item["metadata"]["consecutive_empty_updates"]) == 2

        # Exactly 1 get + 1 put — no extra DynamoDB calls
        assert table.get_item.call_count == 1
        assert table.put_item.call_count == 1
        table.update_item.assert_not_called()
