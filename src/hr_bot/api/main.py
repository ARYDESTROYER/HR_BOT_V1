"""CLI entrypoint for running the FastAPI bridge service."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    host = os.getenv("HR_BOT_API_HOST", "0.0.0.0")
    port = int(os.getenv("HR_BOT_API_PORT", "8502"))
    reload_enabled = os.getenv("HR_BOT_API_RELOAD", "false").lower() in {"1", "true", "yes"}

    uvicorn.run(
        "hr_bot.api.server:app",
        host=host,
        port=port,
        reload=reload_enabled,
        log_level=os.getenv("HR_BOT_API_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
