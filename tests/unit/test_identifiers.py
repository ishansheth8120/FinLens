from __future__ import annotations

import pytest

from finlens.identifiers import (
    accession_nodash,
    archive_dir_url,
    cik_int,
    normalize_accession,
    normalize_cik,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (320193, "0000320193"),
        ("320193", "0000320193"),
        ("0000320193", "0000320193"),
        ("CIK0000320193", "0000320193"),
        ("cik320193", "0000320193"),
        (1, "0000000001"),
    ],
)
def test_normalize_cik_accepts_every_spelling_edgar_uses(raw, expected):
    assert normalize_cik(raw) == expected


@pytest.mark.parametrize("bad", ["", "AAPL", "no-digits-here"])
def test_normalize_cik_rejects_non_numeric(bad):
    with pytest.raises(ValueError):
        normalize_cik(bad)


def test_normalize_cik_rejects_overlong():
    with pytest.raises(ValueError, match="more than 10"):
        normalize_cik("12345678901")


def test_cik_int_drops_padding():
    # The archive URLs use the unpadded form; the padded one 404s.
    assert cik_int("0000320193") == 320193


@pytest.mark.parametrize(
    "raw",
    ["0000320193-24-000123", "000032019324000123"],
)
def test_normalize_accession_is_idempotent_across_forms(raw):
    assert normalize_accession(raw) == "0000320193-24-000123"


def test_accession_nodash():
    assert accession_nodash("0000320193-24-000123") == "000032019324000123"


@pytest.mark.parametrize("bad", ["not-an-accession", "0000320193-24", ""])
def test_normalize_accession_rejects_malformed(bad):
    with pytest.raises(ValueError):
        normalize_accession(bad)


def test_archive_dir_url_uses_unpadded_cik_and_undashed_accession():
    # This asymmetry is the single most common source of 404s against EDGAR.
    url = archive_dir_url("https://www.sec.gov", "0000320193", "0000320193-24-000123")
    assert url == "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123"
