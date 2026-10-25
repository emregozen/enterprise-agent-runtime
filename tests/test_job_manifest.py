import json
import uuid

from control_plane.job_manifest import build_run_manifests
from shared.config import get_settings
from shared.spec import AgentSpec
from tests.test_spec_and_policy import SPEC


def test_job_is_restricted_and_executor_has_no_secrets():
    settings = get_settings()
    settings.job_ttl_seconds = 600
    spec = AgentSpec.model_validate(SPEC).canonical()
    token = "super-secret-token-value"
    dsn = "postgresql://sales_ro:sales-password@db.internal:5432/sales"
    secret, job = build_run_manifests(
        run_id=uuid.uuid4(),
        agent_name="gunluk-satis-ozeti",
        spec_version=3,
        spec=spec,
        token=token,
        datasources=[
            {
                "name": "postgres-sales",
                "dialect": "postgres",
                "dsn_env": "SALES_DATABASE_URL",
                "dsn": dsn,
                "allow_tables": ["sales"],
                "sensitivity": "internal",
            }
        ],
        settings=settings,
        llm_api_key="llm-secret",
    )
    rendered = json.dumps(job)
    assert token not in rendered
    assert "sales-password" not in rendered
    assert "llm-secret" not in rendered
    assert secret["stringData"]["RUN_TOKEN"] == token
    assert secret["stringData"]["SALES_DATABASE_URL"] == dsn
    pod = job["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["enableServiceLinks"] is False
    assert pod["restartPolicy"] == "Never"
    assert "runAsUser" not in pod["securityContext"]
    assert job["spec"]["backoffLimit"] == 0
    assert job["spec"]["activeDeadlineSeconds"] == 900
    assert job["spec"]["ttlSecondsAfterFinished"] == 600
    executor = next(item for item in pod["containers"] if item["name"] == "executor")
    harness = next(item for item in pod["containers"] if item["name"] == "harness")
    assert "valueFrom" not in json.dumps(executor["env"])
    assert "SALES_DATABASE_URL" not in json.dumps(executor)
    assert executor["securityContext"]["readOnlyRootFilesystem"] is True
    assert executor["securityContext"]["allowPrivilegeEscalation"] is False
    assert executor["securityContext"]["capabilities"]["drop"] == ["ALL"]
    assert any(item["name"] == "RUN_TOKEN" and "secretKeyRef" in item["valueFrom"] for item in harness["env"])
    assert secret["metadata"]["namespace"] == settings.run_namespace
    assert job["metadata"]["namespace"] == settings.run_namespace
    assert harness["resources"]["requests"]["ephemeral-storage"] == "1Gi"
    assert executor["resources"]["requests"]["ephemeral-storage"] == "1Gi"
    volumes = pod["volumes"]
    assert {item["name"] for item in volumes} == {"work", "tmp"}
    assert all("emptyDir" in item for item in volumes)
    assert all("persistentVolumeClaim" not in item for item in volumes)


def test_external_datasource_secret_is_not_copied_into_the_run_secret():
    settings = get_settings()
    spec = AgentSpec.model_validate(SPEC).canonical()
    secret, job = build_run_manifests(
        run_id=uuid.uuid4(),
        agent_name="gunluk-satis-ozeti",
        spec_version=1,
        spec=spec,
        token="tok",
        datasources=[
            {
                "name": "postgres-sales",
                "dialect": "postgres",
                "dsn_env": "SALES_DATABASE_URL",
                "dsn": "",
                "allow_tables": ["sales"],
                "sensitivity": "internal",
                "k8s_secret_name": "ds-postgres-sales",
                "k8s_secret_key": "dsn",
            }
        ],
        settings=settings,
    )
    assert "SALES_DATABASE_URL" not in secret["stringData"]
    harness = job["spec"]["template"]["spec"]["containers"][0]
    ref = next(item for item in harness["env"] if item["name"] == "SALES_DATABASE_URL")
    assert ref["valueFrom"]["secretKeyRef"]["name"] == "ds-postgres-sales"
