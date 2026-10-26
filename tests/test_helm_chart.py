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


def test_deepseek_values_use_existing_secret_and_private_exceptions():
    docs = _render("-f", str(CHART / "values-crc-deepseek.yaml"))
    deploy = next(doc for doc in docs if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "control-plane")
    env = deploy["spec"]["template"]["spec"]["containers"][0]["env"]
    key = next(item for item in env if item["name"] == "LLM_API_KEY")
    assert key["valueFrom"]["secretKeyRef"]["name"] == "llm-deepseek"
    assert key["valueFrom"]["secretKeyRef"]["key"] == "api_key"
    names = {item["name"]: item.get("value") for item in env}
    assert names["LLM_K8S_SECRET_NAME"] == "llm-deepseek"
    assert names["LLM_REASONING_EFFORT"] == ""
    policy = next(doc for doc in docs if doc.get("kind") == "NetworkPolicy" and doc["metadata"]["name"] == "agent-run-egress")
    blocks = []
    for rule in policy["spec"]["egress"]:
        for target in rule.get("to") or []:
            if "ipBlock" in target:
                blocks.append(target["ipBlock"])
    assert blocks[0]["cidr"] == "0.0.0.0/0"
    assert "10.0.0.0/8" in blocks[0]["except"]
    master = next(doc for doc in docs if doc.get("kind") == "Secret" and doc["metadata"]["name"] == "agent-runtime-master-key")
    assert master["metadata"]["annotations"]["helm.sh/resource-policy"] == "keep"


def test_postgres_shm_is_a_memory_volume():
    docs = _render()
    postgres = next(doc for doc in docs if doc.get("kind") == "Deployment" and doc["metadata"]["name"] == "postgres")
    spec = postgres["spec"]["template"]["spec"]
    mount = next(item for item in spec["containers"][0]["volumeMounts"] if item["mountPath"] == "/dev/shm")
    assert mount["name"] == "dshm"
    volume = next(item for item in spec["volumes"] if item["name"] == "dshm")
    assert volume["emptyDir"]["medium"] == "Memory"
    assert volume["emptyDir"]["sizeLimit"] == "256Mi"
