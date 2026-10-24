from __future__ import annotations

import hashlib
from pathlib import Path


class ArtifactStore:
    def put_bytes(self, key: str, data: bytes, media_type: str) -> str:
        raise NotImplementedError

    def get_bytes(self, uri: str) -> bytes:
        raise NotImplementedError


class LocalArtifactStore(ArtifactStore):
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, media_type: str) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path.resolve())

    def get_bytes(self, uri: str) -> bytes:
        return Path(uri).read_bytes()


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

    def put_bytes(self, key: str, data: bytes, media_type: str) -> str:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=media_type)
        return f"s3://{self.bucket}/{key}"

    def get_bytes(self, uri: str) -> bytes:
        prefix = f"s3://{self.bucket}/"
        if not uri.startswith(prefix):
            raise ValueError("artifact uri is outside the configured bucket")
        key = uri[len(prefix) :]
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()


def build_store(settings) -> ArtifactStore:
    if settings.artifact_backend == "s3":
        return S3ArtifactStore(
            endpoint_url=settings.s3_endpoint_url,
            bucket=settings.s3_bucket,
            access_key=settings.s3_access_key,
            secret_key=settings.s3_secret_key,
            region=settings.s3_region,
            path_style=settings.s3_use_path_style,
        )
    return LocalArtifactStore(settings.artifact_dir)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
