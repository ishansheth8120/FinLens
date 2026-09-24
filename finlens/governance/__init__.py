"""Governance: who may see what, what happened, and where it came from.

Three controls, and they are the reason this is a system rather than a demo:

`access`   Entity-level authorisation. A principal is permitted a set of CIKs,
           and that set is enforced by rewriting the generated SQL and by
           Postgres row-level security on the vector store - not by asking the
           model nicely.
`audit`    Append-only record of every request: the question, the route, the
           generated SQL, the rows it touched, the chunks retrieved, the answer,
           and the numeric verification result. Replayable by request id.
`lineage`  The chain from a sentence in an answer back to an SEC filing URL.

The order matters. Access decides what a query is allowed to see, audit records
what it actually saw, and lineage explains how that became a sentence.
"""

from finlens.governance.access import (
    AccessPolicy,
    Principal,
    Role,
    scope_sql,
)
from finlens.governance.audit import AuditLog, AuditRecord
from finlens.governance.lineage import LineageTrail, trace

__all__ = [
    "AccessPolicy",
    "AuditLog",
    "AuditRecord",
    "LineageTrail",
    "Principal",
    "Role",
    "scope_sql",
    "trace",
]
