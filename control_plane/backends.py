from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from control_plane.db import SessionLocal
from control_plane.job_manifest import build_run_manifests
from control_plane.models import Run, utcnow
from control_plane.service import audit, load_sources_for_spec, materialize_sources
from shared.config import get_settings

_lock = threading.Lock()
_backend: "RunBackend | None" = None


class RunBackend:
    def submit(self, run_id: uuid.UUID, token: str) -> str:
        raise NotImplementedError

    def reconcile(self) -> None:
        return None

    def read_logs(self, run: Run) -> str:
        if run.log_path and Path(run.log_path).exists():
            return Path(run.log_path).read_text(encoding="utf-8", errors="replace")[-200_000:]
        return ""


@dataclass
class _Proc:
    harness: subprocess.Popen
    executor: subprocess.Popen
    logf: object


class LocalBackend(RunBackend):
    """Two local processes with separate environments, matching the two-container pod."""

    def __init__(self):
        self.procs: dict[uuid.UUID, _Proc] = {}
        self._guard = threading.Lock()

    def submit(self, run_id: uuid.UUID, token: str) -> str:
        settings = get_settings()
        settings.ensure_dirs()
        db = SessionLocal()
        try:
            run = db.get(Run, run_id)
            if run is None:
                raise RuntimeError("koşum kaydı yok")
            sources = materialize_sources(load_sources_for_spec(db, run.spec_snapshot))
            # Relative work roots must be resolved before the child cwd is that
            # directory. Otherwise the executor joins the same relative path again.
            work = (Path(settings.work_root) / str(run_id)).resolve()
            work.mkdir(parents=True, exist_ok=True)
            log_path = (Path(settings.log_dir) / f"{run_id}.log").resolve()
            port = _free_port()
            logf = open(log_path, "ab", buffering=0)
            repo_root = str(Path(__file__).resolve().parents[1])
            base_env = {
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "HOME": "/tmp",
                "TMPDIR": "/tmp",
                "LANG": os.environ.get("LANG", "C.UTF-8"),
                "LC_ALL": os.environ.get("LC_ALL", "C.UTF-8"),
                "PYTHONPATH": repo_root + os.pathsep + os.environ.get("PYTHONPATH", ""),
                "PYTHONNOUSERSITE": "1",
                "PYTHONUNBUFFERED": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            executor = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "executor",
                    "serve",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                    "--workdir",
                    str(work),
                ],
                env=base_env,
                cwd=str(work),
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
            resolved = settings.resolve_model((run.spec_snapshot["spec"].get("model") or {}).get("class") or "local-default")
            harness_env = dict(base_env)
            harness_env.update(
                {
                    "RUN_ID": str(run_id),
                    "RUN_TOKEN": token,
                    "CONTROL_PLANE_URL": settings.control_plane_public_url,
                    "EXECUTOR_URL": f"http://127.0.0.1:{port}",
                    "WORKDIR": str(work),
                    "LLM_MODE": settings.llm_mode,
                    "LLM_BASE_URL": resolved["base_url"],
                    "LLM_MODEL": resolved["model"],
                    "OTEL_EXPORTER_OTLP_ENDPOINT": settings.otel_exporter_otlp_endpoint,
                    "OTEL_SERVICE_NAME": settings.otel_service_name,
                    "LOG_LEVEL": settings.log_level,
                    "HARNESS_FAULT_ROUNDS": os.environ.get("HARNESS_FAULT_ROUNDS", "0"),
                }
            )
            if settings.llm_mode == "openai":
                harness_env["LLM_API_KEY"] = resolved["api_key"]
            for source in sources:
                harness_env[source["dsn_env"]] = source["dsn"]
            harness = subprocess.Popen(
                [sys.executable, "-m", "harness", "--run-id", str(run_id)],
                env=harness_env,
                cwd=str(work),
                stdout=logf,
                stderr=subprocess.STDOUT,
            )
            run.status = "running"
            run.started_at = utcnow()
            run.job_name = f"local-{run_id.hex[:12]}"
            run.log_path = str(log_path)
            db.commit()
            self.procs[run_id] = _Proc(harness, executor, logf)
            threading.Thread(target=self._watch, args=(run_id,), name=f"run-{run_id.hex[:8]}", daemon=True).start()
            return run.job_name
        finally:
            db.close()

    def _watch(self, run_id: uuid.UUID) -> None:
        proc = self.procs.get(run_id)
        if proc is not None:
            proc.harness.wait()
        self.reconcile()

    def reconcile(self) -> None:
        with self._guard:
            self._reconcile_locked()

    def _reconcile_locked(self) -> None:
        if not self.procs:
            return
        db = SessionLocal()
        try:
            finished = []
            for run_id, proc in list(self.procs.items()):
                code = proc.harness.poll()
                if code is None:
                    continue
                if proc.executor.poll() is None:
                    proc.executor.terminate()
                    try:
                        proc.executor.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        proc.executor.kill()
                proc.logf.close()
                run = db.get(Run, run_id)
                if run is not None and run.status in {"pending", "running"}:
                    run.status = "failed"
                    run.error = f"harness çıktı kodu {code}; tamamlanma raporu yazılmadı"
                    run.finished_at = utcnow()
                    audit(db, "controller", "run.completed", "run", str(run.id), {"status": "failed", "exit": code})
                finished.append(run_id)
            db.commit()
            for run_id in finished:
                self.procs.pop(run_id, None)
        finally:
            db.close()


