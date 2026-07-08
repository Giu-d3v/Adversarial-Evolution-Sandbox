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
from datetime import datetime
from glob import glob
from html import escape
from pathlib import Path
from typing import List, Dict, Any, Tuple

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


def downsample_history(history: List[Dict[str, Any]], n: int) -> List[Dict[str, Any]]:
    """Uniform-stride downsample to ~n points, keeping first AND last.
    Returns the original list if shorter than 2n (no benefit)."""
    if n <= 0 or len(history) <= 2 * n:
        return history
    stride = len(history) / n
    out = []
    for i in range(n):
        out.append(history[int(i * stride)])
    # ensure last point is the actual last
    if out[-1] is not history[-1]:
        out.append(history[-1])
    return out


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
def build_timeseries(runs: List[Dict[str, Any]], downsample: int = 0) -> go.Figure:
    """4 stacked subplots: avgAgg / avgCoop / good / pop vs tick.
    Each run is a separate trace (color-coded). If downsample > 0, each run's
    history is reduced to ~N points (strided, first+last preserved)."""
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        subplot_titles=("avgAgg (种群平均攻击性)",
                        "avgCoop (种群平均合作性)",
                        "good_rate (善者占比)",
                        "pop (种群数量)"),
        vertical_spacing=0.06,
    )
    metric_keys = [("agg", 1), ("coop", 2), ("good", 3), ("pop", 4)]
    # good subplot (row 3) also gets a dashed coopOnly line so 善者 vs 合作者对比可见
    for i, run in enumerate(runs):
        color = RUN_COLORS[i % len(RUN_COLORS)]
        label = run["_label"]
        history = downsample_history(run.get("history", []), downsample) if downsample else run.get("history", [])
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
        # coopOnly overlay on the good subplot (dashed, half-width)
        if any("coopOnly" in h for h in history):
            ys_co = [h.get("coopOnly", 0) for h in history]
            fig.add_trace(
                go.Scatter(
                    x=xs, y=ys_co, mode="lines", name=f"{label} (合作者率)",
                    legendgroup=label, showlegend=False,
                    line=dict(color=color, width=1, dash="dot"),
                    hovertemplate=f"coopOnly=%{{y:.3f}}<br>tick=%{{x}}<extra>{escape(label)}</extra>",
                ),
                row=3, col=1,
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
    """Each run gets a horizontal lane with one Bar trace containing all segments
    (each segment is a separate bar inside the trace with its own color).
    Trace count == run count (NOT segment count) — much faster for many runs.
    """
    fig = go.Figure()
    n = len(runs)
    max_ticks = 0
    for i, run in enumerate(runs):
        y_pos = n - i  # newest on top
        transitions = run.get("stage_transitions", [])
        if not transitions:
            continue
        end_tick = run.get("ticks", transitions[-1]["tick"])
        max_ticks = max(max_ticks, end_tick)
        # collect per-segment arrays
        starts, durations, colors, stages = [], [], [], []
        for j, tr in enumerate(transitions):
            start = tr["tick"]
            end = transitions[j + 1]["tick"] if j + 1 < len(transitions) else end_tick
            if end <= start:
                continue
            starts.append(start)
            durations.append(end - start)
            colors.append(_stage_color(tr["stage"]))
            stages.append(tr["stage"])
        if not starts:
            continue
        # ONE trace per run, multiple bars inside (same y_pos, different x/color)
        fig.add_trace(go.Bar(
            x=durations,
            y=[y_pos] * len(starts),
            base=starts,
            orientation="h",
            marker_color=colors,
            marker_line_width=0,
            name=run["_label"],
            legendgroup=run["_label"],
            showlegend=False,
            customdata=stages,  # for hover
            hovertemplate=(f"<b>{escape(run['_label'])}</b><br>"
                           "stage: %{customdata}<br>"
                           "tick: %{base} → %{x:+d}<extra></extra>"),
        ))
    fig.update_layout(
        height=max(300, 60 * n + 100),
        barmode="overlay",
        title_text="§2 阶段时间线 — 每行一局，背景色块=阶段",
        xaxis=dict(title="tick",
                   range=[0, max_ticks * 1.05 if max_ticks else 1]),
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
def build_trajectory(runs: List[Dict[str, Any]], downsample: int = 0,
                     stage_by_tick: Dict[str, List[str]] | None = None) -> go.Figure:
    """Scatter+line plot: each tick a (avgAgg, avgCoop) point.
    Lines+markers, color-graded by time. If downsample > 0, history is
    strided to ~N points. stage_by_tick (optional) maps run-label -> per-tick
    stage label, used in hover."""
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
        history = downsample_history(run.get("history", []), downsample) if downsample else run.get("history", [])
        if not history:
            continue
        color = RUN_COLORS[i % len(RUN_COLORS)]
        xs = [h["agg"] for h in history]
        ys = [h["coop"] for h in history]
        custom = [str(h["tick"]) for h in history]
        stages = None
        if stage_by_tick and run["_label"] in stage_by_tick:
            stages = stage_by_tick[run["_label"]]
        customdata = list(zip(custom, stages)) if stages else custom
        extra = "agg=%{x:.3f}<br>coop=%{y:.3f}<br>tick=%{customdata[0]}<br>stage=%{customdata[1]}<extra></extra>" if stages \
                else "agg=%{x:.3f}<br>coop=%{y:.3f}<extra></extra>"
        fig.add_trace(go.Scatter(
            x=xs, y=ys, mode="lines+markers",
            name=run["_label"],
            line=dict(color=color, width=2),
            marker=dict(size=4, color=color),
            customdata=customdata,
            hovertemplate=(f"<b>{escape(run['_label'])}</b><br>" + extra),
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
def build_summary(runs: List[Dict[str, Any]]) -> Tuple[go.Figure, go.Figure, str]:
    """Returns (stage_dist_fig, endstate_scatter_fig, table_html).

    Three parts: bar chart of end-stage distribution, scatter of (avgAgg, avgCoop)
    end states colored by stage, and a per-run summary table as raw HTML.
    """
    # 4a: end-stage distribution
    stage_counts: Dict[str, int] = {}
    for r in runs:
        s = r.get("final", {}).get("stage", "?")
        stage_counts[s] = stage_counts.get(s, 0) + 1
    items = sorted(stage_counts.items(), key=lambda kv: -kv[1])
    fig_dist = go.Figure(go.Bar(
        x=[k for k, _ in items],
        y=[v for _, v in items],
        marker_color=[_stage_color(k) for k, _ in items],
        text=[v for _, v in items],
        textposition="outside",
    ))
    fig_dist.update_layout(
        height=380,
        title_text=f"§4a 末态阶段分布 ({len(runs)} 局)",
        xaxis_title="stage", yaxis_title="count",
    )

    # 4b: end-state (avgAgg, avgCoop) scatter
    fig_scatter = go.Figure()
    fig_scatter.add_shape(
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
    fig_scatter.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers",
        marker=dict(size=12, color=colors, line=dict(width=1, color="#222")),
        text=labels,
        hovertemplate="<b>%{text}</b><br>agg=%{x:.3f}<br>coop=%{y:.3f}<extra></extra>",
    ))
    fig_scatter.update_layout(
        height=450,
        xaxis=dict(title="avgAgg (末)", range=[0, 1], constrain="domain"),
        yaxis=dict(title="avgCoop (末)", range=[0, 1], scaleanchor="x", scaleratio=1),
        title_text="§4b 末态 (avgAgg, avgCoop) — 颜色=末态阶段",
    )

    # 4c: summary table as raw HTML
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
            f"<td>{f.get('coopOnlyRate', 0):.3f}</td>"
            f"<td style='color:{_stage_color(stage)}'>{escape(stage)}</td>"
            f"<td>{f.get('maxGen', '?')}</td></tr>"
        )
    table_html = (
        "<h3>§4c 关键指标表</h3>"
        "<table style='border-collapse:collapse;width:100%;font-family:monospace;font-size:13px'>"
        "<thead><tr style='background:#222;color:#ddd'>"
        "<th>文件名</th><th>ticks</th><th>退出</th><th>pop</th>"
        "<th>avgAgg</th><th>avgCoop</th><th>good</th><th>合作者</th><th>末态阶段</th><th>maxGen</th>"
        "</tr></thead><tbody>" + "".join(rows_html) + "</tbody></table>"
    )
    return fig_dist, fig_scatter, table_html


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


def build_stage_by_tick(run: Dict[str, Any]) -> List[str]:
    """For each tick in run['history'], return the stage that was active.
    Same length as history."""
    history = run.get("history", [])
    transitions = run.get("stage_transitions", [])
    if not history or not transitions:
        return ["?"] * len(history)
    # build (tick, stage) sorted list of transitions
    segs = []
    end_tick = run.get("ticks", transitions[-1]["tick"])
    for j, tr in enumerate(transitions):
        end = transitions[j + 1]["tick"] if j + 1 < len(transitions) else end_tick
        segs.append((tr["tick"], end, tr["stage"]))
    out = []
    si = 0
    for h in history:
        t = h["tick"]
        # advance si until seg covers t
        while si < len(segs) and segs[si][1] <= t:
            si += 1
        out.append(segs[si][2] if si < len(segs) else "?")
    return out


def compose_html(runs: List[Dict[str, Any]], downsample: int = 0) -> str:
    fig_ts = build_timeseries(runs, downsample=downsample)
    fig_tl = build_stage_timeline(runs)
    # compute stage-by-tick map for §3 hover (only needed if not downsampled)
    stage_by_tick = {r["_label"]: build_stage_by_tick(r) for r in runs}
    fig_tr = build_trajectory(runs, downsample=downsample, stage_by_tick=stage_by_tick)
    fig_dist, fig_scatter, table_html = build_summary(runs)

    fig_data = {
        "timeseries": fig_ts.to_dict(),
        "timeline": fig_tl.to_dict(),
        "trajectory": fig_tr.to_dict(),
        "summary_dist": fig_dist.to_dict(),
        "summary_scatter": fig_scatter.to_dict(),
    }

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
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
    parser.add_argument("--last", type=int, default=0,
                        help="只保留最近 N 局 (按 timestamp 排序)")
    parser.add_argument("--stage", type=str, default=None,
                        help="只保留末态阶段包含此子串的局 (如 '霍布斯', '未分化')")
    parser.add_argument("--seed", type=int, default=None,
                        help="只保留某 seed 的局 (通过 ended_reason 或路径含 seed 判定)")
    parser.add_argument("--sort", choices=["time", "pop", "agg", "coop", "good", "ticks"],
                        default="time",
                        help="排序方式 (默认 time)")
    parser.add_argument("--downsample", type=int, default=0,
                        help="每条时间序列保留 ~N 个点 (0=不抽样, 推荐 200 控制 HTML 大小)")
    args = parser.parse_args(argv)

    # expand globs
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

    # filter by stage
    if args.stage:
        before = len(runs)
        runs = [r for r in runs
                if args.stage in r.get("final", {}).get("stage", "")]
        sys.stderr.write(f"[filter] --stage '{args.stage}': {before} -> {len(runs)} runs\n")

    # filter by seed (look for seed=N in filename or ended_reason)
    if args.seed is not None:
        before = len(runs)
        target = f"seed={args.seed}"
        runs = [r for r in runs
                if target in r.get("_filename", "")
                or target in r.get("ended_reason", "")]
        sys.stderr.write(f"[filter] --seed {args.seed}: {before} -> {len(runs)} runs\n")

    # sort
    if args.sort == "time":
        runs.sort(key=lambda r: r.get("timestamp", ""))
    elif args.sort == "pop":
        runs.sort(key=lambda r: r.get("final", {}).get("pop", 0), reverse=True)
    elif args.sort == "agg":
        runs.sort(key=lambda r: r.get("final", {}).get("avgAgg", 0), reverse=True)
    elif args.sort == "coop":
        runs.sort(key=lambda r: r.get("final", {}).get("avgCoop", 0), reverse=True)
    elif args.sort == "good":
        runs.sort(key=lambda r: r.get("final", {}).get("goodRate", 0), reverse=True)
    elif args.sort == "ticks":
        runs.sort(key=lambda r: r.get("ticks", 0), reverse=True)

    # keep only last N
    if args.last and args.last > 0 and len(runs) > args.last:
        sys.stderr.write(f"[filter] --last {args.last}: keep latest {args.last} of {len(runs)}\n")
        runs = runs[-args.last:]

    if not runs:
        sys.stderr.write("[error] no runs after filtering.\n")
        return 1

    out_path = Path(args.out) if args.out else Path("runs/report.html")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if args.downsample > 0:
        sys.stderr.write(f"[downsample] ~{args.downsample} points per series\n")
    html = compose_html(runs, downsample=args.downsample)
    out_path.write_text(html, encoding="utf-8")
    print(f"[ok] wrote {out_path} ({len(runs)} runs)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))