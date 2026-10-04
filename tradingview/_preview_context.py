#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `_context_ref.py` 的结果画成单文件 SVG 预览（趋势线 / 通道线 / 重要高低点 /
过充 / 破位 / 通道 MM / 背景分段带），用真实数据核对口径。

零外部依赖：只用原生 SVG，离线可开。涨红跌绿沿用中文看盘习惯。
"""
import json
import sys
from pathlib import Path

from _context_ref import CFG, KIND_NAME, zpa01_eval, DEFAULT_PATH
from _zpa_gap_ref import hhmm

W, H = 1320, 690
PAD_L, PAD_R, PAD_T, PAD_B = 62, 96, 58, 56
PLOT_W = W - PAD_L - PAD_R
PLOT_H = H - PAD_T - PAD_B

C_UP, C_DN = "#e53935", "#00897b"        # 涨红 / 跌绿
C_TL, C_CH = "#1565c0", "#6a1b9a"        # 趋势线 / 通道线
C_MAJ_L, C_MAJ_H = "#00897b", "#e53935"
C_OVER, C_BREAK, C_MM = "#ef6c00", "#c2185b", "#8e24aa"
C_AX, C_GRID, C_TXT, C_DIM = "#cfd8dc", "#eceff1", "#263238", "#90a4ae"

SEG_FILL = {
    1: "#80cbc4", 2: "#b2dfdb", 3: "#ffe082",
    4: "#ef9a9a", 5: "#b0bec5", 6: "#ce93d8",
}


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build(d):
    bars = d["bars"]
    tick = d["meta"].get("tickSize") or 0.01
    res = zpa01_eval(bars, tick)
    n = len(bars)
    hi = max(b["h"] for b in bars)
    lo = min(b["l"] for b in bars)
    span = hi - lo
    hi += span * 0.06
    lo -= span * 0.06

    sx = PLOT_W / max(1, n - 1)
    X = lambda i: PAD_L + i * sx
    Y = lambda p: PAD_T + (hi - p) / (hi - lo) * PLOT_H

    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="-apple-system,\'Segoe UI\',\'Microsoft YaHei\',sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>']

    # ── 标题 ──
    sym = d["meta"].get("symbol")
    p.append(f'<text x="{PAD_L}" y="24" font-size="14.5" font-weight="700" fill="{C_TXT}">'
             f'Zpa 01 · 市场背景划分预览 —— 趋势线 / 通道线 / 重要高低点 / 分段</text>')
    p.append(f'<text x="{PAD_L}" y="43" font-size="11.5" fill="{C_DIM}">'
             f'{esc(sym)} {esc(d["meta"].get("interval"))} · {n} 根 · '
             f'{esc(hhmm(bars[0]))}–{esc(hhmm(bars[-1]))} · tick {tick} · '
             f'取点口径：最近两个同向枢轴（最小间隔 {CFG["tlMinBars"]} 根）</text>')

    # ── 绘图区底色与网格 ──
    p.append(f'<rect x="{PAD_L}" y="{PAD_T}" width="{PLOT_W}" height="{PLOT_H}" fill="#fafbfc" '
             f'stroke="{C_AX}" stroke-width="1"/>')
    step = 10 ** round(0) if False else None
    for k in range(0, 9):
        pv = lo + (hi - lo) * k / 8
        y = Y(pv)
        p.append(f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{PAD_L+PLOT_W}" y2="{y:.1f}" '
                 f'stroke="{C_GRID}" stroke-width="1"/>')
        p.append(f'<text x="{PAD_L-6}" y="{y+3.5:.1f}" font-size="10.5" fill="{C_DIM}" '
                 f'text-anchor="end" font-family="monospace">{pv:,.2f}</text>')

    # ── ① 背景分段带（画在 K 线之下）──
    for s in res["segs"]:
        x1, x2 = X(s["start"]) - sx / 2, X(s["last"]) + sx / 2
        y1, y2 = Y(s["hi"]), Y(s["lo"])
        p.append(f'<rect x="{x1:.1f}" y="{y1:.1f}" width="{max(1.2, x2-x1):.1f}" '
                 f'height="{max(1.2, y2-y1):.1f}" fill="{SEG_FILL[s["kind"]]}" '
                 f'fill-opacity="0.34" stroke="{SEG_FILL[s["kind"]]}" stroke-width="1"/>')

    # ── ② 通道（区间填充 + 两条线）──
    # 逐根日志里同一 lineId 的连续段落 = 一次「画线实例」
    runs, cur = [], None
    for i, tl in enumerate(res["tlLog"]):
        lid = (tl["x1"], tl["x2"], tl["kind"]) if tl else None
        if cur and cur["lid"] == lid:
            cur["end"] = i
        else:
            if cur:
                runs.append(cur)
            cur = dict(lid=lid, start=i, end=i, tl=tl)
    if cur:
        runs.append(cur)

    # 只画最后 3 次画线实例：同一份数据一天里趋势线会重画十几次，
    # 全画出来就是一片对角线，反而看不出口径。最后一条实色，其余淡化。
    for idx, r in enumerate(runs[-3:]):
        tl = r["tl"]
        if tl is None:
            continue
        last = idx == len(runs[-3:]) - 1
        op = 0.95 if last else 0.22
        # 只画「实际存在」的那一段（从起点前 2 根到这次实例结束），不无限外推
        ia, ib = max(0, r["start"] - 2), min(n - 1, r["end"])
        xa, xb = X(ia), X(ib)
        ya, yb = Y(tl["y1"] + tl["slope"] * (ia - tl["x1"])), \
                 Y(tl["y1"] + tl["slope"] * (ib - tl["x1"]))
        yca = Y(tl["cy"] + tl["slope"] * (ia - tl["cx"]))
        ycb = Y(tl["cy"] + tl["slope"] * (ib - tl["cx"]))
        p.append(f'<polygon points="{xa:.1f},{ya:.1f} {xb:.1f},{yb:.1f} '
                 f'{xb:.1f},{ycb:.1f} {xa:.1f},{yca:.1f}" fill="{C_TL}" '
                 f'fill-opacity="{0.06 if last else 0.02}"/>')
        dash = "" if last else ' stroke-dasharray="7 4"'
        p.append(f'<line x1="{xa:.1f}" y1="{ya:.1f}" x2="{xb:.1f}" y2="{yb:.1f}" '
                 f'stroke="{C_TL}" stroke-width="{2.0 if last else 1.2}" '
                 f'stroke-opacity="{op}"{dash}/>')
        p.append(f'<line x1="{xa:.1f}" y1="{yca:.1f}" x2="{xb:.1f}" y2="{ycb:.1f}" '
                 f'stroke="{C_CH}" stroke-width="{1.9 if last else 1.1}" '
                 f'stroke-opacity="{op}" stroke-dasharray="9 4"/>')

    # ── ③ K 线 ──
    bw = max(2.0, sx * 0.62)
    for i, b in enumerate(bars):
        up = b["c"] >= b["o"]
        col = C_UP if up else C_DN
        x = X(i)
        p.append(f'<line x1="{x:.1f}" y1="{Y(b["h"]):.1f}" x2="{x:.1f}" y2="{Y(b["l"]):.1f}" '
                 f'stroke="{col}" stroke-width="1"/>')
        yo, yc = Y(b["o"]), Y(b["c"])
        y, hh = min(yo, yc), max(1.0, abs(yc - yo))
        p.append(f'<rect x="{x-bw/2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{hh:.1f}" '
                 f'fill="{col}" stroke="{col}" stroke-width="0.7"/>')

    # ── ④ 重要高低点 ──
    # 标签一律放到绘图区**左缘**：重要位几乎都诞生在最近 30 根内，
    # 挂在起点右侧会全挤在图的最右边。左缘 + 错行既能看清又不打架。
    # ⚠ 高点标签向上错行、低点标签向下错行，两者**各自计数**时会撞：实测
    #   「重要高点 26743.95」与「重要低点 26749.77」只差 5.8 点 ≈ 6px，
    #   而字号 10.5 —— 向上 5px 与向下 12px 落点只隔 10.7px，两行文字贴在一起。
    #   改成**统一登记已占用的行位**，新标签沿自身方向退让到最近的空行。
    LAB_GAP = 13.0
    lo_lim, hi_lim = PAD_T + 12, PAD_T + PLOT_H - 4
    placed = []
    for m in res["majors"]:
        col = C_MAJ_L if m["side"] == "low" else C_MAJ_H
        y = Y(m["level"])
        x1 = X(m["bar"])
        p.append(f'<line x1="{x1:.1f}" y1="{y:.1f}" x2="{PAD_L+PLOT_W}" y2="{y:.1f}" '
                 f'stroke="{col}" stroke-width="1.5" opacity="0.85"/>')
        yl, step = (y + 12, 12.0) if m["side"] == "low" else (y - 5, -12.0)
        for _ in range(24):
            yl = min(hi_lim, max(lo_lim, yl))
            if all(abs(yl - q) >= LAB_GAP for q in placed):
                break
            yl += step
        placed.append(yl)
        st = "已被破" if m["brokenAt"] is not None else "未破"
        txt = f'{"重要低点" if m["side"]=="low" else "重要高点"} {m["level"]:.2f}（{st}）'
        p.append(f'<text x="{PAD_L+8}" y="{yl:.1f}" font-size="10.5" fill="{col}" '
                 f'font-weight="700">{txt}</text>')
        p.append(f'<circle cx="{x1:.1f}" cy="{y:.1f}" r="3.4" fill="{col}"/>')

    # ── ⑤ 过充 / 破位 / 通道 MM ──
    for e in res["overshoots"]:
        x = X(e["start"])
        y = Y(e["level"])
        p.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5.6" fill="none" stroke="{C_OVER}" '
                 f'stroke-width="2"/>')
        p.append(f'<text x="{x:.1f}" y="{y-9:.1f}" font-size="10" fill="{C_OVER}" '
                 f'text-anchor="middle" font-weight="700">过充'
                 f'{"·收盘站上" if e["closeBeyond"] else ""}</text>')

    for k, e in enumerate(res["breaks"]):
        x, y = X(e["at"]), Y(e["level"])
        p.append(f'<path d="M {x-6:.1f} {y-6:.1f} L {x+6:.1f} {y+6:.1f} '
                 f'M {x+6:.1f} {y-6:.1f} L {x-6:.1f} {y+6:.1f}" '
                 f'stroke="{C_BREAK}" stroke-width="2.2"/>')
        p.append(f'<text x="{x:.1f}" y="{y+19:.1f}" font-size="10" fill="{C_BREAK}" '
                 f'text-anchor="middle" font-weight="700">趋势线破位</text>')
        ym = Y(e["mm"])
        p.append(f'<line x1="{x:.1f}" y1="{ym:.1f}" x2="{PAD_L+PLOT_W}" y2="{ym:.1f}" '
                 f'stroke="{C_MM}" stroke-width="1.4" stroke-dasharray="6 4"/>')
        # 标签贴着破位点放（放到右端会和其它 MM 标签挤在一起）
        p.append(f'<text x="{x+6:.1f}" y="{ym + (13 if e["mm"] < e["level"] else -5):.1f}" '
                 f'font-size="10" fill="{C_MM}" font-weight="600">'
                 f'通道MM一倍 {e["mm"]:.2f}</text>')

    # ── ⑥ 段标签（错开两行，避免相邻段标签叠在一起）──
    for k, s in enumerate(res["segs"]):
        x = X(s["start"]) + 2
        y = Y(s["hi"]) - (4 if k % 2 == 0 else 16)
        p.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="9.4" fill="#37474f" '
                 f'font-weight="700" opacity="0.85">{esc(KIND_NAME[s["kind"]])}</text>')

    # ── ⑦ 时间轴 ──
    for i in range(0, n, 24):
        x = X(i)
        p.append(f'<line x1="{x:.1f}" y1="{PAD_T+PLOT_H}" x2="{x:.1f}" y2="{PAD_T+PLOT_H+5}" '
                 f'stroke="{C_AX}"/>')
        p.append(f'<text x="{x:.1f}" y="{PAD_T+PLOT_H+19}" font-size="10.5" fill="{C_DIM}" '
                 f'text-anchor="middle" font-family="monospace">{esc(hhmm(bars[i]))}</text>')

    # ── ⑧ 图例 ──
    lg = [("趋势线", C_TL, "solid"), ("通道线", C_CH, "9 4"), ("重要低点", C_MAJ_L, "solid"),
          ("重要高点", C_MAJ_H, "solid"), ("通道过充", C_OVER, "solid"),
          ("趋势线破位", C_BREAK, "solid"), ("通道MM一倍", C_MM, "6 4")]
    lx = PAD_L
    ly = H - 12
    for name, col, dash in lg:
        p.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+22}" y2="{ly}" stroke="{col}" '
                 f'stroke-width="2.2"' + (f' stroke-dasharray="{dash}"' if dash != "solid" else "") + '/>')
        p.append(f'<text x="{lx+27}" y="{ly+3.6}" font-size="10.5" fill="#546e7a">{name}</text>')
        lx += 27 + len(name) * 11.5 + 16

    p.append("</svg>")
    return "\n".join(p)


def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
    d = json.loads(path.read_text(encoding="utf-8"))
    svg = build(d)
    out = Path(__file__).with_name("背景划分预览.html")
    out.write_text(
        "<!doctype html><meta charset='utf-8'>"
        "<title>Zpa 01 背景划分预览</title>"
        "<style>html,body{margin:0;padding:14px;background:#fff}"
        "svg{display:block;margin:0 auto;max-width:100%;height:auto}"
        ".tip{max-width:1320px;margin:10px auto 0;font:12.5px/1.7 -apple-system,"
        "'Segoe UI','Microsoft YaHei',sans-serif;color:#546e7a}"
        "b{color:#263238}</style>" + svg +
        "<div class='tip'>"
        "<b>怎么核对：</b>灰色系半透明色块 = 背景分段（颜色越暖越偏震荡）；"
        "蓝色实线 = 趋势线、紫色虚线 = 与它平行的通道线（两者之间就是通道）；"
        "虚横线 = 重要高/低点（体系：「大反转的前提是重要低点必须被跌破」）；"
        "橙色圆圈 = 通道线过充（引线冲出通道线）；"
        "洋红叉 + 紫虚线 = 趋势线破位与由它得出的「通道 MM 一倍」目标。"
        "历史画线实例做了淡化处理，只保留最后一次为实色。<br>"
        "<b>注意：</b>脚本只标位置、不产生信号 —— 体系明确要求「等价格对趋势线和通道线"
        "测试之后出现反应才能进场，不能盲目预判」。本图为工程近似，不构成投资建议。"
        "</div>", encoding="utf-8")
    print(f"[ok] {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
