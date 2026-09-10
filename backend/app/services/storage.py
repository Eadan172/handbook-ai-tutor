from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from minio import Minio

from app.core.config import get_settings


class StorageProvider(ABC):
    @abstractmethod
    async def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        raise NotImplementedError

    @abstractmethod
    async def get_bytes(self, key: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def ensure_ready(self) -> None:
        raise NotImplementedError


class LocalStorage(StorageProvider):
    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or get_settings().local_storage_path)
        self.root.mkdir(parents=True, exist_ok=True)

    async def ensure_ready(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path)

    async def get_bytes(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


class MinioStorage(StorageProvider):
    def __init__(self) -> None:
        s = get_settings()
        endpoint = s.s3_endpoint.replace("http://", "").replace("https://", "")
        self.client = Minio(
            endpoint,
            access_key=s.s3_access_key,
            secret_key=s.s3_secret_key,
            secure=s.s3_secure or s.s3_endpoint.startswith("https://"),
            region=s.s3_region,
        )
        self.bucket = s.s3_bucket

    async def ensure_ready(self) -> None:
        from asyncio import to_thread

        def _ensure() -> None:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)

        await to_thread(_ensure)

    async def put_bytes(self, key: str, data: bytes, content_type: str) -> str:
        from asyncio import to_thread
        from io import BytesIO

        def _put() -> None:
            self.client.put_object(
                self.bucket,
                key,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        await to_thread(_put)
        return key

    async def get_bytes(self, key: str) -> bytes:
        from asyncio import to_thread

        def _get() -> bytes:
            resp = self.client.get_object(self.bucket, key)
            try:
                return resp.read()
            finally:
                resp.close()
                resp.release_conn()

        return await to_thread(_get)


_storage: StorageProvider | None = None


def get_storage() -> StorageProvider:
    global _storage
    if _storage is None:
        backend = get_settings().storage_backend
        _storage = MinioStorage() if backend == "minio" else LocalStorage()
    return _storage


def reset_storage() -> None:
    global _storage
    _storage = None
