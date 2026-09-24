"""Single source of truth for runtime configuration.

Every setting is overridable by environment variable with a ``FINLENS_`` prefix.
Vendor credentials keep their conventional names (``GOOGLE_API_KEY``,
``GROQ_API_KEY``, ``R2_ACCESS_KEY_ID``, ...) because the vendor SDKs read those
directly and renaming them just creates two ways to be wrong.

Everything here is chosen to sit inside a permanently-free tier. Where a managed
service is configured but has no credentials, the corresponding component falls
back to a local implementation so the whole pipeline still runs on a laptop.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent

StorageBackend = Literal["local", "s3"]
WarehouseBackend = Literal["duckdb", "bigquery"]
VectorBackend = Literal["duckdb", "pgvector"]
LlmProviderName = Literal["gemini", "groq", "anthropic"]
EmbeddingProviderName = Literal["sentence-transformers", "hash"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="FINLENS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- EDGAR ---------------------------------------------------------------
    sec_user_agent: str = "FinLens/0.1 (set FINLENS_SEC_USER_AGENT)"
    sec_base_url: str = "https://www.sec.gov"
    sec_data_url: str = "https://data.sec.gov"
    # SEC publishes a 10 req/s ceiling. 8 leaves headroom for clock skew.
    sec_rate_limit_rps: float = 8.0
    sec_max_retries: int = 5
    sec_timeout_s: float = 30.0
    # Response cache. On by default: during development you re-run the same
    # pulls constantly, and re-downloading is both slow and rude to SEC.
    sec_cache_dir: Path | None = REPO_ROOT / "data" / "cache" / "edgar"

    # --- Scale asymmetry -----------------------------------------------------
    # The deliberate design decision: broad structured coverage, narrow text
    # coverage. Retrieval cost scales with corpus size and adds little marginal
    # value for commentary; structured coverage is cheap and is what makes
    # cross-entity comparison possible. See docs/ARCHITECTURE.md.
    structured_universe_size: int = 300
    structured_year_min: int = 2019
    text_universe: list[str] = Field(
        default_factory=lambda: [
            "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
            "META", "INTC", "TSLA", "AMD", "CRM",
        ]
    )
    text_year_min: int = 2020
    # Only the narrative sections. Item 8 is financial statements, which are
    # already in the structured layer - indexing them creates two sources of
    # truth for the same number.
    text_items: list[str] = Field(default_factory=lambda: ["1A", "7", "7A"])

    # --- Object storage (Cloudflare R2, S3-compatible) -----------------------
    storage_backend: StorageBackend = "local"
    storage_bucket: str = "finlens"
    storage_prefix: str = ""
    # R2: https://<account_id>.r2.cloudflarestorage.com
    s3_endpoint_url: str | None = Field(default=None, alias="R2_ENDPOINT_URL")
    s3_access_key_id: SecretStr | None = Field(default=None, alias="R2_ACCESS_KEY_ID")
    s3_secret_access_key: SecretStr | None = Field(default=None, alias="R2_SECRET_ACCESS_KEY")
    s3_region: str = "auto"
    # Where the `local` backend writes, and where downloads land before upload.
    lake_root: Path = REPO_ROOT / "data" / "lake"

    # --- Warehouse -----------------------------------------------------------
    warehouse_backend: WarehouseBackend = "duckdb"
    duckdb_path: Path = REPO_ROOT / "data" / "warehouse" / "finlens.duckdb"
    bigquery_project: str | None = Field(default=None, alias="GCP_PROJECT")
    bigquery_dataset: str = "finlens"
    bigquery_location: str = "US"

    dbt_project_dir: Path = REPO_ROOT / "finlens" / "warehouse"
    dbt_profiles_dir: Path = REPO_ROOT / "finlens" / "warehouse"
    dbt_target: str = "dev"

    # --- Vector store (Supabase Postgres + pgvector) -------------------------
    vector_backend: VectorBackend = "duckdb"
    vector_store_path: Path = REPO_ROOT / "data" / "index"
    supabase_db_url: SecretStr | None = Field(default=None, alias="SUPABASE_DB_URL")

    # --- Embeddings ----------------------------------------------------------
    # bge-small-en-v1.5: 384 dimensions, CPU-friendly, free forever. The
    # dimensionality matters - Supabase's free tier is 500 MB, and 768-dim
    # vectors over ~20k chunks would not fit alongside the text.
    embedding_provider: EmbeddingProviderName = "sentence-transformers"
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    embedding_batch_size: int = 32
    chunk_target_tokens: int = 800
    chunk_overlap_tokens: int = 100

    # --- LLM -----------------------------------------------------------------
    # Free tiers, in preference order. Both are rate-limited rather than
    # metered, so the fallback chain is what keeps a long eval run alive.
    llm_provider: LlmProviderName = "gemini"
    llm_fallback_providers: list[LlmProviderName] = Field(default_factory=lambda: ["groq"])
    gemini_model: str = "gemini-2.0-flash"
    groq_model: str = "openai/gpt-oss-120b"
    anthropic_model: str = "claude-opus-5"
    google_api_key: SecretStr | None = Field(default=None, alias="GOOGLE_API_KEY")
    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.0
    llm_timeout_s: float = 120.0

    # --- Retrieval -----------------------------------------------------------
    retrieval_top_k: int = 20
    rerank_top_n: int = 5
    sql_row_limit: int = 1000
    sql_timeout_s: float = 30.0

    # --- API -----------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_cors_origins: list[str] = Field(default_factory=lambda: ["*"])
    # Anonymous callers are unrestricted by default so `make demo` needs no
    # login. Turn this on for any deployment with more than one user.
    require_auth: bool = False
    # 32+ bytes: below that PyJWT warns, and correctly - HS256 with a short key
    # is brute-forceable. Override in any real deployment.
    jwt_secret: SecretStr = SecretStr("dev-only-insecure-change-me-in-production")
    jwt_algorithm: str = "HS256"
    jwt_ttl_minutes: int = 720

    # --- Observability -------------------------------------------------------
    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("sec_rate_limit_rps")
    @classmethod
    def _cap_rate_limit(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("sec_rate_limit_rps must be positive")
        if v > 10:
            raise ValueError(
                "SEC's published limit for automated access is 10 req/s; "
                "refusing to configure a limiter above it"
            )
        return v

    @field_validator("lake_root", "duckdb_path", "vector_store_path")
    @classmethod
    def _absolutise(cls, v: Path) -> Path:
        return v if v.is_absolute() else (REPO_ROOT / v).resolve()

    @field_validator("text_universe")
    @classmethod
    def _upper(cls, v: list[str]) -> list[str]:
        return [t.upper() for t in v]

    # -- credential probes ----------------------------------------------------

    @property
    def has_s3_credentials(self) -> bool:
        return bool(self.s3_endpoint_url and self.s3_access_key_id and self.s3_secret_access_key)

    @property
    def has_bigquery(self) -> bool:
        return bool(self.bigquery_project)

    @property
    def has_supabase(self) -> bool:
        return bool(self.supabase_db_url)

    def api_key_for(self, provider: LlmProviderName) -> str | None:
        secret = {
            "gemini": self.google_api_key,
            "groq": self.groq_api_key,
            "anthropic": self.anthropic_api_key,
        }[provider]
        return secret.get_secret_value() if secret else None

    def model_for(self, provider: LlmProviderName) -> str:
        return {
            "gemini": self.gemini_model,
            "groq": self.groq_model,
            "anthropic": self.anthropic_model,
        }[provider]

    def ensure_dirs(self) -> None:
        """Create the writable roots. Cheap and idempotent; safe at startup."""
        paths = [self.lake_root, self.vector_store_path, self.duckdb_path.parent]
        if self.sec_cache_dir:
            paths.append(self.sec_cache_dir)
        for path in paths:
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton. Call ``.cache_clear()`` in tests."""
    return Settings()
