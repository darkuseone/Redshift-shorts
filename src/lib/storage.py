"""Адаптер внешнего хранилища кэша футажей (§14.4, §14.5, K-12).

В репозитории живут только капнутые библиотеки и ``cache/footage_index.json``.
Сами файлы футажей лежат во внешнем storage: локальный каталог вне git (по
умолчанию) либо S3/R2. При переполнении работает LRU-вытеснение (R-11).

Бэкенд S3 реализован на чистом requests с подписью AWS SigV4 — чтобы не тащить
boto3 в раннер ради трёх операций.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import os
import shutil
import time
import urllib.parse
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

from ..errors import RedshiftError
from .logging import get_logger

_log = get_logger("storage")


@dataclass
class StoredObject:
    key: str
    size_bytes: int
    last_used: float          # unix ts, обновляется при каждом чтении → основа LRU
    created: float


class StorageBackend(ABC):
    @abstractmethod
    def put(self, key: str, src: str | Path) -> str: ...

    @abstractmethod
    def get(self, key: str, dst: str | Path) -> Path: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def list(self) -> Iterator[StoredObject]: ...

    @abstractmethod
    def total_bytes(self) -> int: ...

    def touch(self, key: str) -> None:
        """Отметить обращение — обновляет позицию в LRU."""


class LocalStorage(StorageBackend):
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        safe = key.replace("..", "_").lstrip("/")
        return self.root / safe

    def put(self, key: str, src: str | Path) -> str:
        dst = self._path(key)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if Path(src).resolve() != dst.resolve():
            shutil.copy2(src, dst)
        return str(dst)

    def get(self, key: str, dst: str | Path) -> Path:
        src = self._path(key)
        if not src.exists():
            raise RedshiftError("объект отсутствует в storage", code="STORAGE_MISS", key=key)
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.resolve() != dst.resolve():
            shutil.copy2(src, dst)
        self.touch(key)
        return dst

    def local_path(self, key: str) -> Path | None:
        p = self._path(key)
        return p if p.exists() else None

    def exists(self, key: str) -> bool:
        return self._path(key).exists()

    def delete(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            p.unlink()

    def list(self) -> Iterator[StoredObject]:
        for p in self.root.rglob("*"):
            if p.is_file():
                st = p.stat()
                yield StoredObject(
                    key=str(p.relative_to(self.root)),
                    size_bytes=st.st_size,
                    last_used=st.st_atime,
                    created=st.st_mtime,
                )

    def total_bytes(self) -> int:
        return sum(o.size_bytes for o in self.list())

    def touch(self, key: str) -> None:
        p = self._path(key)
        if p.exists():
            now = time.time()
            os.utime(p, (now, p.stat().st_mtime))


class S3Storage(StorageBackend):
    """Минимальный S3/R2-клиент (SigV4) — put/get/head/delete/list."""

    def __init__(self, *, bucket: str, access_key: str, secret_key: str,
                 endpoint: str = "https://s3.amazonaws.com", region: str = "auto",
                 prefix: str = "") -> None:
        self.bucket = bucket
        self.access_key = access_key
        self.secret_key = secret_key
        self.endpoint = endpoint.rstrip("/")
        self.region = region
        self.prefix = prefix

    # --- SigV4 ---
    def _sign(self, method: str, key: str, *, payload: bytes = b"",
              query: str = "") -> tuple[str, dict[str, str]]:
        import requests  # noqa: F401  (проверка наличия зависимости)

        url = f"{self.endpoint}/{self.bucket}/{urllib.parse.quote(key)}"
        parsed = urllib.parse.urlparse(url)
        host = parsed.netloc
        now = _dt.datetime.now(_dt.timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        date_stamp = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(payload).hexdigest()

        canonical_headers = f"host:{host}\nx-amz-content-sha256:{payload_hash}\nx-amz-date:{amz_date}\n"
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical_request = "\n".join([
            method, parsed.path, query, canonical_headers, signed_headers, payload_hash,
        ])
        scope = f"{date_stamp}/{self.region}/s3/aws4_request"
        string_to_sign = "\n".join([
            "AWS4-HMAC-SHA256", amz_date, scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ])

        def _hmac(key_bytes: bytes, msg: str) -> bytes:
            return hmac.new(key_bytes, msg.encode(), hashlib.sha256).digest()

        k_date = _hmac(f"AWS4{self.secret_key}".encode(), date_stamp)
        k_region = _hmac(k_date, self.region)
        k_service = _hmac(k_region, "s3")
        k_signing = _hmac(k_service, "aws4_request")
        signature = hmac.new(k_signing, string_to_sign.encode(), hashlib.sha256).hexdigest()

        headers = {
            "x-amz-date": amz_date,
            "x-amz-content-sha256": payload_hash,
            "Authorization": (
                f"AWS4-HMAC-SHA256 Credential={self.access_key}/{scope}, "
                f"SignedHeaders={signed_headers}, Signature={signature}"
            ),
        }
        return (url + (f"?{query}" if query else "")), headers

    def _full(self, key: str) -> str:
        return f"{self.prefix}{key}" if self.prefix else key

    def put(self, key: str, src: str | Path) -> str:
        import requests

        payload = Path(src).read_bytes()
        url, headers = self._sign("PUT", self._full(key), payload=payload)
        resp = requests.put(url, data=payload, headers=headers, timeout=300)
        if resp.status_code >= 300:
            raise RedshiftError("S3 PUT не удался", code="STORAGE_ERROR",
                                status=resp.status_code, key=key)
        return f"s3://{self.bucket}/{self._full(key)}"

    def get(self, key: str, dst: str | Path) -> Path:
        import requests

        url, headers = self._sign("GET", self._full(key))
        resp = requests.get(url, headers=headers, timeout=300)
        if resp.status_code >= 300:
            raise RedshiftError("объект отсутствует в S3", code="STORAGE_MISS",
                                status=resp.status_code, key=key)
        dst = Path(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(resp.content)
        return dst

    def exists(self, key: str) -> bool:
        import requests

        url, headers = self._sign("HEAD", self._full(key))
        return requests.head(url, headers=headers, timeout=60).status_code < 300

    def delete(self, key: str) -> None:
        import requests

        url, headers = self._sign("DELETE", self._full(key))
        requests.delete(url, headers=headers, timeout=120)

    def list(self) -> Iterator[StoredObject]:
        import xml.etree.ElementTree as ET

        import requests

        url, headers = self._sign("GET", "", query=f"list-type=2&prefix={urllib.parse.quote(self.prefix)}")
        url = f"{self.endpoint}/{self.bucket}?list-type=2&prefix={urllib.parse.quote(self.prefix)}"
        resp = requests.get(url, headers=headers, timeout=120)
        if resp.status_code >= 300:
            return
        ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}
        for item in ET.fromstring(resp.text).findall(".//s3:Contents", ns):
            key = item.findtext("s3:Key", "", ns)
            size = int(item.findtext("s3:Size", "0", ns) or 0)
            modified = item.findtext("s3:LastModified", "", ns)
            ts = time.time()
            if modified:
                try:
                    ts = _dt.datetime.fromisoformat(modified.replace("Z", "+00:00")).timestamp()
                except ValueError:
                    pass
            yield StoredObject(key=key[len(self.prefix):], size_bytes=size, last_used=ts, created=ts)

    def total_bytes(self) -> int:
        return sum(o.size_bytes for o in self.list())


def build_storage(cfg) -> StorageBackend:
    backend = str(cfg.get("storage.backend", "local")).lower()
    if backend == "local":
        return LocalStorage(cfg.path("storage.local_root", ".redshift_cache/footage"))
    if backend == "s3":
        bucket = cfg.secret_for("storage.s3.bucket_env", required=True, purpose="S3 bucket")
        return S3Storage(
            bucket=bucket or "",
            access_key=cfg.secret_for("storage.s3.access_key_env", required=True, purpose="S3") or "",
            secret_key=cfg.secret_for("storage.s3.secret_key_env", required=True, purpose="S3") or "",
            endpoint=cfg.secret_for("storage.s3.endpoint_env") or "https://s3.amazonaws.com",
            prefix=str(cfg.get("storage.s3.prefix", "")),
        )
    raise RedshiftError(f"неизвестный storage.backend: {backend}", code="CONFIG_ERROR")


def evict_lru(storage: StorageBackend, *, max_bytes: int,
              protected: Iterable[str] = ()) -> list[str]:
    """LRU-вытеснение до попадания в лимит. Возвращает удалённые ключи (§14.4)."""
    protected_set = set(protected)
    objects = sorted(storage.list(), key=lambda o: o.last_used)
    total = sum(o.size_bytes for o in objects)
    removed: list[str] = []
    for obj in objects:
        if total <= max_bytes:
            break
        if obj.key in protected_set:
            continue
        storage.delete(obj.key)
        total -= obj.size_bytes
        removed.append(obj.key)
    if removed:
        _log.info("LRU-вытеснение кэша футажей",
                  extra={"removed": len(removed), "total_bytes": total, "limit": max_bytes})
    return removed
