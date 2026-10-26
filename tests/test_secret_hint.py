from shared.crypto import encrypt_secret, public_hint, secret_hint


def test_short_secrets_are_only_a_mask():
    assert secret_hint("") == ""
    assert secret_hint("agentrt") == "••••"
    assert secret_hint("x" * 20) == "••••"


def test_long_api_keys_keep_the_last_four():
    key = "sk-test-secret-value-extra"
    assert len(key) > 20
    assert secret_hint(key) == f"••••{key[-4:]}"
    assert key not in secret_hint(key)


def test_public_hint_ignores_a_stored_suffix():
    token = encrypt_secret("agentrt")
    assert public_hint(token, "••••ntrt") == "••••"
    long_key = "sk-test-secret-value-extra"
    assert public_hint(encrypt_secret(long_key), "••••xxxx") == f"••••{long_key[-4:]}"
    assert public_hint("", "••••ntrt") == "••••"
    assert public_hint("", "") == ""
