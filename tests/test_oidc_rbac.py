"""OIDC authentication, waiting-list approval, RBAC matrix, and group isolation tests."""

from __future__ import annotations

import base64
import hashlib
import json
import time
import urllib.parse
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from fastapi.testclient import TestClient

from control_plane.auth import clear_oidc_caches
from control_plane.backends import RecordingBackend, set_backend
from control_plane.main import create_app
from control_plane.models import Artifact, DeliveryLog, Run, Schedule
from control_plane.rbac import GroupMembershipInfo, Principal, has_permission, permitted_actions
from control_plane.seed import EXAMPLE_SPEC
from control_plane.service import claim_due
from shared.artifacts import build_store
from shared.config import get_settings


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


class FakeOidcProvider:
    """In-memory OIDC IdP with RSA-2048 JWKS and signed JWT minting."""

    def __init__(self, issuer: str = "https://idp.company.example/realms/agent-runtime", client_id: str = "agent-runtime"):
        self.issuer = issuer
        self.client_id = client_id
        self.kid = "test-key-1"
        self.private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pub_numbers = self.private_key.public_key().public_numbers()
        n_bytes = pub_numbers.n.to_bytes((pub_numbers.n.bit_length() + 7) // 8, "big")
        e_bytes = pub_numbers.e.to_bytes((pub_numbers.e.bit_length() + 7) // 8, "big")
        self.jwks = {
            "keys": [
                {
                    "kty": "RSA",
                    "use": "sig",
                    "alg": "RS256",
                    "kid": self.kid,
                    "n": _b64url(n_bytes),
                    "e": _b64url(e_bytes),
                }
            ]
        }
        self.discovery = {
            "issuer": self.issuer,
            "authorization_endpoint": f"{self.issuer}/protocol/openid-connect/auth",
            "token_endpoint": f"{self.issuer}/protocol/openid-connect/token",
            "userinfo_endpoint": f"{self.issuer}/protocol/openid-connect/userinfo",
            "end_session_endpoint": f"{self.issuer}/protocol/openid-connect/logout",
            "jwks_uri": f"{self.issuer}/protocol/openid-connect/certs",
        }
        self.next_token_claims: dict = {}

    def sign_jwt(
        self,
        *,
        sub: str,
        email: str,
        name: str = "",
        groups: list[str] | None = None,
        aud: str | None = None,
        iss: str | None = None,
        exp_offset: int = 3600,
        nonce: str | None = None,
    ) -> str:
        now = int(time.time())
        header = {"alg": "RS256", "typ": "JWT", "kid": self.kid}
        payload: dict = {
            "iss": iss or self.issuer,
            "sub": sub,
            "aud": aud or self.client_id,
            "iat": now - 5,
            "exp": now + exp_offset,
            "email": email,
            "name": name or email.split("@")[0],
            "groups": groups or [],
        }
        if nonce:
            payload["nonce"] = nonce
        signing_input = f"{_b64url(json.dumps(header).encode())}.{_b64url(json.dumps(payload).encode())}".encode("ascii")
        signature = self.private_key.sign(signing_input, padding.PKCS1v15(), hashes.SHA256())
        return f"{signing_input.decode('ascii')}.{_b64url(signature)}"


@pytest.fixture()
def oidc_env(monkeypatch):
    idp = FakeOidcProvider()
    clear_oidc_caches()
    monkeypatch.setenv("AUTH_MODE", "oidc")
    monkeypatch.setenv("OIDC_ISSUER_URL", idp.issuer)
    monkeypatch.setenv("OIDC_PUBLIC_ISSUER_URL", idp.issuer)
    monkeypatch.setenv("OIDC_CLIENT_ID", idp.client_id)
    monkeypatch.setenv("OIDC_CLIENT_SECRET", "top-secret-oidc-client-secret")
    monkeypatch.setenv("AUTH_BOOTSTRAP_ADMINS", "admin@company.example")
    monkeypatch.setenv("OIDC_GROUP_MAPPING_ENABLED", "false")
    get_settings.cache_clear()

    import control_plane.auth as auth_mod
    import control_plane.auth_routes as auth_routes_mod

    monkeypatch.setattr(auth_mod, "fetch_discovery", lambda _settings: idp.discovery)
    monkeypatch.setattr(auth_routes_mod, "fetch_discovery", lambda _settings: idp.discovery)
    monkeypatch.setattr(auth_mod, "fetch_jwks", lambda _settings, jwks_uri=None, *, force=False: idp.jwks)

    def fake_exchange(_settings, *, code: str, redirect_uri: str, code_verifier: str):
        claims = dict(idp.next_token_claims)
        jwt_tok = idp.sign_jwt(**claims)
        return {"id_token": jwt_tok, "access_token": jwt_tok}

    monkeypatch.setattr(auth_mod, "exchange_code_for_tokens", fake_exchange)
    monkeypatch.setattr(auth_routes_mod, "exchange_code_for_tokens", fake_exchange)
    yield idp
    clear_oidc_caches()
    get_settings.cache_clear()


def test_rbac_permission_matrix_unit():
    gid_a = uuid.uuid4()
    gid_b = uuid.uuid4()
    viewer = Principal(
        user_id=uuid.uuid4(),
        email="v@company.example",
        display_name="Viewer",
        status="active",
        is_admin=False,
        memberships=(GroupMembershipInfo(gid_a, "group-a", "viewer"),),
        active_group_id=gid_a,
    )
    operator = Principal(
        user_id=uuid.uuid4(),
        email="o@company.example",
        display_name="Operator",
        status="active",
        is_admin=False,
        memberships=(GroupMembershipInfo(gid_a, "group-a", "operator"),),
        active_group_id=gid_a,
    )
    editor = Principal(
        user_id=uuid.uuid4(),
        email="e@company.example",
        display_name="Editor",
        status="active",
        is_admin=False,
        memberships=(GroupMembershipInfo(gid_a, "group-a", "editor"),),
        active_group_id=gid_a,
    )
    assert has_permission(viewer, "agent:read", gid_a)
    assert not has_permission(viewer, "agent:run", gid_a)
    assert not has_permission(viewer, "agent:write", gid_a)
    assert not has_permission(viewer, "agent:read", gid_b)

    assert has_permission(operator, "agent:read", gid_a)
    assert has_permission(operator, "agent:run", gid_a)
    assert has_permission(operator, "delivery:resend", gid_a)
    assert has_permission(operator, "schedule:pause", gid_a)
    assert not has_permission(operator, "agent:write", gid_a)
    assert not has_permission(operator, "datasource:write", gid_a)

    assert has_permission(editor, "agent:write", gid_a)
    assert has_permission(editor, "agent:delete", gid_a)
    assert has_permission(editor, "datasource:write", gid_a)
    assert not has_permission(editor, "admin:users", gid_a)
    assert "agent:write" in permitted_actions(editor, gid_a)


def test_oidc_pkce_flow_and_waiting_list_approval(db, oidc_env):
    with TestClient(create_app()) as client:
        # 1. Unauthenticated request to /api/agents returns 401; /api/health stays 200
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/agents").status_code == 401

        # 2. /api/auth/login initiates PKCE S256 redirect and sets signed flow cookie
        login_res = client.get("/api/auth/login?next=/agents", follow_redirects=False)
        assert login_res.status_code == 302
        loc = login_res.headers["location"]
        parsed = urllib.parse.urlparse(loc)
        qs = urllib.parse.parse_qs(parsed.query)
        assert qs["code_challenge_method"] == ["S256"]
        state = qs["state"][0]

        # Extract nonce from flow cookie to simulate IdP returning matching nonce
        flow_cookie = client.cookies.get("agentrt_oidc_flow")
        assert flow_cookie
        raw_payload = flow_cookie.split(".", 1)[0]
        padded = raw_payload + "=" * (-len(raw_payload) % 4)
        flow_data = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))

        oidc_env.next_token_claims = {
            "sub": "sub-pending-1",
            "email": "newcomer@company.example",
            "name": "Newcomer",
            "nonce": flow_data["nonce"],
        }
        cb_res = client.get(f"/api/auth/callback?code=auth-code-123&state={state}", follow_redirects=False)
        assert cb_res.status_code == 302
        assert cb_res.headers["location"] == "/agents"
        assert client.cookies.get("agentrt_session")

        # 3. /api/auth/me succeeds and shows status="pending", but /api/agents is blocked with 403
        me_res = client.get("/api/auth/me")
        assert me_res.status_code == 200
        me_body = me_res.json()
        assert me_body["user"]["status"] == "pending"
        assert me_body["groups"] == []
        csrf_token = me_body["csrf_token"]
        assert csrf_token
        pending_user_id = me_body["user"]["id"]

        blocked = client.get("/api/agents")
        assert blocked.status_code == 403
        assert "onayı bekliyor" in blocked.json()["detail"]

        # 4. Bootstrap admin logs in via Bearer JWT and approves the pending user
        admin_jwt = oidc_env.sign_jwt(sub="sub-admin", email="admin@company.example", name="Platform Admin")
        admin_headers = {"Authorization": f"Bearer {admin_jwt}"}

        groups_res = client.get("/api/admin/groups", headers=admin_headers)
        assert groups_res.status_code == 200
        default_group_id = next(g["id"] for g in groups_res.json() if g["name"] == "default")

        approve_res = client.post(
            f"/api/admin/users/{pending_user_id}/approve",
            headers=admin_headers,
            json={"group_id": default_group_id, "role": "operator"},
        )
        assert approve_res.status_code == 200
        assert approve_res.json()["status"] == "active"

        # 5. Session user is now active with operator role!
        me_after = client.get("/api/auth/me").json()
        assert me_after["user"]["status"] == "active"
        assert me_after["groups"][0]["role"] == "operator"
        assert client.get("/api/agents").status_code == 200

        # 6. CSRF check on session cookie state-mutating request: missing CSRF header -> 403
        no_csrf = client.post("/api/auth/active-group", json={"group_id": default_group_id})
        assert no_csrf.status_code == 403
        with_csrf = client.post(
            "/api/auth/active-group",
            headers={"X-CSRF-Token": csrf_token},
            json={"group_id": default_group_id},
        )
        assert with_csrf.status_code == 200


