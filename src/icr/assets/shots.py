"""Screenshots of every control room view, with a headless browser.

The site is served on localhost for the capture and every page is paused at a fixed
replay time, so the same data always gives the same pictures. Nothing personal can
appear: the pages show only recorded run data.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from icr import config, siteserver
from icr.assets import diagram

SHOTS_DIR = config.ROOT / "assets" / "screenshots"
PORT = 8797


@dataclass(frozen=True)
class Shot:
    name: str
    query: str
    width: int = 1600
    height: int = 900
    out_dir: Path = SHOTS_DIR
    full_page: bool = False


def shots(t: float, pick: int | None = None) -> list[Shot]:
    """The pictures the README and docs use. `t` is the replay time to pause at."""
    paused = f"t={t}&paused=1"
    return [
        Shot("hero", paused, 1600, 900),
        Shot("split", paused, 1600, 900),
        Shot("control-room", f"view=room&{paused}" + (f"&pick={pick}" if pick is not None else "")),
        Shot("what-if", "view=whatif", 1600, 900),
        Shot("autoscaling", "view=autoscale", 1600, 1000),
        Shot("method", "view=about", 1600, 1200, full_page=True),
        Shot("mobile", paused, 390, 844),
        Shot("og", paused, 1200, 630, config.ROOT / "site" / "assets"),
    ]


def capture(items: list[Shot], mock: bool = False) -> list[Path]:
    from playwright.sync_api import sync_playwright

    server = siteserver.serve_in_thread(PORT, mock=mock)
    written = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for shot in items:
                page = browser.new_page(viewport={"width": shot.width, "height": shot.height})
                page.goto(f"http://127.0.0.1:{PORT}/?{shot.query}")
                page.wait_for_selector("html[data-ready='1']", timeout=30000)
                page.wait_for_timeout(700)  # fonts and the lazily loaded view modules
                shot.out_dir.mkdir(parents=True, exist_ok=True)
                path = shot.out_dir / f"{shot.name}.png"
                page.screenshot(path=str(path), full_page=shot.full_page)
                page.close()
                written.append(path)
            # The architecture diagram: SVG from the generator, PNG rendered from that SVG.
            svg = diagram.write()
            page = browser.new_page(viewport={"width": diagram.W, "height": diagram.H})
            page.goto(svg.as_uri())
            png = svg.with_suffix(".png")
            page.screenshot(path=str(png))
            written += [svg, png]
            browser.close()
    finally:
        siteserver.stop(server)
    return written
