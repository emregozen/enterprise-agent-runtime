"""PVC artifact store, retention, and the streamed upload API."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import timedelta

from fastapi.testclient import TestClient

from control_plane.main import create_app
from control_plane.models import Artifact, DataSourceRecord, Run, utcnow
from control_plane.seed import EXAMPLE_SPEC
from control_plane.service import add_artifact, create_agent, hash_token, purge_expired_artifacts
from shared.artifacts import ArtifactTooLarge, PvcArtifactStore
from shared.config import get_settings


def test_pvc_store_round_trip_rejects_traversal_and_limits_size(tmp_path):
    store = PvcArtifactStore(tmp_path)
    payload = "Doğu Anadolu\n".encode()
    uri = store.put_bytes("runs/gunluk/rapor.md", payload, "text/markdown")
    assert uri == "pvc://runs/gunluk/rapor.md"
    assert store.get_bytes(uri) == payload
    assert b"".join(store.iter_chunks(uri)) == payload
    legacy = tmp_path / "runs" / "gunluk" / "eski.md"
    legacy.write_bytes(b"eski")
    assert store.get_bytes(str(legacy.resolve())) == b"eski"

    for key in ("../etc/passwd", "/etc/passwd", "runs/../../x", "runs/../secret"):
        try:
            store.put_bytes(key, b"x", "text/plain")
        except ValueError:
            continue
        raise AssertionError(key)

    upload = store.start_upload("runs/a/buyuk.bin", "application/octet-stream", 8)
    try:
        upload.write(b"0123456789")
    except ArtifactTooLarge:
        pass
    else:
        raise AssertionError("sınır aşımı beklenirdi")
    assert not (tmp_path / "runs" / "a" / "buyuk.bin").exists()
    assert not (tmp_path / "runs" / "a" / "buyuk.bin.partial").exists()

    link = tmp_path / "runs" / "gunluk" / "link.md"
    link.symlink_to(legacy)
    try:
        store.get_bytes("pvc://runs/gunluk/link.md")
    except ValueError:
        pass
    else:
        raise AssertionError("bağ okunmamalı")


def test_store_alias_and_explicit_s3_choice(monkeypatch):
    monkeypatch.setenv("ARTIFACT_STORE", "")
    aliased = get_settings().model_copy(update={"artifact_store": "pvc", "artifact_backend": "local"})
    assert aliased.resolved_artifact_store() == "pvc"
    s3 = get_settings().model_copy(update={"artifact_store": "s3", "artifact_backend": "local"})
    assert s3.resolved_artifact_store() == "s3"
    monkeypatch.setenv("ARTIFACT_STORE", "pvc")
    pinned = get_settings().model_copy(update={"artifact_store": "pvc", "artifact_backend": "s3"})
    assert pinned.resolved_artifact_store() == "pvc"


def _running_run(db, agent, status="succeeded") -> Run:
    run = Run(
        agent_id=agent.id,
        agent_name=agent.name,
        spec_version=1,
        spec_snapshot=EXAMPLE_SPEC,
        trigger="manual",
        status=status,
        run_token_hash=hash_token("pvc-token"),
    )
    db.add(run)
    db.commit()
    return run


def test_retention_deletes_old_files_and_keeps_fresh_and_running(db, tmp_path, monkeypatch):
    settings = get_settings().model_copy(
        update={"artifact_dir": str(tmp_path), "artifact_store": "pvc", "artifact_backend": "", "artifact_retention_days": 14}
    )
    monkeypatch.setattr("control_plane.service.get_settings_safe", lambda: settings)
    db.add(
        DataSourceRecord(
            name="postgres-sales",
            dialect="postgres",
            description="Satış",
            dsn_env="SALES_DATABASE_URL",
            allow_tables=["sales"],
            sensitivity="internal",
        )
    )
    db.commit()
    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="pvc-test")
    old = _running_run(db, agent, "succeeded")
    fresh = _running_run(db, agent, "succeeded")
    busy = _running_run(db, agent, "running")
    old_row = add_artifact(db, old, name="report.md", media_type="text/markdown", data=b"eski rapor", claimed_sha="")
    fresh_row = add_artifact(db, fresh, name="report.md", media_type="text/markdown", data=b"yeni rapor", claimed_sha="")
    busy_row = add_artifact(db, busy, name="report.md", media_type="text/markdown", data=b"suren rapor", claimed_sha="")
    old_row.created_at = utcnow() - timedelta(days=30)
    busy_row.created_at = utcnow() - timedelta(days=30)
    db.commit()
    store = PvcArtifactStore(tmp_path)
    stale = tmp_path / "runs" / "yarim.partial"
    stale.write_bytes(b"partial")
    os.utime(stale, (time.time() - 90000, time.time() - 90000))

    removed = purge_expired_artifacts(db, retention_days=14)
    assert removed == 1
    assert store.get_bytes(fresh_row.storage_uri) == b"yeni rapor"
    assert store.get_bytes(busy_row.storage_uri) == b"suren rapor"
    missing = False
    try:
        store.get_bytes(old_row.storage_uri)
    except FileNotFoundError:
        missing = True
    assert missing
    db.expire_all()
    assert db.get(Artifact, old_row.id) is None
    assert not stale.exists()


def test_upload_api_streams_and_downloads(db, tmp_path, monkeypatch):
    settings = get_settings().model_copy(
        update={
            "artifact_dir": str(tmp_path),
            "artifact_store": "pvc",
            "artifact_backend": "",
            "artifact_max_bytes": 64,
        }
    )
    monkeypatch.setattr("control_plane.routes.get_settings", lambda: settings)
    monkeypatch.setattr("control_plane.service.get_settings_safe", lambda: settings)
    db.add(
        DataSourceRecord(
            name="postgres-sales",
            dialect="postgres",
            description="Satış",
            dsn_env="SALES_DATABASE_URL",
            allow_tables=["sales"],
            sensitivity="internal",
        )
    )
    db.commit()
    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="pvc-api")
    token = "pvc-token-" + uuid.uuid4().hex
    run = Run(
        agent_id=agent.id,
        agent_name=agent.name,
        spec_version=1,
        spec_snapshot=EXAMPLE_SPEC,
        trigger="manual",
        status="running",
        run_token_hash=hash_token(token),
    )
    db.add(run)
    db.commit()
    body = b'{"bolge": "Dogu Anadolu"}\n'
    digest = hashlib.sha256(body).hexdigest()

    def chunks():
        yield body[:8]
        yield body[8:]

    with TestClient(create_app()) as client:
        health = client.get("/api/health")
        assert health.json()["artifact_store"] == "pvc"
        denied = client.post(
            f"/api/internal/runs/{run.id}/artifacts",
            content=body,
            headers={"Authorization": "Bearer yanlis", "X-Artifact-Name": "plan.json", "Content-Type": "application/json"},
        )
        assert denied.status_code == 403
        bad_name = client.post(
            f"/api/internal/runs/{run.id}/artifacts",
            content=body,
            headers={"Authorization": f"Bearer {token}", "X-Artifact-Name": "../report.md", "Content-Type": "text/plain"},
        )
        assert bad_name.status_code == 400
        def oversized():
            yield b"x" * 40
            yield b"y" * 40

        too_big = client.post(
            f"/api/internal/runs/{run.id}/artifacts",
            content=oversized(),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Artifact-Name": "buyuk.bin",
                "Content-Type": "application/octet-stream",
            },
        )
        assert too_big.status_code == 413
        assert not any(tmp_path.rglob("buyuk.bin"))
        assert not any(tmp_path.rglob("buyuk.bin.partial"))
        mismatch = client.post(
            f"/api/internal/runs/{run.id}/artifacts",
            content=body,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Artifact-Name": "plan.json",
                "X-Artifact-Sha256": "0" * 64,
                "Content-Type": "application/json",
            },
        )
        assert mismatch.status_code == 400
        assert not any(tmp_path.rglob("plan.json"))
        uploaded = client.post(
            f"/api/internal/runs/{run.id}/artifacts",
            content=chunks(),
            headers={
                "Authorization": f"Bearer {token}",
                "X-Artifact-Name": "plan.json",
                "X-Artifact-Sha256": digest,
                "Content-Type": "application/json",
            },
        )
        assert uploaded.status_code == 201, uploaded.text
        artifact_id = uploaded.json()["id"]
        assert uploaded.json()["sha256"] == digest
        downloaded = client.get(f"/api/runs/{run.id}/artifacts/{artifact_id}")
        assert downloaded.status_code == 200
        assert downloaded.content == body
        assert downloaded.headers["content-type"].startswith("application/json")
        assert 'filename="plan.json"' in downloaded.headers["content-disposition"]
        listed = client.get(f"/api/runs/{run.id}")
        assert listed.json()["artifacts"][0]["name"] == "plan.json"