def test_jwt_validation_rejects_expired_and_wrong_audience(db, oidc_env):
    with TestClient(create_app()) as client:
        expired = oidc_env.sign_jwt(sub="sub-1", email="admin@company.example", exp_offset=-120)
        res_exp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
        assert res_exp.status_code == 401

        wrong_aud = oidc_env.sign_jwt(sub="sub-1", email="admin@company.example", aud="other-client")
        res_aud = client.get("/api/auth/me", headers={"Authorization": f"Bearer {wrong_aud}"})
        assert res_aud.status_code == 401


def test_cross_group_isolation_and_role_enforcement(db, oidc_env):
    set_backend(RecordingBackend())
    try:
        with TestClient(create_app()) as client:
            admin_jwt = oidc_env.sign_jwt(sub="sub-admin", email="admin@company.example", name="Admin")
            admin_hdr = {"Authorization": f"Bearer {admin_jwt}"}

            # Create Group A and Group B
            grp_a = client.post("/api/admin/groups", headers=admin_hdr, json={"name": "group-a", "description": "Team A"}).json()
            grp_b = client.post("/api/admin/groups", headers=admin_hdr, json={"name": "group-b", "description": "Team B"}).json()

            # Provision Editor A, Operator A, Viewer A, and Editor B
            users = {}
            for key, email, role, gid in [
                ("editor_a", "editor-a@company.example", "editor", grp_a["id"]),
                ("operator_a", "operator-a@company.example", "operator", grp_a["id"]),
                ("viewer_a", "viewer-a@company.example", "viewer", grp_a["id"]),
                ("editor_b", "editor-b@company.example", "editor", grp_b["id"]),
            ]:
                tok = oidc_env.sign_jwt(sub=f"sub-{key}", email=email, name=key)
                me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tok}"}).json()
                client.post(
                    f"/api/admin/users/{me['user']['id']}/approve",
                    headers=admin_hdr,
                    json={"group_id": gid, "role": role},
                )
                users[key] = {"Authorization": f"Bearer {tok}"}

            # Editor A creates a datasource, LLM provider, secret provider, delivery channel, and agent in Group A
            ds_a = client.post(
                "/api/datasources",
                headers=users["editor_a"],
                json={
                    "name": "sales-a",
                    "dialect": "postgres",
                    "dsn_env": "SALES_DATABASE_URL",
                    "allow_tables": ["sales"],
                    "host": "127.0.0.1",
                    "port": 5432,
                    "database_name": "agentrt_test",
                    "username": "agentrt",
                    "password": "agentrt",
                },
            )
            assert ds_a.status_code == 201, ds_a.text
            ds_a_id = ds_a.json()["id"]
            assert ds_a.json()["owner_group_id"] == grp_a["id"]

            sp_a = client.post(
                "/api/secret-providers",
                headers=users["editor_a"],
                json={
                    "name": "vault-a",
                    "kind": "vault",
                    "base_url": "https://vault.company.example",
                },
            )
            assert sp_a.status_code == 201
            sp_a_id = sp_a.json()["id"]

            llm_a = client.post(
                "/api/llm/providers",
                headers=users["editor_a"],
                json={
                    "name": "model-a",
                    "base_url": "https://llm.company.example/v1",
                    "model": "qwen",
                    "api_key": "sk-group-a",
                },
            )
            assert llm_a.status_code == 201
            llm_a_id = llm_a.json()["id"]

            ch_a = client.post(
                "/api/delivery-channels",
                headers=users["editor_a"],
                json={
                    "name": "smtp-a",
                    "kind": "smtp",
                    "from_address": "bot@company.example",
                    "allow_domains": ["company.example"],
                    "config": {"host": "127.0.0.1", "port": 1025, "tls_mode": "none"},
                },
            )
            assert ch_a.status_code == 201, ch_a.text
            ch_a_id = ch_a.json()["id"]

            spec_a = json.loads(json.dumps(EXAMPLE_SPEC))
            spec_a["metadata"]["name"] = "agent-group-a"
            spec_a["spec"]["datasources"] = [{"ref": "sales-a", "allowTables": ["sales"]}]
            ag_a = client.post("/api/agents", headers=users["editor_a"], json={"spec": spec_a, "publish": True})
            assert ag_a.status_code == 201, ag_a.text
            ag_a_id = ag_a.json()["id"]
            assert ag_a.json()["owner_group_id"] == grp_a["id"]

            # Viewer A can read Group A resources, but cannot run, pause, or edit/delete
            assert client.get(f"/api/agents/{ag_a_id}", headers=users["viewer_a"]).status_code == 200
            assert client.post(f"/api/agents/{ag_a_id}/runs", headers=users["viewer_a"], json={}).status_code == 403
            assert client.post(f"/api/agents/{ag_a_id}/pause", headers=users["viewer_a"], json={"paused": True}).status_code == 403
            assert client.delete(f"/api/agents/{ag_a_id}", headers=users["viewer_a"]).status_code == 403
            assert client.post("/api/datasources", headers=users["viewer_a"], json={}).status_code == 403

            # Operator A can trigger a run and pause/resume schedule, but cannot edit or delete agent
            assert client.patch(f"/api/agents/{ag_a_id}", headers=users["operator_a"], json={"description": "x"}).status_code == 403
            assert client.delete(f"/api/agents/{ag_a_id}", headers=users["operator_a"]).status_code == 403
            pause_res = client.post(f"/api/agents/{ag_a_id}/pause", headers=users["operator_a"], json={"paused": False})
            assert pause_res.status_code == 200
            run_res = client.post(f"/api/agents/{ag_a_id}/runs", headers=users["operator_a"], json={"dry_run": False})
            assert run_res.status_code == 202, run_res.text
            run_a_id = run_res.json()["id"]
            assert run_res.json()["owner_group_id"] == grp_a["id"]

            # Attach an artifact to run_a so we can test cross-group artifact download isolation
            store = build_store(get_settings())
            up = store.start_upload(f"{run_a_id}/report.md", "text/markdown", 10000)
            up.write(b"# Group A secret report")
            uri, size, digest = up.finish()
            art = Artifact(
                run_id=uuid.UUID(run_a_id),
                name="report.md",
                media_type="text/markdown",
                storage_uri=uri,
                sha256=digest,
                size_bytes=size,
            )
            db.add(art)
            db.commit()
            art_id = str(art.id)

            # Viewer A can download the artifact
            assert client.get(f"/api/runs/{run_a_id}/artifacts/{art_id}", headers=users["viewer_a"]).status_code == 200

            # Editor B (in Group B) cannot see Group A's records in any list
            assert client.get("/api/agents", headers=users["editor_b"]).json() == []
            assert client.get("/api/runs", headers=users["editor_b"]).json() == []
            assert client.get("/api/datasources", headers=users["editor_b"]).json() == []
            assert client.get("/api/llm/providers", headers=users["editor_b"]).json() == []
            assert client.get("/api/secret-providers", headers=users["editor_b"]).json() == []
            assert client.get("/api/delivery-channels", headers=users["editor_b"]).json() == []

            # Editor B accessing Group A's resources by ID gets 404 (never 200 or 403)
            assert client.get(f"/api/agents/{ag_a_id}", headers=users["editor_b"]).status_code == 404
            assert client.patch(f"/api/agents/{ag_a_id}", headers=users["editor_b"], json={"description": "hack"}).status_code == 404
            assert client.delete(f"/api/agents/{ag_a_id}", headers=users["editor_b"]).status_code == 404
            assert client.post(f"/api/agents/{ag_a_id}/runs", headers=users["editor_b"], json={}).status_code == 404
            assert client.get(f"/api/agents/{ag_a_id}/diff?left=1&right=1", headers=users["editor_b"]).status_code == 404
            assert client.get(f"/api/runs/{run_a_id}", headers=users["editor_b"]).status_code == 404
            assert client.get(f"/api/runs/{run_a_id}/logs", headers=users["editor_b"]).status_code == 404
            assert client.get(f"/api/runs/{run_a_id}/artifacts/{art_id}", headers=users["editor_b"]).status_code == 404
            assert client.post(f"/api/runs/{run_a_id}/cancel", headers=users["editor_b"]).status_code == 404
            assert client.post(f"/api/runs/{run_a_id}/rerun", headers=users["editor_b"]).status_code == 404
            assert client.delete(f"/api/runs/{run_a_id}", headers=users["editor_b"]).status_code == 404
            assert client.get(f"/api/datasources/{ds_a_id}", headers=users["editor_b"]).status_code == 404
            assert client.post(f"/api/datasources/{ds_a_id}/test", headers=users["editor_b"]).status_code == 404
            assert client.patch(f"/api/llm/providers/{llm_a_id}", headers=users["editor_b"], json={"model": "x"}).status_code == 404
            assert client.delete(f"/api/secret-providers/{sp_a_id}", headers=users["editor_b"]).status_code == 404
            assert client.post(f"/api/delivery-channels/{ch_a_id}/test", headers=users["editor_b"]).status_code == 404

            # Editor B cannot create an agent in Group B referencing Group A's datasource
            spec_b = json.loads(json.dumps(EXAMPLE_SPEC))
            spec_b["metadata"]["name"] = "agent-cross-ref"
            spec_b["spec"]["datasources"] = [{"ref": "sales-a", "allowTables": ["sales"]}]
            cross_create = client.post("/api/agents", headers=users["editor_b"], json={"spec": spec_b, "publish": True})
            assert cross_create.status_code == 400

            # Dashboard for Editor B shows 0 agents and 0 runs, while Admin sees Group A's agent and run
            dash_b = client.get("/api/dashboard", headers=users["editor_b"]).json()
            assert dash_b["active_agents"] == 0
            assert dash_b["runs_today"] == 0
            dash_admin = client.get("/api/dashboard", headers=admin_hdr).json()
            assert dash_admin["active_agents"] == 1
            assert dash_admin["runs_today"] == 1

            # Scheduler claims due schedule for Group A's agent and preserves owner_group_id + scheduler actor
            prev_run = db.get(Run, uuid.UUID(run_a_id))
            prev_run.status = "succeeded"
            sched = db.query(Schedule).filter(Schedule.agent_id == uuid.UUID(ag_a_id)).one()
            sched.next_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            db.commit()
            claimed = claim_due(db)
            db.commit()
            assert len(claimed) == 1
            cron_run = db.get(Run, claimed[0][0])
            assert str(cron_run.owner_group_id) == grp_a["id"]

            # Audit log endpoint works for Admin and records user approvals and scheduler trigger
            audit_res = client.get("/api/admin/audit?action=run.requested", headers=admin_hdr)
            assert audit_res.status_code == 200
            actors = {item["actor"] for item in audit_res.json()}
            assert "scheduler" in actors
            assert "operator-a@company.example" in actors
    finally:
        set_backend(None)


