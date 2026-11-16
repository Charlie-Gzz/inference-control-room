"""The local site server can be stopped and started again on the same port."""

import socket
import urllib.request

from icr import siteserver


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_a_stopped_server_frees_its_port_for_the_next_one():
    port = _free_port()
    for _ in range(3):  # video capture starts one server per story, one after the other
        server = siteserver.serve_in_thread(port)
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/index.html", timeout=5) as r:
                assert r.status == 200 and b"Switchyard" in r.read()
        finally:
            siteserver.stop(server)
