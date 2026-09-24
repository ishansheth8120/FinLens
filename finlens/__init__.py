"""FinLens - question answering over SEC EDGAR filings.

Two retrieval paths sit behind one router:

* a **structured** path (XBRL company facts -> Spark -> dbt marts -> DuckDB SQL)
  for anything numeric or comparative, and
* an **unstructured** path (filing text -> chunks -> embeddings -> vector search)
  for anything narrative.

`finlens.agent` decides which of the two (or both) a question needs, and
`finlens.eval` measures whether that decision and the answer were any good.
"""

__version__ = "0.1.0"
