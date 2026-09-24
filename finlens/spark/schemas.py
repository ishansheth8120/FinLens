"""Explicit Spark schemas for every silver table.

Never inferred. Schema inference on EDGAR JSON is both slow (a full extra pass)
and wrong in a way that corrupts data quietly: a concept whose first thousand
values happen to be integral infers as ``long``, then silently truncates the
first fractional value it meets. Declaring types is the fix.
"""

from __future__ import annotations

from pyspark.sql.types import (
    ArrayType,
    BooleanType,
    DateType,
    DoubleType,
    IntegerType,
    LongType,
    StringType,
    StructField,
    StructType,
    TimestampType,
)

# Provenance columns appended to every bronze/silver row. Being able to point at
# the exact source file for any number in an answer is the whole audit story.
PROVENANCE_FIELDS = [
    StructField("source_path", StringType(), nullable=False),
    StructField("ingested_at", TimestampType(), nullable=False),
]

FACT_SCHEMA = StructType(
    [
        StructField("cik", StringType(), nullable=False),
        StructField("taxonomy", StringType(), nullable=False),
        StructField("concept", StringType(), nullable=False),
        StructField("label", StringType(), nullable=True),
        StructField("unit", StringType(), nullable=False),
        # DoubleType, not DecimalType: XBRL values span from sub-cent EPS to
        # trillions, and a fixed scale loses one end or the other. Anything that
        # needs exactness (per-share arithmetic) casts in the warehouse.
        StructField("value", DoubleType(), nullable=True),
        StructField("start_date", DateType(), nullable=True),
        StructField("end_date", DateType(), nullable=False),
        StructField("fiscal_year", IntegerType(), nullable=True),
        StructField("fiscal_period", StringType(), nullable=True),
        StructField("form", StringType(), nullable=True),
        StructField("filed_date", DateType(), nullable=True),
        StructField("accession_number", StringType(), nullable=True),
        StructField("frame", StringType(), nullable=True),
        *PROVENANCE_FIELDS,
    ]
)

FILING_SCHEMA = StructType(
    [
        StructField("cik", StringType(), nullable=False),
        StructField("accession_number", StringType(), nullable=False),
        StructField("form", StringType(), nullable=False),
        StructField("filing_date", DateType(), nullable=False),
        StructField("report_date", DateType(), nullable=True),
        StructField("acceptance_datetime", StringType(), nullable=True),
        StructField("primary_document", StringType(), nullable=True),
        StructField("primary_doc_description", StringType(), nullable=True),
        StructField("items", StringType(), nullable=True),
        StructField("size", LongType(), nullable=True),
        StructField("is_xbrl", BooleanType(), nullable=False),
        StructField("is_inline_xbrl", BooleanType(), nullable=False),
        *PROVENANCE_FIELDS,
    ]
)

COMPANY_SCHEMA = StructType(
    [
        StructField("cik", StringType(), nullable=False),
        StructField("ticker", StringType(), nullable=True),
        StructField("name", StringType(), nullable=False),
        StructField("exchange", StringType(), nullable=True),
        StructField("sic", StringType(), nullable=True),
        StructField("sic_description", StringType(), nullable=True),
        StructField("fiscal_year_end", StringType(), nullable=True),
        StructField("state_of_incorporation", StringType(), nullable=True),
        *PROVENANCE_FIELDS,
    ]
)

SECTION_SCHEMA = StructType(
    [
        StructField("section_id", StringType(), nullable=False),
        StructField("cik", StringType(), nullable=False),
        StructField("accession_number", StringType(), nullable=False),
        StructField("form", StringType(), nullable=False),
        StructField("filing_date", DateType(), nullable=True),
        StructField("fiscal_year", IntegerType(), nullable=True),
        StructField("item", StringType(), nullable=True),
        StructField("title", StringType(), nullable=True),
        StructField("ordinal", IntegerType(), nullable=False),
        StructField("text", StringType(), nullable=False),
        StructField("char_count", IntegerType(), nullable=False),
        StructField("word_count", IntegerType(), nullable=False),
        *PROVENANCE_FIELDS,
    ]
)

CHUNK_SCHEMA = StructType(
    [
        StructField("chunk_id", StringType(), nullable=False),
        StructField("section_id", StringType(), nullable=False),
        StructField("cik", StringType(), nullable=False),
        StructField("accession_number", StringType(), nullable=False),
        StructField("form", StringType(), nullable=False),
        StructField("filing_date", DateType(), nullable=True),
        StructField("item", StringType(), nullable=True),
        StructField("title", StringType(), nullable=True),
        StructField("ordinal", IntegerType(), nullable=False),
        StructField("text", StringType(), nullable=False),
        StructField("token_estimate", IntegerType(), nullable=False),
        StructField("embedding", ArrayType(DoubleType()), nullable=True),
    ]
)
