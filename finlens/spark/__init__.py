"""PySpark jobs that turn the raw zone into conformed silver tables.

Why Spark and not plain Python: companyfacts for the full universe is ~10k
documents and low hundreds of millions of facts, and filing HTML is tens of GB.
Both are embarrassingly parallel per file, which is exactly the shape Spark is
good at, and both need to be re-runnable over a partition rather than end to
end.

The parsing itself is deliberately *not* written in Spark SQL. EDGAR's payloads
are dynamically keyed (concept names are map keys, not values), so the flatten
is Python that runs inside `flatMap`, reusing the same functions
`finlens.ingest` uses. One parser, tested once, used in both places.
"""
