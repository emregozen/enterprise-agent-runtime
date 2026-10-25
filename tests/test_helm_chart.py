"""Rendered chart checks that do not need a cluster."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy" / "helm" / "agent-runtime"
HELM = shutil.which("helm") or "/tmp/linux-amd64/helm"


def _render(*extra: str) -> list[dict]:
    if not Path(HELM).exists():
        pytest.skip("helm yok")
    completed = subprocess.run(
        [HELM, "template", "agent-runtime", str(CHART), "-f", str(CHART / "values-crc.yaml"), *extra],
        check=True,
        capture_output=True,
        text=True,
    )
    return [doc for doc in yaml.safe_load_all(completed.stdout) if doc]


def test_release_namespace_is_left_to_helm_and_postgres_is_fqdn():
    docs = _render()
    namespaces = [doc["metadata"]["name"] for doc in docs if doc.get("kind") == "Namespace"]
    assert namespaces == ["agent-runs"]
    secret = next(doc for doc in docs if doc.get("kind") == "Secret" and doc["metadata"]["name"] == "agent-runtime-env")
    host = "postgres.agent-runtime.svc.cluster.local"
    assert host in secret["stringData"]["DATABASE_URL"]
    assert host in secret["stringData"]["SALES_DATABASE_URL"]
    assert host in secret["stringData"]["SALES_ADMIN_URL"]
    deploy = next(doc for doc in docs if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "control-plane")
    assert deploy["spec"]["strategy"]["type"] == "Recreate"
    env = {item["name"]: item["value"] for item in deploy["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in item}
    assert env["RUN_EPHEMERAL_STORAGE_REQUEST"] == "1Gi"
    assert env["RUN_CPU_REQUEST"] == ""
    requests = deploy["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]
    assert requests["memory"] == "384Mi"


def test_small_values_lower_requests_and_s3_keeps_rolling_update():
    docs = _render("-f", str(CHART / "values-crc-small.yaml"))
    deploy = next(doc for doc in docs if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "control-plane")
    requests = deploy["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]
    assert requests["memory"] == "256Mi"
    assert requests["cpu"] == "50m"
    env = {item["name"]: item["value"] for item in deploy["spec"]["template"]["spec"]["containers"][0]["env"] if "value" in item}
    assert env["RUN_CPU_REQUEST"] == "50m"
    assert env["RUN_MEMORY_REQUEST"] == "128Mi"
    ui = next(doc for doc in docs if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "ui")
    assert ui["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["memory"] == "96Mi"
    postgres = next(doc for doc in docs if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "postgres")
    assert postgres["spec"]["template"]["spec"]["containers"][0]["resources"]["requests"]["memory"] == "256Mi"

    s3 = _render("--set", "artifacts.store=s3")
    control = next(doc for doc in s3 if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "control-plane")
    assert "strategy" not in control["spec"] or control["spec"].get("strategy", {}).get("type") != "Recreate"
    assert not any(doc.get("kind") == "PersistentVolumeClaim" and doc["metadata"]["name"] == "artifacts" for doc in s3)
