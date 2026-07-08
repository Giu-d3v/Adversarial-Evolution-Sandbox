"""
visualize.py — 把 game/runs/*.json 落盘的记录做成 plotly 交互 HTML 报告

四种图:
  §1 时间序列 —— avgAgg / avgCoop / good / pop 随 tick 变化（多局叠加）
  §2 阶段时间线 —— 每局一行的彩色背景块
  §3 (agg, coop) 2D 轨迹 —— 种群在性状空间的漂移路径
  §4 多局终态总结 —— 末态阶段柱状图 + (agg, coop) 散点 + 表格

用法:
  python game/visualize.py game/runs/2026-07-08_*.json       # 多局对比
  python game/visualize.py game/runs/                        # 整个目录
  python game/visualize.py game/runs/file.json --out r.html # 单局
"""

from __future__ import annotations

import argparse
import json
import sys
from html import escape
from pathlib import Path
from typing import List, Dict, Any

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
except ImportError:
    sys.stderr.write(
        "[error] plotly not installed. Run: pip install plotly\n"
    )
    sys.exit(1)


# === Color palette (synchronized with Renderer._draw_hud) ===
STAGE_COLORS = {
    "霍布斯丛林":     "#ff6e6e",
    "维度坍缩中":     "#ff6e6e",
    "濒临灭绝":       "#ff6e6e",
    "夺利丛林":       "#f0aa5a",
    "伊甸园期":       "#6edc96",
    "合作繁荣中":     "#6edc96",
    "朴素合作":       "#6edc96",
    "好善疾恶主导":   "#a0d468",
    "增长中":         "#a0d468",
    "修身主导":       "#a08fd6",
    "起始混乱":       "#888899",
    "空":             "#444450",
    "未分化":         "#cccccc",
}
DEFAULT_STAGE_COLOR = "#888888"

# 9-color qualitative palette for multi-run overlay
RUN_COLORS = [
    "#ff6e6e", "#6edc96", "#f0aa5a", "#6ec0dc", "#a08fd6",
    "#dca86e", "#6edcb5", "#dc6ed0", "#9adc6e",
]

# Trait-space center rect (未分化 zone in classification)
NEUTRAL_RECT = dict(x0=0.4, x1=0.6, y0=0.4, y1=0.6)


def _stage_color(stage: str) -> str:
    return STAGE_COLORS.get(stage, DEFAULT_STAGE_COLOR)


# === Loading ===
def load_runs(paths: List[Path]) -> List[Dict[str, Any]]:
    """Load each path as a JSON run dict. Skip files that don't parse."""
    runs = []
    for p in paths:
        if p.is_dir():
            for f in sorted(p.glob("*.json")):
                _try_load(f, runs)
        elif p.suffix.lower() == ".json":
            _try_load(p, runs)
        else:
            # glob-expanded list
            if p.exists() and p.is_file():
                _try_load(p, runs)
    return runs


def _try_load(path: Path, out: List[Dict[str, Any]]) -> None:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        data["_filename"] = path.name
        data["_label"] = f"{data['timestamp']} ({path.name[:19]})"
        out.append(data)
    except Exception as e:
        sys.stderr.write(f"[warn] skip {path}: {e}\n")


