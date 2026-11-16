"""One interactive Plotly page with the main results: `assets/charts/interactive.html`.

Hover any point or bar for the exact numbers. Built from the same summary as the static
charts. Plotly is loaded from its CDN, so the page stays small.
"""

from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

from icr.assets import theme
from icr.assets.charts import WORKLOAD_LABEL, load_summary

OUT = theme.CHART_DIR / "interactive.html"
LAYOUT = dict(
    paper_bgcolor=theme.BG, plot_bgcolor=theme.BG, font=dict(family="Inter, sans-serif", color=theme.INK),
    margin=dict(l=70, r=30, t=70, b=60), hoverlabel=dict(font_family="JetBrains Mono, monospace"),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)  # fmt: skip
AXIS = dict(gridcolor=theme.LINE, zerolinecolor=theme.LINE, linecolor=theme.LINE)


def operating_points(s: dict) -> go.Figure | None:
    fig = go.Figure()
    k = 0
    for label in ("l4", "h100"):
        for c in s.get("sweep", {}).get(label, {}).get("chat", {}).get("configs", []):
            pts = [
                p
                for p in c["points"]
                if p["cost_per_m_output"] and p["itl_p95_s"] and not p["errors"]
            ]
            if not pts:
                continue
            fig.add_trace(
                go.Scatter(
                    x=[p["cost_per_m_output"] for p in pts],
                    y=[p["itl_p95_s"] * 1000 for p in pts],
                    mode="lines+markers",
                    name=f"{c['config']} ({label.upper()})",
                    line=dict(color=theme.SERIES[k % 12], width=1),
                    marker=dict(size=9, symbol=k % 12),
                    customdata=[[p["rate_rps"], p["ttft_p95_s"], p["goodput"] * 100] for p in pts],
                    hovertemplate="%{fullData.name}<br>%{customdata[0]} req/s<br>$%{x:.3f} per M output tokens"
                    "<br>ITL p95 %{y:.0f} ms<br>TTFT p95 %{customdata[1]:.2f} s"
                    "<br>within SLO %{customdata[2]:.0f}%<extra></extra>",
                )
            )
            k += 1
    if not k:
        return None
    fig.add_hline(y=100, line=dict(color=theme.BAD, dash="dash", width=1), annotation_text="SLO 100 ms",
                  annotation_font_color=theme.BAD)  # fmt: skip
    fig.update_layout(
        title="Every measured operating point: cost against inter-token latency (chat workload)",
        xaxis=dict(title="USD per million output tokens (log)", type="log", **AXIS),
        yaxis=dict(title="p95 inter-token latency, ms (log)", type="log", **AXIS),
        height=560, **LAYOUT,
    )  # fmt: skip
    return fig


def policies(s: dict, metric: str, title: str, scale: float, unit: str) -> go.Figure | None:
    fleet = s.get("fleet", {})
    if not fleet:
        return None
    workloads = [w for w in WORKLOAD_LABEL if w in fleet]
    fig = go.Figure()
    for policy, color in theme.POLICY.items():
        rows = [fleet[w]["policies"].get(policy) for w in workloads]
        if not any(rows):
            continue
        med = [r[metric]["median"] * scale if r else None for r in rows]
        fig.add_trace(
            go.Bar(
                name=policy, x=[WORKLOAD_LABEL[w].replace("\n", " ") for w in workloads], y=med,
                marker_color=color,
                error_y=dict(
                    type="data", symmetric=False, color=theme.INK, thickness=1.2,
                    array=[r[metric]["max"] * scale - m if r else 0 for r, m in zip(rows, med, strict=True)],
                    arrayminus=[m - r[metric]["min"] * scale if r else 0 for r, m in zip(rows, med, strict=True)],
                ),
                hovertemplate=f"{policy}<br>%{{x}}<br>%{{y:.3g}} {unit} (median of 3)<extra></extra>",
            )
        )  # fmt: skip
    fig.update_layout(title=title, barmode="group", xaxis=AXIS, yaxis=dict(title=unit, **AXIS),
                      height=460, **LAYOUT)  # fmt: skip
    return fig


def write():
    s = load_summary()
    figures = [
        operating_points(s),
        policies(
            s,
            "ttft_p95_s",
            "p95 time to first token by routing policy (same traffic)",
            1.0,
            "seconds",
        ),
        policies(s, "itl_p95_s", "p95 inter-token latency by routing policy", 1000.0, "ms"),
        policies(s, "cache_hit_rate", "Prompt tokens served from the prefix cache", 100.0, "%"),
        policies(s, "goodput", "Requests within the SLO", 100.0, "%"),
    ]
    blocks = [
        pio.to_html(
            fig, include_plotlyjs="cdn" if k == 0 else False, full_html=False, div_id=f"fig-{k}"
        )  # fixed id: same data, same file
        for k, fig in enumerate(f for f in figures if f is not None)
    ]
    facts = s.get("facts", {})
    head = s.get("headline", {}).get("text", "")
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Switchyard: interactive results</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600&family=JetBrains+Mono&display=swap" rel="stylesheet">
<style>body{{background:{theme.BG};color:{theme.INK};font-family:Inter,sans-serif;margin:0;padding:24px;}}
main{{max-width:1200px;margin:0 auto;}} h1{{font-size:24px;margin:0 0 6px;}} p{{color:{theme.MUTED};max-width:80ch;line-height:1.5;}}
.fig{{border:1px solid {theme.LINE};border-radius:12px;overflow:hidden;margin:18px 0;}}</style></head>
<body><main><h1>Switchyard: interactive results</h1>
<p>{head}</p>
<p>{facts.get("gpu", "")} · {facts.get("model", "")} · {facts.get("engine", "")}. Hover for exact numbers.
Bars are the median of the repeats, with the min to max range. Arrival pattern: BurstGPT trace (CC BY 4.0).</p>
{"".join(f'<div class="fig">{b}</div>' for b in blocks)}
</main></body></html>"""
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(page, encoding="utf-8", newline="\n")
    return OUT
