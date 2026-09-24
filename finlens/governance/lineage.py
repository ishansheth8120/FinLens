"""From a sentence in an answer back to an SEC filing.

The chain, in both directions:

    answer sentence
      -> numeric claim / citation           (agent output)
      -> warehouse row / chunk id           (query result / vector index)
      -> dbt model                          (fct_company_annual, ...)
      -> silver Parquet object              (curated/silver/facts/...)
      -> raw landed object + SHA-256        (raw/companyfacts/dt=.../CIK*.json)
      -> accession number
      -> https://www.sec.gov/Archives/...

Being able to walk that is what makes the output defensible rather than merely
plausible. It is assembled from things already recorded elsewhere — the audit
record, the dbt manifest, the raw manifest — rather than from a separate
lineage store that could disagree with them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from finlens.config import Settings, get_settings
from finlens.identifiers import accession_nodash, cik_int
from finlens.logging import get_logger

log = get_logger(__name__)

# Which upstream each mart derives from. Read from the dbt manifest when one is
# available; this is the fallback so lineage still resolves on a fresh clone.
MODEL_SOURCES: dict[str, list[str]] = {
    "dim_company": ["stg_companies"],
    "dim_filing": ["stg_filings", "stg_sections"],
    "fct_financial_fact": ["stg_facts", "stg_concept_map"],
    "fct_company_metric": ["fct_financial_fact", "dim_company"],
    "fct_company_annual": ["fct_company_metric", "dim_company"],
    "fct_filing_section": ["stg_sections", "dim_company", "dim_filing"],
    "metric_definitions": ["stg_concept_map", "fct_company_metric"],
}

STAGING_SOURCES: dict[str, str] = {
    "stg_facts": "silver/facts",
    "stg_companies": "silver/companies",
    "stg_filings": "silver/filings",
    "stg_sections": "silver/sections",
    "stg_concept_map": "seeds/concept_map.csv",
}

SILVER_ORIGINS: dict[str, str] = {
    "silver/facts": "raw/companyfacts",
    "silver/companies": "raw/submissions",
    "silver/filings": "raw/submissions",
    "silver/sections": "raw/documents",
}


@dataclass
class LineageNode:
    layer: str
    name: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.layer}: {self.name}" + (f" ({self.detail})" if self.detail else "")


@dataclass
class LineageTrail:
    """The resolved chain for one claim or citation."""

    origin: str
    nodes: list[LineageNode] = field(default_factory=list)
    source_url: str | None = None
    accession_number: str | None = None

    def add(self, layer: str, name: str, detail: str = "") -> LineageTrail:
        self.nodes.append(LineageNode(layer=layer, name=name, detail=detail))
        return self

    def to_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "chain": [{"layer": n.layer, "name": n.name, "detail": n.detail} for n in self.nodes],
            "accession_number": self.accession_number,
            "source_url": self.source_url,
        }

    def render(self) -> str:
        """One line per hop, for the CLI and the report diagram."""
        lines = [f"{self.origin}"]
        for i, node in enumerate(self.nodes):
            lines.append(f"{'  ' * (i + 1)}-> {node}")
        if self.source_url:
            lines.append(f"{'  ' * (len(self.nodes) + 1)}-> {self.source_url}")
        return "\n".join(lines)


def filing_url(cik: str | int, accession: str, document: str | None = None) -> str:
    """Resolvable sec.gov URL for a filing or one of its documents."""
    base = (
        f"https://www.sec.gov/Archives/edgar/data/"
        f"{cik_int(cik)}/{accession_nodash(accession)}"
    )
    return f"{base}/{document}" if document else f"{base}/"


def _dbt_upstreams(model: str, settings: Settings) -> list[str]:
    """Read a model's parents from the dbt manifest, falling back to the map.

    Always returns a fresh list. Callers walk the graph by popping off a
    frontier, and handing back the module-level list would drain the fallback
    map in place - lineage would resolve correctly once per process and return
    nothing thereafter.
    """
    manifest_path = Path(settings.dbt_project_dir) / "target" / "manifest.json"
    if not manifest_path.exists():
        return list(MODEL_SOURCES.get(model, []))
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return list(MODEL_SOURCES.get(model, []))

    for node in manifest.get("nodes", {}).values():
        if node.get("name") == model:
            return [ref.rsplit(".", 1)[-1] for ref in node.get("depends_on", {}).get("nodes", [])]
    return list(MODEL_SOURCES.get(model, []))


def trace_table(table: str, settings: Settings | None = None) -> LineageTrail:
    """Walk one mart back to the raw zone."""
    settings = settings or get_settings()
    name = table.rsplit(".", 1)[-1]

    trail = LineageTrail(origin=f"warehouse table {name}")
    trail.add("dbt model", name, "materialised in the marts schema")

    seen: set[str] = set()
    frontier = list(_dbt_upstreams(name, settings))
    while frontier:
        upstream = frontier.pop(0)
        if upstream in seen:
            continue
        seen.add(upstream)

        if upstream in STAGING_SOURCES:
            silver = STAGING_SOURCES[upstream]
            trail.add("dbt staging", upstream, f"reads {silver}")
            if silver in SILVER_ORIGINS:
                trail.add("lake (silver)", f"curated/{silver}", "Parquet, written by Spark")
                trail.add("lake (raw)", SILVER_ORIGINS[silver], "landed JSON/HTML, SHA-256 in manifest")
        else:
            trail.add("dbt model", upstream)
            frontier.extend(_dbt_upstreams(upstream, settings))

    trail.add("source", "SEC EDGAR", "data.sec.gov / www.sec.gov")
    return trail


def trace_citation(
    citation: dict[str, Any] | Any, settings: Settings | None = None
) -> LineageTrail:
    """Walk a retrieved chunk back to the filing document it came from."""
    settings = settings or get_settings()
    get = citation.get if isinstance(citation, dict) else lambda k, d=None: getattr(citation, k, d)

    chunk_id = get("chunk_id")
    section_id = get("section_id")
    accession = get("accession_number")
    label = get("label") or "retrieved excerpt"

    trail = LineageTrail(origin=f"citation {label}", accession_number=accession)
    if chunk_id:
        trail.add("vector index", f"chunk {chunk_id}", "embedded chunk in filing_chunks")
    if section_id:
        trail.add("dbt model", "fct_filing_section", f"section {section_id}")
    trail.add("lake (silver)", "curated/silver/sections", "parsed item sections")
    trail.add("lake (raw)", "raw/documents", "landed filing HTML, SHA-256 in manifest")

    cik = get("cik")
    if accession:
        trail.add("filing", accession, "SEC accession number")
        if cik:
            trail.source_url = filing_url(cik, accession)
    trail.add("source", "SEC EDGAR", "www.sec.gov/Archives")
    return trail


def trace(
    *,
    tables: list[str] | None = None,
    citations: list[Any] | None = None,
    settings: Settings | None = None,
) -> list[LineageTrail]:
    """Every trail behind one answer.

    Given an `Answer`, pass `referenced_tables(answer.sql_result.sql)` and
    `answer.citations` to get the full provenance of what was served.
    """
    settings = settings or get_settings()
    trails = [trace_table(t, settings) for t in (tables or [])]
    trails.extend(trace_citation(c, settings) for c in (citations or []))
    return trails
