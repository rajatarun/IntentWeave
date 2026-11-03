from intentweave.fingerprint import diff_fingerprints, extract_fingerprint, fingerprint_digest


def test_extract_and_diff():
    body = {
        "model": "m",
        "tool_choice": {"type": "auto"},
        "betas": ["message-threads-2026-08-12", "other"],
    }
    fp = extract_fingerprint(body)
    assert fp["model"] == "m"
    assert fp["feature_flags"] == ["message-threads-2026-08-12", "other"]

    other = extract_fingerprint({**body, "model": "m2"})
    assert diff_fingerprints(fp, other) == ["model"]
    assert fingerprint_digest(fp) != fingerprint_digest(other)
