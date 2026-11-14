"""One look for every chart: the Switchyard palette, fonts and title layout."""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402

from icr import config  # noqa: E402

BG = "#0B0F17"
PANEL = "#131A26"
LINE = "#1F2937"
INK = "#E5E7EB"
MUTED = "#9CA3AF"
ROSE = "#FB7185"
GOOD = "#22C55E"
WARN = "#F59E0B"
BAD = "#EF4444"
POLICY = {"round-robin": "#9CA3AF", "least-loaded": "#38BDF8", "prefix-aware": "#FB7185"}
POLICY_HATCH = {"round-robin": "", "least-loaded": "//", "prefix-aware": ""}
POLICY_MARKER = {"round-robin": "o", "least-loaded": "s", "prefix-aware": "D"}
SERIES = ["#FB7185", "#38BDF8", "#A78BFA", "#34D399", "#FBBF24", "#F472B6", "#22D3EE",
          "#C4B5FD", "#86EFAC", "#FDBA74", "#93C5FD", "#E879F9"]  # fmt: skip
MARKERS = ["o", "s", "D", "^", "v", "P", "X", "*", "<", ">", "h", "p"]

CHART_DIR = config.ROOT / "assets" / "charts"
FONT_DIR = Path(__file__).parent / "fonts"
WIDTH_PX = 1600
DPI = 200
SANS, MONO = "Inter", "JetBrains Mono"
TITLE_CHARS, SUBTITLE_CHARS = 84, 120  # line lengths that fit 1600 px at the sizes below


def apply() -> None:
    """Register the bundled fonts and set matplotlib's defaults to the Switchyard look."""
    for path in FONT_DIR.glob("*.ttf"):
        font_manager.fontManager.addfont(str(path))
    plt.rcParams.update(
        {
            "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
            "text.color": INK, "axes.labelcolor": MUTED, "axes.edgecolor": LINE,
            "xtick.color": MUTED, "ytick.color": MUTED, "grid.color": LINE,
            "axes.grid": True, "axes.axisbelow": True, "grid.linewidth": 0.8,
            "axes.spines.top": False, "axes.spines.right": False,
            "font.family": SANS, "font.size": 10, "axes.titlesize": 10,
            "axes.titleweight": "regular", "axes.titlecolor": MUTED, "axes.titlelocation": "left",
            # SVG text is stored as outlines, so it looks the same without the fonts installed.
            "legend.frameon": False, "legend.fontsize": 9, "svg.fonttype": "path",
            "xtick.labelsize": 9, "ytick.labelsize": 9, "axes.labelsize": 9.5,
        }
    )  # fmt: skip


def mono() -> str:
    return MONO


def figure(height_px: int = 900):
    """A 1600 px wide figure."""
    apply()
    return plt.figure(figsize=(WIDTH_PX / DPI, height_px / DPI), dpi=DPI)


def titles(fig, title: str, subtitle: str = "") -> float:
    """Draw the takeaway title and a muted subtitle, both wrapped to the figure width.

    Returns the top of the plotting area as a figure fraction: pass it to
    `fig.subplots_adjust(top=...)` so the axes start below the header.
    """
    height = fig.get_figheight() * DPI
    y = height - 34  # pixels from the bottom
    for line in textwrap.wrap(title, TITLE_CHARS):
        fig.text(0.035, y / height, line, fontsize=12.5, fontweight="bold", color=INK, va="top")
        y -= 46
    y -= 6
    for line in textwrap.wrap(subtitle, SUBTITLE_CHARS):
        fig.text(0.035, y / height, line, fontsize=8.6, color=MUTED, va="top")
        y -= 31
    return (y - 72) / height  # room for the axes' own titles


def footer(fig, text: str) -> None:
    fig.text(0.035, 14 / (fig.get_figheight() * DPI), text, fontsize=7.4, color=MUTED, va="bottom")


def bottom(fig, pixels: int = 150) -> float:
    """Bottom of the plotting area as a figure fraction: room for the x label and footer."""
    return pixels / (fig.get_figheight() * DPI)


def save(fig, name: str) -> list[Path]:
    """Write `assets/charts/<name>.png` (1600 px wide) and `.svg`."""
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    paths = [CHART_DIR / f"{name}.png", CHART_DIR / f"{name}.svg"]
    for path in paths:
        fig.savefig(path, dpi=DPI)
    plt.close(fig)
    svg = paths[1]  # same line endings on every OS, so the file does not change between machines
    svg.write_text(svg.read_text("utf-8"), encoding="utf-8", newline="\n")
    return paths
