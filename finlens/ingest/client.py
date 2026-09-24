"""The one HTTP client that talks to sec.gov.

Everything SEC asks of an automated consumer is enforced here rather than left
to callers: a descriptive User-Agent with a contact address, a rate limit below
the published ceiling, gzip, and backoff that honours ``Retry-After``.

Two hosts are in play and they are not interchangeable:

* ``data.sec.gov``  - the JSON APIs (submissions, companyfacts, frames)
* ``www.sec.gov``   - the archives (the filing documents themselves)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from finlens.config import Settings, get_settings
from finlens.ingest.ratelimit import TokenBucket
from finlens.logging import get_logger

log = get_logger(__name__)

# 403 is included deliberately: EDGAR's edge returns it (not 429) when it
# decides you are being impolite, and it clears on its own after a pause.
RETRY_STATUS = frozenset({403, 429, 500, 502, 503, 504})


class EdgarError(RuntimeError):
    """Any non-retryable failure talking to EDGAR."""


class EdgarNotFound(EdgarError):
    """The resource does not exist.

    Common and usually benign: a company with no XBRL history has no
    ``companyfacts`` document at all, and that is a fact about the company
    rather than an error in the pipeline.
    """


@dataclass(frozen=True)
class FetchResult:
    url: str
    status_code: int
    content: bytes
    headers: dict[str, str]
    from_cache: bool = False

    def json(self) -> Any:
        return json.loads(self.content)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")


class EdgarClient:
    """Rate-limited, retrying EDGAR reader.

    Usable as a context manager; a single instance is safe to share across
    threads because the limiter is locked and ``httpx.Client`` is thread-safe.

        with EdgarClient() as edgar:
            facts = edgar.get_json("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json")
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if "example.com" in self.settings.sec_user_agent:
            log.warning(
                "sec_user_agent still contains the placeholder contact address; "
                "SEC blocks requests without a real one",
                user_agent=self.settings.sec_user_agent,
            )
        self._bucket = TokenBucket(self.settings.sec_rate_limit_rps)
        self._owns_client = client is None
        self._client = client or httpx.Client(
            headers={
                "User-Agent": self.settings.sec_user_agent,
                "Accept-Encoding": "gzip, deflate",
            },
            timeout=self.settings.sec_timeout_s,
            follow_redirects=True,
        )
        self._cache_dir = cache_dir or self.settings.sec_cache_dir
        if self._cache_dir is not None:
            Path(self._cache_dir).mkdir(parents=True, exist_ok=True)

    # -- lifecycle ------------------------------------------------------------

    def __enter__(self) -> EdgarClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # -- caching --------------------------------------------------------------

    def _cache_path(self, url: str) -> Path | None:
        if self._cache_dir is None:
            return None
        import hashlib

        digest = hashlib.sha256(url.encode()).hexdigest()[:32]
        return Path(self._cache_dir) / f"{digest}.bin"

    # -- fetching -------------------------------------------------------------

    def fetch(self, url: str, *, allow_missing: bool = False) -> FetchResult | None:
        """GET ``url``, respecting the rate limit and retrying transient failures.

        Returns ``None`` instead of raising on 404 when ``allow_missing`` is set,
        which is the common case for optional per-company documents.
        """
        cache_path = self._cache_path(url)
        if cache_path is not None and cache_path.exists():
            return FetchResult(
                url=url,
                status_code=200,
                content=cache_path.read_bytes(),
                headers={},
                from_cache=True,
            )

        last_error: Exception | None = None
        for attempt in range(self.settings.sec_max_retries):
            self._bucket.acquire()
            try:
                response = self._client.get(url)
            except httpx.TransportError as exc:
                last_error = exc
                self._sleep_backoff(attempt, reason=type(exc).__name__, url=url)
                continue

            if response.status_code == 404:
                if allow_missing:
                    log.debug("edgar.missing", url=url)
                    return None
                raise EdgarNotFound(f"404 for {url}")

            if response.status_code in RETRY_STATUS:
                last_error = EdgarError(f"{response.status_code} for {url}")
                self._sleep_backoff(
                    attempt,
                    reason=str(response.status_code),
                    url=url,
                    retry_after=response.headers.get("Retry-After"),
                )
                continue

            if response.status_code >= 400:
                raise EdgarError(f"{response.status_code} for {url}: {response.text[:200]}")

            if cache_path is not None:
                cache_path.write_bytes(response.content)

            return FetchResult(
                url=url,
                status_code=response.status_code,
                content=response.content,
                headers=dict(response.headers),
            )

        raise EdgarError(
            f"giving up on {url} after {self.settings.sec_max_retries} attempts"
        ) from last_error

    def get_json(self, url: str, *, allow_missing: bool = False) -> Any | None:
        result = self.fetch(url, allow_missing=allow_missing)
        if result is None:
            return None
        try:
            return result.json()
        except json.JSONDecodeError as exc:
            # EDGAR occasionally serves an HTML error page with a 200.
            raise EdgarError(f"{url} did not return JSON: {result.text[:200]}") from exc

    def _sleep_backoff(
        self,
        attempt: int,
        *,
        reason: str,
        url: str,
        retry_after: str | None = None,
    ) -> None:
        delay = float(retry_after) if retry_after and retry_after.isdigit() else 2.0**attempt
        log.warning("edgar.retry", url=url, reason=reason, attempt=attempt + 1, sleep_s=delay)
        time.sleep(delay)

    # -- convenience URLs -----------------------------------------------------

    @property
    def data_url(self) -> str:
        return self.settings.sec_data_url.rstrip("/")

    @property
    def www_url(self) -> str:
        return self.settings.sec_base_url.rstrip("/")
