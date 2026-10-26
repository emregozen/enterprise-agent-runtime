import pytest
from cryptography.fernet import Fernet

from control_plane.models import DataSourceRecord, LlmProvider
from control_plane.rotate_master_key import RotationError, main, rotate_stored_secrets
from shared.config import get_settings
from shared.crypto import decrypt_secret, encrypt_secret


def _use(monkeypatch, current: str, old: str = ""):
    monkeypatch.setenv("CONFIG_MASTER_KEY", current)
    if old:
        monkeypatch.setenv("CONFIG_MASTER_KEY_OLD", old)
    else:
        monkeypatch.delenv("CONFIG_MASTER_KEY_OLD", raising=False)
    get_settings.cache_clear()


def test_rotate_reencrypts_with_the_new_key(db, monkeypatch):
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    try:
        _use(monkeypatch, old)
        source = DataSourceRecord(
            name="rotate-sales",
            dialect="postgres",
            dsn_env="DS_ROTATE",
            allow_tables=["sales"],
            password_ciphertext=encrypt_secret("gizli-parola"),
        )
        provider = LlmProvider(
            name="rotate-model",
            base_url="http://127.0.0.1:9/v1",
            model="test",
            api_key_ciphertext=encrypt_secret("sk-rotate-test-key-value"),
        )
        db.add(source)
        db.add(provider)
        db.commit()
        old_password = source.password_ciphertext
        old_api = provider.api_key_ciphertext

        _use(monkeypatch, new, old)
        assert decrypt_secret(old_password) == "gizli-parola"
        result = rotate_stored_secrets(db)
        assert result["rewritten"] == 2
        assert source.password_ciphertext != old_password
        assert provider.api_key_ciphertext != old_api

        _use(monkeypatch, new)
        assert decrypt_secret(source.password_ciphertext) == "gizli-parola"
        assert decrypt_secret(provider.api_key_ciphertext) == "sk-rotate-test-key-value"
        _use(monkeypatch, old)
        try:
            decrypt_secret(source.password_ciphertext)
            raise AssertionError("eski anahtar yeni şifreyi açmamalı")
        except RuntimeError:
            pass
    finally:
        monkeypatch.delenv("CONFIG_MASTER_KEY_OLD", raising=False)
        monkeypatch.setenv("CONFIG_MASTER_KEY", "test-master-key-agent-runtime-poc")
        get_settings.cache_clear()


def test_rotate_stops_when_the_old_key_is_missing(db, monkeypatch):
    old = Fernet.generate_key().decode()
    new = Fernet.generate_key().decode()
    try:
        _use(monkeypatch, old)
        source = DataSourceRecord(
            name="rotate-missing",
            dialect="oracle",
            dsn_env="DS_ROTATE_MISSING",
            allow_tables=["SALES"],
            password_ciphertext=encrypt_secret("eski-sifre"),
        )
        db.add(source)
        db.commit()
        stored = source.password_ciphertext
        _use(monkeypatch, new)
        try:
            rotate_stored_secrets(db)
            raise AssertionError("eski anahtar olmadan döndürme bitmemeli")
        except RotationError:
            db.rollback()
        assert source.password_ciphertext == stored
    finally:
        monkeypatch.setenv("CONFIG_MASTER_KEY", "test-master-key-agent-runtime-poc")
        get_settings.cache_clear()


def test_cli_help_and_unknown_args_do_not_open_the_database(monkeypatch):
    def boom(*_args, **_kwargs):
        raise AssertionError("veritabanı açılmamalı")

    monkeypatch.setattr("control_plane.db.SessionLocal", boom)
    with pytest.raises(SystemExit) as helped:
        main(["--help"])
    assert helped.value.code in (0, None)
    with pytest.raises(SystemExit) as unknown:
        main(["--rotate"])
    assert unknown.value.code == 2
    with pytest.raises(SystemExit) as both:
        main(["--yes", "--dry-run"])
    assert both.value.code == 2


def test_cli_dry_run_is_the_default_and_yes_writes(db, capsys):
    source = DataSourceRecord(
        name="rotate-cli",
        dialect="postgres",
        dsn_env="DS_ROTATE_CLI",
        allow_tables=["sales"],
        password_ciphertext=encrypt_secret("gizli-parola"),
    )
    empty = DataSourceRecord(
        name="rotate-empty",
        dialect="postgres",
        dsn_env="DS_ROTATE_EMPTY",
        allow_tables=["sales"],
        password_ciphertext="",
    )
    db.add(source)
    db.add(empty)
    db.commit()
    stored = source.password_ciphertext
    main([])
    db.expire_all()
    assert source.password_ciphertext == stored
    out = capsys.readouterr().out
    assert "kuru çalıştırma" in out
    assert "gizli-parola" not in out
    main(["--dry-run"])
    db.expire_all()
    assert source.password_ciphertext == stored
    assert "gizli-parola" not in capsys.readouterr().out
    main(["--yes"])
    db.expire_all()
    assert source.password_ciphertext != stored
    assert decrypt_secret(source.password_ciphertext) == "gizli-parola"
    assert empty.password_ciphertext == ""
    written = capsys.readouterr().out
    assert "kuru çalıştırma" not in written
    assert "gizli-parola" not in written
