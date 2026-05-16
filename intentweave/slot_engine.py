from __future__ import annotations


def compute_missing_slots(required_slots: list[str], filled_slots: dict) -> list[str]:
    """
    Deterministic: missing = required_slots - filled_slots.keys().
    Order is preserved from required_slots.
    No inference; no defaults.
    """
    return [slot for slot in required_slots if slot not in filled_slots]


def apply_slot_updates(filled_slots: dict, slot_updates: dict) -> dict:
    """
    Merge slot_updates into filled_slots.
    Updates MUST originate from ContextWeave.analyze() slot_updates only.
    No transformation, no inference.
    """
    updated = dict(filled_slots)
    updated.update(slot_updates)
    return updated
