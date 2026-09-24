"""Filesystem-backed object store.

Same key semantics as S3, so switching backends changes no calling code. Keys
map directly onto relative paths under a root directory - which also means the
local lake and the R2 bucket have byte-identical layouts, and you can `rclone`
one into the other.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from finlens.storage.base import ObjectStore, StoredObject


class LocalObjectStore(ObjectStore):
    def __init__(self, root: Path | str, prefix: str = "") -> None:
        self.root = Path(root)
        self.prefix = prefix.strip("/")
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, key: str) -> Path:
        full_key = f"{self.prefix}/{key}" if self.prefix else key
        path = (self.root / full_key).resolve()
        # A key containing `../` would otherwise escape the root. Keys are
        # constructed from EDGAR identifiers, but they are still external input.
        if not str(path).startswith(str(self.root.resolve())):
            raise ValueError(f"key escapes the storage root: {key!r}")
        return path

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/json") -> str:
        path = self._resolve(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename: a crash mid-write leaves the previous object intact
        # rather than a truncated one that parses as valid-but-wrong.
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_bytes(data)
        temp.replace(path)
        return self.uri(key)

    def get_bytes(self, key: str) -> bytes | None:
        path = self._resolve(key)
        return path.read_bytes() if path.exists() else None

    def exists(self, key: str) -> bool:
        return self._resolve(key).exists()

    def list(self, prefix: str) -> Iterator[StoredObject]:
        base = self._resolve(prefix)
        search_root = base if base.is_dir() else base.parent
        if not search_root.exists():
            return

        root_with_prefix = self._resolve("")
        for path in sorted(search_root.rglob("*")):
            if not path.is_file() or path.suffix == ".tmp":
                continue
            key = str(path.relative_to(root_with_prefix))
            if not key.startswith(prefix):
                continue
            stat = path.stat()
            yield StoredObject(
                key=key,
                size=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            )

    def uri(self, key: str) -> str:
        return f"file://{self._resolve(key)}"

    def local_path(self, key: str) -> str:
        return str(self._resolve(key))
