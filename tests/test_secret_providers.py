"""Conjur and CCP adapters, run-secret placement, and the provider API."""

from __future__ import annotations

import json
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from control_plane.backends import set_backend
from control_plane.job_manifest import build_run_manifests
from control_plane.main import create_app
from control_plane.models import DataSourceRecord, SecretProvider
from control_plane.seed import EXAMPLE_SPEC
from control_plane.service import ServiceError, _runs_today, create_agent, materialize_sources, trigger_run
from secret_sources.cache import cache_clear
from secret_sources.errors import SecretProviderError
from secret_sources.providers import ccp, conjur, vault
from secret_sources.resolve import fetch_provider_secret
from shared.config import get_settings


class _Silent(BaseHTTPRequestHandler):
    requests: list[tuple[str, str, bytes]] = []
    conjur_secret = "db-password-from-conjur"
    ccp_secret = "ccp-password-from-safe"

    def log_message(self, fmt, *args):
        return

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.requests.append(("POST", self.path, body))
        if self.path.startswith("/authn"):
            self._send(200, b"dG9rZW4tYWJj")
            return
        if "/variable/" in self.path:
            self._send(201, b"")
            return
        self._send(404, b"")

    def do_GET(self):
        parsed = urlparse(self.path)
        self.requests.append(("GET", parsed.path + ("?" + parsed.query if parsed.query else ""), b""))
        if parsed.path.startswith("/secrets/") and "/variable/" in parsed.path:
            self._send(200, self.conjur_secret.encode())
            return
        if parsed.path == "/AIMWebService/api/Accounts":
            query = parse_qs(parsed.query)
            if not query.get("AppID"):
                self._send(400, b"{}")
                return
            payload = json.dumps({"Content": self.ccp_secret, "UserName": "sales_ro", "PasswordChangeInProcess": "False"}).encode()
            self._send(200, payload, "application/json")
            return
        self._send(404, b"")

    def _send(self, status: int, body: bytes, content_type: str = "text/plain"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def pam_server():
    _Silent.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Silent)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    try:
        yield f"http://{host}:{port}"
    finally:
        server.shutdown()
        server.server_close()
        cache_clear()


def _conjur(db, base_url: str) -> SecretProvider:
    row = SecretProvider(
        name="conjur-deneme",
        kind="conjur",
        base_url=base_url,
        account="agentrt",
        auth_method="api-key",
        config={"login": "host/agent-runtime/control"},
        credential_secret_name="conjur-host",
        credential_secret_key="api_key",
        enabled=True,
    )
    db.add(row)
    db.commit()
    return row


def test_conjur_mock_authenticates_and_reads_variable(pam_server, monkeypatch):
    monkeypatch.setattr("secret_sources.resolve.read_secret_data", lambda name, namespace: {"api_key": "host-api-key"})
    logs = _capture_logs()
    value = conjur.fetch_variable(
        base_url=pam_server,
        account="agentrt",
        auth_method="api-key",
        login="host/agent-runtime/control",
        api_key="host-api-key",
        variable_id="agent-runtime/postgres-sales/password",
    )
    assert value == "db-password-from-conjur"
    paths = [item[1] for item in _Silent.requests]
    assert paths[0].startswith("/authn/agentrt/host%2Fagent-runtime%2Fcontrol/authenticate")
    assert any("agent-runtime%2Fpostgres-sales%2Fpassword" in path for path in paths)
    assert _Silent.requests[0][2] == b"host-api-key"
    blob = "\n".join(logs)
    assert "db-password-from-conjur" not in blob
    assert "host-api-key" not in blob


def test_conjur_cache_skips_the_second_read(db, pam_server, monkeypatch):
    monkeypatch.setattr("secret_sources.resolve.read_secret_data", lambda name, namespace: {"api_key": "host-api-key"})
    provider = _conjur(db, pam_server)
    cache_clear()
    first = fetch_provider_secret(db, provider.id, "agent-runtime/postgres-sales/password", {})
    calls = len(_Silent.requests)
    second = fetch_provider_secret(db, provider.id, "agent-runtime/postgres-sales/password", {})
    assert first == second == "db-password-from-conjur"
    assert len(_Silent.requests) == calls


