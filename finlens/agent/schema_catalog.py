"""Rendering the warehouse schema into the text-to-SQL prompt.

The single biggest lever on generated-SQL accuracy is what the model is told
about the tables, and the second biggest is that the description is *true*. So
the catalogue is generated from dbt's manifest rather than written by hand:
`schema.yml` documents the models, dbt compiles it into `manifest.json`, and
this module renders it. A column description cannot drift from the model,
because there is only one copy.

Falls back to `information_schema` when the manifest is absent - names and types
with no prose, which produces noticeably worse SQL but still works on a fresh
clone that has not run `dbt docs`.

The rendered text is byte-stable and goes at the front of the system prompt, so
it sits behind the prompt-cache breakpoint.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from finlens.config import Settings, get_settings
from finlens.logging import get_logger

log = get_logger(__name__)

# Only these are offered to the SQL generator. Staging models are intentionally
# hidden: they are implementation detail, and exposing them roughly doubles the
# prompt while inviting queries that bypass the marts' correctness logic.
EXPOSED_MODELS = (
    "dim_company",
    "dim_filing",
    "fct_company_metric",
    "fct_company_annual",
    "fct_financial_fact",
    "fct_filing_section",
    "metric_definitions",
)


@dataclass
class Column:
    name: str
    data_type: str
    description: str = ""


@dataclass
class Table:
    name: str
    schema: str
    description: str = ""
    columns: list[Column] = field(default_factory=list)

    @property
    def qualified(self) -> str:
        return f"{self.schema}.{self.name}"


def _load_manifest(settings: Settings) -> dict[str, Any] | None:
    path = Path(settings.dbt_project_dir) / "target" / "manifest.json"
    if not path.exists():
        log.warning(
            "schema_catalog.no_manifest",
            path=str(path),
            detail="run `dbt compile` for column descriptions in the prompt",
        )
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("schema_catalog.manifest_unreadable", error=str(exc))
        return None


def tables_from_manifest(manifest: dict[str, Any]) -> list[Table]:
    tables: list[Table] = []
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "model" or node.get("name") not in EXPOSED_MODELS:
            continue
        tables.append(
            Table(
                name=node["name"],
                schema=node.get("schema") or "main",
                description=(node.get("description") or "").strip(),
                columns=[
                    Column(
                        name=column_name,
                        data_type=(column.get("data_type") or "").lower(),
                        description=(column.get("description") or "").strip(),
                    )
                    for column_name, column in (node.get("columns") or {}).items()
                ],
            )
        )
    # Stable ordering keeps the prompt byte-identical between runs, which is
    # what makes the cache breakpoint useful.
    tables.sort(key=lambda t: EXPOSED_MODELS.index(t.name))
    return tables


def tables_from_database(settings: Settings) -> list[Table]:
    """Fallback: read `information_schema` directly."""
    import duckdb

    path = Path(settings.duckdb_path)
    if not path.exists():
        return []

    con = duckdb.connect(str(path), read_only=True)
    try:
        rows = con.execute(
            """
            SELECT table_schema, table_name, column_name, data_type
            FROM information_schema.columns
            WHERE table_name IN ({placeholders})
            ORDER BY table_schema, table_name, ordinal_position
            """.format(placeholders=", ".join("?" for _ in EXPOSED_MODELS)),
            list(EXPOSED_MODELS),
        ).fetchall()
    finally:
        con.close()

    by_table: dict[tuple[str, str], Table] = {}
    for schema, table_name, column_name, data_type in rows:
        key = (schema, table_name)
        if key not in by_table:
            by_table[key] = Table(name=table_name, schema=schema)
        by_table[key].columns.append(Column(name=column_name, data_type=str(data_type).lower()))

    return sorted(by_table.values(), key=lambda t: EXPOSED_MODELS.index(t.name))


def load_tables(settings: Settings | None = None) -> list[Table]:
    settings = settings or get_settings()
    manifest = _load_manifest(settings)
    if manifest:
        tables = tables_from_manifest(manifest)
        if tables:
            return tables
    return tables_from_database(settings)


def render_catalog(tables: list[Table]) -> str:
    """Render as annotated DDL.

    DDL rather than prose or JSON: it is the densest format the model already
    knows how to read, and descriptions ride along as SQL comments where they
    are unambiguously attached to their column.
    """
    if not tables:
        return "(no warehouse tables found - the warehouse has not been built)"

    blocks: list[str] = []
    for table in tables:
        lines = [f"-- {table.description}"] if table.description else []
        lines.append(f"CREATE TABLE {table.qualified} (")

        width = max((len(c.name) for c in table.columns), default=0)
        for i, column in enumerate(table.columns):
            comma = "," if i < len(table.columns) - 1 else ""
            comment = f"  -- {column.description}" if column.description else ""
            data_type = column.data_type or "unknown"
            lines.append(f"    {column.name.ljust(width)} {data_type}{comma}{comment}")

        lines.append(");")
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks)


@lru_cache(maxsize=1)
def get_catalog_text(_cache_key: str = "") -> str:
    """Cached rendered catalogue.

    Cached because it is rebuilt on every question otherwise, and because a
    byte-identical prefix is what the prompt cache keys on. Call
    `get_catalog_text.cache_clear()` after a warehouse rebuild.
    """
    return render_catalog(load_tables())


def metric_names(settings: Settings | None = None) -> list[str]:
    """Metric names available in the warehouse, for the router's vocabulary.

    Returns the seed's list if the warehouse is unreachable, so routing still
    works before a first build.
    """
    settings = settings or get_settings()
    try:
        import duckdb

        con = duckdb.connect(str(settings.duckdb_path), read_only=True)
        try:
            rows = con.execute("SELECT DISTINCT metric FROM semantic.metric_definitions").fetchall()
            return sorted(r[0] for r in rows)
        finally:
            con.close()
    except Exception:  # noqa: BLE001 - pre-build fallback is expected
        seed = Path(settings.dbt_project_dir) / "seeds" / "concept_map.csv"
        if not seed.exists():
            return []
        lines = seed.read_text(encoding="utf-8").splitlines()[1:]
        return sorted({line.split(",")[0] for line in lines if line.strip()})
