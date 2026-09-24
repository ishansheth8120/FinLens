"""Prompt templates, kept as Markdown files rather than Python strings.

Three reasons: they are reviewable in a diff without escaping noise, they can be
edited without touching code (which matters when the eval harness is
hill-climbing on them), and the files are byte-stable, which is what the prompt
cache keys on.

Placeholders use `{name}` and are filled with `str.format`, so a literal brace
in a prompt must be doubled.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_DIR = Path(__file__).parent


@lru_cache(maxsize=16)
def load_prompt(name: str) -> str:
    """Read a prompt by stem, e.g. ``load_prompt("router")``."""
    path = PROMPT_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"no prompt named {name!r} in {PROMPT_DIR}")
    return path.read_text(encoding="utf-8").strip()


def render(name: str, **values: object) -> str:
    """Load and fill a prompt template."""
    try:
        return load_prompt(name).format(**values)
    except KeyError as exc:
        raise KeyError(f"prompt {name!r} needs a value for {exc}") from exc
