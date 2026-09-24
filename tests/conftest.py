from __future__ import annotations

import json
from pathlib import Path

import pytest

from finlens.config import Settings, get_settings


@pytest.fixture(autouse=True)
def _isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point every test at a throwaway lake, warehouse, index and cache.

    Autouse because a test that accidentally writes into the real `data/`
    directory is both slow and confusing to debug later. The EDGAR response
    cache in particular *must* be per-test: it is on by default, and a cached
    response from an earlier test silently satisfies a later test's request, so
    the request-counting assertions pass without the code under test running.
    """
    root = Path(str(tmp_path))
    monkeypatch.setenv("FINLENS_LAKE_ROOT", str(root / "lake"))
    monkeypatch.setenv("FINLENS_DUCKDB_PATH", str(root / "warehouse" / "finlens.duckdb"))
    monkeypatch.setenv("FINLENS_VECTOR_STORE_PATH", str(root / "index"))
    monkeypatch.setenv("FINLENS_SEC_CACHE_DIR", str(root / "cache"))
    monkeypatch.setenv("FINLENS_SEC_USER_AGENT", "FinLens-test/0.1 (test@example.invalid)")
    monkeypatch.setenv("FINLENS_EMBEDDING_PROVIDER", "hash")
    monkeypatch.setenv("FINLENS_EMBEDDING_DIM", "64")
    monkeypatch.setenv("FINLENS_STORAGE_BACKEND", "local")
    # No real credentials should ever be picked up from the developer's shell.
    for leaked in ("GOOGLE_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY", "SUPABASE_DB_URL"):
        monkeypatch.delenv(leaked, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def object_store(settings):
    """A local object store rooted in the per-test lake."""
    from finlens.storage import get_store

    return get_store(settings)


@pytest.fixture
def settings() -> Settings:
    return get_settings()


@pytest.fixture
def companyfacts_payload() -> dict:
    """A minimal companyfacts document exercising the cases that matter.

    Contains: a duration fact, an instant fact, a restatement of the same
    period with a different value, and a fact with a null value.
    """
    return {
        "cik": 320193,
        "entityName": "Apple Inc.",
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "label": "Revenues",
                    "description": "Total revenue",
                    "units": {
                        "USD": [
                            {
                                "start": "2022-09-25",
                                "end": "2023-09-30",
                                "val": 383285000000,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "accn": "0000320193-23-000106",
                            },
                            {
                                # Same period, later filing, restated value.
                                "start": "2022-09-25",
                                "end": "2023-09-30",
                                "val": 383290000000,
                                "fy": 2024,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2024-11-01",
                                "accn": "0000320193-24-000123",
                            },
                        ]
                    },
                },
                "Assets": {
                    "label": "Assets",
                    "units": {
                        "USD": [
                            {
                                "end": "2023-09-30",
                                "val": 352583000000,
                                "fy": 2023,
                                "fp": "FY",
                                "form": "10-K",
                                "filed": "2023-11-03",
                                "accn": "0000320193-23-000106",
                            },
                            {
                                # No `end` - must be dropped, not defaulted.
                                "start": "2023-01-01",
                                "val": 1,
                            },
                        ]
                    },
                },
            }
        },
    }


@pytest.fixture
def submissions_payload() -> dict:
    """A submissions document with the columnar `recent` block."""
    return {
        "cik": "320193",
        "name": "Apple Inc.",
        "tickers": ["AAPL"],
        "exchanges": ["Nasdaq"],
        "sic": "3571",
        "sicDescription": "Electronic Computers",
        "fiscalYearEnd": "0930",
        "stateOfIncorporation": "CA",
        "filings": {
            "recent": {
                "accessionNumber": ["0000320193-24-000123", "0000320193-23-000106"],
                "form": ["10-K", "10-K"],
                "filingDate": ["2024-11-01", "2023-11-03"],
                "reportDate": ["2024-09-28", "2023-09-30"],
                "acceptanceDateTime": ["2024-11-01T18:01:14.000Z", "2023-11-03T18:08:27.000Z"],
                "primaryDocument": ["aapl-20240928.htm", "aapl-20230930.htm"],
                "primaryDocDescription": ["10-K", "10-K"],
                "items": ["", ""],
                "size": [7000000, 6800000],
                "isXBRL": [1, 1],
                "isInlineXBRL": [1, 1],
            },
            "files": [],
        },
    }


@pytest.fixture
def filing_html() -> str:
    """A 10-K-shaped document: a table of contents, then real item sections."""
    body = " ".join(["Filler sentence about operations and results."] * 40)
    return f"""
    <html><head><style>.x {{ color: red; }}</style><title>Form 10-K</title></head>
    <body>
      <div>TABLE OF CONTENTS</div>
      <div>Item 1. Business</div>
      <div>Item 1A. Risk Factors</div>
      <div>Item 2. Properties</div>
      <div>Item 3. Legal Proceedings</div>
      <div>Item 7. Management's Discussion and Analysis</div>
      <div>Item 8. Financial Statements</div>

      <p>Item 1. Business</p>
      <p>The Company designs and markets smartphones and personal computers. {body}</p>

      <p>Item 1A. Risk Factors</p>
      <p>The Company depends on single-source suppliers for critical components. {body}</p>

      <p>Item 7. Management's Discussion and Analysis</p>
      <p>Gross margin decreased due to unfavourable product mix. {body}</p>

      <table><tr><td>2023</td><td>383,285</td></tr><tr><td>2022</td><td>394,328</td></tr></table>
      <script>var tracking = 1;</script>
    </body></html>
    """


@pytest.fixture
def landed_companyfacts(tmp_path: Path, companyfacts_payload: dict) -> Path:
    path = tmp_path / "companyfacts.json"
    path.write_text(json.dumps(companyfacts_payload), encoding="utf-8")
    return path
