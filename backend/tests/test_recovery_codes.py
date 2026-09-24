from __future__ import annotations

from app.gateway.auth.recovery_codes import (
    RECOVERY_CODE_COUNT,
    generate_recovery_codes,
    hash_recovery_code,
    recovery_code_matches,
)


def test_generate_recovery_codes_count_and_uniqueness():
    codes = generate_recovery_codes()
    assert len(codes) == RECOVERY_CODE_COUNT == 10
    assert len(set(codes)) == len(codes)
    for code in codes:
        assert len(code) == 11  # "xxxxx-xxxxx"
        assert code[5] == "-"


def test_hash_is_deterministic_and_not_the_raw_code():
    code = generate_recovery_codes(1)[0]
    digest = hash_recovery_code(code)
    assert digest == hash_recovery_code(code)
    assert digest != code
    assert len(digest) == 64  # sha256 hex


def test_recovery_code_matches_is_case_and_dash_insensitive():
    code = generate_recovery_codes(1)[0]
    digest = hash_recovery_code(code)
    assert recovery_code_matches(digest, code) is True
    assert recovery_code_matches(digest, code.upper()) is True
    assert recovery_code_matches(digest, code.replace("-", "")) is True
    assert recovery_code_matches(digest, f" {code} ") is True


def test_recovery_code_matches_rejects_wrong_code_and_empty_input():
    code = generate_recovery_codes(1)[0]
    digest = hash_recovery_code(code)
    other = generate_recovery_codes(1)[0]
    assert recovery_code_matches(digest, other) is False
    assert recovery_code_matches(digest, "") is False
    assert recovery_code_matches("", code) is False
