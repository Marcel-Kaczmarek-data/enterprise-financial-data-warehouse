"""Object storage abstraction: S3-compatible (SeaweedFS/MinIO locally, AWS S3 in cloud) or filesystem.

Every object written by the pipeline goes through :class:`ObjectStore`, so the landing-zone layout,
checksums and manifests are identical across backends.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from finance_common.config import local_config, repo_path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class ObjectInfo:
    key: str
    size: int


class ObjectStore(Protocol):
    bucket: str

    def put_bytes(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> None: ...
    def put_file(self, key: str, path: Path, metadata: dict[str, str] | None = None) -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def download(self, key: str, path: Path) -> None: ...
    def exists(self, key: str) -> bool: ...
    def list(self, prefix: str) -> Iterator[ObjectInfo]: ...
    def copy(self, src_key: str, dst_key: str) -> None: ...
    def uri(self, key: str) -> str: ...


def _bypass_proxy_for_local(endpoint: str | None) -> None:
    """Corporate HTTP(S)_PROXY settings must not intercept traffic to a local S3 endpoint."""
    if not endpoint:
        return
    host = urlparse(endpoint).hostname or ""
    if host in ("localhost", "127.0.0.1") or host.endswith(".local") or "." not in host:
        current = {h.strip() for h in os.environ.get("NO_PROXY", "").split(",") if h.strip()}
        current |= {"localhost", "127.0.0.1", host}
        os.environ["NO_PROXY"] = os.environ["no_proxy"] = ",".join(sorted(current))


class S3ObjectStore:
    def __init__(self, bucket: str, endpoint_url: str | None, region: str, access_key: str | None,
                 secret_key: str | None) -> None:
        import boto3
        from botocore.config import Config

        _bypass_proxy_for_local(endpoint_url)
        self.bucket = bucket
        self.endpoint_url = endpoint_url
        self.client = boto3.client(
            "s3", endpoint_url=endpoint_url or None, region_name=region,
            aws_access_key_id=access_key or None, aws_secret_access_key=secret_key or None,
            config=Config(retries={"max_attempts": 6, "mode": "standard"}, s3={"addressing_style": "path"}),
        )

    def ensure_bucket(self, versioning: bool = True) -> None:
        existing = {b["Name"] for b in self.client.list_buckets().get("Buckets", [])}
        if self.bucket not in existing:
            self.client.create_bucket(Bucket=self.bucket)
        if versioning:
            self.client.put_bucket_versioning(Bucket=self.bucket, VersioningConfiguration={"Status": "Enabled"})

    def put_bytes(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> None:
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, Metadata=metadata or {})

    def put_file(self, key: str, path: Path, metadata: dict[str, str] | None = None) -> None:
        self.client.upload_file(str(path), self.bucket, key, ExtraArgs={"Metadata": metadata or {}})

    def get_bytes(self, key: str) -> bytes:
        body: Any = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        return body.read()

    def download(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.client.download_file(self.bucket, key, str(path))

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                yield ObjectInfo(obj["Key"], obj["Size"])

    def copy(self, src_key: str, dst_key: str) -> None:
        self.client.copy_object(Bucket=self.bucket, Key=dst_key, CopySource={"Bucket": self.bucket, "Key": src_key})

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"


class FilesystemObjectStore:
    """Drop-in local backend (no Docker). Keys map to files under ``root/bucket``."""

    def __init__(self, root: Path, bucket: str) -> None:
        self.bucket = bucket
        self.root = root / bucket
        self.root.mkdir(parents=True, exist_ok=True)

    def _p(self, key: str) -> Path:
        p = (self.root / key).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError(f"key escapes the store root: {key}")
        return p

    def ensure_bucket(self, versioning: bool = True) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, key: str, data: bytes, metadata: dict[str, str] | None = None) -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_bytes(data)
        tmp.replace(p)  # atomic publish

    def put_file(self, key: str, path: Path, metadata: dict[str, str] | None = None) -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, p)

    def get_bytes(self, key: str) -> bytes:
        return self._p(key).read_bytes()

    def download(self, key: str, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._p(key), path)

    def exists(self, key: str) -> bool:
        return self._p(key).exists()

    def list(self, prefix: str) -> Iterator[ObjectInfo]:
        base = self.root
        for p in sorted(base.rglob("*")):
            if p.is_file() and not p.name.endswith(".tmp"):
                key = p.relative_to(base).as_posix()
                if key.startswith(prefix):
                    yield ObjectInfo(key, p.stat().st_size)

    def copy(self, src_key: str, dst_key: str) -> None:
        dst = self._p(dst_key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self._p(src_key), dst)

    def uri(self, key: str) -> str:
        return f"file://{self._p(key).as_posix()}"


def object_store_from_config() -> S3ObjectStore | FilesystemObjectStore:
    cfg = local_config()["object_store"]
    if cfg["backend"] == "filesystem":
        return FilesystemObjectStore(repo_path(local_config()["paths"]["local_object_store"]), cfg["bucket"])
    return S3ObjectStore(cfg["bucket"], cfg.get("endpoint_url"), cfg["region"], cfg.get("access_key"),
                         cfg.get("secret_key"))
