"""Round-trip artifacts through a local S3 API. Skips when nothing listens."""

from __future__ import annotations

import os
import socket
import uuid

import pytest

from control_plane.models import Run
from control_plane.seed import EXAMPLE_SPEC
from control_plane.service import add_artifact, create_agent, hash_token
from shared.artifacts import build_store
from shared.config import get_settings


ENDPOINT = os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:8833")
BUCKET = os.environ.get("S3_BUCKET", "agent-artifacts")
ACCESS = os.environ.get("S3_ACCESS_KEY", "agentrt")
SECRET = os.environ.get("S3_SECRET_KEY", "agentrt-secret")


def _s3_up() -> bool:
    host_port = ENDPOINT.split("://", 1)[-1].split("/", 1)[0]
    host, _, port = host_port.partition(":")
    sock = socket.socket()
    sock.settimeout(0.4)
    try:
        sock.connect((host or "127.0.0.1", int(port or "80")))
        return True
    except OSError:
        return False
    finally:
        sock.close()


pytestmark = pytest.mark.skipif(not _s3_up(), reason=f"S3 yok: {ENDPOINT}")


def _settings():
    return get_settings().model_copy(
        update={
            "artifact_backend": "s3",
            "s3_endpoint_url": ENDPOINT,
            "s3_bucket": BUCKET,
            "s3_access_key": ACCESS,
            "s3_secret_key": SECRET,
            "s3_region": "us-east-1",
            "s3_use_path_style": True,
        }
    )


def _ensure_bucket(settings) -> None:
    import boto3
    from botocore.client import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(s3={"addressing_style": "path"}),
    )
    existing = {item["Name"] for item in client.list_buckets().get("Buckets", [])}
    if settings.s3_bucket not in existing:
        client.create_bucket(Bucket=settings.s3_bucket)


def test_s3_store_round_trip():
    settings = _settings()
    _ensure_bucket(settings)
    store = build_store(settings)
    payload = "Doğu Anadolu sapması\n".encode()
    uri = store.put_bytes("runs/bench/report.md", payload, "text/markdown")
    assert uri == f"s3://{BUCKET}/runs/bench/report.md"
    assert store.get_bytes(uri) == payload


def test_control_plane_artifact_lands_in_s3(db, datasource, monkeypatch):
    settings = _settings()
    _ensure_bucket(settings)
    monkeypatch.setattr("control_plane.service.get_settings_safe", lambda: settings)
    agent = create_agent(db, EXAMPLE_SPEC, publish=True, actor="s3-test")
    run = Run(
        agent_id=agent.id,
        agent_name=agent.name,
        spec_version=1,
        spec_snapshot=EXAMPLE_SPEC,
        trigger="manual",
        status="running",
        run_token_hash=hash_token("s3-token"),
    )
    db.add(run)
    db.commit()
    body = f"rapor-{uuid.uuid4().hex}".encode()
    row = add_artifact(db, run, name="report.md", media_type="text/markdown", data=body, claimed_sha="")
    assert row.storage_uri.startswith(f"s3://{BUCKET}/")
    assert row.size_bytes == len(body)
    assert build_store(settings).get_bytes(row.storage_uri) == body
