from __future__ import annotations

import io
import logging

from plugin_agent.logging_config import configure_logging


def test_configure_logging_writes_structured_stdout_format() -> None:
    stream = io.StringIO()
    configure_logging(level="INFO", stream=stream, force=True)

    logging.getLogger("plugin_agent.test").info("hello")

    output = stream.getvalue()
    assert "plugin_agent.test" in output
    assert "INFO" in output
    assert "hello" in output
