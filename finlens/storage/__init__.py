"""Object storage.

One interface, two backends. `S3ObjectStore` talks to Cloudflare R2 through
boto3 - R2 is S3-compatible, so this is ordinary S3 code with an
``endpoint_url``, and anything written against it works unchanged on real S3.
`LocalObjectStore` writes to the filesystem with the same key semantics, so the
whole pipeline runs before any account exists.

Keys, not paths. Everything downstream addresses objects as
``raw/companyfacts/dt=2026-09-12/CIK0000320193.json`` regardless of backend,
which is what keeps the local and remote layouts identical.
"""

from finlens.storage.base import ObjectStore, StoredObject
from finlens.storage.factory import get_store
from finlens.storage.local import LocalObjectStore
from finlens.storage.s3 import S3ObjectStore

__all__ = [
    "LocalObjectStore",
    "ObjectStore",
    "S3ObjectStore",
    "StoredObject",
    "get_store",
]