def test_authn_k8s_posts_the_service_account_token(pam_server, tmp_path):
    token = tmp_path / "sa.token"
    token.write_text("sa-jwt-token", encoding="utf-8")
    conjur.authenticate(
        base_url=pam_server,
        account="agentrt",
        auth_method="authn-k8s",
        login="host/agent-runtime/control",
        api_key="",
        service_id="crc",
        token_path=str(token),
    )
    method, path, body = _Silent.requests[-1]
    assert method == "POST"
    assert path.startswith("/authn-k8s/crc/agentrt/")
    assert b"jwt=sa-jwt-token" in body


def test_authn_k8s_without_token_file_is_a_turkish_error(pam_server, tmp_path):
    with pytest.raises(SecretProviderError) as caught:
        conjur.authenticate(
            base_url=pam_server,
            account="agentrt",
            auth_method="authn-k8s",
            login="host/agent-runtime/control",
            api_key="",
            token_path=str(tmp_path / "missing"),
        )
    assert "servis hesabı" in str(caught.value)
    assert "API anahtarı" in str(caught.value)


def test_ccp_mock_returns_content_for_appid_safe_object(pam_server):
    value = ccp.fetch_account(
        base_url=pam_server,
        app_id="AgentRuntime",
        safe="TestSafe",
        object_name="oracle-sales",
    )
    assert value == "ccp-password-from-safe"
    path = _Silent.requests[-1][1]
    assert path.startswith("/AIMWebService/api/Accounts?")
    assert "AppID=AgentRuntime" in path
    assert "Safe=TestSafe" in path
    assert "Object=oracle-sales" in path


def test_ccp_query_is_sent_as_documented(pam_server):
    ccp.fetch_account(base_url=pam_server, app_id="AgentRuntime", query="Safe=TestSafe;Object=oracle-sales")
    path = _Silent.requests[-1][1]
    assert "Query=Safe%3DTestSafe%3BObject%3Doracle-sales" in path or "Query=Safe=TestSafe;Object=oracle-sales" in path
    assert "Safe=TestSafe&" not in path.split("?", 1)[-1].split("Query=")[0]


def test_ccp_unreachable_is_turkish():
    with pytest.raises(SecretProviderError) as caught:
        ccp.fetch_account(base_url="http://127.0.0.1:1", app_id="AgentRuntime", object_name="oracle-sales")
    message = str(caught.value)
    assert "CyberArk CCP" in message
    assert "ulaşılamadı" in message


def test_ccp_client_cert_is_passed_to_the_http_client(monkeypatch, tmp_path):
    seen = {}

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"Content": "from-cert"}

    class FakeClient:
        def __init__(self, **kwargs):
            seen["cert"] = kwargs.get("cert")
            seen["verify"] = kwargs.get("verify")

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def get(self, url, params=None):
            seen["params"] = params
            return FakeResponse()

    monkeypatch.setattr("secret_sources.http.httpx.Client", FakeClient)
    cert = tmp_path / "tls.crt"
    key = tmp_path / "tls.key"
    cert.write_text("CERT", encoding="utf-8")
    key.write_text("KEY", encoding="utf-8")
    value = ccp.fetch_account(
        base_url="https://ccp.example",
        app_id="AgentRuntime",
        safe="TestSafe",
        object_name="db",
        cert=(str(cert), str(key)),
        verify=str(tmp_path / "ca.pem"),
    )
    assert value == "from-cert"
    assert seen["cert"] == (str(cert), str(key))
    assert seen["params"]["AppID"] == "AgentRuntime"
    assert seen["verify"].endswith("ca.pem")


def test_vault_adapter_refuses_clearly():
    with pytest.raises(SecretProviderError) as caught:
        vault.fetch_secret()
    assert "OpenBao" in str(caught.value)
    assert "Vault" in str(caught.value)


