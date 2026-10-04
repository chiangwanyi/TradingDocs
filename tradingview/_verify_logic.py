#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用真实盘面数据验证 Pine 指标的核心算法口径（背景证据 / 支撑阻力聚类）。

⚑ 2026-09-28 缺口口径修正后，本文件里原有的「相邻跳空」缺口验证已弃用 ——
  缺口验证请用 `_zpa_gap_ref.py`（回扫版 vs Pine 状态机版 双向差集）。

⚑ 2026-09-28 背景量去重：本文件原来自带一份 context_metrics()/body_quality()，
  与 `_context_ref.zpa01_eval` 是**两份实现**，且已经分叉（那边加了 ⑥ 通道分 /
  s8 / chanNarrow 覆盖，这边还停在旧的 7 分量）。现在 [2] 只调用
  `_context_ref.zpa01_eval` 并打印分量、权重、分级 —— 单一口径来源。

本文件现在的职责：
  [1] 缺口：委托 `_zpa_gap_ref.cross_validate`
  [2] 背景证据：委托 `_context_ref.zpa01_eval`（含结构性不变量）
  [3] 支撑阻力聚类：本文件自带（Zpa-03 的复刻，暂未共享）
"""
import json
import sys
from pathlib import Path


# ───────────────────────── Pine 口径复刻 ─────────────────────────

# ⚑ 已删除 detect_gaps_pine()：那是旧的「相邻跳空」口径的 Pine 复刻，与体系无关。
#   缺口验证见 _zpa_gap_ref.py。


def pivots(bars, k=3):
    """Pine ta.pivothigh/pivotlow 的对称严格分形。返回 [(index, 'H'|'L', price)]"""
    res = []
    for i in range(k, len(bars) - k):
        h = bars[i]["h"]
        l = bars[i]["l"]
        if all(h > bars[i - j]["h"] for j in range(1, k + 1)) and all(h > bars[i + j]["h"] for j in range(1, k + 1)):
            res.append((i, "H", h))
        if all(l < bars[i - j]["l"] for j in range(1, k + 1)) and all(l < bars[i + j]["l"] for j in range(1, k + 1)):
            res.append((i, "L", l))
    return sorted(res)


# ⚑ 已删除本文件内嵌的 asc_ratio / highestbars / lowestbars / context_metrics / body_quality。
#   那是 Zpa-01 背景量的**第二份实现**，与 Pine 侧悄悄分叉过：Pine 后来加了
#   ⑥ 趋势线/通道（含 s8 通道质量分、chanNarrow 覆盖、8 分量加权），本文件却还停在
#   旧的 7 分量 0.22·s1 + 0.22·s2 + 0.16·s3 + 0.14·s4 + 0.10·s5 + 0.08·s6 + 0.08·s7
#   上 —— 是个会骗人的「验证」。现在唯一口径来源是 `_context_ref.zpa01_eval`，
#   本文件只做**调用 + 打印**，不再自己算。
#   保留 `pivots()`：下面的 [3] 支撑阻力聚类要用它，与背景量无关。


def cluster_levels(bars, pv_k=3, tick=0.25, tol=2.0, max_levels=16):
    """复刻 Zpa-03 的候选位聚类 + 叠加计数。"""
    pool = {}

    def add(price, name):
        if price is None:
            return
        for k in list(pool.keys()):
            if abs(k - price) <= tol:
                pool[k]["hits"] += 1
                if name not in pool[k]["names"]:
                    pool[k]["n"] += 1
                    pool[k]["names"].append(name)
                return
        pool[price] = dict(n=1, hits=1, names=[name])

    pv = pivots(bars, pv_k)
    last_hi = last_lo = None
    for idx, typ, price in pv:
        if typ == "H":
            add(price, "前高")
            add(bars[idx]["c"], "前高收")
            if last_lo is not None:
                add((last_lo + price) / 2, "50%位")
            last_hi = price
        else:
            add(price, "前低")
            add(bars[idx]["c"], "前低收")
            if last_hi is not None:
                add((last_hi + price) / 2, "50%位")
            last_lo = price

    # ⑤ 缺口位（体系口径：被反向实体突破的那根 K 线的极值）—— 复刻 Zpa-03 的 ⑤
    # 未回补登记表同时充当去重表；引线触及即回补 → 让出该价位。
    # ⚠ 旧实现这里是「相邻两根引线不重叠」的跳空口径，已弃用。
    open_lv = []
    open_dir = []
    last_bull_low = last_bear_high = None
    for i in range(1, len(bars)):
        cur = bars[i]
        for j in range(len(open_lv) - 1, -1, -1):          # 回补检查（先于检测）
            lv, dd = open_lv[j], open_dir[j]
            if (dd > 0 and cur["l"] <= lv) or (dd < 0 and cur["h"] >= lv):
                open_lv.pop(j)
                open_dir.pop(j)
        is_bull = cur["c"] > cur["o"]
        is_bear = cur["c"] < cur["o"]

        def _dup(direction, level):
            return any(dd == direction and abs(lv - level) < tick
                       for lv, dd in zip(open_lv, open_dir))

        if is_bear and last_bull_low is not None and cur["c"] < last_bull_low - tick and not _dup(-1, last_bull_low):
            add(last_bull_low, "缺口")
            open_lv.append(last_bull_low)
            open_dir.append(-1)
        if is_bull and last_bear_high is not None and cur["c"] > last_bear_high + tick and not _dup(1, last_bear_high):
            add(last_bear_high, "缺口")
            open_lv.append(last_bear_high)
            open_dir.append(1)
        if is_bull:
            last_bull_low = cur["l"]
        if is_bear:
            last_bear_high = cur["h"]

    return sorted(pool.items(), key=lambda kv: -kv[1]["n"])[:max_levels]


def main():
    path = Path(r"E:/Data/projects/zpa/reports/MNQ-5m-2026-09-25.facts.json")
    d = json.loads(path.read_text(encoding="utf-8"))
    bars = d["bars"]
    tick = d["meta"]["tickSize"]
    close = bars[-1]["c"]
    print(f"数据: {d['meta']['symbol']} {d['meta']['interval']}  n={len(bars)}  tick={tick}  收盘={close}")
    print("-" * 78)

    # ── 1) 缺口：已改用体系口径（详见 _zpa_gap_ref.py）──
    # ⚑ 原来的「相邻两根 K 线引线/实体不重叠」是**跳空**口径，2026-09-28 确认与体系无关，已弃用。
    #   这里不再与 CLI 的 detect_gaps 对比 —— 两者口径已分叉。
    #   校验逻辑统一放在 _zpa_gap_ref.cross_validate（避免两处各写一份而漂移）。
    try:                                    # 项目内布局（模块名带下划线）
        from _zpa_gap_ref import cross_validate, format_cross, micro_gaps as _zg_micro
    except ImportError:                     # 技能 scripts/ 布局（模块名不带下划线）
        from zpa_gap_ref import cross_validate, format_cross, micro_gaps as _zg_micro

    v = cross_validate(bars, tick)
    _mic = _zg_micro(bars, tick)

    print("[1] 缺口（体系口径：被反向实体突破的极值价位）")
    print(format_cross(v))
    _open = [g for g in v["pine"] if not g["filled"]]
    print(f"    未回补 {len(_open)} 条" + "".join(
        f"\n      · {'向上' if g['dir'] > 0 else '向下'} {g['level']:.2f}（破位 {g['depth']:.2f}）"
        for g in _open))
    print(f"    隔一根的微缺口 {len(_mic)} 条")

    # ── 2) 背景证据（Zpa-01）──
    # ⚑ 唯一口径来源：_context_ref.zpa01_eval（与 Zpa-01-市场背景.pine 逐字同构）。
    #   本文件只**调用 + 打印**，不再自带第二份实现（见文件头那条注释）。
    #   这一节补的是参考实现 main() 没打印的部分：八分量取值 + 权重 + 分级。
    #   两种模块布局都兼容：项目内 `_context_ref.py` ／ 技能 `scripts/context_ref.py`。
    try:
        import _context_ref as _cref
    except ImportError:
        import context_ref as _cref

    ctx = _cref.zpa01_eval(bars, tick)
    CW = _cref.W
    S = ctx["series"]
    k = len(bars) - 1
    tl = ctx["tlLog"][-1]
    KEYS = ("s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8")
    NAMES = dict(s1="结构", s2="缺口", s3="回调浅", s4="重叠低",
                 s5="K线质量", s6="逆势未连续", s7="回调不长", s8="通道质量")

    print(f"\n[2] Zpa-01 背景证据（口径来源：{_cref.__name__}.zpa01_eval）")
    print(f"    结构: 高点递增 {S['hiRise'][k]*100:.0f}% ／ 低点递增 {S['loRise'][k]*100:.0f}%"
          f"  → 结构分 {S['struct'][k]:+.2f}" + ("  [扩张三角形]" if S["expanding"][k] else ""))
    print(f"    回调: 深度 {S['pull'][k]*100:.1f}% ／ 时长 {S['pullBar'][k]} 根")
    print(f"    重叠: 平均 {S['avgOvl'][k]*100:.1f}% ／ 小实体 {S['dojiPct'][k]*100:.1f}%")
    print(f"    方向: trendDir={S['dir'][k]:+d}　"
          f"K线质量 {S['bodyQ'][k]:.2f}（逆势最长连续 {S['oppMax'][k]} 根）")
    print(f"    缺口: 未回补 {S['openGaps'][k]} ／ 窗口内 {S['recentGaps'][k]}"
          f"（快速回补 {S['recentFake'][k]}）")
    if tl:
        w = tl["chWAtr"]
        print(f"    通道: 高度 {w:.2f} ATR（{'窄通道' if w < 2.5 else '宽通道'}）"
              f" ／ 距趋势线 {tl['distAtr']:+.2f} ATR"
              f" ／ {'已破位' if tl['broken'] else '完好'}"
              + ("　· 过充中" if tl["overRun"] else ""))
    else:
        print("    通道: 无有效趋势线（枢轴对不足）→ s8 取中性 0.50")

    print("    分量: " + "  ".join(f"{NAMES[t]}={S[t][k]:.2f}" for t in KEYS))
    print("    权重: " + " + ".join(f"{CW[t]:.2f}·{t}" for t in KEYS))
    hand = sum(CW[t] * S[t][k] for t in KEYS)
    print(f"    → 趋势分 {S['score'][k]:.3f}（按上面权重手算复核 {hand:.3f}，应相等）"
          f"  → 分级：{S['phase'][k]}")

    # 缺口：与 [1] 同源，这里只补一句「两处实现对得上」的结论
    print(f"    [缺口口径] 回扫版 {v['n_ref']} ／ Pine 状态机版 {v['n_pine']} 条；"
          f"双向差集 {len(v['only_ref'])} / {len(v['only_pine'])}（应都为 0）")
    probs = _cref.check_invariants(bars, ctx)
    print(f"    [结构性不变量] {'全部通过 ✓' if not probs else str(len(probs)) + ' 处问题'}")
    for p in probs[:6]:
        print(f"      ✗ {p}")

    # ── 3) 支撑阻力聚类（Zpa-03）──
    # ⚠ 容差必须用 **RMA 口径**的 ATR —— Pine 的 Zpa-03 用的是 `ta.atr(14)`（RMA = 7.198）。
    #   早期这里图省事取了 facts.json 的 `atr`（= 简单平均 6.270）→ 容差 1.57 而非 1.80，
    #   聚类出来的位会不一样。又一处「验证脚本与指标不同源」，和 [2] 那个是同一类错误。
    atr = _cref.atr_series(bars, 14)[-1]
    tol = max(0.25 * atr, 2 * tick)
    lv = cluster_levels(bars, tol=tol, tick=tick)
    print(f"\n[3] Zpa-03 支撑阻力聚类（容差 {tol:.2f} = 0.25 × ATR(RMA) {atr:.2f}）")
    for price, info in lv[:8]:
        side = "支撑" if price < close else "阻力"
        print(f"    {side} {price:>10.2f}  理由 {info['n']} 类 / 命中 {info['hits']} 次  ← {' + '.join(info['names'])}")

    print("\n[4] 与 reports 已产出的 facts 对比（⚠ facts 仍是旧的跳空口径，数字不可与指标直接对照）")
    print(f"    facts.gaps: total={d['gaps']['total']} unfilled={d['gaps']['unfilled']} "
          f"nPrice={d['gaps']['nPrice']} nBody={d['gaps']['nBody']} noise={d['gaps']['noise']}")
    print(f"    facts.levelCandidates: {len(d['levelCandidates'])} 个聚类位（脚本给出 {len(lv)} 个，容差口径可能不同）")


if __name__ == "__main__":
    main()