class KubernetesBackend(RunBackend):
    def __init__(self):
        from kubernetes import client, config

        settings = get_settings()
        if settings.kubeconfig:
            config.load_kube_config(config_file=settings.kubeconfig)
        else:
            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()
        self.api = client.ApiClient()
        self.batch = client.BatchV1Api()
        self.core = client.CoreV1Api()
        self.namespace = settings.run_namespace

    def submit(self, run_id: uuid.UUID, token: str) -> str:
        from kubernetes import utils

        settings = get_settings()
        db = SessionLocal()
        try:
            run = db.get(Run, run_id)
            if run is None:
                raise RuntimeError("koşum kaydı yok")
            sources = materialize_sources(load_sources_for_spec(db, run.spec_snapshot))
            secret, job = build_run_manifests(
                run_id=run.id,
                agent_name=run.agent_name,
                spec_version=run.spec_version,
                spec=run.spec_snapshot,
                token=token,
                datasources=sources,
                settings=settings,
                llm_api_key=settings.resolve_model((run.spec_snapshot["spec"].get("model") or {}).get("class") or "local-default")["api_key"],
            )
            utils.create_from_dict(self.api, secret, namespace=self.namespace)
            created = utils.create_from_dict(self.api, job, namespace=self.namespace)
            job_name = job["metadata"]["name"]
            job_uid = None
            if created:
                job_uid = created[0].metadata.uid
            if job_uid:
                self.core.patch_namespaced_secret(
                    secret["metadata"]["name"],
                    self.namespace,
                    {
                        "metadata": {
                            "ownerReferences": [
                                {
                                    "apiVersion": "batch/v1",
                                    "kind": "Job",
                                    "name": job_name,
                                    "uid": job_uid,
                                    "controller": False,
                                    "blockOwnerDeletion": False,
                                }
                            ]
                        }
                    },
                )
            run.job_name = job_name
            run.status = "running"
            run.started_at = utcnow()
            db.commit()
            return job_name
        finally:
            db.close()

    def reconcile(self) -> None:
        db = SessionLocal()
        try:
            jobs = self.batch.list_namespaced_job(self.namespace, label_selector="app=agent-run")
            for job in jobs.items:
                annotations = job.metadata.annotations or {}
                run_id = annotations.get("agent.internal/run-id")
                if not run_id:
                    continue
                run = db.get(Run, uuid.UUID(run_id))
                if run is None or run.status not in {"pending", "running"}:
                    continue
                status = job.status
                failed = (status.failed or 0) if status else 0
                succeeded = (status.succeeded or 0) if status else 0
                if failed:
                    run.status = "failed"
                    run.error = "Kubernetes Job başarısız oldu (backoffLimit=0)"
                    run.finished_at = utcnow()
                    audit(db, "controller", "run.completed", "run", str(run.id), {"status": "failed"})
                elif succeeded and not run.report_markdown and run.summary is None:
                    run.status = "needs_review"
                    run.needs_review_reason = "Job bitti ama harness rapor yazmadı"
                    run.finished_at = utcnow()
                    audit(db, "controller", "run.needs_review", "run", str(run.id), {})
            db.commit()
        finally:
            db.close()

    def read_logs(self, run: Run) -> str:
        if not run.job_name:
            return ""
        pods = self.core.list_namespaced_pod(self.namespace, label_selector=f"job-name={run.job_name}")
        chunks = []
        for pod in pods.items:
            try:
                chunks.append(
                    self.core.read_namespaced_pod_log(pod.metadata.name, self.namespace, container="harness")
                )
            except Exception as exc:  # noqa: BLE001
                chunks.append(f"(log okunamadı: {exc})")
        return "\n".join(chunks)[-200_000:]


class RecordingBackend(RunBackend):
    def __init__(self):
        self.submitted: list[uuid.UUID] = []

    def submit(self, run_id: uuid.UUID, token: str) -> str:
        self.submitted.append(run_id)
        db = SessionLocal()
        try:
            run = db.get(Run, run_id)
            if run is not None:
                run.status = "running"
                run.job_name = f"rec-{run_id.hex[:12]}"
                run.started_at = utcnow()
                db.commit()
                return run.job_name
        finally:
            db.close()
        return f"rec-{run_id.hex[:12]}"


def get_backend() -> RunBackend:
    global _backend
    with _lock:
        if _backend is None:
            kind = get_settings().run_backend
            if kind == "kubernetes":
                _backend = KubernetesBackend()
            elif kind == "recording":
                _backend = RecordingBackend()
            else:
                _backend = LocalBackend()
        return _backend


def set_backend(backend: RunBackend | None) -> None:
    global _backend
    with _lock:
        _backend = backend


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