# === §1 时间序列 ===
def build_timeseries(runs: List[Dict[str, Any]]) -> go.Figure:
    """4 stacked subplots: avgAgg / avgCoop / good / pop vs tick.
    Each run is a separate trace (color-coded)."""
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        subplot_titles=("avgAgg (种群平均攻击性)",
                        "avgCoop (种群平均合作性)",
                        "good_rate (善者占比)",
                        "pop (种群数量)"),
        vertical_spacing=0.06,
    )
    metric_keys = [("agg", 1), ("coop", 2), ("good", 3), ("pop", 4)]
    for i, run in enumerate(runs):
        color = RUN_COLORS[i % len(RUN_COLORS)]
        label = run["_label"]
        history = run.get("history", [])
        if not history:
            continue
        xs = [h["tick"] for h in history]
        for key, row in metric_keys:
            ys = [h[key] for h in history]
            fig.add_trace(
                go.Scatter(
                    x=xs, y=ys, mode="lines", name=label,
                    legendgroup=label, showlegend=(row == 1),
                    line=dict(color=color, width=1.5),
                    hovertemplate=f"{key}=%{{y:.3f}}<br>tick=%{{x}}<extra>{escape(label)}</extra>",
                ),
                row=row, col=1,
            )
    fig.update_layout(
        height=700, hovermode="x unified",
        title_text="§1 时间序列 — 多局叠加",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    fig.update_yaxes(range=[0, 1], row=1, col=1)
    fig.update_yaxes(range=[0, 1], row=2, col=1)
    fig.update_yaxes(range=[0, 1], row=3, col=1)
    fig.update_xaxes(title_text="tick", row=4, col=1)
    return fig


# === §2 阶段时间线 ===
def build_stage_timeline(runs: List[Dict[str, Any]]) -> go.Figure:
    """Each run gets a horizontal lane; colored blocks for each stage segment."""
    fig = go.Figure()
    n = len(runs)
    # y-axis: run index (top = newest), each lane is height 1
    for i, run in enumerate(runs):
        y_pos = n - i  # newest on top
        transitions = run.get("stage_transitions", [])
        if not transitions:
            continue
        # extend the last transition through end-of-run
        end_tick = run.get("ticks", transitions[-1]["tick"])
        # build segments
        segments = []
        for j, tr in enumerate(transitions):
            start = tr["tick"]
            end = transitions[j + 1]["tick"] if j + 1 < len(transitions) else end_tick
            segments.append((start, end, tr["stage"]))
        # plot as one trace per segment for hover details
        for start, end, stage in segments:
            if end <= start:
                continue
            fig.add_trace(go.Bar(
                x=[end - start],
                y=[y_pos],
                base=[start],
                orientation="h",
                marker_color=_stage_color(stage),
                marker_line_width=0,
                name=stage,
                legendgroup=stage,
                showlegend=(i == 0 and stage not in {t.name for t in fig.data}),
                hovertemplate=(f"<b>{escape(run['_label'])}</b><br>"
                               f"{escape(stage)}<br>"
                               f"tick {start} → {end}<br>"
                               f"duration {end - start}<extra></extra>"),
            ))
    fig.update_layout(
        height=max(300, 60 * n + 100),
        barmode="overlay",
        title_text="§2 阶段时间线 — 每行一局，背景色块=阶段",
        xaxis=dict(title="tick", range=[0, max((r.get("ticks", 0) for r in runs), default=0) * 1.05]),
        yaxis=dict(
            title="run (最新在上)",
            tickvals=list(range(1, n + 1)),
            ticktext=[runs[n - i - 1]["_label"][:25] for i in range(n)],
            range=[0.3, n + 0.7],
        ),
        showlegend=False,
        hovermode="closest",
        margin=dict(l=200),
    )
    return fig


# === §3 (agg, coop) 2D 轨迹 ===
def build_trajectory(runs: List[Dict[str, Any]]) -> go.Figure:
    """Scatter+line plot: each tick a (avgAgg, avgCoop) point.
    Lines+markers, color-graded by time."""
    fig = go.Figure()
    # neutral zone rectangle (未分化 in classification)
    fig.add_shape(
        type="rect",
        x0=NEUTRAL_RECT["x0"], x1=NEUTRAL_RECT["x1"],
        y0=NEUTRAL_RECT["y0"], y1=NEUTRAL_RECT["y1"],
        line=dict(width=0), fillcolor="#888888", opacity=0.15,
        layer="below",
    )
    fig.add_annotation(
        x=0.5, y=0.5, text="未分化带 (0.4–0.6)",
        showarrow=False, font=dict(size=10, color="#888"),
    )
    # 4 corner labels (same as Renderer._hue_for_label)
    corner_labels = [
        (0.8, 0.2, "夺利",      "#ff6e6e"),
        (0.2, 0.8, "互助合作",   "#6ec0dc"),
        (0.8, 0.8, "好善疾恶",   "#a0d468"),
        (0.2, 0.2, "修身",       "#a08fd6"),
    ]
    for x, y, label, color in corner_labels:
        fig.add_annotation(
            x=x, y=y, text=label, showarrow=False,
            font=dict(size=11, color=color),
        )
    # trajectory lines
    for i, run in enumerate(runs):
        history = run.get("history", [])
        if not history:
            continue
        color = RUN_COLORS[i % len(RUN_COLORS)]
        xs = [h["agg"] for h in history]
        ys = [h["coop"] for h in history]
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            name=run["_label"],
            line=dict(color=color, width=2),
            marker=dict(size=4, color=color),
            hovertemplate=(f"<b>{escape(run['_label'])}</b><br>"
                           "agg=%{x:.3f}<br>coop=%{y:.3f}<extra></extra>"),
        ))
    fig.update_layout(
        height=550,
        xaxis=dict(title="avgAgg", range=[0, 1], constrain="domain"),
        yaxis=dict(title="avgCoop", range=[0, 1], scaleanchor="x", scaleratio=1),
        title_text="§3 (avgAgg, avgCoop) 2D 轨迹 — 种群在性状空间怎么漂",
        hovermode="closest",
    )
    return fig


