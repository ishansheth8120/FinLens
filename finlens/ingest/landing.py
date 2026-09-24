"""Writing fetched bytes into the raw zone, with a manifest.

The invariant: **raw is append-only and self-describing.** Every write records
where the bytes came from, when, and their SHA-256, in a JSONL manifest
partitioned by ingest date. That manifest is what makes a reprocess auditable a
year later, and it is the first link in the lineage chain that ends at a
sentence in an answer.

Writes go through `finlens.storage`, so the same code lands to a local
directory or to Cloudflare R2 with no change at the call site.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone

from finlens.logging import get_logger
from finlens.storage.base import ObjectStore, manifest_key

log = get_logger(__name__)


@dataclass(frozen=True)
class LandedObject:
    key: str
    uri: str
    url: str
    sha256: str
    bytes_written: int
    fetched_at: str


def land_bytes(
    store: ObjectStore,
    key: str,
    content: bytes,
    *,
    url: str,
    content_type: str = "application/json",
    when: date | str | None = None,
) -> LandedObject:
    """Write ``content`` at ``key`` and append a manifest entry."""
    digest = store.digest(content)
    uri = store.put_bytes(key, content, content_type=content_type)

    landed = LandedObject(
        key=key,
        uri=uri,
        url=url,
        sha256=digest,
        bytes_written=len(content),
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )
    append_manifest(store, landed, when=when)
    log.debug("landing.wrote", key=key, bytes=len(content))
    return landed


def land_json(
    store: ObjectStore,
    key: str,
    payload: object,
    *,
    url: str,
    when: date | str | None = None,
) -> LandedObject:
    """Land a parsed payload as canonical JSON.

    ``sort_keys`` makes the digest a stable content identity, so an unchanged
    upstream document produces an unchanged hash even if SEC's own key ordering
    drifts between pulls.
    """
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return land_bytes(store, key, content, url=url, when=when)


def append_manifest(
    store: ObjectStore, landed: LandedObject, *, when: date | str | None = None
) -> None:
    """Append one entry to the day's manifest.

    Read-modify-write because object stores have no append. That is fine at this
    volume - the manifest is one small line per landed object per day - and it
    keeps the manifest a single readable artefact rather than thousands of
    sidecars.
    """
    key = manifest_key(when)
    existing = store.get_bytes(key) or b""
    line = json.dumps(asdict(landed), sort_keys=True).encode("utf-8") + b"\n"
    store.put_bytes(key, existing + line, content_type="application/x-ndjson")


def read_manifest(store: ObjectStore, *, when: date | str | None = None) -> list[LandedObject]:
    """Everything landed on one date, oldest first."""
    raw = store.get_bytes(manifest_key(when))
    if not raw:
        return []
    return [
        LandedObject(**json.loads(line))
        for line in raw.decode("utf-8").splitlines()
        if line.strip()
    ]


def already_landed(
    store: ObjectStore,
    url: str,
    *,
    sha256: str | None = None,
    when: date | str | None = None,
) -> bool:
    """Whether ``url`` was landed on this date, optionally with the same bytes.

    Without a digest this answers "have we fetched this today"; with one, "has
    it changed since". Both are what make a re-run idempotent instead of
    duplicative.
    """
    for entry in read_manifest(store, when=when):
        if entry.url == url and (sha256 is None or entry.sha256 == sha256):
            return True
    return False
