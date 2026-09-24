"""Typed views over the EDGAR payloads.

These are validation boundaries, not the warehouse schema - they exist so a
shape change at SEC fails loudly at ingest time instead of producing nulls four
layers downstream. The warehouse schema lives in dbt.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from finlens.identifiers import normalize_accession, normalize_cik


class Company(BaseModel):
    """One row of ``company_tickers.json``, enriched from submissions."""

    model_config = ConfigDict(populate_by_name=True)

    cik: str
    ticker: str | None = None
    name: str
    exchange: str | None = None
    sic: str | None = None
    sic_description: str | None = None
    fiscal_year_end: str | None = None  # "MMDD"
    state_of_incorporation: str | None = None

    @field_validator("cik", mode="before")
    @classmethod
    def _norm_cik(cls, v: Any) -> str:
        return normalize_cik(v)


class Filing(BaseModel):
    """One filing from a company's submission history."""

    model_config = ConfigDict(populate_by_name=True)

    cik: str
    accession_number: str
    form: str
    filing_date: date
    report_date: date | None = None
    acceptance_datetime: str | None = None
    primary_document: str | None = None
    primary_doc_description: str | None = None
    items: str | None = None
    size: int | None = None
    is_xbrl: bool = False
    is_inline_xbrl: bool = False

    @field_validator("cik", mode="before")
    @classmethod
    def _norm_cik(cls, v: Any) -> str:
        return normalize_cik(v)

    @field_validator("accession_number", mode="before")
    @classmethod
    def _norm_accession(cls, v: Any) -> str:
        return normalize_accession(str(v))

    @field_validator("report_date", "filing_date", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        return None if v in ("", None) else v


class Fact(BaseModel):
    """One reported XBRL fact.

    The grain is (concept, unit, period, accession): a single 10-K restates
    prior periods, so the same (concept, period) appears in several filings with
    different values. Deduplication is a warehouse concern - we keep every
    version here, because "what did they report at the time" and "what is the
    number now" are both real questions.
    """

    cik: str
    taxonomy: str  # "us-gaap", "ifrs-full", "dei", "srt"
    concept: str  # e.g. "RevenueFromContractWithCustomerExcludingAssessedTax"
    label: str | None = None
    description: str | None = None
    unit: str  # e.g. "USD", "shares", "USD/shares"
    value: float | None = None
    start_date: date | None = None
    end_date: date
    fiscal_year: int | None = Field(default=None, description="fy as reported")
    fiscal_period: str | None = Field(default=None, description="FY, Q1, Q2, Q3, Q4")
    form: str | None = None
    filed_date: date | None = None
    accession_number: str | None = None
    frame: str | None = None

    @field_validator("cik", mode="before")
    @classmethod
    def _norm_cik(cls, v: Any) -> str:
        return normalize_cik(v)

    @property
    def is_duration(self) -> bool:
        """Duration facts (revenue) vs instant facts (cash on hand).

        Matters because summing an instant across quarters is meaningless, and
        the only signal distinguishing them is the presence of a start date.
        """
        return self.start_date is not None


class FilingDocument(BaseModel):
    """A single document inside a filing's archive directory."""

    cik: str
    accession_number: str
    sequence: int | None = None
    document: str
    doc_type: str | None = None
    description: str | None = None
    url: str
    size: int | None = None
