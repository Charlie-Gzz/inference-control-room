"""Local static server for the control room. Binds to 127.0.0.1 only.

`mock=True` serves `/data/` from `.scratch/site-data/` (mock runs, for development).
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import threading
from pathlib import Path

from icr.analysis.site_data import MOCK_DATA_DIR, SITE_DIR


class Handler(http.server.SimpleHTTPRequestHandler):
    data_dir: Path | None = None

    def translate_path(self, path: str) -> str:
        clean = path.split("?", 1)[0].split("#", 1)[0]
        if self.data_dir and clean.startswith("/data/"):
            return str(self.data_dir / clean[len("/data/") :])
        return super().translate_path(path)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")  # always the newest files while developing
        super().end_headers()

    def log_message(self, *args) -> None:  # quiet
        pass


def make_server(port: int, mock: bool = False) -> http.server.ThreadingHTTPServer:
    handler = functools.partial(Handler, directory=str(SITE_DIR))
    handler.func.data_dir = MOCK_DATA_DIR if mock else None
    return http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)


def serve(port: int, mock: bool = False) -> None:
    server = make_server(port, mock)
    print(f"Switchyard control room: http://127.0.0.1:{port}/" + ("  (MOCK data)" if mock else ""))
    with contextlib.suppress(KeyboardInterrupt):
        server.serve_forever()


def serve_in_thread(port: int, mock: bool = False) -> http.server.ThreadingHTTPServer:
    """For screenshots and video capture: returns the running server (end it with `stop`)."""
    server = make_server(port, mock)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def stop(server: http.server.ThreadingHTTPServer) -> None:
    """Stop a server from `serve_in_thread` and close its socket.

    Without the close the port stays bound. On Windows a later server can still bind it,
    and connections then land on the dead socket and time out.
    """
    server.shutdown()
    server.server_close()
