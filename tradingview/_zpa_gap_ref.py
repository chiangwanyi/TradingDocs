#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Zpa 突破型缺口 —— 体系口径参考实现（与旧「跳空」口径做对照）。

口径来源（videos/Z说交易/价格行为系列之缺口+杂谈 逐字稿）：

  （一）179-185：
      「那什么是突破性缺口 —— 是一个这有一根很好的这根**阳线的低点**，
        当被**阴线的实体突破**，并且有跟随的时候，就制造出了缺口，
        所以说多头需要在这里解套，**这个低点就是突破性缺口**」
  （一）193-194：
      「还有这个位置也是突破性缺口，但一根比较好的**阴线**被这个
        **多头实体 k 线突破**，并且有跟随的时候就产生的缺口」
  （一）197-199：
      「并不是说非要有跟随，当这根**实体收在上面**的时候，就已经有缺口制造」
  （三）1132：
      「（差信号 K）大概率没有办法会对**前一根 k 线的这个低点高点或者
        波段高低点**会制造出缺口」

结论：**缺口是一个「价位」，不是一段跳空区间。**
  向下缺口位 = 被阴线实体（收盘价）跌破的那根阳线的「最低价」
  向上缺口位 = 被阳线实体（收盘价）突破的那根阴线的「最高价」

