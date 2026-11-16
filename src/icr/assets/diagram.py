"""Architecture diagram in the Switchyard palette, written as SVG with hand-placed boxes.

`write()` saves `assets/diagrams/architecture.svg`. The PNG next to it is rendered from
the SVG by the screenshot step (`icr.assets.shots`), so both always match.
"""

from __future__ import annotations

from icr import config
from icr.assets.theme import BG, INK, LINE, MUTED, PANEL, ROSE

OUT = config.ROOT / "assets" / "diagrams" / "architecture.svg"
W, H = 1600, 760
MONO = "JetBrains Mono, Consolas, monospace"
ROSE_FILL = "#1A1420"


def _box(x, y, w, h, title, sub=(), stroke=LINE, fill=PANEL, title_color=INK) -> str:
    """A rounded box with a title and up to two muted lines under it."""
    ty = y + h / 2 - 9 * len(sub) + 5
    out = [
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="12" fill="{fill}" stroke="{stroke}" '
        'stroke-width="1.6"/>',
        f'<text x="{x + w / 2}" y="{ty}" text-anchor="middle" fill="{title_color}" font-size="17" '
        f'font-weight="600">{title}</text>',
    ]
    for k, line in enumerate(sub):
        out.append(
            f'<text x="{x + w / 2}" y="{ty + 20 + 17 * k}" text-anchor="middle" fill="{MUTED}" '
            f'font-size="13">{line}</text>'
        )
    return "".join(out)


def _label(x, y, text, anchor="middle") -> str:
    return (
        f'<text x="{x}" y="{y}" text-anchor="{anchor}" fill="{MUTED}" font-size="12.5" '
        f'font-family="{MONO}">{text}</text>'
    )


def _arrow(points, color=MUTED, both=False) -> str:
    d = "M" + " L".join(f"{x},{y}" for x, y in points)
    marker = "arrow-rose" if color == ROSE else "arrow"
    start = f' marker-start="url(#{marker})"' if both else ""
    return (
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.8" '
        f'marker-end="url(#{marker})"{start}/>'
    )


def _marker(name: str, color: str) -> str:
    return (
        f'<marker id="{name}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" '
        f'fill="{color}"/></marker>'
    )


def svg() -> str:
    n = config.FLEET_REPLICAS
    # Replica boxes are 96 tall with a 36 gap, centered in the space four of them fill.
    first = 140 + (492 - (n * 96 + (n - 1) * 36)) / 2
    ys = [round(first + i * 132) for i in range(n)]
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
        'font-family="Inter, Segoe UI, Arial, sans-serif" role="img" '
        'aria-label="Switchyard architecture: workload and trace feed an open-loop load generator, '
        "a Go router picks one of the vLLM replicas, a recorder saves every request, and the "
        'results feed the optimizer and the control room site">',
        "<defs>" + _marker("arrow", MUTED) + _marker("arrow-rose", ROSE) + "</defs>",
        f'<rect width="{W}" height="{H}" fill="{BG}"/>',
        f'<text x="40" y="50" fill="{INK}" font-size="24" font-weight="700">Switchyard</text>',
        f'<text x="190" y="50" fill="{MUTED}" font-size="16">how a request flows, and where every '
        "number comes from</text>",
        # The container boundary.
        f'<rect x="300" y="80" width="940" height="640" rx="18" fill="#0E1420" stroke="{LINE}" '
        'stroke-width="1.6" stroke-dasharray="7 6"/>',
        f'<text x="322" y="110" fill="{MUTED}" font-size="14" font-weight="600">ONE MODAL '
        f"CONTAINER  ·  {n} x NVIDIA L4  ·  localhost only, nothing exposed</text>",
        # Inputs.
        _box(40, 160, 210, 96, "Workload generator", ("seeded prompts with", "shared prefixes")),
        _box(40, 310, 210, 96, "BurstGPT trace", ("real arrival times,", "rescaled (CC BY 4.0)")),
        _arrow([(250, 208), (295, 208), (295, 260), (338, 260)]),
        _arrow([(250, 358), (295, 358), (295, 310), (338, 310)]),
        f'<text x="40" y="478" fill="{MUTED}" font-size="13">Development and tests use a</text>',
        f'<text x="40" y="496" fill="{MUTED}" font-size="13">local mock fleet with the same</text>',
        f'<text x="40" y="514" fill="{MUTED}" font-size="13">API. It never produces</text>',
        f'<text x="40" y="532" fill="{MUTED}" font-size="13">published numbers.</text>',
        # Inside the container.
        _box(
            340,
            230,
            200,
            110,
            "Load generator",
            ("open loop: sends at the", "scheduled time, always"),
        ),
        _box(
            610,
            230,
            200,
            110,
            "Router (Go)",
            ("round-robin · least-loaded", "prefix-aware"),
            ROSE,
            ROSE_FILL,
            ROSE,
        ),  # fmt: skip
        _box(340, 510, 200, 110, "Recorder", ("per-request timings,", "/metrics every 250 ms")),
        _box(
            610, 510, 200, 110, "Autoscaler", ("starts and stops replicas", "from load and KV use")
        ),
        _arrow([(542, 285), (608, 285)], ROSE, both=True),
        _label(575, 196, "requests out, streamed tokens back"),
    ]
    for i, y in enumerate(ys):
        parts.append(
            _box(950, y, 260, 96, f"vLLM replica {i}", (f"GPU {i} · Qwen2.5-7B · prefix cache",))
        )
        parts.append(
            _arrow([(812, 285), (880, 285), (880, y + 40), (948, y + 40)], ROSE, both=i == 0)
        )
    parts += [
        _arrow([(440, 342), (440, 508)]),
        _label(450, 430, "timings, decisions", "start"),
        _arrow([(542, 565), (608, 565)]),
        _label(575, 553, "load"),
        _arrow([(710, 508), (710, 342)]),
        _label(720, 430, "live replicas", "start"),
        _arrow([(812, 600), (880, 600), (880, ys[-1] + 70), (948, ys[-1] + 70)]),
        _label(820, 622, "start / stop", "start"),
        _arrow([(1080, ys[-1] + 98), (1080, 668), (500, 668), (500, 622)]),
        _label(790, 660, "/metrics every 250 ms"),
        _arrow([(400, 622), (400, 700), (1265, 700), (1265, 208), (1288, 208)]),
        _label(835, 692, "run files"),
        # Outputs.
        _box(
            1290,
            160,
            280,
            96,
            "Run files",
            ("results/runs/&lt;id&gt;/", "requests · replicas · meta"),
        ),
        _box(
            1290,
            340,
            280,
            96,
            "icr results",
            ("metrics · Pareto frontier", "cheapest config for an SLO"),
        ),
        _box(
            1290,
            520,
            280,
            110,
            "Control room site",
            ("replays the real runs,", "request by request"),
            ROSE,
            ROSE_FILL,
            ROSE,
        ),  # fmt: skip
        _arrow([(1430, 258), (1430, 338)]),
        _label(1442, 302, "saved runs", "start"),
        _arrow([(1430, 438), (1430, 518)]),
        _label(1442, 482, "summary + replay", "start"),
        "</svg>",
    ]
    return "\n".join(parts)


def write():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(svg(), encoding="utf-8", newline="\n")
    return OUT
