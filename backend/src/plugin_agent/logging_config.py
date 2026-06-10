from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import TextIO

DEFAULT_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"


def configure_logging(
    level: str | int | None = None,
    *,
    stream: TextIO | None = None,
    log_file: str | Path | None = None,
    force: bool = False,
) -> int:
    """Configure backend logging for CLI/server entrypoints.

    Library imports should not configure logging implicitly. CLI/server code calls this
    once at process startup; tests can pass an in-memory stream and force=True.
    """

    configured_level = level or os.getenv("PLUGIN_AGENT_LOG_LEVEL", "INFO")
    numeric_level = _normalize_level(configured_level)
    configured_file = log_file or os.getenv("PLUGIN_AGENT_LOG_FILE")
    handlers: list[logging.Handler] | None = None
    if configured_file:
        path = Path(configured_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers = [logging.FileHandler(path, encoding="utf-8")]

    kwargs = {"level": numeric_level, "format": DEFAULT_LOG_FORMAT, "force": force}
    if handlers is not None:
        kwargs["handlers"] = handlers
    else:
        kwargs["stream"] = stream or sys.stdout
    logging.basicConfig(**kwargs)
    logging.getLogger("plugin_agent").setLevel(numeric_level)
    logging.getLogger("plugin_agent_sdk").setLevel(numeric_level)
    return numeric_level


def _normalize_level(level: str | int) -> int:
    if isinstance(level, int):
        return level
    normalized = str(level).strip().upper()
    if not normalized:
        return logging.INFO
    value = getattr(logging, normalized, None)
    if isinstance(value, int):
        return value
    raise ValueError(f"unknown log level: {level}")