def test_materialize_puts_conjur_password_only_in_the_run_secret(db, pam_server, monkeypatch):
    monkeypatch.setattr("secret_sources.resolve.read_secret_data", lambda name, namespace: {"api_key": "host-api-key"})
    provider = _conjur(db, pam_server)
    row = DataSourceRecord(
        name="oracle-sales",
        dialect="oracle",
        dsn_env="DS_ORACLE_SALES",
        allow_tables=["sales"],
        host="oracle.oracle-test.svc",
        port=1521,
        database_name="FREEPDB1",
        username="sales_ro",
        secret_backend="conjur",
        secret_provider_id=provider.id,
        secret_path="agent-runtime/oracle-sales/password",
    )
    db.add(row)
    db.commit()
    cache_clear()
    materialized = materialize_sources(db, [row])
    assert materialized[0]["k8s_secret_name"] is None
    assert "db-password-from-conjur" in materialized[0]["dsn"]
    settings = get_settings()
    secret, job = build_run_manifests(
        run_id=__import__("uuid").uuid4(),
        agent_name="gunluk",
        spec_version=1,
        spec=EXAMPLE_SPEC,
        token="run-token-value",
        datasources=materialized,
        settings=settings,
        llm={"base_url": "http://llm", "model": "m", "api_key": "llm-from-conjur", "k8s_secret_name": ""},
    )
    rendered_job = json.dumps(job)
    rendered_exec = json.dumps(next(item for item in job["spec"]["template"]["spec"]["containers"] if item["name"] == "executor"))
    assert secret["stringData"]["DS_ORACLE_SALES"] == materialized[0]["dsn"]
    assert "db-password-from-conjur" not in rendered_job
    assert "db-password-from-conjur" not in rendered_exec
    assert "llm-from-conjur" not in rendered_exec
    assert "conjur-host" not in rendered_job
    assert "run-token-value" not in rendered_job


def test_unreachable_provider_does_not_count_toward_the_daily_limit(db, monkeypatch):
    provider = SecretProvider(
        name="conjur-kapali",
        kind="conjur",
        base_url="http://127.0.0.1:1",
        account="agentrt",
        auth_method="api-key",
        config={"login": "host/agent-runtime/control"},
        credential_secret_name="conjur-host",
        credential_secret_key="api_key",
        enabled=True,
    )
    db.add(provider)
    db.flush()
    db.add(
        DataSourceRecord(
            name="postgres-sales",
            dialect="postgres",
            description="Satış",
            dsn_env="SALES_DATABASE_URL",
            allow_tables=["sales"],
            host="127.0.0.1",
            port=5432,
            database_name="sales",
            username="sales_ro",
            secret_backend="conjur",
            secret_provider_id=provider.id,
            secret_path="agent-runtime/postgres-sales/password",
        )
    )
    db.commit()
    monkeypatch.setattr("secret_sources.resolve.read_secret_data", lambda name, namespace: {"api_key": "host-api-key"})
    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="pam")
    from control_plane.models import Schedule

    schedule = db.query(Schedule).filter_by(agent_id=agent.id).one()
    schedule.max_runs_per_day = 1
    db.commit()
    set_backend(None)
    try:
        with pytest.raises(ServiceError) as caught:
            trigger_run(db, agent, trigger="manual", dry_run=False, actor="pam")
        assert caught.value.status_code == 502
        assert "Conjur" in str(caught.value)
        assert "host-api-key" not in str(caught.value)
        assert _runs_today(db, agent.id, schedule.timezone) == 0
        from control_plane.models import Run

        failed = db.query(Run).filter(Run.agent_id == agent.id).one()
        assert failed.status == "failed"
        assert failed.started_at is None
        assert "host-api-key" not in (failed.error or "")
    finally:
        set_backend(None)


def test_api_stores_a_reference_and_drops_a_pasted_key(db):
    set_backend(None)
    with TestClient(create_app()) as client:
        created = client.post(
            "/api/secret-providers",
            json={
                "name": "conjur-deneme",
                "kind": "conjur",
                "base_url": "http://conjur.conjur-test.svc",
                "account": "agentrt",
                "auth_method": "api-key",
                "config": {"login": "host/agent-runtime/control"},
                "credential_secret_name": "conjur-host",
                "credential_secret_key": "api_key",
                "api_key": "pasted-conjur-api-key",
                "password": "pasted-password",
            },
        )
        assert created.status_code == 201, created.text
        assert "pasted-conjur-api-key" not in created.text
        assert "pasted-password" not in created.text
        body = created.json()
        assert body["credential_secret_name"] == "conjur-host"
        assert "api_key" not in body or body.get("api_key") in (None, "")
        provider_id = body["id"]
        row = db.get(SecretProvider, __import__("uuid").UUID(provider_id))
        stored = json.dumps(row.config)
        assert "pasted-conjur-api-key" not in stored
        assert row.ca_bundle == ""
        source = client.post(
            "/api/datasources",
            json={
                "name": "oracle-ccp",
                "dialect": "oracle",
                "allow_tables": ["sales"],
                "host": "oracle.example",
                "port": 1521,
                "database_name": "FREEPDB1",
                "username": "sales_ro",
                "password": "should-not-be-stored",
                "secret_backend": "conjur",
                "secret_provider_id": provider_id,
                "secret_path": "agent-runtime/oracle-sales/password",
            },
        )
        assert source.status_code == 201, source.text
        assert "should-not-be-stored" not in source.text
        payload = source.json()
        assert payload["secret_backend"] == "conjur"
        assert payload["password_set"] is True
        assert payload["password_hint"] == "••••"
        assert "password" not in payload
        saved = db.query(DataSourceRecord).filter(DataSourceRecord.name == "oracle-ccp").one()
        assert saved.password_ciphertext == ""
        assert saved.secret_path == "agent-runtime/oracle-sales/password"
        assert saved.secret_form == "password"
        assert payload["secret_form"] == "password"


