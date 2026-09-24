"""Storage backends, and the key layout both share.

The local backend is exercised directly; the S3 backend is exercised through a
stub client, because the point is that identical calling code produces identical
key semantics on both.
"""

from __future__ import annotations

import pytest

from finlens.storage.base import (
    companyfacts_key,
    filing_document_key,
    filing_metadata_key,
    submissions_key,
    universe_key,
)
from finlens.storage.local import LocalObjectStore
from finlens.storage.s3 import S3ObjectStore

# --- key layout --------------------------------------------------------------


def test_keys_are_partitioned_by_ingest_date():
    # Partitioning from day one is what makes reprocessing idempotent.
    assert companyfacts_key(320193, "2026-09-12") == (
        "raw/companyfacts/dt=2026-09-12/CIK0000320193.json"
    )
    assert submissions_key("AAPL0000320193", "2026-09-12") == (
        "raw/submissions/dt=2026-09-12/CIK0000320193.json"
    )
    assert universe_key("2026-09-12") == "raw/universe/dt=2026-09-12/company_tickers.json"


def test_document_keys_are_immutable_not_dated():
    # A filing's bytes cannot change once published, so a re-fetch should
    # overwrite rather than create a second dated copy.
    key = filing_document_key(320193, "0000320193-24-000123", "aapl-20240928.htm")
    assert key == "raw/documents/CIK0000320193/000032019324000123/aapl-20240928.htm"
    assert "dt=" not in key

    meta = filing_metadata_key(320193, "0000320193-24-000123")
    assert meta.endswith("/_filing.json")


def test_keys_normalise_the_cik_spelling():
    assert companyfacts_key(320193, "2026-01-01") == companyfacts_key("0000320193", "2026-01-01")


# --- local backend -----------------------------------------------------------


@pytest.fixture
def local(tmp_path):
    return LocalObjectStore(tmp_path / "lake")


def test_put_and_get_round_trip(local):
    local.put_bytes("raw/a/b.json", b'{"x":1}')
    assert local.get_bytes("raw/a/b.json") == b'{"x":1}'


def test_get_missing_returns_none(local):
    assert local.get_bytes("nope.json") is None
    assert not local.exists("nope.json")


def test_put_json_is_canonical(local):
    # Key order must not change the digest, or every re-pull looks like a change.
    a = local.put_json("a.json", {"b": 2, "a": 1})
    b = local.put_json("b.json", {"a": 1, "b": 2})
    assert a != b
    assert local.get_bytes("a.json") == local.get_bytes("b.json")


def test_get_json_round_trips(local):
    payload = {"cik": 320193, "facts": {"us-gaap": {}}}
    local.put_json("cf.json", payload)
    assert local.get_json("cf.json") == payload


def test_list_filters_by_prefix(local):
    local.put_bytes("raw/x/1.json", b"1")
    local.put_bytes("raw/x/2.json", b"2")
    local.put_bytes("raw/y/3.json", b"3")

    keys = {o.key for o in local.list("raw/x")}
    assert keys == {"raw/x/1.json", "raw/x/2.json"}


def test_list_of_a_missing_prefix_is_empty(local):
    assert list(local.list("nothing/here")) == []


def test_partial_writes_are_not_visible(local):
    # Write-then-rename: `.tmp` files must never appear in a listing.
    local.put_bytes("raw/x/1.json", b"1")
    assert all(not o.key.endswith(".tmp") for o in local.list("raw"))


def test_a_key_cannot_escape_the_root(local):
    with pytest.raises(ValueError, match="escapes"):
        local.put_bytes("../../etc/passwd", b"nope")


def test_prefix_is_applied_transparently(tmp_path):
    store = LocalObjectStore(tmp_path / "lake", prefix="finlens")
    store.put_bytes("raw/a.json", b"1")

    assert (tmp_path / "lake" / "finlens" / "raw" / "a.json").exists()
    # The prefix is invisible to callers - keys read back unchanged.
    assert [o.key for o in store.list("raw")] == ["raw/a.json"]


def test_uri_and_local_path(local):
    assert local.uri("raw/a.json").startswith("file://")
    assert local.local_path("raw/a.json").endswith("raw/a.json")


# --- s3 backend --------------------------------------------------------------


class StubS3:
    """Just enough of the boto3 S3 client to check the calls we make."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803 - boto3 casing
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

        class Body:
            def __init__(self, data):
                self._data = data

            def read(self):
                return self._data

        return {"Body": Body(self.objects[Key])}

    def head_object(self, Bucket, Key):  # noqa: N803
        if Key not in self.objects:
            from botocore.exceptions import ClientError

            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")
        return {}


pytest.importorskip("botocore", reason="s3 backend needs finlens[storage]")


@pytest.fixture
def s3():
    return S3ObjectStore("finlens", client=StubS3(), endpoint_url="https://acct.r2.example")


def test_s3_round_trip(s3):
    s3.put_bytes("raw/a.json", b"1")
    assert s3.get_bytes("raw/a.json") == b"1"
    assert s3.exists("raw/a.json")


def test_s3_missing_key_returns_none(s3):
    assert s3.get_bytes("nope") is None
    assert not s3.exists("nope")


def test_s3_uri_and_spark_path_differ():
    store = S3ObjectStore("finlens", client=StubS3())
    assert store.uri("raw/a.json") == "s3://finlens/raw/a.json"
    # Spark reads through the Hadoop connector, which needs the s3a scheme.
    assert store.local_path("raw/a.json") == "s3a://finlens/raw/a.json"


def test_r2_spark_conf_uses_path_style_access():
    store = S3ObjectStore(
        "finlens",
        client=StubS3(),
        endpoint_url="https://acct.r2.cloudflarestorage.com",
        access_key_id="k",
        secret_access_key="s",
    )
    conf = store.spark_conf()
    # R2 has no virtual-host addressing; without path-style access every read 404s.
    assert conf["spark.hadoop.fs.s3a.path.style.access"] == "true"
    assert conf["spark.hadoop.fs.s3a.endpoint"] == "https://acct.r2.cloudflarestorage.com"
    assert conf["spark.hadoop.fs.s3a.access.key"] == "k"


def test_backends_agree_on_keys(tmp_path):
    """The point of the abstraction: same calls, same keys, either backend."""
    local = LocalObjectStore(tmp_path / "lake")
    remote = S3ObjectStore("finlens", client=StubS3())

    key = companyfacts_key(320193, "2026-09-12")
    local.put_json(key, {"a": 1})
    remote.put_json(key, {"a": 1})

    assert local.get_json(key) == remote.get_json(key)
