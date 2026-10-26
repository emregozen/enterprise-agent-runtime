"""Reserved adapter. OpenBao and Vault share this KV-shaped entry point."""

from __future__ import annotations

from secret_sources.errors import SecretProviderError


def fetch_secret(**_kwargs) -> str:
    raise SecretProviderError(
        "OpenBao ve HashiCorp Vault henüz bağlı değil. Sağlayıcı kaydı durur; KV okuma sonraki sürümde eklenecek."
    )