# === §4 多局终态总结 ===
def build_summary(runs: List[Dict[str, Any]]) -> List[go.Figure]:
    """Three figures: stage distribution, (agg, coop) end-state scatter, table."""
    figs = []

    # 4a: end-stage distribution
    stage_counts: Dict[str, int] = {}
    for r in runs:
        s = r.get("final", {}).get("stage", "?")
        stage_counts[s] = stage_counts.get(s, 0) + 1
    items = sorted(stage_counts.items(), key=lambda kv: -kv[1])
    fig1 = go.Figure(go.Bar(
        x=[k for k, _ in items],
        y=[v for _, v in items],
        marker_color=[_stage_color(k) for k, _ in items],
        text=[v for _, v in items],
        textposition="outside",
    ))
    fig1.update_layout(
        height=380,
        title_text=f"§4a 末态阶段分布 ({len(runs)} 局)",
        xaxis_title="stage", yaxis_title="count",
    )
    figs.append(fig1)

    # 4b: end-state (avgAgg, avgCoop) scatter
    fig2 = go.Figure()
    # neutral rect again
    fig2.add_shape(
        type="rect",
        x0=NEUTRAL_RECT["x0"], x1=NEUTRAL_RECT["x1"],
        y0=NEUTRAL_RECT["y0"], y1=NEUTRAL_RECT["y1"],
        line=dict(width=0), fillcolor="#888888", opacity=0.15,
        layer="below",
    )
    xs = [r.get("final", {}).get("avgAgg", 0) for r in runs]
    ys = [r.get("final", {}).get("avgCoop", 0) for r in runs]
    colors = [_stage_color(r.get("final", {}).get("stage", "未分化")) for r in runs]
    labels = [r["_label"] for r in runs]
    fig2.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers",
        marker=dict(size=12, color=colors, line=dict(width=1, color="#222")),
        text=labels,
        hovertemplate="<b>%{text}</b><br>agg=%{x:.3f}<br>coop=%{y:.3f}<extra></extra>",
    ))
    fig2.update_layout(
        height=450,
        xaxis=dict(title="avgAgg (末)", range=[0, 1], constrain="domain"),
        yaxis=dict(title="avgCoop (末)", range=[0, 1], scaleanchor="x", scaleratio=1),
        title_text="§4b 末态 (avgAgg, avgCoop) — 颜色=末态阶段",
    )
    figs.append(fig2)

    # 4c: summary table as HTML
    rows_html = []
    for r in runs:
        f = r.get("final", {})
        stage = f.get("stage", "?")
        rows_html.append(
            f"<tr><td>{escape(r['_filename'])}</td>"
            f"<td>{r.get('ticks', '?')}</td>"
            f"<td>{escape(r.get('ended_reason', '?'))}</td>"
            f"<td>{f.get('pop', '?')}</td>"
            f"<td>{f.get('avgAgg', 0):.3f}</td>"
            f"<td>{f.get('avgCoop', 0):.3f}</td>"
            f"<td>{f.get('goodRate', 0):.3f}</td>"
            f"<td style='color:{_stage_color(stage)}'>{escape(stage)}</td>"
            f"<td>{f.get('maxGen', '?')}</td></tr>"
        )
    table_html = (
        "<h3>§4c 关键指标表</h3>"
        "<table style='border-collapse:collapse;width:100%;font-family:monospace;font-size:13px'>"
        "<thead><tr style='background:#222;color:#ddd'>"
        "<th>文件名</th><th>ticks</th><th>退出</th><th>pop</th>"
        "<th>avgAgg</th><th>avgCoop</th><th>good</th><th>末态阶段</th><th>maxGen</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )
    figs.append(table_html)  # type: ignore  (string passed downstream)
    return figs


# === HTML composition ===
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>对抗演化 · 涌现 · 演化报告</title>
<script src="https://cdn.plot.ly/plotly-2.35.0.min.js"></script>
<style>
  body {{
    font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #0e0e14; color: #dcdce0; margin: 0; padding: 20px;
  }}
  h1 {{ color: #fff; border-bottom: 1px solid #444; padding-bottom: 10px; }}
  h2 {{ color: #6edc96; margin-top: 40px; }}
  .meta {{ background: #181822; padding: 12px 16px; border-radius: 8px;
           font-family: monospace; font-size: 12px; line-height: 1.6; }}
  .meta b {{ color: #f0aa5a; }}
  .section {{ margin: 30px 0; }}
  table {{ margin: 16px 0; }}
  th, td {{ padding: 4px 10px; border: 1px solid #333; text-align: left; }}
  th {{ background: #2a2a35; }}
</style>
</head>
<body>
<h1>对抗演化 · 涌现 — 演化报告</h1>
<div class="meta">
  <b>报告生成：</b>{generated_at}<br>
  <b>局数：</b>{n_runs} 局<br>
  <b>局列表：</b><br>
  {run_meta}
</div>
<div class="section">
  <h2>§1 时间序列</h2>
  <div id="fig_timeseries"></div>
</div>
<div class="section">
  <h2>§2 阶段时间线</h2>
  <div id="fig_timeline"></div>
</div>
<div class="section">
  <h2>§3 (avgAgg, avgCoop) 2D 轨迹</h2>
  <div id="fig_trajectory"></div>
</div>
<div class="section">
  <h2>§4 多局终态总结</h2>
  <div id="fig_summary_dist"></div>
  <div id="fig_summary_scatter"></div>
  {summary_table}
</div>
<script>
  const figs = {fig_data};
  Plotly.newPlot('fig_timeseries', figs.timeseries.data, figs.timeseries.layout, {{displayModeBar: true}});
  Plotly.newPlot('fig_timeline', figs.timeline.data, figs.timeline.layout, {{displayModeBar: true}});
  Plotly.newPlot('fig_trajectory', figs.trajectory.data, figs.trajectory.layout, {{displayModeBar: true}});
  Plotly.newPlot('fig_summary_dist', figs.summary_dist.data, figs.summary_dist.layout, {{displayModeBar: true}});
  Plotly.newPlot('fig_summary_scatter', figs.summary_scatter.data, figs.summary_scatter.layout, {{displayModeBar: true}});
</script>
</body>
</html>
"""


def compose_html(runs: List[Dict[str, Any]]) -> str:
    fig_ts = build_timeseries(runs)
    fig_tl = build_stage_timeline(runs)
    fig_tr = build_trajectory(runs)
    summary_figs = build_summary(runs)
    fig_dist, fig_scatter, table_html = summary_figs[0], summary_figs[1], summary_figs[2]

    # serialize all figures
    fig_data = {
        "timeseries": fig_ts.to_dict(),
        "timeline": fig_tl.to_dict(),
        "trajectory": fig_tr.to_dict(),
        "summary_dist": fig_dist.to_dict(),
        "summary_scatter": fig_scatter.to_dict(),
    }

    # header metadata
    import datetime
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    meta_lines = []
    for r in runs:
        f = r.get("final", {})
        meta_lines.append(
            f"&nbsp;&nbsp;• <b>{escape(r['_filename'])}</b> — "
            f"ticks={r.get('ticks','?')} ended={escape(r.get('ended_reason','?'))} "
            f"maxGen={f.get('maxGen','?')} "
            f"末态=<span style='color:{_stage_color(f.get('stage','未分化'))}'>{escape(f.get('stage','?'))}</span>"
        )
    return HTML_TEMPLATE.format(
        generated_at=now,
        n_runs=len(runs),
        run_meta="<br>".join(meta_lines),
        summary_table=table_html,
        fig_data=json.dumps(fig_data, ensure_ascii=False),
    )


# === CLI ===
def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(description="可视化对抗演化 JSON 落盘记录")
    parser.add_argument("paths", nargs="+", help="JSON 文件 / 目录 / glob")
    parser.add_argument("--out", "-o", default=None,
                        help="输出 HTML 路径 (默认 runs/report.html)")
    args = parser.parse_args(argv)

    # expand globs
    from glob import glob
    expanded: List[Path] = []
    for p in args.paths:
        if "*" in p or "?" in p:
            for m in glob(p):
                expanded.append(Path(m))
        else:
            expanded.append(Path(p))
    runs = load_runs(expanded)
    if not runs:
        sys.stderr.write("[error] no runs loaded. Check paths.\n")
        return 1

    out_path = Path(args.out) if args.out else Path("runs/report.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    html = compose_html(runs)
    out_path.write_text(html, encoding="utf-8")
    print(f"[ok] wrote {out_path} ({len(runs)} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))