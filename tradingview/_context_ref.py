#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zpa 市场背景（Zpa-01）—— 体系口径参考实现。

本文件是 `Zpa-01-市场背景.pine` 的**逐行 Python 复刻**，负责两件事：

  1. 把「背景定性」的全部量化证据（六条 + 通道）算出来，供人复核；
  2. 把「背景划分」落地：趋势线 / 通道线 / 重要高低点 / 通道过充 / 趋势线破位 /
     通道 MM 一倍目标 / 分段价格带。

⚠ 它是 Zpa-01 口径的**唯一 Python 来源**：`_verify_logic.py` 的 [2] 段也调它，
  不要再各写一份（历史上两处各写一份，其中一份漂成了错误的键，把 55 条折成 45 条）。

───────────────────────── 口径来源（逐字稿考据） ─────────────────────────

【怎么画】
  · videos/蒋老师/PA不是形态学市场周期最重要【识别重要高低点】.txt L43-44
      「趋势线/通道线怎么画：顺着走势，发现有一个通道就画出来；
        发现更高高点或更低低点，连接即可。」
  · docs/蒋老师/通道转区间.md §三
      「通道由两个点画出第三个点；通道被强势跌破，可能代表区间的形成。」

【重要高低点】
  · 同上一份逐字稿 L186-197
      「我们很清楚的知道这个重要低点在这儿……你想要形成大反转，那么重要低点就得破」
      「这是一个问题，就（是）强势突破前面的低点就是重要低点」
      同段 L199-211：「按常规我们从突破开始数，现在重要低点可能是第二推的重要低点，
        然后最后一涨是第三推」；「你要他弱势很弱的一个突破……强突破是这儿或者说这儿」
    → 重要低点 = **最强的那一段推进的起点**，不是随便一个波段低点。

【怎么用】
  · videos/Z说交易/价格行为系列之如何找到有效的支撑阻力位.txt L859-865
      「关键是看趋势，趋势线非常的多，主要我们需要等待价格对这个趋势线和通道线
        进行测试之后出现反应，我们才能去进场，不能去盲目地预判那个支撑阻力会生效。」
    → 趋势线本身**不是入场信号**，只是「待测位置」。脚本只标位置，不产生信号。
  · Z说交易-概念库/04-趋势恢复与反转逻辑.md §4.1（MTR 的两个条件）
      「① 跌破趋势线；② 制造出 EMA20 均线缺口 K 线」
    → 「趋势线破位」是反转链路的第一步证据。
  · docs/蒋老师/大背景下市场周期演变.md §五
      「通道过靶大概率五根 K 线内反转」
    → 本文件会实测这条概率（体系说的是「大概率」）。
  · docs/蒋老师/通道转区间.md §六
      「测量区间的目标时，不要拉整个区间的一倍……正确做法：拉『区间形成段』的一倍。」
    → 通道被跌破后，MM 目标 = 破位价 ± 通道自身高度（一倍）。

【背景划分】
  · Z说交易-概念库/01-市场背景与二元决策.md §2 市场周期分级
      趋势：突破（Breakout）/ 窄通道（强趋势）/ 宽通道（弱趋势）；震荡：震荡区间
  · docs/蒋老师/大背景下市场周期演变.md §三-四
      「不要拿『大区间』当『区间』做……以当前的市场周期（当前这一段）为标准去做单」
      「区间段 vs 趋势段」—— 本文件的「分段」就是替人把这一段段切出来。

