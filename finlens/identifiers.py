"""Normalisation for the identifiers EDGAR uses inconsistently.

EDGAR spells the same CIK three ways depending on the endpoint - ``320193`` in
``company_tickers.json``, ``CIK0000320193`` in submissions, ``0000320193`` in
paths - and accession numbers appear both dashed and undashed. Every one of
those has bitten a join at some point, so all of it is funnelled through here.
"""

from __future__ import annotations

import re

_CIK_DIGITS = re.compile(r"(\d+)")
_ACCESSION = re.compile(r"^\d{10}-?\d{2}-?\d{6}$")


def normalize_cik(value: str | int) -> str:
    """Return the canonical zero-padded 10-digit CIK.

    >>> normalize_cik(320193)
    '0000320193'
    >>> normalize_cik("CIK0000320193")
    '0000320193'
    """
    match = _CIK_DIGITS.search(str(value))
    if not match:
        raise ValueError(f"no digits in CIK {value!r}")
    digits = match.group(1).lstrip("0") or "0"
    if len(digits) > 10:
        raise ValueError(f"CIK {value!r} has more than 10 significant digits")
    return digits.zfill(10)


def cik_int(value: str | int) -> int:
    """CIK as an integer, which is the form ``data.sec.gov`` paths want."""
    return int(normalize_cik(value))


def normalize_accession(value: str) -> str:
    """Return the dashed accession number, e.g. ``0000320193-24-000123``."""
    raw = value.strip()
    if not _ACCESSION.match(raw):
        raise ValueError(f"{value!r} is not an accession number")
    digits = raw.replace("-", "")
    return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"


def accession_nodash(value: str) -> str:
    """Undashed accession, which is what EDGAR archive directory names use."""
    return normalize_accession(value).replace("-", "")


def archive_dir_url(base_url: str, cik: str | int, accession: str) -> str:
    """URL of a filing's archive directory.

    Note the asymmetry: the CIK segment is *unpadded* while the accession
    segment is *undashed*. Getting either wrong returns a 404, not a redirect.
    """
    return f"{base_url}/Archives/edgar/data/{cik_int(cik)}/{accession_nodash(accession)}"
