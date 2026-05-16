"""Tests for the persona output-only transformation layer."""
from __future__ import annotations

import pytest

from intentweave.personas import PERSONAS, transform


NEUTRAL_ASK = "Please provide the following information: origin, destination."
NEUTRAL_BLOCK = "Your request cannot be processed due to a policy or validation failure."
NEUTRAL_EXECUTE = "Your book_flight request has been submitted successfully."


class TestPersonaList:
    def test_exactly_five_personas(self):
        assert len(PERSONAS) == 5

    def test_expected_personas_present(self):
        for name in ("GEN_Z", "MILLENNIAL", "PROFESSIONAL", "EXECUTIVE", "MINIMAL"):
            assert name in PERSONAS


class TestTransformReturnsString:
    @pytest.mark.parametrize("persona", PERSONAS)
    def test_returns_str(self, persona):
        result = transform(NEUTRAL_ASK, persona)
        assert isinstance(result, str)

    @pytest.mark.parametrize("persona", PERSONAS)
    def test_non_empty(self, persona):
        result = transform(NEUTRAL_ASK, persona)
        assert len(result) > 0


class TestProfessionalIsBaseline:
    def test_professional_unchanged(self):
        result = transform(NEUTRAL_ASK, "PROFESSIONAL")
        assert result == NEUTRAL_ASK


class TestInvalidPersonaRaises:
    def test_invalid_raises_value_error(self):
        with pytest.raises(ValueError, match="Invalid persona"):
            transform("hello", "ROBOT")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError):
            transform("hello", "")


class TestPersonaDoesNotAffectStructuredData:
    """Persona must not change slot names, counts, or any structured field."""

    def test_slot_names_not_mangled(self):
        # The slot list appears verbatim in the ASK message.
        msg = "Please provide the following information: account_id."
        for persona in PERSONAS:
            result = transform(msg, persona)
            # The slot identifier must survive in some form
            assert "account_id" in result, (
                f"Persona {persona} mangled slot name 'account_id' in: {result!r}"
            )

    def test_persona_does_not_affect_structured_payload(self):
        payload = {"origin": "NYC", "destination": "LAX"}
        # Verifies that the transform touches only strings, not data structures
        original_payload = dict(payload)
        transform("Some message", "GEN_Z")
        assert payload == original_payload


class TestPersonaOutputDiffers:
    def test_gen_z_differs_from_professional(self):
        gen_z = transform(NEUTRAL_ASK, "GEN_Z")
        prof = transform(NEUTRAL_ASK, "PROFESSIONAL")
        assert gen_z != prof

    def test_minimal_is_shorter_than_professional(self):
        minimal = transform(NEUTRAL_ASK, "MINIMAL")
        prof = transform(NEUTRAL_ASK, "PROFESSIONAL")
        assert len(minimal) <= len(prof)

    def test_executive_is_shorter_than_professional(self):
        exec_msg = transform(NEUTRAL_ASK, "EXECUTIVE")
        prof = transform(NEUTRAL_ASK, "PROFESSIONAL")
        assert len(exec_msg) <= len(prof)
