"""S3-compatible object store, used against Cloudflare R2.

R2 speaks the S3 API, so this is plain boto3 with an ``endpoint_url``. Nothing
here is R2-specific except two details that will bite you otherwise:

* **Region must be ``auto``.** R2 has no regions; boto3 insists on a value and
  signing fails with anything else.
* **No egress charge, but requests are metered.** So `exists` uses `head_object`
  rather than listing, and `list` paginates rather than fetching everything.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

from finlens.logging import get_logger
from finlens.storage.base import ObjectStore, StoredObject

if TYPE_CHECKING:  # pragma: no cover
    from mypy_boto3_s3.client import S3Client

log = get_logger(__name__)


class S3ObjectStore(ObjectStore):
    def __init__(
        self,
        bucket: str,
        *,
        endpoint_url: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        region: str = "auto",
        prefix: str = "",
        client: Any = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.endpoint_url = endpoint_url
        self._client = client
        self._client_kwargs = {
            "endpoint_url": endpoint_url,
            "aws_access_key_id": access_key_id,
            "aws_secret_access_key": secret_access_key,
            "region_name": region,
        }

    @property
    def client(self) -> S3Client:
        if self._client is None:
            try:
                import boto3
                from botocore.config import Config
            except ImportError as exc:  # pragma: no cover - depends on extras
                raise RuntimeError("the s3 backend needs `pip install 'finlens[storage]'`") from exc

            self._client = boto3.client(
                "s3",
                config=Config(
                    signature_version="s3v4",
                    retries={"max_attempts": 5, "mode": "standard"},
                ),
                **self._client_kwargs,
            )
        return self._client

    def _full_key(self, key: str) -> str:
        return f"{self.prefix}/{key}" if self.prefix else key

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/json") -> str:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._full_key(key),
            Body=data,
            ContentType=content_type,
        )
        return self.uri(key)

    def get_bytes(self, key: str) -> bytes | None:
        from botocore.exceptions import ClientError

        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._full_key(key))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return None
            raise
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._full_key(key))
        except ClientError as exc:
            if exc.response["Error"]["Code"] in ("NoSuchKey", "404"):
                return False
            raise
        return True

    def list(self, prefix: str) -> Iterator[StoredObject]:
        paginator = self.client.get_paginator("list_objects_v2")
        strip = len(self.prefix) + 1 if self.prefix else 0

        for page in paginator.paginate(Bucket=self.bucket, Prefix=self._full_key(prefix)):
            for item in page.get("Contents", []):
                yield StoredObject(
                    key=item["Key"][strip:],
                    size=item["Size"],
                    etag=item.get("ETag", "").strip('"') or None,
                    last_modified=item.get("LastModified"),
                )

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{self._full_key(key)}"

    def local_path(self, key: str) -> str:
        # `s3a://` is the Hadoop connector Spark uses; `s3://` is not readable
        # by Spark's own reader on most distributions.
        return f"s3a://{self.bucket}/{self._full_key(key)}"

    def spark_conf(self) -> dict[str, str]:
        """Hadoop settings a Spark session needs to read this bucket."""
        conf = {
            "spark.hadoop.fs.s3a.impl": "org.apache.hadoop.fs.s3a.S3AFileSystem",
            "spark.hadoop.fs.s3a.path.style.access": "true",
            "spark.hadoop.fs.s3a.aws.credentials.provider": (
                "org.apache.hadoop.fs.s3a.SimpleAWSCredentialsProvider"
            ),
        }
        if self.endpoint_url:
            conf["spark.hadoop.fs.s3a.endpoint"] = self.endpoint_url
        access_key = self._client_kwargs.get("aws_access_key_id")
        secret_key = self._client_kwargs.get("aws_secret_access_key")
        if access_key and secret_key:
            conf["spark.hadoop.fs.s3a.access.key"] = str(access_key)
            conf["spark.hadoop.fs.s3a.secret.key"] = str(secret_key)
        return conf