⚠ 免责：量化口径是工程近似，只标位置不做信号，结论需人工确认，不构成投资建议。
"""
import json
import sys
from pathlib import Path

# 复用同一份助手 / 缺口状态机。模块名两种布局都兼容：
#   项目内 `_zpa_gap_ref.py` ／ 技能 `scripts/zpa_gap_ref.py`
try:
    from _zpa_gap_ref import EPS, hhmm, pine_equivalent  # noqa: E402
except ImportError:                                       # pragma: no cover
    from zpa_gap_ref import EPS, hhmm, pine_equivalent    # noqa: E402

DEFAULT_PATH = r"E:/Data/projects/zpa/reports/MNQ-5m-2026-09-25.facts.json"

# 段类型码 —— 必须与 Pine 里的 kindCode 一一对应
KIND_SPIKE = 1     # 突破 / 急速（Spike）
KIND_TIGHT = 2     # 窄通道（强趋势）
KIND_BROAD = 3     # 宽通道（弱趋势 · 阶梯模式）
KIND_RANGE = 4     # 震荡区间（Trading Range）
KIND_TTR = 5       # 窄幅震荡 TTR
KIND_EXPAND = 6    # 扩张三角形（本质是震荡）

KIND_NAME = {
    KIND_SPIKE: "突破/急速", KIND_TIGHT: "窄通道", KIND_BROAD: "宽通道",
    KIND_RANGE: "震荡区间", KIND_TTR: "窄幅震荡TTR", KIND_EXPAND: "扩张三角",
}

CFG = dict(
    pvK=3,          # 枢轴左右宽度（证据一与趋势线共用）
    structN=4,      # 证据一评估所用波段数
    keepPiv=24,     # 趋势线保留的枢轴条数
    tlMinBars=8,    # 趋势线两个取点的最小间隔
    tlTolAtr=0.15,  # 「有效跌破趋势线」的容差（ATR 倍数）
    mjLook=80,      # 重要高低点回扫根数
    mjMinLen=5,     # 「强突破段」最少几根（挡掉「当根就是极值」的退化情形）
    mjMinAtr=1.5,   # 强突破段的最小幅度（ATR 倍数）
    mjMinGap=10,    # 重要位之间至少隔多少根才另记
    keepMajor=4,
    keepBreak=3,
    segConfirm=3,   # 段切换需要连续几根同向确认（防抖动）
    segMinBars=8,   # 一个段至少活这么多根，才允许切走（防碎片）
    keepSeg=12,
    chopLen=20, deepPct=0.62, longBars=20,
    bodyFull=0.55, oppRunMx=3, dojiBody=0.30,
    narrowAtr=2.5,  # 通道高度 < 该 ATR 倍数 → 记「窄通道」
    gapLook=100, fastBars=2,
)

# 趋势分权重：唯一来源。Pine 的 `input.float(...)` 默认值、本文件的 score、
# `_verify_logic.py` 打印的分量表都从这里取值 —— 三处各写一遍必然会分叉。
W = dict(s1=0.20, s2=0.20, s3=0.14, s4=0.12, s5=0.09, s6=0.07, s7=0.08, s8=0.10)


# ══════════════════════════ 基础量（对齐 Pine 的 ta.*）══════════════════════════

def _tr(bars):
    out = []
    for i, b in enumerate(bars):
        out.append(b["h"] - b["l"] if i == 0 else
                   max(b["h"] - b["l"], abs(b["h"] - bars[i - 1]["c"]), abs(b["l"] - bars[i - 1]["c"])))
    return out


def _rma(vals, length):
    """Pine ta.rma —— 前 length 个用 SMA 播种，之后 alpha = 1/length。"""
    out = [None] * len(vals)
    if len(vals) < length:
        return out
    prev = sum(vals[:length]) / length
    out[length - 1] = prev
    for i in range(length, len(vals)):
        prev = (prev * (length - 1) + vals[i]) / length
        out[i] = prev
    return out


def _ema(vals, length):
    """Pine ta.ema —— 前 length 个用 SMA 播种，之后 alpha = 2/(length+1)。"""
    out = [None] * len(vals)
    if len(vals) < length:
        return out
    prev = sum(vals[:length]) / length
    out[length - 1] = prev
    a = 2.0 / (length + 1)
    for i in range(length, len(vals)):
        prev = a * vals[i] + (1 - a) * prev
        out[i] = prev
    return out


def atr_series(bars, length=14):
    return _rma(_tr(bars), length)


def ema_series(bars, length=20):
    return _ema([b["c"] for b in bars], length)


def highestbars(vals, length):
    """Pine ta.highestbars：窗口内最大值相对当前 bar 的偏移，为负或 0；同值取**最近**的。"""
    win = vals[-length:]
    mx = max(win)
    return max(-(len(win) - 1 - i) for i, v in enumerate(win) if v == mx)


def lowestbars(vals, length):
    win = vals[-length:]
    mn = min(win)
    return max(-(len(win) - 1 - i) for i, v in enumerate(win) if v == mn)


def asc_ratio(seq):
    if len(seq) < 2:
        return 0.0
    return sum(1 for i in range(1, len(seq)) if seq[i] > seq[i - 1]) / (len(seq) - 1)


# ══════════════════ 枢轴（手工数，与 Pine 逐字一致）══════════════════
#
# ⚠ 不用 ta.pivothigh/ta.pivotlow：它们对「平台期」（相邻等高的极值）取哪一根没写死，
#   而 Python 与 Pine 必须给出**完全一样**的枢轴，否则趋势线会在两边分叉。
#   自己数：左侧允许相等、右侧必须严格更小 → 确定性地取平台期最左边那根。
#   注意「右侧」是未来数据，所以枢轴只能在 bar(i + pvK) 才被确认，并回填它的真实序号。

def confirm_pivot(bars, i, k):
    piv = i - k
    if piv < k:                      # 左侧不足 k 根
        return None
    ch, cl = bars[piv]["h"], bars[piv]["l"]
    is_ph = (all(bars[piv + j]["h"] <= ch for j in range(1, k + 1))
             and all(bars[piv - j]["h"] < ch for j in range(1, k + 1)))
    is_pl = (all(bars[piv + j]["l"] >= cl for j in range(1, k + 1))
             and all(bars[piv - j]["l"] > cl for j in range(1, k + 1)))
    if is_ph:
        return ("high", piv, ch)
    if is_pl:
        return ("low", piv, cl)
    return None


def pick_trend_pair(bar_ary, val_ary, higher, min_bars):
    """在枢轴序列里找「最近的两个同向枢轴」，返回 (x1, y1, x2, y2) 或 None。

    higher=True  → 要求后面的点更高（上涨趋势线：更高的低点）
    higher=False → 要求后面的点更低（下跌趋势线：更低的高点）

    搜索顺序：i 从最新往回、j 从 i-1 往回 → 优先取「第二个点最新」的一对。
    与 Pine 里的双重 for 完全同构（Pine 用 break + 标志位，不用 continue）。
    """
    n = len(bar_ary)
    for i in range(n - 1, 0, -1):
        for j in range(i - 1, -1, -1):
            if bar_ary[i] - bar_ary[j] < min_bars:
                continue
            if (val_ary[i] > val_ary[j] + EPS) if higher else (val_ary[i] < val_ary[j] - EPS):
                return (bar_ary[j], val_ary[j], bar_ary[i], val_ary[i])
    return None


# ══════════════════ 逐根推进：Zpa-01 的完整口径复刻 ══════════════════

def zpa01_eval(bars, tick, cfg=None):
    c = dict(CFG)
    c.update(cfg or {})
    n = len(bars)
    atr = atr_series(bars, 14)
    ema = ema_series(bars, 20)
    closes = [b["c"] for b in bars]
    highs = [b["h"] for b in bars]
    lows = [b["l"] for b in bars]

    # ── 输出序列（与 Pine 的逐根量一一对应）──
    S = dict(atr=atr, ema20=ema, hiRise=[0.0] * n, loRise=[0.0] * n, struct=[0.0] * n,
             expanding=[False] * n, dir=[0] * n, pull=[0.0] * n, pullBar=[0] * n,
             avgOvl=[0.0] * n, dojiPct=[0.0] * n, bodyQ=[0.5] * n, oppMax=[0] * n,
             s1=[0.0] * n, s2=[0.0] * n, s3=[0.0] * n, s4=[0.0] * n, s5=[0.0] * n,
             s6=[0.0] * n, s7=[0.0] * n, s8=[0.5] * n, score=[0.0] * n,
             phase=[""] * n, kind=[KIND_RANGE] * n,
             openGaps=[0] * n, recentGaps=[0] * n, recentFake=[0] * n,
             tlWidthAtr=[None] * n, tlDistAtr=[None] * n, tlAlive=[False] * n,
             tlBroken=[False] * n, tlOvershot=[False] * n)

    # ── 证据一：波段结构（最近 structN 个枢轴）──
    hi_ary, lo_ary = [], []
    # ── 趋势线：枢轴表（带序号）──
    pl_bar, pl_val, ph_bar, ph_val = [], [], [], []

    # ── 趋势线 / 通道的跨根状态（换线时全部重置）──
    tl_state = dict(lineId=None, broken=False, brokenAt=None,
                    overRun=False, overStart=None, overKind=None,
                    overLevel=None, overCloseBeyond=False, overCount=0)

    events = dict(breaks=[], overshoots=[], majors=[], segs=[], tlLog=[])

    # ── 缺口（证据二）的跨根状态（与 Zpa-02 同一套规则）──
    g_open_lv, g_open_dir = [], []
    g_hist = []                      # 绘图/历史表：dict(level,dir,filled,born,fillBar)
    g_last_bull_low = g_last_bull_bar = None
    g_last_bear_high = g_last_bear_bar = None

    cur_seg = None
    pend_kind, pend_cnt = None, 0

    for i in range(n):
        cur = bars[i]
        o, h, l, cl = cur["o"], cur["h"], cur["l"], cur["c"]
        a = atr[i]
        e20 = ema[i]
        rng = h - l
        body = abs(cl - o)

        # ───── A. 确认枢轴 ─────
        pv = confirm_pivot(bars, i, c["pvK"])
        if pv:
            kind, pidx, pval = pv
            if kind == "high":
                ph_bar.append(pidx); ph_val.append(pval)
                while len(ph_bar) > c["keepPiv"]:
                    ph_bar.pop(0); ph_val.pop(0)
                hi_ary.append(pval)
                while len(hi_ary) > c["structN"]:
                    hi_ary.pop(0)
            else:
                pl_bar.append(pidx); pl_val.append(pval)
                while len(pl_bar) > c["keepPiv"]:
                    pl_bar.pop(0); pl_val.pop(0)
                lo_ary.append(pval)
                while len(lo_ary) > c["structN"]:
                    lo_ary.pop(0)

        # ───── B. 证据一：结构分 ─────
        hi_rise, lo_rise = asc_ratio(hi_ary), asc_ratio(lo_ary)
        ready = len(hi_ary) >= 2 and len(lo_ary) >= 2
        struct_score = (hi_rise + lo_rise) - 1.0 if ready else 0.0
        expanding = ready and hi_rise >= 0.66 and lo_rise <= 0.34

        # ───── C. 方向（先结构、后 EMA 兜底；必须在通道模块之前）────
        e20_5 = ema[i - 5] if i >= 5 else None
        if e20 is None or e20_5 is None:
            slope = 0.0
        else:
            slope = e20 - e20_5
        dirn = 0
        if e20 is not None:
            if slope > 0 and cl > e20:
                dirn = 1
            elif slope < 0 and cl < e20:
                dirn = -1
        if struct_score > 0.20:
            dirn = 1
        elif struct_score < -0.20:
            dirn = -1

        # ───── D. 趋势线 / 通道线 ─────
        up_pair = pick_trend_pair(pl_bar, pl_val, True, c["tlMinBars"])
        dn_pair = pick_trend_pair(ph_bar, ph_val, False, c["tlMinBars"])
        if dirn > 0:
            pair, tl_kind = up_pair, "up"
        elif dirn < 0:
            pair, tl_kind = dn_pair, "down"
        elif up_pair and dn_pair:
            (pair, tl_kind) = (up_pair, "up") if up_pair[2] >= dn_pair[2] else (dn_pair, "down")
        else:
            pair, tl_kind = (up_pair, "up") if up_pair else (dn_pair, "down")

        tl = None
        if pair and a is not None:
            x1, y1, x2, y2 = pair
            sl = (y2 - y1) / (x2 - x1)
            line_id = (x1, x2, tl_kind)
            st = tl_state
            if line_id != st["lineId"]:      # 换线 → 全部状态重置（未收尾的过充先归档）
                if st["overRun"]:
                    events["overshoots"].append(dict(
                        start=st["overStart"], end=None, kind=st["overKind"],
                        bars=i - st["overStart"], level=st["overLevel"],
                        closeBeyond=st["overCloseBeyond"], backIn5=None,
                        lineId=st["lineId"]))
                st.update(lineId=line_id, broken=False, brokenAt=None,
                          overRun=False, overStart=None, overKind=None,
                          overLevel=None, overCloseBeyond=False)
            # 通道线：过 [x1, x2] 内与趋势线相对的那个极值作平行线
            if tl_kind == "up":
                cx = max(range(x1, x2 + 1), key=lambda t: highs[t]); cy = highs[cx]
            else:
                cx = min(range(x1, x2 + 1), key=lambda t: lows[t]); cy = lows[cx]
            ch_w = abs((cy - sl * cx) - (y1 - sl * x1))      # 通道垂直高度（常量）
            tl_now = y1 + sl * (i - x1)
            ch_now = cy + sl * (i - cx)
            tol = c["tlTolAtr"] * a

            if not st["broken"] and i > x2:
                if tl_kind == "up" and cl < tl_now - tol:
                    st["broken"], st["brokenAt"] = True, i
                elif tl_kind == "down" and cl > tl_now + tol:
                    st["broken"], st["brokenAt"] = True, i
                if st["broken"] and ch_w > 0:
                    mm = cl - ch_w if tl_kind == "up" else cl + ch_w
                    events["breaks"].append(dict(i=i, at=i, kind=tl_kind, level=cl,
                                                 chW=ch_w, mm=mm, x1=x1, y1=y1, x2=x2, y2=y2,
                                                 reached=None))
                if len(events["breaks"]) > c["keepBreak"]:
                    events["breaks"].pop(0)

            # ── 通道线过充（体系：「通道线我们经常用来判断一段趋势是不是过充了、
            #    是不是高潮了」；「过充向下突破，失败之后回到通道之内」）──
            # 记成**事件**：从引线冲出通道线那根起，到重新回到通道内那根止。
            # 同时区分两种结局：① 只有引线冲出、收盘没站上（真过充 → 该回落）
            #                    ② 收盘也站上（不是过充，是通道被上破/重估）
            hit_over = (h > ch_now) if tl_kind == "up" else (l < ch_now)
            close_beyond = (cl > ch_now) if tl_kind == "up" else (cl < ch_now)
            if hit_over:
                if not st["overRun"]:
                    st.update(overRun=True, overStart=i, overKind=tl_kind,
                              overLevel=ch_now, overCloseBeyond=False)
                if close_beyond:
                    st["overCloseBeyond"] = True
            elif st["overRun"]:
                events["overshoots"].append(dict(
                    start=st["overStart"], end=i, kind=st["overKind"],
                    bars=i - st["overStart"], level=st["overLevel"],
                    closeBeyond=st["overCloseBeyond"],
                    backIn5=(i - st["overStart"]) <= 5, lineId=line_id))
                st.update(overRun=False, overStart=None, overCloseBeyond=False)

            tl = dict(kind=tl_kind, x1=x1, y1=y1, x2=x2, y2=y2, slope=sl, cx=cx, cy=cy,
                      chW=ch_w, now=tl_now, chNow=ch_now, broken=st["broken"],
                      brokenAt=st["brokenAt"], overRun=st["overRun"],
                      overStart=st["overStart"], overCount=st["overCount"],
                      tol=tol,
                      chWAtr=(ch_w / a) if a else None,
                      distAtr=((cl - tl_now) / a) if a else None,
                      alive=(i <= x2 or not st["broken"]))

        # 破位后的 MM 一倍目标是否已到达
        for bk in events["breaks"]:
            if bk["reached"] is None and i > bk["at"]:
                if bk["kind"] == "up" and h <= bk["mm"]:
                    bk["reached"] = i
                elif bk["kind"] == "down" and l >= bk["mm"]:
                    bk["reached"] = i

        # ───── E. 重要高低点：最陡的那一段推进的起点 ─────
        # 「强势突破前面的低点就是重要低点」→ 取「单位时间位移最大」的那一段，
        # 它的起点就是重要高/低点。mjMinLen 用来挡掉「当根就是极值」这种退化情形
        # （否则 h-l 一根的位移除以 1 会赢过任何长腿）。
        best_up = best_dn = None          # (斜率, 总位移, 价位, 序号)
        run_hi = run_lo = None
        for b in range(0, min(c["mjLook"], i + 1)):
            t = i - b
            run_hi = highs[t] if run_hi is None else max(run_hi, highs[t])
            run_lo = lows[t] if run_lo is None else min(run_lo, lows[t])
            if b < c["mjMinLen"]:
                continue
            up_gain, dn_gain = run_hi - lows[t], highs[t] - run_lo
            if best_up is None or up_gain / (b + 1) > best_up[0]:
                best_up = (up_gain / (b + 1), up_gain, lows[t], t)
            if best_dn is None or dn_gain / (b + 1) > best_dn[0]:
                best_dn = (dn_gain / (b + 1), dn_gain, highs[t], t)
        if a is not None:
            if best_up and best_up[1] >= c["mjMinAtr"] * a:
                _record_major(events["majors"], "low", best_up[2], best_up[3], i, c)
            if best_dn and best_dn[1] >= c["mjMinAtr"] * a:
                _record_major(events["majors"], "high", best_dn[2], best_dn[3], i, c)
        # 重要位是否被跌破/升破（「大反转的前提：重要低点必须被破」）
        for m in events["majors"]:
            if m["brokenAt"] is None and i > m["born"]:
                if m["side"] == "low" and cl < m["level"] - EPS:
                    m["brokenAt"] = i
                elif m["side"] == "high" and cl > m["level"] + EPS:
                    m["brokenAt"] = i

        # ───── F. 证据二：缺口 ─────
        for j in range(len(g_open_lv) - 1, -1, -1):
            lv, dd = g_open_lv[j], g_open_dir[j]
            if (dd > 0 and l <= lv) or (dd < 0 and h >= lv):
                g_open_lv.pop(j); g_open_dir.pop(j)
                for k in range(len(g_hist) - 1, -1, -1):     # 同步改写绘图/历史表
                    if (not g_hist[k]["filled"] and g_hist[k]["dir"] == dd
                            and abs(g_hist[k]["level"] - lv) < tick):
                        g_hist[k]["filled"], g_hist[k]["fillBar"] = True, i
                        break
        is_bull, is_bear = cl > o + EPS, cl < o - EPS

        def _dup(direction, level):
            return any(dd == direction and abs(lv - level) < tick
                       for lv, dd in zip(g_open_lv, g_open_dir))

        if is_bear and g_last_bull_low is not None and cl < g_last_bull_low - tick \
                and not _dup(-1, g_last_bull_low):
            g_open_lv.append(g_last_bull_low); g_open_dir.append(-1)
            g_hist.append(dict(level=g_last_bull_low, dir=-1, filled=False,
                               born=i, fillBar=-1))
        if is_bull and g_last_bear_high is not None and cl > g_last_bear_high + tick \
                and not _dup(1, g_last_bear_high):
            g_open_lv.append(g_last_bear_high); g_open_dir.append(1)
            g_hist.append(dict(level=g_last_bear_high, dir=1, filled=False,
                               born=i, fillBar=-1))
        if is_bull:
            g_last_bull_low, g_last_bull_bar = l, i
        if is_bear:
            g_last_bear_high, g_last_bear_bar = h, i

        # ───── G. 证据三：回调深度与时长 ─────
        win_hi = max(highs[max(0, i - c["chopLen"] + 1):i + 1])
        win_lo = min(lows[max(0, i - c["chopLen"] + 1):i + 1])
        bh = highestbars(highs[:i + 1], c["chopLen"])
        bl = lowestbars(lows[:i + 1], c["chopLen"])
        leg = win_hi - win_lo
        pull, pull_bar = 0.0, 0
        if leg > 0:
            if bl < bh:
                pull, pull_bar = (win_hi - cl) / leg, -bh
            else:
                pull, pull_bar = (cl - win_lo) / leg, -bl

        # ───── H. 证据四/五：重叠、十字星、顺势实体、逆势连续 ─────
        ovl_sum = ovl_cnt = doji = 0
        for k in range(1, c["chopLen"] + 1):
            if i - k < 0:
                break
            a1, a0 = bars[i - k], bars[i - k + 1]
            uni = max(a1["h"], a0["h"]) - min(a1["l"], a0["l"])
            if uni > 0:
                inter = min(a1["h"], a0["h"]) - max(a1["l"], a0["l"])
                ovl_sum += max(0.0, min(1.0, inter / uni)); ovl_cnt += 1
        for k in range(0, c["chopLen"]):
            if i - k < 0:
                break
            b0 = bars[i - k]
            r0 = b0["h"] - b0["l"]
            if r0 > 0 and abs(b0["c"] - b0["o"]) / r0 < c["dojiBody"]:
                doji += 1
        avg_ovl = ovl_sum / ovl_cnt if ovl_cnt else 0.0
        doji_pct = doji / c["chopLen"]

        good = with_cnt = opp_cur = opp_max = 0
        for k in range(c["chopLen"] - 1, -1, -1):
            if i - k < 0:
                continue
            b0 = bars[i - k]
            up = b0["c"] > b0["o"]
            r0 = b0["h"] - b0["l"]
            if dirn == 0:
                opp_cur = 0
            elif up if dirn > 0 else (not up):
                with_cnt += 1
                if r0 > 0 and abs(b0["c"] - b0["o"]) / r0 >= c["bodyFull"]:
                    good += 1
                opp_cur = 0
            else:
                opp_cur += 1; opp_max = max(opp_max, opp_cur)
        body_q = good / with_cnt if with_cnt else 0.5

        # ───── I. 评分 ─────
        open_gaps = len(g_open_lv)
        recent = [g for g in g_hist if i - g["born"] <= c["gapLook"]]
        recent_gaps = len(recent)
        recent_filled = sum(1 for g in recent if g["filled"])
        recent_fake = sum(1 for g in recent if g["filled"]
                          and g["fillBar"] - g["born"] <= c["fastBars"])
        if open_gaps > 0:
            s2 = 1.00
        elif recent_gaps == 0:
            s2 = 0.25
        elif recent_filled > 0 and recent_fake == recent_filled:
            s2 = 0.15
        else:
            s2 = 0.40

        s1 = min(1.0, abs(struct_score))
        s3 = 1.0 - min(1.0, pull / c["deepPct"])
        s4 = 1.0 - min(1.0, avg_ovl / 0.80)
        s5 = body_q
        s6 = 1.0 if opp_max < c["oppRunMx"] else 0.0
        s7 = 0.0 if pull_bar > c["longBars"] else 1.0
        # s8 通道质量：趋势线完好且价格在正确一侧 → 1；已破位 → 0；无趋势线 → 中性
        if tl is None:
            s8 = 0.5
        elif tl["broken"]:
            s8 = 0.0
        elif tl["kind"] == "up" and cl >= tl["now"]:
            s8 = 1.0
        elif tl["kind"] == "down" and cl <= tl["now"]:
            s8 = 1.0
        else:
            s8 = 0.3

        score = (W["s1"] * s1 + W["s2"] * s2 + W["s3"] * s3 + W["s4"] * s4
                 + W["s5"] * s5 + W["s6"] * s6 + W["s7"] * s7 + W["s8"] * s8)

        # ───── J. 周期分级 ─────
        narrow = tl is not None and tl["chWAtr"] is not None and tl["chWAtr"] < c["narrowAtr"]
        if expanding:
            phase = "扩张三角形（本质是震荡）"
        elif score >= 0.72:
            phase = "窄通道（强趋势）" if (avg_ovl >= 0.22 or narrow) else "突破 / 急速（Spike）"
        elif score >= 0.55:
            phase = "宽通道（弱趋势 · 阶梯模式）"
        elif avg_ovl > 0.70 and leg < 6 * a:
            phase = "窄幅震荡 TTR（几乎不操作）"
        else:
            phase = "震荡区间"

        # ───── K. 分段 ─────
        # 段切换要过两道闸：① 连续 segConfirm 根同向；② 旧段已活够 segMinBars 根。
        # 只过第一道的话，20 根窗口的评分每抖一次就切一段（实测 198 根切出 20 段）。
        # 切段时把新段起点回退到「确认窗口的第一根」，旧段结束于它前一根 → 无缝首尾相接。
        kid = _kind_of(phase)
        seg_age = i - cur_seg["start"] if cur_seg else 0
        if cur_seg is None:
            cur_seg = dict(kind=kid, start=i, hi=h, lo=l, last=i)
            events["segs"].append(cur_seg)
        elif kid != cur_seg["kind"]:
            if kid == pend_kind:
                pend_cnt += 1
            else:
                pend_kind, pend_cnt = kid, 1
            if pend_cnt >= c["segConfirm"] and seg_age >= c["segMinBars"]:
                start = i - c["segConfirm"] + 1
                cur_seg["last"] = start - 1
                cur_seg = dict(kind=kid, start=start,
                               hi=max(highs[start:i + 1]), lo=min(lows[start:i + 1]), last=i)
                events["segs"].append(cur_seg)
                pend_cnt = 0
        cur_seg["hi"] = max(cur_seg["hi"], h)
        cur_seg["lo"] = min(cur_seg["lo"], l)
        cur_seg["last"] = i

        # ───── 记录序列 ─────
        for kk, vv in dict(hiRise=hi_rise, loRise=lo_rise, struct=struct_score,
                           expanding=expanding, dir=dirn, pull=pull, pullBar=pull_bar,
                           avgOvl=avg_ovl, dojiPct=doji_pct, bodyQ=body_q, oppMax=opp_max,
                           s1=s1, s2=s2, s3=s3, s4=s4, s5=s5, s6=s6, s7=s7, s8=s8,
                           score=score, phase=phase, kind=kid, openGaps=open_gaps,
                           recentGaps=recent_gaps, recentFake=recent_fake).items():
            S[kk][i] = vv
        S["tlWidthAtr"][i] = tl["chWAtr"] if tl else None
        S["tlDistAtr"][i] = tl["distAtr"] if tl else None
        S["tlAlive"][i] = bool(tl and tl["alive"])
        S["tlBroken"][i] = bool(tl and tl["broken"])
        S["tlOvershot"][i] = bool(tl and tl["overRun"])
        events["tlLog"].append(tl)

    events["series"] = S
    events["bars"] = bars
    events["atr"] = atr
    events["ema"] = ema
    events["gapHist"] = g_hist
    events["gapOpen"] = list(zip(g_open_lv, g_open_dir))
    return events


def _record_major(majors, side, level, bar, cur_i, c):
    """重要高低点只在出现「不同的起点」时才另记（避免每根抖动）。

    同侧、且**尚未被跌破/升破**的旧记录会被新的取代 —— 决定盘面的永远是
    「最近那一段强突破的起点」，旧那些一旦被破就已经失去意义。
    已被破的记录留着当历史（它证明了那次反转成立）。
    """
    for m in majors:
        if m["side"] == side and m["bar"] == bar:
            return
    if majors and majors[-1]["side"] == side and abs(bar - majors[-1]["bar"]) < c["mjMinGap"]:
        return
    majors[:] = [m for m in majors if not (m["side"] == side and m["brokenAt"] is None)]
    majors.append(dict(side=side, level=level, bar=bar, born=cur_i, brokenAt=None))
    while len(majors) > c["keepMajor"]:
        majors.pop(0)


def _kind_of(phase):
    """把分级文本映射成段类型码（Pine 的 kindCode 同构）。"""
    if phase.startswith("扩张"):
        return KIND_EXPAND
    if phase.startswith("突破"):
        return KIND_SPIKE
    if phase.startswith("窄通道") or phase.startswith("窄幅"):
        return KIND_TTR if phase.startswith("窄幅") else KIND_TIGHT
    if phase.startswith("宽通道"):
        return KIND_BROAD
    return KIND_RANGE


# ══════════════════════════ 结构性不变量检查 ══════════════════════════

def check_invariants(bars, res):
    """不判「对不对」，只查自相矛盾的硬伤。任何一条非空都要回去改算法。"""
    P = []
    segs = res["segs"]

    prev_end = None
    for s in segs:
        if prev_end is not None and s["start"] != prev_end + 1:
            P.append(f"分段不连续：段起点 {s['start']}，上一段结束 {prev_end}")
        prev_end = s["last"]
    if segs and (segs[0]["start"] != 0 or segs[-1]["last"] != len(bars) - 1):
        P.append(f"分段未覆盖全区间：{segs[0]['start']} .. {segs[-1]['last']}")

    for ev in res["breaks"]:
        x1, y1, x2, y2 = ev["x1"], ev["y1"], ev["x2"], ev["y2"]
        k = (y2 - y1) / (x2 - x1)
        if ev["kind"] == "up" and k <= 0:
            P.append(f"上涨趋势线斜率为非正 @bar {x1}->{x2}")
        if ev["kind"] == "down" and k >= 0:
            P.append(f"下跌趋势线斜率为非负 @bar {x1}->{x2}")
        if ev["chW"] <= 0:
            P.append(f"通道高度非正 @bar {ev['i']}")
        v = y1 + k * (ev["i"] - x1)
        c = bars[ev["i"]]["c"]
        if ev["kind"] == "up" and not (c < v):
            P.append(f"标了向下跌破，但收盘 {c} 不低于趋势线 {v:.2f} @bar {ev['i']}")
        if ev["kind"] == "down" and not (c > v):
            P.append(f"标了向上升破，但收盘 {c} 不高于趋势线 {v:.2f} @bar {ev['i']}")

    for m in res["majors"]:
        tail = bars[m["bar"]:]
        if not tail:
            continue
        if m["side"] == "low" and m["level"] >= max(b["h"] for b in tail):
            P.append(f"重要低点 {m['level']:.2f} 并不低于其后最高点 @bar {m['bar']}")
        if m["side"] == "high" and m["level"] <= min(b["l"] for b in tail):
            P.append(f"重要高点 {m['level']:.2f} 并不高于其后最低点 @bar {m['bar']}")

    for ev in res["overshoots"]:
        if ev["bars"] < 0:
            P.append(f"过充持续根数为负 @bar {ev['start']}")
        if ev["end"] is not None and ev["end"] <= ev["start"]:
            P.append(f"过充事件结束不晚于开始 @bar {ev['start']}")
        if ev["backIn5"] is not None and ev["backIn5"] != (ev["bars"] <= 5):
            P.append(f"backIn5 与持续根数不自洽 @bar {ev['start']}")
    return P


# ══════════════════════════ CLI ══════════════════════════

def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_PATH)
    d = json.loads(path.read_text(encoding="utf-8"))
    bars = d["bars"]
    tick = d["meta"].get("tickSize") or 0.01

    res = zpa01_eval(bars, tick)
    S = res["series"]
    n = len(bars)
    tl = res["tlLog"][-1]

    print(f"数据: {d['meta']['symbol']} {d['meta']['interval']}  n={n}  tick={tick}  "
          f"末根收盘={bars[-1]['c']}")

    # ⚠ ATR 有**两个定义**，别把两者的差当成误差：
    #   本文件用 RMA（前 length 个 SMA 播种，之后 alpha = 1/length）= 与 Pine `ta.atr` 同口径 → 7.198
    #   facts.json 存的是「最近 14 根 TR 的**简单平均**」（CLI `market_facts.atr()` 口径）→ 6.270
    #   本文件内所有以 ATR 为单位的容差都用 RMA 那个（跟 Pine 走）。
    fa = d.get("atr")
    if isinstance(fa, (list, float)):
        ref = fa[-1] if isinstance(fa, list) else fa
        print(f"  ATR(14) 本文件 {S['atr'][-1]:.3f}（RMA/Wilder，同 Pine ta.atr）"
              f" ／ facts.json {ref:.3f}（简单平均，CLI 口径）"
              f" → 差 {abs(S['atr'][-1] - ref):.3f}，定义不同，不是误差")
    fe = d.get("ema")
    if isinstance(fe, list) and len(fe) == n and fe[-1]:
        print(f"  EMA20  本文件 {S['ema20'][-1]:.3f} ／ facts.json {fe[-1]:.3f}"
              f"（差异来自播种方式，应在 0.01 内）")

    print(f"\n[趋势线 / 通道线]　取点口径：最近两个同向枢轴（最小间隔 {CFG['tlMinBars']} 根）")
    if tl is None:
        print("  暂无有效趋势线（枢轴对不足）")
    else:
        print(f"  方向 {('上涨' if tl['kind']=='up' else '下跌')}　"
              f"{hhmm(bars[tl['x1']])}@{tl['y1']:.2f} → {hhmm(bars[tl['x2']])}@{tl['y2']:.2f}"
              f"　斜率 {tl['slope']:.4f} 点/根")
        print(f"  通道线过 {hhmm(bars[tl['cx']])}@{tl['cy']:.2f}　"
              f"通道高度 {tl['chW']:.2f}（{tl['chWAtr']:.2f} ATR）"
              f"　→ {'窄通道' if tl['chWAtr'] < CFG['narrowAtr'] else '宽通道'}")
        print(f"  现价距趋势线 {tl['distAtr']:+.2f} ATR　"
              f"{'已破位 @' + hhmm(bars[tl['brokenAt']]) if tl['broken'] else '趋势线完好'}"
              + (f"　· 正处于过充中（自 {hhmm(bars[tl['overStart']])}）"
                 if tl["overRun"] else ""))

    print(f"\n[通道破位 → 通道 MM 一倍目标]　共 {len(res['breaks'])} 次")
    for e in res["breaks"]:
        st = f"已到达 {hhmm(bars[e['reached']])}" if e["reached"] is not None else "未到达"
        print(f"  {hhmm(bars[e['at']])}  {'升破' if e['kind']=='down' else '跌破'} "
              f"破位价 {e['level']:.2f}　通道高 {e['chW']:.2f}　→ 一倍 {e['mm']:.2f}　{st}")

    ov = res["overshoots"]
    print(f"\n[通道线过充 / 过靶]　共 {len(ov)} 次"
          f"（从引线冲出通道线那根起、到重新回到通道内那根止）")
    for e in ov:
        endt = hhmm(bars[e["end"]]) if e["end"] is not None else "尚未收回"
        tag = "收盘也站上（→通道被上破）" if e["closeBeyond"] else "仅引线冲出（→真过充）"
        b5 = {True: "≤5 根收回 ✓", False: ">5 根才收回 ✗", None: "-"}[e["backIn5"]]
        print(f"  {hhmm(bars[e['start']])}→{endt}　{'上冲' if e['kind']=='up' else '下破'} "
              f"通道线 {e['level']:.2f}　持续 {e['bars']} 根　{tag}　{b5}")
    pure = [e for e in ov if not e["closeBeyond"] and e["backIn5"] is not None]
    if pure:
        ok = sum(1 for e in pure if e["backIn5"])
        print(f"  → 只看「真过充」（引线冲出、收盘没站上）：{ok}/{len(pure)} = "
              f"{ok/len(pure)*100:.0f}% 在 5 根内回到通道内"
              f"（体系说法：「通道过靶大概率五根 K 线内反转」）")
    n_cb = sum(1 for e in ov if e["closeBeyond"])
    if n_cb:
        print(f"  → 另有 {n_cb} 次是「收盘也站上通道线」：那不是过充，是通道被上破 / 需重画")

    print(f"\n[重要高低点]　共 {len(res['majors'])} 个（= 最强那段推进的起点）")
    for m in res["majors"]:
        st = f"已被{'跌破' if m['side']=='low' else '升破'} @{hhmm(bars[m['brokenAt']])}" \
            if m["brokenAt"] is not None else "未破"
        print(f"  {hhmm(bars[m['bar']])}  {'重要低点' if m['side']=='low' else '重要高点'} "
              f"{m['level']:.2f}　（{m['born']-m['bar']} 根前确立）　{st}")

    segs = res["segs"]
    print(f"\n[背景分段]　共 {len(segs)} 段（切换需连续 {CFG['segConfirm']} 根确认）")
    for j, s in enumerate(segs, 1):
        print(f"  {j:>2}. {hhmm(bars[s['start']])}-{hhmm(bars[s['last']])} "
              f"{KIND_NAME[s['kind']]:>10}　{s['last']-s['start']+1:>3} 根　"
              f"{s['lo']:.2f} ~ {s['hi']:.2f}")

    # 缺口：与 _zpa_gap_ref.pine_equivalent 对一下（同一套规则、两处实现）
    pe = pine_equivalent(bars, tick)
    mine = {(g["dir"], round(g["level"], 6), g["born"]) for g in res["gapHist"]}
    theirs = {(g["dir"], round(g["level"], 6), g["born"]) for g in pe}
    print(f"\n[缺口]　本文件 {len(mine)} 条 ／ pine_equivalent {len(theirs)} 条"
          f"　差集 {len(mine-theirs)} / {len(theirs-mine)}（应都为 0）")

    probs = check_invariants(bars, res)
    print(f"\n[结构性不变量]　{'全部通过 ✓' if not probs else str(len(probs)) + ' 处问题'}")
    for p in probs[:10]:
        print(f"  ✗ {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
