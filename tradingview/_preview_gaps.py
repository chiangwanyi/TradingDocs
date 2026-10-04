#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用真实盘面数据渲染「体系口径缺口」的预览图（单文件 HTML，原生 SVG，零依赖）。

用途：在把指标粘进 TradingView 之前，先在这张图上确认缺口口径对不对 ——
每个缺口位应该正好落在一根「被反向实体突破的 K 线极值」上。
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _zpa_gap_ref import zpa_gaps, micro_gaps, hhmm  # noqa: E402

SRC = r"E:/Data/projects/zpa/reports/MNQ-5m-2026-09-25.facts.json"
OUT = Path(__file__).parent / "缺口预览.html"

W, H = 1180, 560
PAD_L, PAD_R, PAD_T, PAD_B = 62, 96, 26, 34


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def main():
    d = json.loads(Path(SRC).read_text(encoding="utf-8"))
    bars = d["bars"]
    tick = d["meta"]["tickSize"]
    gaps = zpa_gaps(bars, tick)
    micros = micro_gaps(bars, tick)

    lo = min(b["l"] for b in bars)
    hi = max(b["h"] for b in bars)
    span = hi - lo or 1
    lo -= span * 0.05
    hi += span * 0.05
    span = hi - lo

    pw = W - PAD_L - PAD_R
    ph = H - PAD_T - PAD_B
    n = len(bars)
    bw = max(1.6, pw / n * 0.62)

    def X(i):
        return PAD_L + (i + 0.5) * pw / n

    def Y(p):
        return PAD_T + (hi - p) / span * ph

    p = []
    p.append(f'<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet">')
    p.append(f'<rect x="0" y="0" width="{W}" height="{H}" fill="#fbfcfd"/>')

    # 网格 + 价格刻度
    for k in range(6):
        yy = PAD_T + ph * k / 5
        val = hi - span * k / 5
        p.append(f'<line x1="{PAD_L}" y1="{yy:.1f}" x2="{PAD_L+pw}" y2="{yy:.1f}" stroke="#e8ebef" stroke-width="1"/>')
        p.append(f'<text x="{PAD_L-8}" y="{yy+4:.1f}" font-size="11" fill="#8a939d" text-anchor="end" font-family="monospace">{val:.1f}</text>')

    # 微缺口（最底层，淡色带）
    for mg in micros:
        x1 = X(max(0, mg["i"] - 1))
        x2 = X(min(n - 1, mg["i"] + 1))
        col = "#26a69a" if mg["dir"] == "up" else "#ef5350"
        p.append(f'<rect x="{x1:.1f}" y="{Y(mg["hi"]):.1f}" width="{max(1.5,x2-x1):.1f}" '
                 f'height="{max(1.0,Y(mg["lo"])-Y(mg["hi"])):.1f}" fill="{col}" fill-opacity="0.16"/>')

    # K 线
    for i, b in enumerate(bars):
        x = X(i)
        up = b["c"] >= b["o"]
        col = "#d94a45" if up else "#1f9d55"          # 中国习惯：涨红跌绿
        p.append(f'<line x1="{x:.1f}" y1="{Y(b["h"]):.1f}" x2="{x:.1f}" y2="{Y(b["l"]):.1f}" stroke="{col}" stroke-width="1"/>')
        top, bot = max(b["o"], b["c"]), min(b["o"], b["c"])
        hgt = max(1.0, Y(bot) - Y(top))
        p.append(f'<rect x="{x-bw/2:.1f}" y="{Y(top):.1f}" width="{bw:.1f}" height="{hgt:.1f}" fill="{col}"/>')

    # 缺口位横线
    for g in gaps:
        y = Y(g["level"])
        up = g["dir"] == "up"
        col = "#26a69a" if up else "#ef5350"
        if g["filled"]:
            # 已回补：短灰虚线，向右多画一点（真实回补往往就在下 1~2 根，否则看不见）
            x2 = X(min(n - 1, g["i"] + 10))
            p.append(f'<line x1="{X(g["i"]):.1f}" y1="{y:.1f}" x2="{x2:.1f}" y2="{y:.1f}" '
                     f'stroke="#c3cad2" stroke-width="1" stroke-dasharray="3 3"/>')
        else:
            p.append(f'<line x1="{X(g["brokenBar"]):.1f}" y1="{y:.1f}" x2="{PAD_L+pw:.1f}" y2="{y:.1f}" '
                     f'stroke="{col}" stroke-width="2"/>')
            # 被突破 K 的极值（缺口位的来源）
            p.append(f'<circle cx="{X(g["brokenBar"]):.1f}" cy="{y:.1f}" r="3.6" fill="none" '
                     f'stroke="{col}" stroke-width="1.6"/>')
            # 触发 K：反向实体收盘价越过该极值的那一根
            bx = X(g["i"])
            by = Y(bars[g["i"]]["c"])
            p.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="2.8" fill="{col}"/>')
            p.append(f'<line x1="{X(g["brokenBar"]):.1f}" y1="{y:.1f}" x2="{bx:.1f}" y2="{by:.1f}" '
                     f'stroke="{col}" stroke-width="1" stroke-dasharray="2 3" stroke-opacity="0.65"/>')
            p.append(f'<text x="{PAD_L+pw+6}" y="{y+4:.1f}" font-size="11" fill="{col}" '
                     f'font-family="monospace">{g["level"]:.2f}</text>')

    # 时间轴
    for i in range(0, n, 24):
        t = hhmm(bars[i])
        p.append(f'<text x="{X(i):.1f}" y="{H-12}" font-size="10.5" fill="#8a939d" text-anchor="middle" font-family="monospace">{t}</text>')

    p.append('</svg>')

    # ── 清单 ──
    zg_open = [g for g in gaps if not g["filled"]]
    rows = []
    for g in zg_open:
        rows.append(
            f'<tr><td>{esc(g["hhmm"])}</td><td>{"▲ 向上" if g["dir"]=="up" else "▼ 向下"}</td>'
            f'<td class="num">{g["level"]:.2f}</td><td class="num">{g["depth"]:.2f}</td>'
            f'<td>{esc(g["brokenHHMM"])}</td></tr>')
    if not rows:
        rows.append('<tr><td colspan="5">无</td></tr>')

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Zpa 缺口口径预览 · MNQ 5m</title>
<style>
  :root{{--bg:#f6f7f9;--card:#fff;--line:#e3e6ea;--text:#1c2024;--dim:#5b6470;--up:#d94a45;--dn:#1f9d55;}}
  *{{box-sizing:border-box}}
  body{{margin:0;background:var(--bg);color:var(--text);
    font:14px/1.65 -apple-system,"Segoe UI","Microsoft YaHei",system-ui,sans-serif}}
  .wrap{{max-width:1240px;margin:0 auto;padding:28px 22px 56px}}
  h1{{font-size:21px;margin:0 0 4px}}
  .sub{{color:var(--dim);font-size:13px;margin:0 0 18px}}
  .card{{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px;margin-bottom:16px}}
  .chart{{padding:6px 6px 0}}
  .legend{{display:flex;gap:22px;flex-wrap:wrap;font-size:12.5px;color:var(--dim);padding:6px 8px 10px}}
  .legend i{{display:inline-block;width:22px;height:3px;vertical-align:middle;margin-right:6px;border-radius:2px}}
  table{{width:100%;border-collapse:collapse;font-size:13px}}
  th,td{{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left}}
  th{{background:#f0f2f5;color:#3c454f;font-weight:600;font-size:12.5px}}
  td.num{{font-family:"Cascadia Mono",Consolas,monospace}}
  .warn{{background:#fff;border:1px solid var(--line);border-left:4px solid #d93025;border-radius:8px;
    padding:12px 16px;font-size:13.5px;margin-bottom:16px}}
  .note{{background:#fff;border:1px solid var(--line);border-left:4px solid #d9822b;border-radius:8px;
    padding:12px 16px;font-size:13.5px;margin-bottom:16px}}
  code{{background:#eef2f7;padding:1px 5px;border-radius:3px;font-family:"Cascadia Mono",Consolas,monospace;font-size:12.5px}}
  ul{{margin:6px 0 0;padding-left:20px}}
  li{{margin:3px 0}}
</style></head><body><div class="wrap">
<h1>Zpa 突破型缺口 · 口径预览</h1>
<p class="sub">MNQ 5 分钟 · {n} 根 K 线 · 数据源 <code>reports/MNQ-5m-2026-09-25.facts.json</code>
　涨<span style="color:var(--up)">■</span> 跌<span style="color:var(--dn)">■</span>（中国习惯）</p>

<div class="card chart">
  {''.join(p)}
  <div class="legend">
    <span><i style="background:#ef5350"></i>未回补 · 向下缺口位（阳线最低价）</span>
    <span><i style="background:#26a69a"></i>未回补 · 向上缺口位（阴线最高价）</span>
    <span><i style="background:#c3cad2"></i>已回补（虚线）</span>
    <span><i style="background:#26a69a;opacity:.3"></i>微缺口（隔一根）</span>
    <span>○ 被突破 K 的极值　● 触发 K（实体越过它的那根）</span>
  </div>
</div>

<div class="warn">
  <b>怎么看这张图对不对</b>
  <ul>
    <li>每个<b>空心圆</b>是「被突破 K 的极值」—— 向下缺口落在<b>阳线的最低点</b>，向上缺口落在<b>阴线的最高点</b>；<b>实心点</b>是「触发 K」，即收盘价越过该极值的那根反向实体 K 线，虚线连的是两者的关系。</li>
    <li><b>关键</b>：空心圆与实心点<b>不必相邻</b>。这正是你举的例子 —— B1 阳线、B2 阴线、B3 阴线，B2 没跌破 B1 的最低价、B3 跌破了，缺口位仍然是 <b>B1 的最低价</b>。</li>
    <li>看图中例子：<code>04:35</code> 那条向下缺口位 <code>26783.72</code>，来源是它前面最近的阳线低点；价格一路走低，再没回到该位 → 保持敞开。</li>
  </ul>
</div>

<div class="card">
  <b>未回补缺口（{len(zg_open)} 条）</b>
  <table>
    <thead><tr><th>触发时间</th><th>方向</th><th>缺口位</th><th>破位深度</th><th>被突破 K</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>

<div class="note">
  <b>统计</b>：共检出 <b>{len(gaps)}</b> 条缺口位，其中未回补 <b>{len(zg_open)}</b> 条；
  隔一根的微缺口 <b>{len(micros)}</b> 条。<br>
  口径：<code>向下缺口位 = 被阴线实体跌破的那根阳线的最低价</code>；
  <code>向上缺口位 = 被阳线实体突破的那根阴线的最高价</code>；参考 K 线取<b>往前最近的一根反向实体 K 线</b>；引线触及即算回补。
  <br><span style="color:var(--dim)">这是按该体系的分析推演做的口径预览，不构成投资建议。</span>
</div>
</div></body></html>
"""
    OUT.write_text(html, encoding="utf-8")
    print(f"已生成 {OUT}")
    print(f"  缺口 {len(gaps)} 条 / 未回补 {len(zg_open)} 条 / 微缺口 {len(micros)} 条")


if __name__ == "__main__":
    main()
