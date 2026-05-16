"""Tests for the deterministic slot engine."""
from __future__ import annotations

import pytest

from intentweave.slot_engine import apply_slot_updates, compute_missing_slots


class TestComputeMissingSlots:
    def test_all_missing_when_filled_empty(self):
        required = ["origin", "destination", "date"]
        assert compute_missing_slots(required, {}) == required

    def test_none_missing_when_all_filled(self):
        required = ["origin", "destination"]
        filled = {"origin": "NYC", "destination": "LAX"}
        assert compute_missing_slots(required, filled) == []

    def test_partial_fill_returns_remaining(self):
        required = ["a", "b", "c"]
        filled = {"a": "val_a"}
        assert compute_missing_slots(required, filled) == ["b", "c"]

    def test_preserves_order_from_required(self):
        required = ["z", "a", "m"]
        filled = {"a": 1}
        assert compute_missing_slots(required, filled) == ["z", "m"]

    def test_extra_filled_keys_are_ignored(self):
        required = ["x"]
        filled = {"x": 1, "y": 2, "z": 3}
        assert compute_missing_slots(required, filled) == []

    def test_empty_required_always_returns_empty(self):
        assert compute_missing_slots([], {"a": 1}) == []

    def test_no_inference_from_related_keys(self):
        required = ["full_name"]
        filled = {"first_name": "Alice", "last_name": "Smith"}
        assert compute_missing_slots(required, filled) == ["full_name"]


class TestApplySlotUpdates:
    def test_adds_new_slots(self):
        filled = {"a": 1}
        updates = {"b": 2}
        result = apply_slot_updates(filled, updates)
        assert result == {"a": 1, "b": 2}

    def test_overwrites_existing_slot(self):
        filled = {"a": "old"}
        updates = {"a": "new"}
        result = apply_slot_updates(filled, updates)
        assert result == {"a": "new"}

    def test_does_not_mutate_original(self):
        filled = {"a": 1}
        updates = {"b": 2}
        apply_slot_updates(filled, updates)
        assert filled == {"a": 1}

    def test_empty_updates_returns_copy(self):
        filled = {"a": 1}
        result = apply_slot_updates(filled, {})
        assert result == {"a": 1}
        assert result is not filled

    def test_empty_filled_and_updates(self):
        assert apply_slot_updates({}, {}) == {}
