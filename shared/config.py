from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from shared.artifacts import normalize_artifact_store

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://agentrt:agentrt@127.0.0.1:5432/agentrt"
    sales_database_url: str = ""
    sales_admin_url: str = ""
    sales_ro_password: str = "sales_ro"

    llm_mode: str = "fake"
    llm_base_url: str = "http://127.0.0.1:11434/v1"
    llm_api_key: str = "not-set"
    llm_model: str = "local-default"
    llm_model_classes: str = ""
    llm_timeout_seconds: float = 120

    run_backend: str = "local"
    control_plane_public_url: str = "http://127.0.0.1:8841"
    control_plane_internal_url: str = "http://127.0.0.1:8841"

    # pvc is the control-plane directory (a PersistentVolume on OpenShift). s3 stays optional.
    # ARTIFACT_BACKEND=local is accepted as an alias of pvc when ARTIFACT_STORE is unset.
    artifact_store: str = "pvc"
    artifact_backend: str = ""
    artifact_dir: str = "var/artifacts"
    artifact_retention_days: int = 14
    artifact_max_bytes: int = 20_000_000
    s3_endpoint_url: str = ""
    s3_bucket: str = "agent-artifacts"
    s3_access_key: str = ""
    s3_secret_key: str = ""
    s3_region: str = "us-east-1"
    s3_use_path_style: bool = True

    image_registry: str = ""
    runtime_image: str = "agent-runtime-py312:0.2.0"
    image_pull_policy: str = "IfNotPresent"
    run_namespace: str = "agent-runs"
    run_cpu_request: str = ""
    run_memory_request: str = ""
    run_ephemeral_storage_request: str = "1Gi"
    run_service_account: str = "agent-run"
    job_ttl_seconds: int = 600
    kubeconfig: str = ""
    llm_k8s_secret_name: str = ""
    llm_k8s_secret_key: str = "api_key"

    scheduler_enabled: bool = True
    scheduler_interval_seconds: float = 10
    seed_demo: bool = False
    seed_sales_rows: int = 0
    work_root: str = "var/work"
    log_dir: str = "var/logs"
    port: int = 8841

    sql_max_limit: int = 2_000_000
    sql_statement_timeout_ms: int = 30_000
    sql_max_cost: float = 10_000_000
    arrow_batch_rows: int = 10_000
    llm_max_preview_rows: int = 200

    email_api_url: str = ""
    email_api_token: str = ""
    sms_api_url: str = ""
    sms_api_token: str = ""
    http_tool_base_url: str = ""
    http_tool_token: str = ""
    email_recipient_allowlist: str = "finans@sirket.local,*@sirket.local"
    tool_rate_limit_per_hour: int = 30

    otel_exporter_otlp_endpoint: str = ""
    otel_service_name: str = "agent-runtime"
    log_level: str = "INFO"
    migrate_on_start: bool = True

    def model_class_map(self) -> dict:
        raw = (self.llm_model_classes or "").strip()
        if not raw:
            model_name = self.llm_model if self.llm_model != "local-default" else "local-default"
            return {
                "local-default": {
                    "base_url": self.llm_base_url,
                    "model": model_name,
                    "api_key_env": "LLM_API_KEY",
                }
            }
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("LLM_MODEL_CLASSES must be a JSON object")
        return data

    def resolve_model(self, class_name: str) -> dict:
        mapping = self.model_class_map()
        item = mapping.get(class_name) or mapping.get("local-default") or {}
        api_key = item.get("api_key") or ""
        env_name = item.get("api_key_env") or "LLM_API_KEY"
        if not api_key:
            api_key = os.environ.get(env_name, "") or self.llm_api_key
        return {
            "base_url": item.get("base_url") or self.llm_base_url,
            "model": item.get("model") or self.llm_model,
            "api_key": api_key,
        }

    def recipient_allowlist(self) -> list[str]:
        return [part.strip() for part in self.email_recipient_allowlist.split(",") if part.strip()]

    def resolved_artifact_store(self) -> str:
        store = (self.artifact_store or "").strip().lower()
        backend = (self.artifact_backend or "").strip().lower()
        if store and store != "pvc":
            return normalize_artifact_store(store)
        if os.environ.get("ARTIFACT_STORE", "").strip():
            return normalize_artifact_store(store or "pvc")
        if backend:
            return normalize_artifact_store(backend)
        return normalize_artifact_store(store or "pvc")

    def ensure_dirs(self) -> None:
        Path(self.artifact_dir).mkdir(parents=True, exist_ok=True)
        Path(self.work_root).mkdir(parents=True, exist_ok=True)
        Path(self.log_dir).mkdir(parents=True, exist_ok=True)

    def runtime_image_ref(self, image_from_spec: str | None = None) -> str:
        image = image_from_spec or self.runtime_image
        registry = self.image_registry.strip().rstrip("/")
        if registry and not image.startswith(registry) and "/" not in image.split(":")[0]:
            return f"{registry}/{image}"
        if registry and ":" in image and "/" not in image:
            return f"{registry}/{image}"
        return image


@lru_cache
def get_settings() -> Settings:
    return Settings()
