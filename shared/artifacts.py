from __future__ import annotations

import hashlib
import tempfile
import time
from pathlib import Path


class ArtifactTooLarge(Exception):
    def __init__(self, limit: int):
        super().__init__(f"artefakt {limit} bayt sınırını aşıyor")
        self.limit = limit


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_artifact_name(name: str) -> str:
    cleaned = (name or "").strip()
    if not cleaned or len(cleaned) > 180 or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned or ".." in cleaned:
        raise ValueError("geçersiz artefakt adı")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if any(char not in allowed for char in cleaned):
        raise ValueError("geçersiz artefakt adı")
    return cleaned


def normalize_key(key: str) -> str:
    raw = (key or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/"):
        raise ValueError("geçersiz artefakt anahtarı")
    parts = [part for part in raw.split("/") if part != ""]
    if not parts or any(part in {".", ".."} for part in parts):
        raise ValueError("geçersiz artefakt anahtarı")
    return "/".join(parts)


class Upload:
    def write(self, chunk: bytes) -> None:
        raise NotImplementedError

    def finish(self) -> tuple[str, int, str]:
        raise NotImplementedError

    def abort(self) -> None:
        raise NotImplementedError


class ArtifactStore:
    def put_bytes(self, key: str, data: bytes, media_type: str) -> str:
        upload = self.start_upload(key, media_type, max(len(data), 1))
        try:
            upload.write(data)
            uri, _size, _digest = upload.finish()
        except Exception:
            upload.abort()
            raise
        return uri

    def start_upload(self, key: str, media_type: str, max_bytes: int) -> Upload:
        raise NotImplementedError

    def get_bytes(self, uri: str) -> bytes:
        return b"".join(self.iter_chunks(uri))

    def iter_chunks(self, uri: str, chunk_size: int = 65536):
        raise NotImplementedError

    def delete(self, uri: str) -> None:
        raise NotImplementedError

    def sweep_partials(self, max_age_seconds: int) -> int:
        return 0


class _PvcUpload(Upload):
    def __init__(self, root: Path, key: str, max_bytes: int):
        self.key = normalize_key(key)
        self.max_bytes = max_bytes
        self.size = 0
        self._digest = hashlib.sha256()
        self.path = root.joinpath(*self.key.split("/"))
        self.partial = self.path.with_name(self.path.name + ".partial")
        self.partial.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.partial.open("wb")
        self._done = False
        self._aborted = False

    def write(self, chunk: bytes) -> None:
        if self._done or self._aborted:
            raise RuntimeError("yükleme kapandı")
        if not chunk:
            return
        self.size += len(chunk)
        if self.size > self.max_bytes:
            self.abort()
            raise ArtifactTooLarge(self.max_bytes)
        self._digest.update(chunk)
        self._handle.write(chunk)

    def finish(self) -> tuple[str, int, str]:
        if self._aborted:
            raise RuntimeError("yükleme iptal edildi")
        try:
            self._handle.close()
            self.partial.replace(self.path)
        except Exception:
            self.abort()
            raise
        self._done = True
        return f"pvc://{self.key}", self.size, self._digest.hexdigest()

    def abort(self) -> None:
        if self._done or self._aborted:
            return
        self._aborted = True
        try:
            self._handle.close()
        except Exception:
            pass
        self.partial.unlink(missing_ok=True)


class PvcArtifactStore(ArtifactStore):
    """Files on a directory. On OpenShift that directory is the control-plane PVC."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def start_upload(self, key: str, media_type: str, max_bytes: int) -> Upload:
        return _PvcUpload(self.root, key, max_bytes)

    def _resolve(self, uri: str) -> Path:
        if uri.startswith("pvc://"):
            relative = normalize_key(uri[len("pvc://") :])
            path = self.root.joinpath(*relative.split("/"))
        else:
            path = Path(uri)
            if not path.is_absolute():
                raise ValueError("artefakt adresi bu depoda değil")
            path = path.resolve()
            if not path.is_relative_to(self.root):
                raise ValueError("artefakt adresi bu depoda değil")
        if path.is_symlink():
            raise ValueError("artefakt bağ olamaz")
        return path

    def iter_chunks(self, uri: str, chunk_size: int = 65536):
        path = self._resolve(uri)
        if not path.is_file():
            raise FileNotFoundError(uri)
        with path.open("rb") as handle:
            while True:
                block = handle.read(chunk_size)
                if not block:
                    break
                yield block

    def delete(self, uri: str) -> None:
        path = self._resolve(uri)
        if path.is_symlink():
            raise ValueError("artefakt bağ olamaz")
        path.unlink(missing_ok=True)
        parent = path.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def sweep_partials(self, max_age_seconds: int) -> int:
        if not self.root.exists():
            return 0
        now = time.time()
        removed = 0
        for partial in self.root.rglob("*.partial"):
            try:
                if partial.is_symlink() or not partial.is_file():
                    continue
                if now - partial.stat().st_mtime < max_age_seconds:
                    continue
                partial.unlink()
                removed += 1
            except OSError:
                continue
        return removed


class _S3Upload(Upload):
    def __init__(self, client, bucket: str, key: str, media_type: str, max_bytes: int):
        self.client = client
        self.bucket = bucket
        self.key = normalize_key(key)
        self.media_type = media_type or "application/octet-stream"
        self.max_bytes = max_bytes
        self.size = 0
        self._digest = hashlib.sha256()
        self._spool = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
        self._done = False
        self._aborted = False

    def write(self, chunk: bytes) -> None:
        if self._done or self._aborted:
            raise RuntimeError("yükleme kapandı")
        if not chunk:
            return
        self.size += len(chunk)
        if self.size > self.max_bytes:
            self.abort()
            raise ArtifactTooLarge(self.max_bytes)
        self._digest.update(chunk)
        self._spool.write(chunk)

    def finish(self) -> tuple[str, int, str]:
        if self._aborted:
            raise RuntimeError("yükleme iptal edildi")
        try:
            self._spool.seek(0)
            self.client.put_object(
                Bucket=self.bucket,
                Key=self.key,
                Body=self._spool,
                ContentType=self.media_type,
                ContentLength=self.size,
            )
        except Exception:
            self.abort()
            raise
        self._done = True
        self._spool.close()
        return f"s3://{self.bucket}/{self.key}", self.size, self._digest.hexdigest()

    def abort(self) -> None:
        if self._done or self._aborted:
            return
        self._aborted = True
        try:
            self._spool.close()
        except Exception:
            pass


class S3ArtifactStore(ArtifactStore):
    def __init__(self, *, endpoint_url: str, bucket: str, access_key: str, secret_key: str, region: str, path_style: bool):
        import boto3
        from botocore.client import Config

        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key or None,
            aws_secret_access_key=secret_key or None,
            region_name=region,
            config=Config(s3={"addressing_style": "path" if path_style else "auto"}),
        )

    def start_upload(self, key: str, media_type: str, max_bytes: int) -> Upload:
        return _S3Upload(self.client, self.bucket, key, media_type, max_bytes)

    def _key(self, uri: str) -> str:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("artifact uri is outside the configured bucket")
        return normalize_key(uri[len(prefix) :])

    def iter_chunks(self, uri: str, chunk_size: int = 65536):
        from botocore.exceptions import ClientError

        key = self._key(uri)
        try:
            body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NotFound"}:
                raise FileNotFoundError(uri) from exc
            raise
        for chunk in body.iter_chunks(chunk_size):
            if chunk:
                yield chunk

    def delete(self, uri: str) -> None:
        key = self._key(uri)
        self.client.delete_object(Bucket=self.bucket, Key=key)


def normalize_artifact_store(value: str) -> str:
    name = (value or "").strip().lower()
    if name in {"pvc", "local", "filesystem", "fs"}:
        return "pvc"
    if name == "s3":
        return "s3"
    raise ValueError(f"ARTIFACT_STORE pvc veya s3 olmalı, gelen: {value}")


def build_store(settings) -> ArtifactStore:
    kind = settings.resolved_artifact_store()
    if kind == "s3":
        return S3ArtifactStore(
            endpoint_url=settings.s3_endpoint_url,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
            path_style=settings.s3_use_path_style,
        )
    return PvcArtifactStore(settings.artifact_dir)
