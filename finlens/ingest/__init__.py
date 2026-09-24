"""EDGAR clients.

`client.EdgarClient` is the only thing in the project that talks to sec.gov.
Everything else in this package is a thin, typed wrapper over one endpoint:

* `tickers`      - ticker <-> CIK resolution
* `submissions`  - a company's filing history
* `companyfacts` - all XBRL facts a company has ever reported
* `frames`       - one concept across all companies for one period
* `documents`    - the filing documents themselves
"""

from finlens.ingest.client import EdgarClient, EdgarError, EdgarNotFound

__all__ = ["EdgarClient", "EdgarError", "EdgarNotFound"]
