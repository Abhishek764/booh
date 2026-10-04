"""Supported local/server entrypoint with privacy-safe HTTP logging defaults.

Uvicorn's default access formatter includes the raw request line. OAuth
callbacks carry authorization codes and state in that line, so the supported
entrypoint disables access logging and the default logging configuration.
Application errors remain handled by the FastAPI boundary without request URL
or credential logging.
"""

from __future__ import annotations

import uvicorn

from backend.app.main import app


def run() -> None:
    """Run BOOH without access logs that could contain callback query values."""

    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    run()
