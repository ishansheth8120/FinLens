"""The HTTP service.

Thin by design: the API validates, delegates to `finlens.agent`, and serialises.
No business logic lives here, which is what lets the CLI, the Airflow tasks and
the eval harness exercise the same code paths a user hits.
"""

from finlens.api.main import app, create_app

__all__ = ["app", "create_app"]
