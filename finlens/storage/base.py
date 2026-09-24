"""The object-store interface and the key layout every backend shares."""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any

from finlens.identifiers import accession_nodash, normalize_cik


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    etag: str | None = None
    last_modified: datetime | None = None


class ObjectStore(ABC):
    """Minimal blob store. Deliberately small - anything richer would leak
    backend semantics into callers and make the local fallback a lie."""

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/json") -> str:
        """Write an object. Returns its URI."""

    @abstractmethod
    def get_bytes(self, key: str) -> bytes | None:
        """Read an object, or ``None`` if it does not exist."""

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def list(self, prefix: str) -> Iterator[StoredObject]: ...

    @abstractmethod
    def uri(self, key: str) -> str:
        """A stable, human-quotable address. Ends up in the lineage trail."""

    @abstractmethod
    def local_path(self, key: str) -> str:
        """A path Spark can read.

        For the local backend this is a real filesystem path; for S3 it is an
        ``s3a://`` URL. Spark needs one string it can hand to its own reader,
        and the two backends spell it differently.
        """

    # -- conveniences ---------------------------------------------------------

    def put_json(self, key: str, payload: Any) -> str:
        """Write canonical JSON.

        ``sort_keys`` makes the digest a stable content identity, so an
        unchanged upstream document produces an unchanged hash even if SEC's own
        key ordering drifts.
        """
        data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.put_bytes(key, data, content_type="application/json")

    def get_json(self, key: str) -> Any | None:
        data = self.get_bytes(key)
        return None if data is None else json.loads(data)

    @staticmethod
    def digest(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()


# --- key layout --------------------------------------------------------------
#
# Partitioned by ingest date from the start. That is what makes reprocessing
# idempotent: a re-pull lands under a new `dt=`, nothing is overwritten, and a
# backfill can be replayed for one date without touching the rest.


def _dt(when: date | str | None = None) -> str:
    if when is None:
        return datetime.now(timezone.utc).date().isoformat()
    return when if isinstance(when, str) else when.isoformat()


def companyfacts_key(cik: str | int, when: date | str | None = None) -> str:
    return f"raw/companyfacts/dt={_dt(when)}/CIK{normalize_cik(cik)}.json"


def submissions_key(cik: str | int, when: date | str | None = None) -> str:
    return f"raw/submissions/dt={_dt(when)}/CIK{normalize_cik(cik)}.json"


def universe_key(when: date | str | None = None) -> str:
    return f"raw/universe/dt={_dt(when)}/company_tickers.json"


def filing_document_key(cik: str | int, accession: str, document: str) -> str:
    """Filing documents are immutable once published.

    Keyed by accession rather than ingest date, so a re-fetch overwrites instead
    of accumulating a second copy of bytes that cannot have changed.
    """
    return (
        f"raw/documents/CIK{normalize_cik(cik)}/"
        f"{accession_nodash(accession)}/{document}"
    )


def filing_metadata_key(cik: str | int, accession: str) -> str:
    return f"raw/documents/CIK{normalize_cik(cik)}/{accession_nodash(accession)}/_filing.json"


def curated_key(layer: str, table: str) -> str:
    """Prefix for Spark's Parquet output, e.g. ``curated/silver/facts``."""
    return f"curated/{layer}/{table}"


def manifest_key(when: date | str | None = None) -> str:
    return f"raw/_manifests/dt={_dt(when)}/manifest.jsonl"
