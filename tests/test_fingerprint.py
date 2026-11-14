from intentweave.fingerprint import (
    FINGERPRINT_VERSION,
    attach_history_digest,
    diff_fingerprints,
    extract_fingerprint,
    fingerprint_digest,
    history_digest,
    is_legacy_fingerprint,
    legacy_model_mismatch,
    normalize_fingerprint,
    verify_history_digest,
)


def test_extract_omits_model():
    body = {
        "model": "m",
        "tool_choice": {"type": "auto"},
        "betas": ["message-threads-2026-08-12", "other"],
    }
    fp = extract_fingerprint(body)
    assert "model" not in fp
    assert fp["fingerprint_version"] == FINGERPRINT_VERSION
    assert fp["feature_flags"] == ["message-threads-2026-08-12", "other"]

    other = extract_fingerprint({**body, "model": "m2"})
    assert diff_fingerprints(fp, other) == []
    assert fingerprint_digest(fp) == fingerprint_digest(other)


def test_diff_non_routing_fields():
    a = extract_fingerprint({"model": "a", "cache_control": {"type": "ephemeral"}})
    b = extract_fingerprint({"model": "b", "cache_control": {"type": "persistent"}})
    assert diff_fingerprints(a, b) == ["cache_control"]


def test_legacy_fingerprint_model_pin():
    legacy = {"model": "m1", "cache_control": {"type": "ephemeral"}}
    assert is_legacy_fingerprint(legacy)
    assert legacy_model_mismatch(legacy, "m2", None)
    assert not legacy_model_mismatch(legacy, "m1", None)

    current = extract_fingerprint({"model": "x", "cache_control": {"type": "ephemeral"}})
    assert not is_legacy_fingerprint(current)


def test_history_digest_tamper():
    system = "sys"
    messages = [{"role": "user", "content": "hi"}]
    fp = attach_history_digest(extract_fingerprint({}), system=system, messages=messages)
    assert verify_history_digest(fp, system=system, messages=messages)
    tampered = messages + [{"role": "user", "content": "injected"}]
    assert not verify_history_digest(fp, system=system, messages=tampered)
    assert history_digest(system=system, messages=messages) == fp["history_digest"]


def test_normalize_strips_legacy_model():
    legacy = {"model": "m", "cache_control": {"type": "ephemeral"}, "fingerprint_version": 1}
    assert "model" not in normalize_fingerprint(legacy)
