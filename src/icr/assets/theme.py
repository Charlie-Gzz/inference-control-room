"""One look for every chart: the Switchyard palette, fonts and axis style."""

from __future__ import annotations

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
WIDTH_PX = 1600
DPI = 200


def _font(preferred: list[str]) -> str:
    installed = {f.name for f in font_manager.fontManager.ttflist}
    return next((name for name in preferred if name in installed), "DejaVu Sans")


def apply() -> None:
    """Set matplotlib's defaults to the Switchyard look."""
    sans = _font(["Inter", "Segoe UI", "Arial"])
    plt.rcParams.update(
        {
            "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
            "text.color": INK, "axes.labelcolor": MUTED, "axes.edgecolor": LINE,
            "xtick.color": MUTED, "ytick.color": MUTED, "grid.color": LINE,
            "axes.grid": True, "axes.axisbelow": True, "grid.linewidth": 0.8,
            "axes.spines.top": False, "axes.spines.right": False,
            "font.family": sans, "font.size": 10, "axes.titlesize": 10.5,
            "axes.titleweight": "regular", "axes.titlecolor": MUTED, "axes.titlelocation": "left",
            "legend.frameon": False, "legend.fontsize": 9, "svg.fonttype": "none",
            "xtick.labelsize": 9, "ytick.labelsize": 9, "axes.labelsize": 9.5,
        }
    )  # fmt: skip


def mono() -> str:
    return _font(["JetBrains Mono", "Consolas", "DejaVu Sans Mono"])


def figure(height_px: int = 900, **kwargs):
    """A 1600 px wide figure. The takeaway goes in `title`, the detail in `subtitle`."""
    apply()
    fig = plt.figure(figsize=(WIDTH_PX / DPI, height_px / DPI), dpi=DPI, **kwargs)
    return fig


def titles(fig, title: str, subtitle: str = "") -> None:
    """Takeaway title (large, top left) and a muted subtitle under it."""
    fig.text(0.035, 0.955, title, fontsize=13.5, fontweight="bold", color=INK, va="top", ha="left")
    if subtitle:
        fig.text(0.035, 0.955 - 0.062 * 900 / (fig.get_figheight() * DPI), subtitle,
                 fontsize=9, color=MUTED, va="top", ha="left")  # fmt: skip


def footer(fig, text: str) -> None:
    fig.text(0.035, 0.018, text, fontsize=7.5, color=MUTED, va="bottom", ha="left")


def save(fig, name: str) -> list[Path]:
    """Write `assets/charts/<name>.png` (1600 px wide) and `.svg`."""
    CHART_DIR.mkdir(parents=True, exist_ok=True)
    paths = [CHART_DIR / f"{name}.png", CHART_DIR / f"{name}.svg"]
    for path in paths:
        fig.savefig(path, dpi=DPI)
    plt.close(fig)
    return paths
