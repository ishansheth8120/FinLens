"""Provider-agnostic LLM access.

Three providers behind one interface, with an automatic fallback chain. The
chain is not a nicety: both free tiers are rate-limited rather than metered, so
a 70-question eval run *will* hit a limit partway through, and without a
fallback the run dies at question 40 having spent an hour.

    Gemini Flash  (primary)   free tier, ~15 req/min
    Groq          (fallback)  free tier, different limit pool
    Anthropic     (optional)  paid; kept for a quality baseline in the report

Two call shapes, because that is all the agent needs:

    complete(prompt, system) -> str
    parse(prompt, system, schema) -> a validated Pydantic model

`parse` is the important one. Router decisions, generated SQL and judge verdicts
are all structured, and every provider here supports constrained JSON output
natively - so a malformed response is a validation error at the boundary rather
than a `KeyError` three frames deeper.
"""

from __future__ import annotations

import json
import re
import time
from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from finlens.agent.types import Usage
from finlens.config import LlmProviderName, Settings, get_settings
from finlens.logging import get_logger

log = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# Retryable: rate limits and transient server errors. Everything else is a bug
# in the request and retrying just burns quota.
_RETRYABLE = re.compile(
    r"429|resource.?exhausted|rate.?limit|quota|500|502|503|504|overloaded|unavailable",
    re.IGNORECASE,
)


class LlmError(RuntimeError):
    """A model call failed in a way the caller has to handle."""


class LlmRateLimited(LlmError):
    """Retryable. Triggers the fallback chain."""


def _is_retryable(exc: Exception) -> bool:
    return bool(_RETRYABLE.search(str(exc)))


