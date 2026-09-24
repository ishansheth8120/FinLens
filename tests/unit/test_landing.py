from __future__ import annotations

from finlens.ingest.landing import already_landed, land_bytes, land_json, read_manifest
from finlens.storage.base import companyfacts_key

WHEN = "2026-09-12"


def test_land_bytes_writes_and_records(object_store):
    landed = land_bytes(
        object_store, "raw/x.json", b'{"a":1}', url="https://sec.gov/x.json", when=WHEN
    )

    assert object_store.get_bytes("raw/x.json") == b'{"a":1}'
    assert landed.bytes_written == 7
    assert len(landed.sha256) == 64

    manifest = read_manifest(object_store, when=WHEN)
    assert len(manifest) == 1
    assert manifest[0].url == "https://sec.gov/x.json"
    assert manifest[0].key == "raw/x.json"


def test_land_json_is_content_addressable(object_store):
    # Key order must not change the digest, or every re-pull looks like a change.
    a = land_json(object_store, "a.json", {"b": 2, "a": 1}, url="u", when=WHEN)
    b = land_json(object_store, "b.json", {"a": 1, "b": 2}, url="u", when=WHEN)
    assert a.sha256 == b.sha256


def test_manifest_appends_rather_than_overwrites(object_store):
    land_bytes(object_store, "a.json", b"1", url="u1", when=WHEN)
    land_bytes(object_store, "b.json", b"2", url="u2", when=WHEN)
    assert [e.url for e in read_manifest(object_store, when=WHEN)] == ["u1", "u2"]


def test_manifests_are_partitioned_by_date(object_store):
    land_bytes(object_store, "a.json", b"1", url="u1", when="2026-09-11")
    land_bytes(object_store, "b.json", b"2", url="u2", when="2026-09-12")

    assert len(read_manifest(object_store, when="2026-09-11")) == 1
    assert len(read_manifest(object_store, when="2026-09-12")) == 1


def test_already_landed_by_url_and_by_content(object_store):
    landed = land_bytes(
        object_store, "x.json", b"content", url="https://sec.gov/x.json", when=WHEN
    )

    assert already_landed(object_store, "https://sec.gov/x.json", when=WHEN)
    assert already_landed(object_store, "https://sec.gov/x.json", sha256=landed.sha256, when=WHEN)
    # Same URL, different content - "has it changed since" is False.
    assert not already_landed(object_store, "https://sec.gov/x.json", sha256="0" * 64, when=WHEN)
    assert not already_landed(object_store, "https://sec.gov/other.json", when=WHEN)


def test_manifest_of_an_untouched_date_is_empty(object_store):
    assert read_manifest(object_store, when="1999-01-01") == []


def test_landed_json_round_trips(object_store):
    payload = {"cik": 320193, "facts": {}}
    key = companyfacts_key(320193, WHEN)
    land_json(object_store, key, payload, url="u", when=WHEN)
    assert object_store.get_json(key) == payload