def test_idp_group_mapping_and_user_rejection_lifecycle(db, oidc_env, monkeypatch):
    monkeypatch.setenv("OIDC_GROUP_MAPPING_ENABLED", "true")
    monkeypatch.setenv(
        "OIDC_GROUP_MAPPING",
        json.dumps({"idp-analysts": {"group": "analysts", "role": "operator"}}),
    )
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        # 1. User with mapped IdP group claim is automatically activated in 'analysts' with 'operator' role
        mapped_jwt = oidc_env.sign_jwt(
            sub="sub-mapped",
            email="analyst@company.example",
            name="Mapped Analyst",
            groups=["idp-analysts"],
        )
        mapped_hdr = {"Authorization": f"Bearer {mapped_jwt}"}
        me_mapped = client.get("/api/auth/me", headers=mapped_hdr).json()
        assert me_mapped["user"]["status"] == "active"
        assert me_mapped["groups"][0]["name"] == "analysts"
        assert me_mapped["groups"][0]["role"] == "operator"
        assert client.get("/api/agents", headers=mapped_hdr).status_code == 200

        # 2. Admin rejects a pending user, then disables an active user
        admin_jwt = oidc_env.sign_jwt(sub="sub-admin", email="admin@company.example", name="Admin")
        admin_hdr = {"Authorization": f"Bearer {admin_jwt}"}

        pending_jwt = oidc_env.sign_jwt(sub="sub-reject", email="outsider@company.example", name="Outsider")
        pending_hdr = {"Authorization": f"Bearer {pending_jwt}"}
        pending_me = client.get("/api/auth/me", headers=pending_hdr).json()
        assert pending_me["user"]["status"] == "pending"

        rej = client.post(
            f"/api/admin/users/{pending_me['user']['id']}/reject",
            headers=admin_hdr,
            json={"reason": "Not in department"},
        )
        assert rej.status_code == 200
        assert rej.json()["status"] == "rejected"
        assert client.get("/api/agents", headers=pending_hdr).status_code == 403

        # Disable the mapped analyst
        dis = client.patch(
            f"/api/admin/users/{me_mapped['user']['id']}",
            headers=admin_hdr,
            json={"status": "disabled"},
        )
        assert dis.status_code == 200
        assert dis.json()["status"] == "disabled"
        assert client.get("/api/agents", headers=mapped_hdr).status_code == 403
