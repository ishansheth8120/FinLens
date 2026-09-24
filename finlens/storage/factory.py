"""Choosing a backend.

The rule: honour the configured backend, but never fail silently into a state
where data appears to be written and is not. If `s3` is configured without
credentials that is a misconfiguration, and it should say so at startup rather
than at 3am in a DAG.
"""

from __future__ import annotations

from finlens.config import Settings, get_settings
from finlens.logging import get_logger
from finlens.storage.base import ObjectStore
from finlens.storage.local import LocalObjectStore
from finlens.storage.s3 import S3ObjectStore

log = get_logger(__name__)


def get_store(settings: Settings | None = None) -> ObjectStore:
    settings = settings or get_settings()

    if settings.storage_backend == "s3":
        if not settings.has_s3_credentials:
            raise RuntimeError(
                "FINLENS_STORAGE_BACKEND=s3 but R2 credentials are missing. Set "
                "R2_ENDPOINT_URL, R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY, or "
                "set FINLENS_STORAGE_BACKEND=local to work off the filesystem."
            )
        assert settings.s3_access_key_id is not None
        assert settings.s3_secret_access_key is not None

        log.info("storage.s3", bucket=settings.storage_bucket, endpoint=settings.s3_endpoint_url)
        return S3ObjectStore(
            bucket=settings.storage_bucket,
            endpoint_url=settings.s3_endpoint_url,
            access_key_id=settings.s3_access_key_id.get_secret_value(),
            secret_access_key=settings.s3_secret_access_key.get_secret_value(),
            region=settings.s3_region,
            prefix=settings.storage_prefix,
        )

    log.info("storage.local", root=str(settings.lake_root))
    return LocalObjectStore(settings.lake_root, prefix=settings.storage_prefix)