与旧实现（相邻两根 K 线引线/实体不重叠）是**完全不同的东西**：
旧口径找的是「跳空空洞」；体系口径找的是「反向实体突破掉的极值位」，
也就是**被套方打平离场的价位**。
"""
import json
import sys
from pathlib import Path

EPS = 1e-9


def hhmm(bar):
    """显示用的小时:分钟。

    ⚠ 必须按【源数据自带的时区偏移】直接截取（`iso` 里带 +08:00），
      绝不要统一转成 UTC —— 本项目曾因此整整差 8 小时。
      数据里 `t` 可能已是 `HH:MM`（5 字符）或完整 RFC3339，两种都要能吃。
    """
    s = (bar.get("iso") or bar.get("t") or "")
    return s[11:16] if len(s) >= 16 else s


# ────────────────── 体系口径：反向实体突破 ──────────────────

def zpa_gaps(bars, tick, min_ticks=1):
    """突破型缺口。

    向下：阴线 i 的收盘价 < 它之前「最近一根阳线」j 的最低价 → 缺口位 = low[j]
    向上：阳线 i 的收盘价 > 它之前「最近一根阴线」j 的最高价 → 缺口位 = high[j]

    「最近一根」意味着中间可以隔着同向 K 线 —— 正是 `B1阳 / B2阴 / B3阴，
    B3 收盘 < B1 最低` 这个例子的情形（B2 没跌破，B3 跌破了）。
    """
    out = []
    for i in range(1, len(bars)):
        cur = bars[i]
        o, c = cur["o"], cur["c"]
        is_bear = c < o - EPS
        is_bull = c > o + EPS
        if not (is_bear or is_bull):
            continue  # 十字线/平盘不制造缺口

        # 往前找最近的一根反向实体 K 线
        j = None
        for k in range(i - 1, -1, -1):
            pb = bars[k]
            if is_bear and pb["c"] > pb["o"] + EPS:
                j = k
                break
            if is_bull and pb["c"] < pb["o"] - EPS:
                j = k
                break
        if j is None:
            continue

        if is_bear:
            level = bars[j]["l"]          # 阳线的最低价 —— 被套多头打平的位置
            depth = level - c             # 实体跌破的深度
            direction = "down"
        else:
            level = bars[j]["h"]          # 阴线的最高价 —— 被套空头打平的位置
            depth = c - level
            direction = "up"

        if depth < min_ticks * tick - EPS:
            continue

        # 回补：价格回到该价位（从触发 K 的下一根开始算）
        fill_idx = None
        for k in range(i + 1, len(bars)):
            if direction == "down" and bars[k]["h"] >= level - EPS:
                fill_idx = k
                break
            if direction == "up" and bars[k]["l"] <= level + EPS:
                fill_idx = k
                break

        # 跟随：触发 K 的下一根是否同向延续（体系看重，但非必要条件）
        follow = None
        if i + 1 < len(bars):
            nxt = bars[i + 1]
            follow = (nxt["c"] < nxt["o"]) if direction == "down" else (nxt["c"] > nxt["o"])

        out.append(dict(
            i=i, t=cur["t"], hhmm=hhmm(cur), dir=direction,
            level=level, brokenBar=j, brokenT=bars[j]["t"], brokenHHMM=hhmm(bars[j]),
            depth=depth, depthTicks=depth / tick if tick else None,
            follow=follow,
            filled=fill_idx is not None,
            fillAt=fill_idx, fillIn=(fill_idx - i) if fill_idx is not None else None,
        ))

    # 顺序去重（必须与 Pine 状态机口径一致）：
    #   按诞生顺序逐条过，若已存在【同方向 + 同价位】且【在它诞生时仍未回补】的记录 → 跳过。
    #   已回补的记录会让出该价位 —— 之后再次被反向实体突破，是一批【新的】被套方。
    #   ⚠ 不能拿「最终」回补状态去重：某条记录可能在 B 诞生后才被回补，
    #     那种情况下状态机会跳过 B，用最终状态去重则会错误地保留 B。
    uniq = []
    for g in out:                                   # out 已按诞生先后排列
        dup = False
        for o in uniq:
            if o["dir"] != g["dir"] or abs(o["level"] - g["level"]) >= tick:
                continue
            open_at_birth = (not o["filled"]) or (o["fillAt"] is not None and o["fillAt"] > g["i"])
            if open_at_birth:
                dup = True
                break
        if not dup:
            uniq.append(g)
    return uniq


def pine_equivalent(bars, tick, min_ticks=1, keep_max=None, with_log=False):
    """Zpa-02 Pine 脚本的逐行复刻（**状态机版**）。

    Pine 里没法每根 K 线回扫整个历史，所以脚本用的是状态变量：
      lastBullLow / lastBearHigh —— 最近一根阳线的最低价 / 最近一根阴线的最高价

    与「回扫版」zpa_gaps 的唯一区别是实现路径：一个每根回扫历史，一个只记状态。
    两条路径的输出必须逐条一致（方向、价位、诞生序号、回补状态），
    这正是 `_zpa_gap_ref.py` 主流程做的双向差集。

    去重规则（两个版本必须一致）：同方向 + 同价位上若已有【未回补】缺口 →
    不另记（回补过的会让出该价位，之后再次被突破 = 一批新的被套方）。

    keep_max：模拟【旧的单表实现】—— 用 `array.shift` 裁掉最旧记录，而那张表
      同时充当去重表与回补扫描表。若被裁掉的是【未回补】记录，那个价位就被
      「让出」了，之后会被重复检出（**口径被渲染容量污染**）。
      Zpa-02 现已改为【双表】：未回补登记表（口径，不裁剪）+ 绘图/历史表（可裁剪），
      对应 `keep_max=None`。此参数保留下来专门用于量化旧实现的偏差。
    with_log：额外返回一份【不裁剪】的检出日志与被裁时仍未回补的条数。
    """
    recs = []
    log = []                       # 每一次检出（不裁剪）；与 recs 共享同一批 dict
    dropped_open = 0               # 被裁掉时仍未回补的条数
    last_bull_low = last_bull_bar = None
    last_bear_high = last_bear_bar = None
    thr = min_ticks * tick

    def _push(rec):
        nonlocal dropped_open
        recs.append(rec)
        log.append(rec)
        if keep_max is not None and len(recs) > keep_max:
            old = recs.pop(0)
            if not old["filled"]:
                dropped_open += 1

    for i, cur in enumerate(bars):
        # 第一步 · 回补检查（在检测之前 → 新缺口最早下一根才判回补）
        for g in recs:
            if g["filled"]:
                continue
            if g["dir"] > 0 and cur["l"] <= g["level"]:
                g["filled"], g["fillBar"] = True, i
            elif g["dir"] < 0 and cur["h"] >= g["level"]:
                g["filled"], g["fillBar"] = True, i

        # 第二步 · 检测新缺口
        is_bull = cur["c"] > cur["o"]
        is_bear = cur["c"] < cur["o"]

        # 唯一的去重规则：同方向同价位上已有【未回补】缺口 → 就是同一个缺口，不另记。
        # 回补过的记录会让出该价位（之后再次被跌破 = 一批新的被套方）。
        def _already_open(direction, level):
            for o in recs:
                if o["dir"] == direction and abs(o["level"] - level) < thr and not o["filled"]:
                    return True
            return False

        if (is_bear and last_bull_low is not None
                and cur["c"] < last_bull_low - thr
                and not _already_open(-1, last_bull_low)):
            _push(dict(level=last_bull_low, dir=-1, born=i, broken=last_bull_bar,
                       filled=False, fillBar=None, depth=last_bull_low - cur["c"],
                       dropped=None))
        if (is_bull and last_bear_high is not None
                and cur["c"] > last_bear_high + thr
                and not _already_open(1, last_bear_high)):
            _push(dict(level=last_bear_high, dir=1, born=i, broken=last_bear_bar,
                       filled=False, fillBar=None, depth=cur["c"] - last_bear_high,
                       dropped=None))

        # 第三步 · 状态更新（必须放在检测之后）
        if is_bull:
            last_bull_low, last_bull_bar = cur["l"], i
        if is_bear:
            last_bear_high, last_bear_bar = cur["h"], i

    if with_log:
        return recs, log, dropped_open
    return recs


def micro_gaps(bars, tick, min_ticks=1):
    """微缺口（体系：三根 K 线中间、隔一根形成的微型缺口）。

    原文（三）1212：「前一根 k 线和后一根 k 线，就是中间一根 k 隔开，
    反正三根 k 线中间的这个微型缺口」→ 用 bar[i-1] 与 bar[i+1] 比较。
    """
    out = []
    for i in range(1, len(bars) - 1):
        p, n = bars[i - 1], bars[i + 1]
        if p["h"] < n["l"] - EPS:
            lo, hi, d = p["h"], n["l"], "up"
        elif n["h"] < p["l"] - EPS:
            lo, hi, d = n["h"], p["l"], "down"
        else:
            continue
        if (hi - lo) < min_ticks * tick - EPS:
            continue
        out.append(dict(i=i, t=bars[i]["t"], hhmm=hhmm(bars[i]), dir=d, lo=lo, hi=hi, size=hi - lo))
    return out


# ────────────────── 旧（跳空）口径，仅用于对照 ──────────────────

def legacy_gaps(bars, tick, min_ticks=1):
    out = []
    for i in range(1, len(bars)):
        p, cur = bars[i - 1], bars[i]
        if p["h"] < cur["l"] - EPS:
            lo, hi, d = p["h"], cur["l"], "up"
        elif cur["h"] < p["l"] - EPS:
            lo, hi, d = cur["h"], p["l"], "down"
        else:
            continue
        if (hi - lo) < min_ticks * tick - EPS:
            continue
        out.append(dict(i=i, t=cur["t"], dir=d, lo=lo, hi=hi, size=hi - lo))
    return out


# ────────────────── 双向差集：回扫版 vs Pine 状态机版 ──────────────────

def cross_validate(bars, tick, min_ticks=1):
    """两条实现路径的**双向差集**。键 = (方向, 价位, 诞生序号)。

    ⚠ 键里必须带【诞生序号】。只按 (方向, 价位) 去重会把「同一价位被反复突破」
      的多条记录折叠成一条（本数据 55 条会折叠成 45 条），
      曾因此把「其实不一致」误判为「完全一致」。这是本文件最重要的一条教训。
    """
    zg = zpa_gaps(bars, tick, min_ticks)
    pe = pine_equivalent(bars, tick, min_ticks)

    def key(g, born_key):
        d = g["dir"]
        return (1 if d in (1, "up") else -1, round(g["level"], 6), g[born_key])

    k_ref = {key(g, "i") for g in zg}
    k_pin = {key(g, "born") for g in pe}
    ref_map = {key(g, "i"): g for g in zg}
    pin_map = {key(g, "born"): g for g in pe}
    diff_fill = sorted(k for k in (k_ref & k_pin)
                       if bool(ref_map[k]["filled"]) != bool(pin_map[k]["filled"]))

    return dict(
        ref=zg, pine=pe,
        n_ref=len(zg), n_pine=len(pe),
        n_uniq_ref=len({(key(g, "i")[0], key(g, "i")[1]) for g in zg}),
        n_uniq_pine=len({(key(g, "born")[0], key(g, "born")[1]) for g in pe}),
        only_ref=sorted(k_ref - k_pin),
        only_pine=sorted(k_pin - k_ref),
        diff_fill=diff_fill,
        open_ref=sum(1 for g in zg if not g["filled"]),
        open_pine=sum(1 for g in pe if not g["filled"]),
    )


def format_cross(v):
    """把 cross_validate 的结果排成人读文本（三处调用点共用同一份措辞）。"""
    return "\n".join([
        f"  回扫版 {v['n_ref']} 条 ／ Pine 状态机版 {v['n_pine']} 条"
        f"（去重后 (方向,价位) 唯一 {v['n_uniq_ref']} ／ {v['n_uniq_pine']}）",
        f"  仅在回扫版出现：{len(v['only_ref'])} 条（应为 0）",
        f"  仅在 Pine 版出现：{len(v['only_pine'])} 条（应为 0）",
        f"  回补状态不一致：{len(v['diff_fill'])} 条（应为 0）",
        f"  未回补计数：回扫 {v['open_ref']} ／ 状态机 {v['open_pine']}",
    ])


# ───────────────────────── 主流程 ─────────────────────────

def main():
    path = Path(sys.argv[1] if len(sys.argv) > 1
                 else r"E:/Data/projects/zpa/reports/MNQ-5m-2026-09-25.facts.json")
    d = json.loads(path.read_text(encoding="utf-8"))
    bars = d["bars"]
    meta = d["meta"]
    tick = meta.get("tickSize") or 0.01
    close = bars[-1]["c"]

    print(f"数据: {meta.get('symbol')} {meta.get('interval')}  n={len(bars)}  "
          f"tick={tick}  末根收盘={close}")

    zg = zpa_gaps(bars, tick)
    lg = legacy_gaps(bars, tick)
    mg = micro_gaps(bars, tick)
    open_z = [g for g in zg if not g["filled"]]

    # ── 双向差集：回扫版 vs Pine 状态机版（与 _verify_logic.py 共用同一个函数）──
    v = cross_validate(bars, tick)
    pe = v["pine"]
    k_pine = {(g["dir"], round(g["level"], 6), g["born"]) for g in pe}

    print(f"\n[口径自校验]")
    print(format_cross(v))

    print(f"\n[口径对照]")
    print(f"  体系口径（反向实体突破）：{len(zg)} 条，其中未回补 {len(open_z)} 条")
    print(f"  旧口径（相邻跳空）      ：{len(lg)} 条")
    print(f"  微缺口（隔一根）        ：{len(mg)} 条")
    print(f"  facts.json 记录         ：total={d['gaps']['total']} unfilled={d['gaps']['unfilled']}")

    # ── 渲染容量（keepMax）对口径的影响 ──
    # 旧实现是单表：`最多保留缺口数` 用 array.shift 裁掉最旧记录，而那张表同时
    # 充当去重表 → 裁掉未回补记录就会「让出」价位 → 重复检出。
    # 新实现是双表：未回补登记表不裁剪 → 检出结果与 keepMax 完全无关。
    print(f"\n[渲染容量 keepMax 对口径的影响]")
    for km in (40, 200, 1000):
        _, lg_k, drop_open = pine_equivalent(bars, tick, keep_max=km, with_log=True)
        dev = len(lg_k) - len(pe)
        flag = f"← 重复检出 {dev} 条（口径被污染）" if dev else "与不裁剪一致"
        print(f"  旧单表 keepMax={km:<5} 检出 {len(lg_k)} 条"
              f"／被裁时仍未回补 {drop_open} 条　{flag}")
    print(f"  新双表（Zpa-02 现版）   检出 {len(pe)} 条／未回补 "
          f"{sum(1 for g in pe if not g['filled'])} 条　与 keepMax 无关 ✓")

    print(f"\n[体系口径 · 缺口清单]（按时间，位=被套方打平价）")
    print(f"  {'#':>3} {'时间':>6} {'方向':>4} {'缺口位':>10} {'破位深度':>10} "
          f"{'跟随':>4} {'状态':>10} {'回补于':>7}")
    for n, g in enumerate(zg, 1):
        state = "未回补" if not g["filled"] else f"+{g['fillIn']}根"
        fill_t = hhmm(bars[g["fillAt"]]) if g["filled"] else "-"
        print(f"  {n:>3} {g['hhmm']:>6} {'向下' if g['dir']=='down' else '向上':>4} "
              f"{g['level']:>10.2f} {g['depthTicks']:>8.0f}t "
              f"{'✓' if g['follow'] else ('×' if g['follow'] is False else '-'):>4} "
              f"{state:>10} {fill_t:>7}")

    if open_z:
        print(f"\n[未回补缺口 → 测量缺口 / 最后一个缺口候选]")
        for g in open_z:
            print(f"  {g['hhmm']}  {'向下' if g['dir']=='down' else '向上'}  位 {g['level']:.2f}  "
                  f"（现价 {close}，距离 {abs(close - g['level']):.2f}）")

    print(f"\n[微缺口]")
    for g in mg:
        print(f"  {g['hhmm']}  {'向上' if g['dir']=='up' else '向下'}  {g['lo']:.2f} ~ {g['hi']:.2f}  "
              f"宽 {g['size']:.2f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
