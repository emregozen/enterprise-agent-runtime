"""Read a Kubernetes Secret. The bytes are returned to the caller and not logged."""

from __future__ import annotations

import base64

from secret_sources.errors import SecretProviderError


def read_secret_data(name: str, namespace: str) -> dict[str, str]:
    if not name or not namespace:
        raise SecretProviderError("Kubernetes Secret adı veya ad alanı boş")
    try:
        from kubernetes import client, config
        from kubernetes.client.rest import ApiException
    except Exception as exc:  # noqa: BLE001
        raise SecretProviderError("Kubernetes istemcisi yok; Secret okunamadı") from exc
    from shared.config import get_settings

    settings = get_settings()
    try:
        if settings.kubeconfig:
            config.load_kube_config(config_file=settings.kubeconfig)
        else:
            try:
                config.load_incluster_config()
            except Exception:
                config.load_kube_config()
        secret = client.CoreV1Api().read_namespaced_secret(name, namespace)
    except ApiException as exc:
        status = getattr(exc, "status", None)
        if status == 404:
            raise SecretProviderError(f"Kubernetes Secret bulunamadı: {namespace}/{name}") from exc
        raise SecretProviderError(
            f"Kubernetes Secret okunamadı ({status}). "
            "Kontrol düzleminin bu ad alanındaki Secret'ları görme yetkisi olmayabilir."
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise SecretProviderError(
            "Kubernetes API'ye ulaşılamadı. Kontrol düzlemi küme içinden Secret okuyamıyor."
        ) from exc
    raw = secret.data or {}
    decoded: dict[str, str] = {}
    for key, value in raw.items():
        if not value:
            continue
        try:
            decoded[key] = base64.b64decode(value).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise SecretProviderError(f"Kubernetes Secret anahtarı metin değil: {key}") from exc
    return decoded
