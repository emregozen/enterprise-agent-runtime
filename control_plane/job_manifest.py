from __future__ import annotations

import uuid


def _half_cpu(cpu: str) -> str:
    if cpu.endswith("m"):
        return f"{max(int(int(cpu[:-1]) / 2), 50)}m"
    try:
        value = float(cpu)
    except ValueError:
        return cpu
    half = value / 2
    return str(int(half)) if half.is_integer() else str(half)


def _half_memory(memory: str) -> str:
    units = [("Gi", 1024), ("Mi", 1), ("G", 1024), ("M", 1)]
    for suffix, _scale in units:
        if memory.endswith(suffix):
            number = float(memory[: -len(suffix)])
            half = number / 2
            rendered = str(int(half)) if half.is_integer() else str(half)
            return f"{rendered}{suffix}"
    return memory


def _container_security() -> dict:
    return {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "runAsNonRoot": True,
        "capabilities": {"drop": ["ALL"]},
        "seccompProfile": {"type": "RuntimeDefault"},
    }


def build_run_manifests(
    *,
    run_id: uuid.UUID,
    agent_name: str,
    spec_version: int,
    spec: dict,
    token: str,
    datasources: list[dict],
    settings,
    llm_api_key: str = "",
) -> tuple[dict, dict]:
    short = run_id.hex[:12]
    job_name = f"run-{short}"
    secret_name = f"run-{short}-env"
    body = spec["spec"]
    runtime = body.get("runtime") or {}
    timeout = int(runtime.get("timeoutSeconds") or 900)
    cpu = str(runtime.get("cpu") or "1")
    memory = str(runtime.get("memory") or "2Gi")
    image = settings.runtime_image_ref(runtime.get("image"))
    resolved = settings.resolve_model((body.get("model") or {}).get("class") or "local-default")
    string_data = {"RUN_TOKEN": token}
    env = [
        {"name": "RUN_ID", "value": str(run_id)},
        {"name": "CONTROL_PLANE_URL", "value": settings.control_plane_internal_url},
        {"name": "EXECUTOR_URL", "value": "http://127.0.0.1:7070"},
        {"name": "WORKDIR", "value": "/work"},
        {"name": "LLM_MODE", "value": settings.llm_mode},
        {"name": "LLM_BASE_URL", "value": resolved["base_url"]},
        {"name": "LLM_MODEL", "value": resolved["model"]},
        {"name": "HOME", "value": "/tmp"},
        {"name": "TMPDIR", "value": "/tmp"},
        {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
        {"name": "PYTHONUNBUFFERED", "value": "1"},
        {"name": "OTEL_EXPORTER_OTLP_ENDPOINT", "value": settings.otel_exporter_otlp_endpoint},
        {"name": "OTEL_SERVICE_NAME", "value": settings.otel_service_name},
        {
            "name": "RUN_TOKEN",
            "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "RUN_TOKEN"}},
        },
    ]
    for source in datasources:
        env_name = source["dsn_env"]
        if source.get("k8s_secret_name"):
            env.append(
                {
                    "name": env_name,
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": source["k8s_secret_name"],
                            "key": source.get("k8s_secret_key") or "dsn",
                        }
                    },
                }
            )
        else:
            string_data[env_name] = source["dsn"]
            env.append(
                {
                    "name": env_name,
                    "valueFrom": {"secretKeyRef": {"name": secret_name, "key": env_name}},
                }
            )
    if settings.llm_mode == "openai":
        if settings.llm_k8s_secret_name:
            env.append(
                {
                    "name": "LLM_API_KEY",
                    "valueFrom": {
                        "secretKeyRef": {
                            "name": settings.llm_k8s_secret_name,
                            "key": settings.llm_k8s_secret_key,
                        }
                    },
                }
            )
        else:
            string_data["LLM_API_KEY"] = llm_api_key
            env.append(
                {
                    "name": "LLM_API_KEY",
                    "valueFrom": {"secretKeyRef": {"name": secret_name, "key": "LLM_API_KEY"}},
                }
            )
    namespace = settings.run_namespace
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": secret_name,
            "namespace": namespace,
            "labels": {"app": "agent-run", "agent.internal/run-id": str(run_id)},
        },
        "type": "Opaque",
        "stringData": string_data,
    }
    # A limit without a request makes Kubernetes copy the limit into the request.
    # 10Gi/20Gi of ephemeral storage then keeps the Job Pending on a small node.
    requests = {
        "cpu": (settings.run_cpu_request or "").strip() or _half_cpu(cpu),
        "memory": (settings.run_memory_request or "").strip() or _half_memory(memory),
        "ephemeral-storage": (settings.run_ephemeral_storage_request or "").strip() or "1Gi",
    }
    limits = {"cpu": cpu, "memory": memory, "ephemeral-storage": "10Gi"}
    harness = {
        "name": "harness",
        "image": image,
        "imagePullPolicy": settings.image_pull_policy,
        "command": ["python", "-m", "harness"],
        "args": ["--run-id", str(run_id)],
        "env": env,
        "resources": {"requests": requests, "limits": limits},
        "securityContext": _container_security(),
        "volumeMounts": [
            {"name": "work", "mountPath": "/work"},
            {"name": "tmp", "mountPath": "/tmp"},
        ],
    }
    executor = {
        "name": "executor",
        "image": image,
        "imagePullPolicy": settings.image_pull_policy,
        "command": ["python", "-m", "executor"],
        "args": ["serve", "--host", "127.0.0.1", "--port", "7070", "--workdir", "/work"],
        "env": [
            {"name": "HOME", "value": "/tmp"},
            {"name": "TMPDIR", "value": "/tmp"},
            {"name": "PYTHONDONTWRITEBYTECODE", "value": "1"},
            {"name": "PYTHONUNBUFFERED", "value": "1"},
        ],
        "resources": {"requests": requests, "limits": {**limits, "ephemeral-storage": "20Gi"}},
        "securityContext": _container_security(),
        "volumeMounts": [
            {"name": "work", "mountPath": "/work"},
            {"name": "tmp", "mountPath": "/tmp"},
        ],
    }
    job = {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": job_name,
            "namespace": namespace,
            "labels": {
                "app": "agent-run",
                "agent-id": agent_name[:63],
                "agent-version": str(spec_version),
                "run-id": short,
            },
            "annotations": {"agent.internal/run-id": str(run_id)},
        },
        "spec": {
            "backoffLimit": 0,
            "activeDeadlineSeconds": timeout,
            "ttlSecondsAfterFinished": int(settings.job_ttl_seconds),
            "template": {
                "metadata": {"labels": {"app": "agent-run", "run-id": short}},
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "enableServiceLinks": False,
                    "serviceAccountName": settings.run_service_account,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [harness, executor],
                    # Scratch only. Report files are streamed to the control plane;
                    # the artifact PVC is mounted on the control plane, not on this pod.
                    "volumes": [
                        {"name": "work", "emptyDir": {"sizeLimit": "20Gi"}},
                        {"name": "tmp", "emptyDir": {"sizeLimit": "2Gi"}},
                    ],
                },
            },
        },
    }
    return secret, job
