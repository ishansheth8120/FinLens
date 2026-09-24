from __future__ import annotations

from datetime import date

from finlens.ingest.submissions import older_filing_files, parse_company, parse_filings


def test_parse_company(submissions_payload):
    company = parse_company(submissions_payload)
    assert company.cik == "0000320193"
    assert company.ticker == "AAPL"
    assert company.name == "Apple Inc."
    assert company.sic == "3571"
    assert company.fiscal_year_end == "0930"


def test_parse_filings_transposes_the_columnar_block(submissions_payload):
    filings = parse_filings(submissions_payload, "320193")
    assert len(filings) == 2

    newest = filings[0]
    assert newest.accession_number == "0000320193-24-000123"
    assert newest.form == "10-K"
    assert newest.filing_date == date(2024, 11, 1)
    assert newest.report_date == date(2024, 9, 28)
    assert newest.is_inline_xbrl is True


def test_blank_report_date_becomes_none(submissions_payload):
    submissions_payload["filings"]["recent"]["reportDate"] = ["", ""]
    filings = parse_filings(submissions_payload, "320193")
    assert all(f.report_date is None for f in filings)


def test_ragged_columns_truncate_rather_than_raise(submissions_payload):
    # A short column should cost us the trailing rows, not the whole history.
    submissions_payload["filings"]["recent"]["form"] = ["10-K"]
    filings = parse_filings(submissions_payload, "320193")
    assert len(filings) == 1


def test_empty_recent_block_returns_nothing():
    assert parse_filings({"filings": {"recent": {}}}, "320193") == []


def test_older_filing_files_are_surfaced(submissions_payload):
    submissions_payload["filings"]["files"] = [
        {"name": "CIK0000320193-submissions-001.json"},
        {"name": ""},
    ]
    assert older_filing_files(submissions_payload) == ["CIK0000320193-submissions-001.json"]
