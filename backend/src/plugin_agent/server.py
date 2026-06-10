from __future__ import annotations

import logging
import socket
import threading
import time

import uvicorn

from plugin_agent.api import AppState, create_app, create_app_state

logger = logging.getLogger(__name__)


class PluginAgentHTTPServer:
    def __init__(self, state: AppState | None = None, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.state = state or create_app_state()
        self.host = host
        self.port = port
        self.app = create_app(self.state)
        self.socket = self._bind_socket(host, port)
        bound_host, bound_port = self.socket.getsockname()[:2]
        self.bound_host = str(bound_host)
        self.bound_port = int(bound_port)
        self.server = uvicorn.Server(
            uvicorn.Config(
                self.app,
                host=host,
                port=port,
                log_config=None,
                access_log=False,
                lifespan="off",
            )
        )
        self.thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        return f"http://{self.bound_host}:{self.bound_port}"

    def start(self) -> None:
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [self.socket]}, daemon=True)
        self.thread.start()
        while not self.server.started:
            if not self.thread.is_alive():
                raise RuntimeError("Plugin Agent HTTP service failed to start")
            time.sleep(0.01)
        logger.info("Plugin Agent HTTP service started at %s", self.base_url)

    def stop(self) -> None:
        self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
        self.socket.close()
        logger.info("Plugin Agent HTTP service stopped at %s", self.base_url)

    def _bind_socket(self, host: str, port: int) -> socket.socket:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(2048)
        return sock


__all__ = ["AppState", "PluginAgentHTTPServer", "create_app", "create_app_state"]