def test_ccp_datasource_reference_has_no_ciphertext(db):
    provider = SecretProvider(
        name="ccp-deneme",
        kind="ccp",
        base_url="https://ccp.example",
        auth_method="mtls",
        config={"app_id": "AgentRuntime"},
        credential_secret_name="ccp-client",
        tls_cert_key="tls.crt",
        tls_key_key="tls.key",
        enabled=True,
    )
    db.add(provider)
    db.commit()
    with TestClient(create_app()) as client:
        created = client.post(
            "/api/datasources",
            json={
                "name": "pg-ccp",
                "dialect": "postgres",
                "allow_tables": ["sales"],
                "host": "db.internal",
                "username": "sales_ro",
                "password": "nope",
                "secret_backend": "ccp",
                "secret_provider_id": str(provider.id),
                "secret_ref": {"safe": "TestSafe", "object": "postgres-sales"},
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["secret_ref"]["object"] == "postgres-sales"
        assert "nope" not in created.text
        row = db.query(DataSourceRecord).filter(DataSourceRecord.name == "pg-ccp").one()
        assert row.password_ciphertext == ""
        assert row.secret_ref["safe"] == "TestSafe"


def test_url_form_uses_the_raw_value_and_password_form_refuses_a_url_looking_secret(db, pam_server, monkeypatch):
    monkeypatch.setattr("secret_sources.resolve.read_secret_data", lambda name, namespace: {"api_key": "host-api-key"})
    provider = _conjur(db, pam_server)
    url_row = DataSourceRecord(
        name="postgres-sales",
        dialect="postgres",
        dsn_env="SALES_DATABASE_URL",
        allow_tables=["sales"],
        host="",
        username="",
        secret_backend="conjur",
        secret_provider_id=provider.id,
        secret_path="agent-runtime/postgres-sales/password",
        secret_form="url",
    )
    db.add(url_row)
    db.commit()
    cache_clear()
    materialized = materialize_sources(db, [url_row])
    assert materialized[0]["dsn"] == "db-password-from-conjur"
    assert materialized[0]["k8s_secret_name"] is None
    url_row.secret_form = "password"
    db.commit()
    cache_clear()
    previous = _Silent.conjur_secret
    _Silent.conjur_secret = "postgresql://sales_ro:gizli-parola@db.internal/sales"
    try:
        with pytest.raises(ServiceError) as caught:
            materialize_sources(db, [url_row])
        assert caught.value.status_code == 400
        assert "sunucu" in str(caught.value)
        assert "gizli-parola" not in str(caught.value)
        assert "postgresql://" not in str(caught.value)
    finally:
        _Silent.conjur_secret = previous
        cache_clear()


def test_kubernetes_password_form_builds_the_dsn_into_the_run_secret(db, monkeypatch):
    monkeypatch.setattr(
        "secret_sources.resolve.read_secret_data",
        lambda name, namespace: {"password": "sales-secret"},
    )
    row = DataSourceRecord(
        name="pg-k8s",
        dialect="postgres",
        dsn_env="DS_PG_K8S",
        allow_tables=["sales"],
        host="db.internal",
        port=5432,
        database_name="sales",
        username="sales_ro",
        secret_backend="kubernetes",
        k8s_secret_name="ds-pg",
        k8s_secret_key="password",
        secret_form="password",
    )
    db.add(row)
    db.commit()
    materialized = materialize_sources(db, [row])
    assert materialized[0]["k8s_secret_name"] is None
    assert materialized[0]["dsn"].startswith("postgresql+psycopg://sales_ro:sales-secret@db.internal:5432/sales")
    kept = DataSourceRecord(
        name="pg-k8s-url",
        dialect="postgres",
        dsn_env="DS_PG_K8S_URL",
        allow_tables=["sales"],
        secret_backend="kubernetes",
        k8s_secret_name="ds-postgres-sales",
        k8s_secret_key="dsn",
        secret_form="url",
    )
    db.add(kept)
    db.commit()
    external = materialize_sources(db, [kept])
    assert external[0]["dsn"] == ""
    assert external[0]["k8s_secret_name"] == "ds-postgres-sales"


def test_migration_marks_empty_host_external_refs_as_url(db):
    from control_plane.db import get_engine
    from control_plane.migrate import apply_migrations

    db.add_all(
        [
            DataSourceRecord(
                name="postgres-sales",
                dialect="postgres",
                dsn_env="SALES_DATABASE_URL",
                allow_tables=["sales"],
                host="",
                username="",
                secret_backend="conjur",
                secret_path="agent-runtime/postgres-sales/password",
                secret_form="password",
            ),
            DataSourceRecord(
                name="oracle-sales",
                dialect="oracle",
                dsn_env="DS_ORACLE",
                allow_tables=["SALES"],
                host="oracle.example",
                username="sales_ro",
                secret_backend="conjur",
                secret_path="agent-runtime/oracle-sales/password",
                secret_form="password",
            ),
            DataSourceRecord(
                name="legacy-k8s",
                dialect="postgres",
                dsn_env="DS_LEGACY",
                allow_tables=["sales"],
                host="",
                username="",
                secret_backend="db",
                k8s_secret_name="ds-postgres-sales",
                password_ciphertext="",
                secret_form="password",
            ),
            DataSourceRecord(
                name="platform-db",
                dialect="postgres",
                dsn_env="DS_PLATFORM",
                allow_tables=["sales"],
                host="",
                username="",
                secret_backend="db",
                password_ciphertext="ciphertext-stays",
                secret_form="password",
            ),
        ]
    )
    db.commit()
    with get_engine().begin() as conn:
        apply_migrations(conn)
    db.expire_all()
    forms = {row.name: row.secret_form for row in db.query(DataSourceRecord).all()}
    assert forms["postgres-sales"] == "url"
    assert forms["oracle-sales"] == "password"
    assert forms["legacy-k8s"] == "url"
    assert forms["platform-db"] == "password"


def test_api_url_form_allows_an_empty_host_and_password_form_does_not(db):
    provider = SecretProvider(
        name="conjur-form",
        kind="conjur",
        base_url="http://conjur.conjur-test.svc",
        account="agentrt",
        auth_method="api-key",
        config={"login": "host/agent-runtime/control"},
        credential_secret_name="conjur-host",
        enabled=True,
    )
    db.add(provider)
    db.commit()
    with TestClient(create_app()) as client:
        missing = client.post(
            "/api/datasources",
            json={
                "name": "pg-missing-host",
                "dialect": "postgres",
                "allow_tables": ["sales"],
                "secret_backend": "conjur",
                "secret_provider_id": str(provider.id),
                "secret_path": "agent-runtime/postgres-sales/password",
                "secret_form": "password",
            },
        )
        assert missing.status_code == 400
        assert "sunucu" in missing.text
        created = client.post(
            "/api/datasources",
            json={
                "name": "pg-url",
                "dialect": "postgres",
                "allow_tables": ["sales"],
                "secret_backend": "conjur",
                "secret_provider_id": str(provider.id),
                "secret_path": "agent-runtime/postgres-sales/password",
                "secret_form": "url",
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["secret_form"] == "url"
        assert created.json()["host"] == ""
        assert "password" not in created.json()


def _capture_logs() -> list[str]:
    found: list[str] = []

    class Handler(logging.Handler):
        def emit(self, record):
            found.append(self.format(record))

    handler = Handler()
    root = logging.getLogger()
    root.addHandler(handler)
    return found