def _extract_json(text: str) -> Any:
    """Parse a JSON object out of a model response.

    Constrained decoding usually returns bare JSON, but Groq's JSON mode
    occasionally wraps it in a fenced block, so the fence is stripped before
    parsing rather than after a failure.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned, flags=re.MULTILINE).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Last resort: the outermost brace-balanced span.
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise
        return json.loads(cleaned[start : end + 1])


class LlmProvider(ABC):
    """One model behind one interface."""

    name: LlmProviderName
    model: str

    @abstractmethod
    def complete(self, prompt: str, *, system: str, max_tokens: int) -> tuple[str, Usage]: ...

    @abstractmethod
    def complete_json(
        self, prompt: str, *, system: str, schema: dict[str, Any], max_tokens: int
    ) -> tuple[str, Usage]: ...


# --- Gemini ------------------------------------------------------------------


class GeminiProvider(LlmProvider):
    """Google AI Studio free tier. Supports a response schema natively."""

    name: LlmProviderName = "gemini"

    def __init__(self, api_key: str, model: str, temperature: float, timeout_s: float) -> None:
        try:
            from google import genai
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError("the gemini provider needs `pip install 'finlens[llm]'`") from exc

        self.model = model
        self.temperature = temperature
        self._genai = genai
        self._client = genai.Client(api_key=api_key)
        self._timeout_ms = int(timeout_s * 1000)

    def _config(self, system: str, max_tokens: int, schema: dict[str, Any] | None) -> Any:
        from google.genai import types

        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=self.temperature,
            max_output_tokens=max_tokens,
            response_mime_type="application/json" if schema else "text/plain",
            response_schema=schema,
            http_options=types.HttpOptions(timeout=self._timeout_ms),
        )

    def _call(
        self, prompt: str, system: str, max_tokens: int, schema: dict[str, Any] | None
    ) -> tuple[str, Usage]:
        try:
            response = self._client.models.generate_content(
                model=self.model,
                contents=prompt,
                config=self._config(system, max_tokens, schema),
            )
        except Exception as exc:
            if _is_retryable(exc):
                raise LlmRateLimited(f"gemini: {exc}") from exc
            raise LlmError(f"gemini: {exc}") from exc

        metadata = getattr(response, "usage_metadata", None)
        usage = Usage(
            input_tokens=getattr(metadata, "prompt_token_count", 0) or 0,
            output_tokens=getattr(metadata, "candidates_token_count", 0) or 0,
            cache_read_tokens=getattr(metadata, "cached_content_token_count", 0) or 0,
            calls=1,
            provider=self.name,
            model=self.model,
        )
        text = response.text or ""
        if not text.strip():
            # Almost always a safety block or a max_tokens cut-off.
            raise LlmError(f"gemini returned no text (finish reason: {_finish_reason(response)})")
        return text, usage

    def complete(self, prompt: str, *, system: str, max_tokens: int) -> tuple[str, Usage]:
        return self._call(prompt, system, max_tokens, None)

    def complete_json(
        self, prompt: str, *, system: str, schema: dict[str, Any], max_tokens: int
    ) -> tuple[str, Usage]:
        return self._call(prompt, system, max_tokens, schema)


def _finish_reason(response: Any) -> str:
    try:
        return str(response.candidates[0].finish_reason)
    except Exception:  # noqa: BLE001
        return "unknown"


# --- Groq --------------------------------------------------------------------


class GroqProvider(LlmProvider):
    """Groq free tier. OpenAI-shaped API, JSON mode but no schema enforcement."""

    name: LlmProviderName = "groq"

    def __init__(self, api_key: str, model: str, temperature: float, timeout_s: float) -> None:
        try:
            from groq import Groq
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError("the groq provider needs `pip install 'finlens[llm]'`") from exc

        self.model = model
        self.temperature = temperature
        self._client = Groq(api_key=api_key, timeout=timeout_s)

    def _call(
        self, prompt: str, system: str, max_tokens: int, json_mode: bool
    ) -> tuple[str, Usage]:
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                ],
                temperature=self.temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"} if json_mode else None,
            )
        except Exception as exc:
            if _is_retryable(exc):
                raise LlmRateLimited(f"groq: {exc}") from exc
            raise LlmError(f"groq: {exc}") from exc

        usage_data = getattr(response, "usage", None)
        usage = Usage(
            input_tokens=getattr(usage_data, "prompt_tokens", 0) or 0,
            output_tokens=getattr(usage_data, "completion_tokens", 0) or 0,
            calls=1,
            provider=self.name,
            model=self.model,
        )
        return response.choices[0].message.content or "", usage

    def complete(self, prompt: str, *, system: str, max_tokens: int) -> tuple[str, Usage]:
        return self._call(prompt, system, max_tokens, json_mode=False)

    def complete_json(
        self, prompt: str, *, system: str, schema: dict[str, Any], max_tokens: int
    ) -> tuple[str, Usage]:
        # Groq's JSON mode guarantees valid JSON but not schema conformance, so
        # the schema goes in the prompt and Pydantic validates the result.
        augmented = (
            f"{system}\n\nRespond with a single JSON object matching this schema:\n"
            f"{json.dumps(schema, indent=2)}"
        )
        return self._call(prompt, augmented, max_tokens, json_mode=True)


# --- Anthropic (optional, paid) ----------------------------------------------


class AnthropicProvider(LlmProvider):
    """Claude. Not free - configured only when explicitly selected, and kept so
    the report can compare a paid frontier model against the free tiers."""

    name: LlmProviderName = "anthropic"

    def __init__(self, api_key: str | None, model: str, timeout_s: float) -> None:
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise RuntimeError("the anthropic provider needs `pip install anthropic`") from exc

        self.model = model
        # Zero-arg when no key: the SDK also resolves ANTHROPIC_AUTH_TOKEN and
        # an `ant auth login` profile, so an unset key is not proof of no
        # credentials.
        self._client = (
            anthropic.Anthropic(api_key=api_key, timeout=timeout_s)
            if api_key
            else anthropic.Anthropic(timeout=timeout_s)
        )

    def _usage(self, response: Any) -> Usage:
        usage = getattr(response, "usage", None)
        return Usage(
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            cache_read_tokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            calls=1,
            provider=self.name,
            model=self.model,
        )

    def complete(self, prompt: str, *, system: str, max_tokens: int) -> tuple[str, Usage]:
        import anthropic

        try:
            with self._client.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                # Cache the system block: it carries the schema catalogue, which
                # is large and byte-stable across every request.
                system=[
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ],
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
            ) as stream:
                response = stream.get_final_message()
        except anthropic.APIStatusError as exc:
            if exc.status_code in (429, 500, 502, 503, 529):
                raise LlmRateLimited(f"anthropic: {exc.message}") from exc
            raise LlmError(f"anthropic ({exc.status_code}): {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise LlmRateLimited(f"anthropic: {exc}") from exc

        if response.stop_reason == "refusal":
            detail = getattr(response.stop_details, "explanation", None) or "no explanation"
            raise LlmError(f"anthropic declined: {detail}")

        text = "".join(b.text for b in response.content if b.type == "text")
        return text, self._usage(response)

    def complete_json(
        self, prompt: str, *, system: str, schema: dict[str, Any], max_tokens: int
    ) -> tuple[str, Usage]:
        import anthropic

        try:
            response = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=[
                    {"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}
                ],
                messages=[{"role": "user", "content": prompt}],
                thinking={"type": "adaptive"},
                output_config={"format": {"type": "json_schema", "schema": schema}},
            )
        except anthropic.APIStatusError as exc:
            if exc.status_code in (429, 500, 502, 503, 529):
                raise LlmRateLimited(f"anthropic: {exc.message}") from exc
            raise LlmError(f"anthropic ({exc.status_code}): {exc.message}") from exc

        text = next((b.text for b in response.content if b.type == "text"), "")
        return text, self._usage(response)


# --- the client --------------------------------------------------------------


def build_provider(name: LlmProviderName, settings: Settings) -> LlmProvider:
    key = settings.api_key_for(name)
    model = settings.model_for(name)

    if name == "gemini":
        if not key:
            raise LlmError("GOOGLE_API_KEY is not set")
        return GeminiProvider(key, model, settings.llm_temperature, settings.llm_timeout_s)

    if name == "groq":
        if not key:
            raise LlmError("GROQ_API_KEY is not set")
        return GroqProvider(key, model, settings.llm_temperature, settings.llm_timeout_s)

    return AnthropicProvider(key, model, settings.llm_timeout_s)


class LlmClient:
    """The only thing the agent calls. Owns the fallback chain and retries."""

    def __init__(self, settings: Settings | None = None, *, providers: list[LlmProvider] | None = None):
        self.settings = settings or get_settings()
        self._explicit = providers
        self._chain: list[LlmProvider] | None = providers

    @property
    def chain(self) -> list[LlmProvider]:
        """Providers in preference order, built lazily.

        A provider whose credential is missing is skipped with a warning rather
        than raising - a partially-configured environment should degrade to the
        providers it *can* reach.
        """
        if self._chain is None:
            names = [self.settings.llm_provider, *self.settings.llm_fallback_providers]
            chain: list[LlmProvider] = []
            for name in dict.fromkeys(names):  # de-duplicate, preserve order
                try:
                    chain.append(build_provider(name, self.settings))
                except (LlmError, RuntimeError) as exc:
                    log.warning("llm.provider_unavailable", provider=name, reason=str(exc))
            if not chain:
                raise LlmError(
                    "no LLM provider is configured. Set GOOGLE_API_KEY (free at "
                    "aistudio.google.com) or GROQ_API_KEY (free at console.groq.com)."
                )
            self._chain = chain
            log.info("llm.chain", providers=[p.name for p in chain])
        return self._chain

    @property
    def primary(self) -> LlmProvider:
        return self.chain[0]

    def _attempt(self, call, *, description: str) -> tuple[str, Usage]:
        """Run ``call`` against each provider in turn, retrying retryables."""
        last: Exception | None = None

        for provider in self.chain:
            for attempt in range(3):
                try:
                    return call(provider)
                except LlmRateLimited as exc:
                    last = exc
                    delay = 2.0 * (2**attempt)
                    log.warning(
                        "llm.rate_limited",
                        provider=provider.name,
                        attempt=attempt + 1,
                        sleep_s=delay,
                        call=description,
                    )
                    time.sleep(delay)
                except LlmError as exc:
                    # Not retryable on this provider; try the next one, because
                    # a prompt one model rejects another may well accept.
                    last = exc
                    log.warning("llm.failed", provider=provider.name, error=str(exc))
                    break

        raise LlmError(f"every provider failed for {description}: {last}")

    def complete(self, prompt: str, *, system: str, max_tokens: int | None = None) -> tuple[str, Usage]:
        limit = max_tokens or self.settings.llm_max_tokens
        return self._attempt(
            lambda p: p.complete(prompt, system=system, max_tokens=limit),
            description="complete",
        )

    def parse(
        self,
        prompt: str,
        *,
        system: str,
        schema: type[T],
        max_tokens: int | None = None,
    ) -> tuple[T, Usage]:
        """A completion constrained to a Pydantic model."""
        limit = max_tokens or self.settings.llm_max_tokens
        json_schema = _gemini_safe_schema(schema.model_json_schema())

        def call(provider: LlmProvider) -> tuple[str, Usage]:
            return provider.complete_json(
                prompt, system=system, schema=json_schema, max_tokens=limit
            )

        text, usage = self._attempt(call, description=f"parse[{schema.__name__}]")

        try:
            return schema.model_validate(_extract_json(text)), usage
        except (json.JSONDecodeError, ValidationError) as exc:
            raise LlmError(f"model did not return a valid {schema.__name__}: {exc}") from exc


def _gemini_safe_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Inline `$ref`s and drop keywords Gemini's schema validator rejects.

    Pydantic emits `$defs` plus `$ref` for nested models and enums, and Gemini's
    response-schema parser supports neither. Groq gets the schema as prompt text
    and does not care, so normalising once here is simpler than branching.
    """
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, list):
            return [resolve(item) for item in node]
        if not isinstance(node, dict):
            return node

        if "$ref" in node:
            name = node["$ref"].rsplit("/", 1)[-1]
            merged = {**defs.get(name, {}), **{k: v for k, v in node.items() if k != "$ref"}}
            return resolve(merged)

        # `anyOf: [X, null]` is how Pydantic spells Optional; Gemini wants a
        # plain nullable type instead.
        if "anyOf" in node:
            variants = [v for v in node["anyOf"] if v.get("type") != "null"]
            if len(variants) == 1:
                return {**resolve(variants[0]), "nullable": True}

        drop = {"$defs", "additionalProperties", "discriminator", "title", "default"}
        return {k: resolve(v) for k, v in node.items() if k not in drop}

    return resolve({k: v for k, v in schema.items() if k != "$defs"})


_client: LlmClient | None = None


def get_llm(settings: Settings | None = None) -> LlmClient:
    """Process-wide client. Sharing one keeps the fallback chain warm."""
    global _client
    if _client is None:
        _client = LlmClient(settings)
    return _client


def reset_llm() -> None:
    """Drop the cached client. For tests and for config changes at runtime."""
    global _client
    _client = None
