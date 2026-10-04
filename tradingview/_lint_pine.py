#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Pine 脚本静态自检：缩进 / 括号 / 全角字符 / 声明完整性 / **语义陷阱**。

不做完整语法分析，但覆盖了这几类真正会让 TradingView 编译失败或算错的硬伤：

  ① 格式类：TAB、缩进非 4 的倍数、括号不配对、代码位置出现全角字符
  ② 声明类：indicator()/strategy() 必须恰好一条且在全局作用域（CE10243）
  ③ 语义类（新增）：
     · 逗号连续赋值 `x := 1, y := 2` —— Pine 不支持，必须拆行
     · plotshape/plot 用了不存在的 `yloc=` 参数
     · 函数体最后一句是 for/while/if → 无返回值，Pine 报 cannot return void
     · 使用了**从未声明**的标识符（拼写错误 / 变量名漂移）
     · 全局变量在声明之前就被使用
     · 在 if/for 块里调用 ta.* —— Pine 内部序列状态会漏掉 K 线，结果静默错误
     · 倒序 for `for i = n - 1 to 0` 缺可证明的下界 —— n == 0 时 Pine 从 -1 数到 0
     · int / float 类型错配（CE10173）：float 循环边界 → 计数器变 float；
       以及 v6 起 `/` **永远返回 float**，`int x = a / b` 也编译不过
     · 历史引用 `[]` 拿了「绝对 K 线序号」当偏移 —— `[]` 只接受「往回根数」，
       用 bar_index 量级的值当下标会取错 K 线（静默）或报 Invalid number of bars back
     · v5 已移除的 iff() / v6 已移除的 transp()

用法：python _lint_pine.py Zpa-01-*.pine ...
"""
import re
import sys
from pathlib import Path

FULLWIDTH = "（）［］｛｝，；：！？＋－＊／＝＜＞｜＆＃＠＂＇"

# TradingView「新建空白指标/策略」自带的模板声明（粘贴污染的头号来源）
TEMPLATE_DECLS = ("indicator(\"My script\")", "indicator('My script')",
                  "strategy(\"My Strategy\"", "strategy('My Strategy'")

TYPES = r"(?:int|float|bool|string|color|line|label|box|table|plot|hline|array<[^>]*>|matrix<[^>]*>|map<[^>]*>)"

# Pine 里「不是变量」的裸标识符：关键字、常量、简单内置量
KEYWORDS = {
    "na", "true", "false", "and", "or", "not", "if", "else", "for", "while", "to", "by",
    "break", "continue", "switch", "var", "varip", "int", "float", "bool", "string",
    "color", "line", "label", "box", "table", "array", "matrix", "map", "import", "export",
    "open", "high", "low", "close", "volume", "time", "time_close", "bar_index",
    "last_bar_index", "hl2", "hlc3", "ohlc4", "hlcc4", "timenow", "barstate", "syminfo",
    "strategy", "timeframe", "session", "dayofweek", "request", "runtime", "math", "str",
    "ta", "input", "plot", "format", "size", "text", "location", "shape", "position",
    "extend", "xloc", "yloc", "display", "alert", "currency", "scale", "order",
    "adjustment", "backadjustment", "settlement_as_close", "earnings", "dividends",
    "splits", "dayofmonth", "dayofyear", "month", "year", "weekofyear", "hour", "minute",
    "second", "last_bar_time", "timeframe_period", "ticker", "label", "line", "box",
}


COLOR_LIT = re.compile(r"#[0-9a-fA-F]{6,8}\b")


def strip_strings(line: str) -> str:
    """把双引号字符串**内容**替换成等长空格，并把 #rrggbb 色值抹掉。

    ⚠ 字符串内容必须用空格而不是占位字母：用字母的话，长串占位符本身会被后面的
      「未声明标识符」扫描当成一个变量名（这个坑踩过一次）。色值同理 ——
      `#ef5350` 里的 `ef5350` 会被当成标识符。
    """
    out, in_str, esc = [], False, False
    for ch in line:
        if in_str:
            if esc:
                esc = False
                out.append(" ")
            elif ch == "\\":
                esc = True
                out.append(" ")
            elif ch == '"':
                in_str = False
                out.append('"')
            else:
                out.append(" ")
        else:
            if ch == '"':
                in_str = True
            out.append(ch)
    return COLOR_LIT.sub(lambda m: " " * len(m.group(0)), "".join(out))


def strip_comment(raw: str) -> str:
    """去掉行内注释；字符串里的 // 不算注释。"""
    code = strip_strings(raw)
    h = code.find("//")
    return raw[:h] if h >= 0 else raw


def code_of(raw: str) -> str:
    return strip_strings(strip_comment(raw))


# ══════════════════ ② 声明语句完整性（CE10243）══════════════════

def check_declaration(lines):
    errs, warns = [], []
    decls, version_lines, code_before_decl = [], [], []

    for i, raw in enumerate(lines, 1):
        if "\t" in raw:
            continue
        stripped = raw.lstrip(" ")
        if not stripped:
            continue
        if stripped.startswith("//@version"):
            version_lines.append(i)
            continue
        if stripped.startswith("//"):
            continue
        code_clean = code_of(raw)
        m = re.search(r"\b(indicator|strategy|library)\s*\(", code_clean)
        if m:
            decls.append((i, len(raw) - len(stripped), m.group(1), stripped))
            continue
        if not decls:
            code_before_decl.append(i)

    if len(decls) == 0:
        errs.append("声明语句缺失：脚本必须包含且仅包含一条 indicator() / strategy() / library()")
    elif len(decls) > 1:
        errs.append(f"声明语句有 {len(decls)} 条（必须恰好 1 条）→ CE10243。"
                    f"行号：{', '.join(str(d[0]) for d in decls)}")
        for ln, ind, fn, src in decls:
            hit = "  ← 疑似 TradingView 模板残留" if any(t in src for t in TEMPLATE_DECLS) else ""
            errs.append(f"    第 {ln} 行: {fn}(){hit}")
        errs.append("    修法：编辑器内 Ctrl+A 全选 → 删除 → 再粘贴本文件全文（编辑器不会自动清空）")
    for ln, ind, fn, src in decls:
        if ind != 0:
            errs.append(f"第 {ln} 行：{fn}() 有 {ind} 空格缩进，声明语句必须在全局作用域")

    if not version_lines:
        warns.append("缺少 //@version=6 编译注释（省略时按 version 1 解析，`ta.` 系列全部失效）")
    elif len(version_lines) > 1:
        errs.append(f"//@version 出现 {len(version_lines)} 次（行 {version_lines}）→ 疑似两次粘贴叠加")
    elif version_lines[0] != 1:
        warns.append(f"//@version=6 在第 {version_lines[0]} 行，建议置于首行")

    if decls:
        before = [i for i in code_before_decl if i < decls[0][0]]
        if before:
            warns.append(f"声明语句（第 {decls[0][0]} 行）之前存在可执行代码：行 {before[:6]}")
    return errs, warns


# ══════════════════ ③ 语义检查 ══════════════════

def collect_declared(lines):
    """收集全文件声明过的标识符 → {名字: 首次声明行}。"""
    declared = {}
    tuple_re = re.compile(r"^\s*\[([^\]]+)\]\s*=")
    assign_re = re.compile(r"([A-Za-z_]\w*)\s*(?::=|=)(?!=)")
    func_re = re.compile(r"^(\w+)\s*\(([^)]*)\)\s*=>")

    for i, raw in enumerate(lines, 1):
        code = code_of(raw)
        if not code.strip():
            continue
        for name, *_ in func_re.findall(code):
            declared.setdefault(name, i)
        m = func_re.search(code)
        if m:
            for prm in m.group(2).split(","):
                w = re.findall(r"[A-Za-z_]\w*", prm)
                if w:
                    declared.setdefault(w[-1], i)
        tm = tuple_re.search(code)
        if tm:
            for name in tm.group(1).split(","):
                name = name.strip()
                if re.fullmatch(r"[A-Za-z_]\w*", name):
                    declared.setdefault(name, i)
            continue
        for name in assign_re.findall(code):
            declared.setdefault(name, i)
        fm = re.search(r"\bfor\s+([A-Za-z_]\w*)\s*=", code)
        if fm:
            declared.setdefault(fm.group(1), i)
        fm2 = re.search(r"\bfor\s+\[([^\]]+)\]\s+in\b", code)
        if fm2:
            for name in fm2.group(1).split(","):
                declared.setdefault(name.strip(), i)
    return declared


BUILTIN_PREFIX = re.compile(
    r"^(ta|math|str|array|matrix|map|line|label|box|table|color|input|request|timeframe|"
    r"syminfo|barstate|strategy|session|dayofweek|display|extend|xloc|yloc|location|shape|"
    r"position|size|text|format|scale|alert|currency|order|adjustment|runtime|plot|"
    r"ticker|earnings|dividends|splits|backadjustment|settlement)\.\w+$")

CALL_RE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
# 后面紧跟 `(` 的是函数调用、紧跟 `.` 的是枚举/命名空间（barmerge.gaps_off），都不算变量
IDENT_RE = re.compile(r"(?<![\w.$])([A-Za-z_]\w*)(?![\w.(])")


def check_semantics(lines):
    errs, warns = [], []
    declared = collect_declared(lines)

    # ── ① 逗号连续赋值：Pine 不支持 `a := 1, b := 2` ──
    for i, raw in enumerate(lines, 1):
        code = code_of(raw)
        if re.search(r":=[^,]*,\s*\w+\s*(?::=|=)", code):
            errs.append(f"{i}: 逗号连续赋值 `x := a, y := b` —— Pine 不支持，必须拆成多行 → {raw.strip()[:60]}")
        # plotshape / plot 没有 yloc 参数
        if re.search(r"\byloc\s*=", code) and re.search(r"\bplot(shape|char|arrow|candle|bar)?\s*\(", code):
            errs.append(f"{i}: plot()/plotshape() 没有 yloc 参数（用 location.absolute + 把价位写进 series）")
        # 已移除的函数
        if re.search(r"\biff\s*\(", code):
            errs.append(f"{i}: 使用了 v5 已移除的 iff()")
        if re.search(r"\btransp\s*\(", code):
            errs.append(f"{i}: 使用了 v6 已移除的 transp()，应用 color.new()")
        if re.search(r",\s*,", code):
            errs.append(f"{i}: 出现连续逗号")

    # ── ② 函数体最后一句是循环/if → 无返回值 ──
    func_re = re.compile(r"^(\w+)\s*\([^)]*\)\s*=>")
    i = 0
    while i < len(lines):
        m = func_re.match(lines[i])
        if not m:
            i += 1
            continue
        base = len(lines[i]) - len(lines[i].lstrip(" "))
        body = []
        j = i + 1
        while j < len(lines):
            raw = lines[j]
            if not raw.strip():
                j += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if ind <= base:
                break
            if not raw.lstrip(" ").startswith("//"):
                body.append((j + 1, raw.strip(), ind))
            j += 1
        if body:
            last_ln, last_txt, _ = body[-1]
            if re.match(r"^(for|while|if)\b", last_txt):
                errs.append(f"{last_ln}: 函数 `{m.group(1)}()` 体的最后一句是 `{last_txt[:30]}` "
                            f"→ 函数没有返回值，Pine 会报「cannot return void」。补一句返回表达式。")
        i = j

    # ── ③ 未声明的标识符 / 声明前使用 ──
    for i, raw in enumerate(lines, 1):
        code = code_of(raw)
        if not code.strip() or code.lstrip().startswith("//"):
            continue
        for name in IDENT_RE.findall(code):
            if name in KEYWORDS or name in declared:
                continue
            if BUILTIN_PREFIX.match(name) or name.count(".") > 0:
                continue
            # 后面紧跟 . 的（命名空间）与紧跟 ( 的（函数调用）已在正则里排除
            errs.append(f"{i}: 使用了未声明的标识符 `{name}` → {raw.strip()[:60]}")

    for name, dl in sorted(declared.items(), key=lambda kv: kv[1]):
        if name in KEYWORDS:
            continue
        for i, raw in enumerate(lines, 1):
            if i >= dl:
                break
            if re.search(r"(?<![\w.$])" + re.escape(name) + r"(?![\w.(])", code_of(raw)):
                warns.append(f"{i}: 标识符 `{name}` 在第 {dl} 行才声明，此处已使用")
                break

    # ── ④ 条件块里调用 ta.* ──
    ta_call = re.compile(r"\bta\.\w+\s*\(")
    for i, raw in enumerate(lines, 1):
        code = code_of(raw)
        if not ta_call.search(code):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if indent == 0:
            continue
        errs.append(f"{i}: `ta.*` 出现在缩进块内（缩进 {indent}）—— Pine 的内部序列状态会漏掉 K 线，"
                    f"结果会静默算错。必须移到全局作用域无条件求值。")

    # ── ⑤ 倒序 for 循环缺守卫 ──
    # Pine 的 `for i = a to b` 在 a < b 时**自动升序**。所以 `for i = n - 1 to 0`
    # 在 n == 0 时会从 -1 数到 0 → 拿 -1 去 array.get → 越界运行时报错。
    #
    # 判定「安全」的三条路，命中任一即放过：
    #   A 外层 if 带守卫：`if array.size(X) > 0` / `if X > 0` / `X >= 1` / `X != 0`
    #   B 外层 for 的**终点是正字面量**：`for i = n - 1 to 1` ⇒ i ≥ 1 ⇒ `i - 1 ≥ 0`
    #   C 基变量初值是 `input.int(..., minval = K)` 且 K ≥ 偏移：
    #     `chopLen = input.int(20, minval = 5)` ⇒ chopLen - 1 ≥ 4
    # ⚠ 早期版本只认 A，把 B / C 两种**真安全**的写法当硬伤（误报 2 处）。
    #   误报的危害不比漏报小 —— 会诱导人去写毫无作用的死守卫。
    input_minval = {}
    for raw in lines:
        m = re.search(r"([A-Za-z_]\w*)\s*=\s*input\.int\s*\(([^)]*)\)", code_of(raw))
        if m:
            mv = re.search(r"minval\s*=\s*(-?\d+)", m.group(2))
            if mv:
                input_minval[m.group(1)] = int(mv.group(1))

    rev_re = re.compile(r"^\s*for\s+(\w+)\s*=\s*(.+?)\s+to\s+0\s*$")
    encl_for_re = re.compile(r"^\s*for\s+([A-Za-z_]\w*)\s*=\s*.+?\s+to\s+(\d+)\s*$")
    for i, raw in enumerate(lines, 1):
        m = rev_re.match(raw.rstrip())
        if not m:
            continue
        expr = m.group(2).strip()
        em = re.fullmatch(r"([A-Za-z_]\w*)\s*-\s*(\d+)", expr)
        base, off = (em.group(1), int(em.group(2))) if em else (None, 1)
        indent = len(raw) - len(raw.lstrip(" "))
        ok = bool(base) and base in input_minval and input_minval[base] - off >= 0  # C

        # A / B：沿缩进逐层向外找可证明的下界
        for j in range(i - 2, max(-1, i - 60), -1):
            prev = lines[j]
            if not prev.strip():
                continue
            pind = len(prev) - len(prev.lstrip(" "))
            if pind >= indent:
                continue
            pc = code_of(prev).rstrip()
            if re.match(r"^\s*(elif|else)\b", pc):
                continue
            fm = encl_for_re.match(pc)
            if fm and base and fm.group(1) == base and int(fm.group(2)) - off >= 0:
                ok = True   # B
                break
            if re.match(r"^\s*if\b", pc):
                hit = ("size(" in pc
                       or re.search(r"(>\s*0|!=\s*0|>=\s*1)\s*$", pc) is not None
                       or (base is not None
                           and re.search(rf"\b{re.escape(base)}\s*(>=\s*1|>\s*0|!=\s*0)", pc)))
                if hit:
                    ok = True   # A
                    break
                continue        # 无守卫的 if 不是终点，继续往外找（守卫可能在它外层的 for 上）
            break
        if not ok:
            errs.append(f"{i}: 倒序 for `{raw.strip()}` 缺可证明的下界 —— "
                        f"计数为 0 时 Pine 会从 -1 数到 0，array.get(-1) 越界报错。"
                        f"加 `if <expr> > 0` 守卫，或把终点写成正字面量")

    # ── ⑥ int / float 类型错配（CE10173）──
    # Pine 有两处推断会咬人：
    #   1) `for k = a to b` 的**计数器继承边界的类型**。边界是 float 时 k 也是 float，
    #      于是 `extB := k`（extB 是 int）报
    #      CE10173: Cannot assign a value of the "float" type to the "int" variable.
    #   2) v6 起 `/` **永远返回 float**（官方 Operators 文档：5/2 = 2.5），
    #      所以 `int x = a / b` 同样编译不过。
    #
    # 判定原则：**只对能证明是 float 的右值报错**。名字在 int/float 两边都出现过
    # （作用域遮蔽）时一律按「未知」放过 —— 误报会诱导人去写没用的 int() 包装。
    type_decl = re.compile(r"\b(?:var\s+|varip\s+)?(int|float)\s+([A-Za-z_]\w*)\b")
    int_names, float_names = set(), set()
    for raw in lines:
        code = code_of(raw)
        for t, nm in type_decl.findall(code):
            (int_names if t == "int" else float_names).add(nm)
        fm = re.search(r"\bfor\s+([A-Za-z_]\w*)\s*=", code)
        if fm:
            int_names.add(fm.group(1))
    unclear = int_names & float_names
    int_only = int_names - unclear
    float_only = float_names - unclear

    float_lit = re.compile(r"\d+\.\d*|\d*\.\d+")

    def provably_float(expr: str) -> bool:
        e = expr.strip()
        if re.fullmatch(r"[A-Za-z_]\w*", e):
            return e in float_only
        if float_lit.search(e):
            return True
        # 除法在 v6 里恒为 float —— 除非外层已经用 int()/math.floor() 收口
        if "/" in e and not re.search(r"\bint\s*\(|\bmath\.floor\s*\(", e):
            return True
        return False

    for_re2 = re.compile(r"^\s*for\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s+to\s+([^,]+)$")
    for i, raw in enumerate(lines, 1):
        code = code_of(raw).rstrip()
        m = for_re2.match(code)
        if not m:
            continue
        counter, lo, hi = m.group(1), m.group(2), re.split(r"\s+by\s+", m.group(3))[0]
        for bound in (lo, hi):
            if provably_float(bound):
                errs.append(f"{i}: `for {counter} = ... to ...` 的边界 `{bound.strip()}` 是 float "
                            f"→ 计数器 {counter} 会被推断成 float，赋值给 int 变量时报 CE10173。"
                            f"横坐标（bar_index / 数组下标）必须声明成 int")
                break

    # 声明：int x = <float 表达式>
    decl_asg = re.compile(r"^\s*(?:var\s+|varip\s+)?(int|float)\s+([A-Za-z_]\w*)\s*=\s*(?!=)(.+)$")
    # 重新赋值：x := / += / -= / *= / /=  <float 表达式>
    re_asg = re.compile(r"^\s*([A-Za-z_]\w*)\s*(\+=|-=|\*=|/=|:=|=)\s*(?!=)(.+)$")
    for i, raw in enumerate(lines, 1):
        code = code_of(raw).rstrip()
        m = decl_asg.match(code)
        if m:
            if m.group(1) == "int" and provably_float(m.group(3)):
                errs.append(f"{i}: `int {m.group(2)} = {m.group(3).strip()[:40]}` —— 右值是 float，"
                            f"Pine 报 CE10173（注意 v6 里 `a / b` 恒为 float，要收口用 int()）")
            continue
        m = re_asg.match(code)
        if m and m.group(1) in int_only and provably_float(m.group(3)):
            errs.append(f"{i}: 把 float 赋给 int 变量 `{m.group(1)}` → "
                        f"CE10173（右值 `{m.group(3).strip()[:40]}`）")

    # ── ⑦ 历史引用运算符 [] 拿了「绝对 K 线序号」当偏移 ──
    # `[]` 只接受**往回根数**（0 .. max_bars_back）。把绝对序号（bar_index 量级）当下标，
    # 有两种后果，而且都很隐蔽：
    #   ① 语义全错：`high[10001]` 取的是「图表开头那根」，不是第 10001 根，且**不报错**；
    #   ② 直接崩：Error on bar 10001: Invalid number of bars back specified in the
    #      history-referencing operator. It accepts a value between 0 and 10000.
    # 本项目实测两种都撞过：`high[t]`（t = bar_index - b，b = 0 时 t = bar_index）、
    # `high[k]`（k 是枢轴的绝对序号）、`high[q]`（q 从 neuStart 数到 bar_index）。
    #
    # 判定思路：按**作用域**把名字分成两类，再看它有没有被历史引用当下标用。
    #   ABS —— 绝对 K 线序号（bar_index 量级）
    #   OFF —— 往回根数（字面量 / n-1 / 数组长度 / input.int 这类计数）
    #   · `bar_index` → ABS；`bar_index - 字面量或计数` → ABS；`bar_index - ABS` → OFF
    #   · for 计数器：边界里有 ABS → ABS；边界里有独立数字字面量 → OFF
    #   · `array.push` 过 ABS 值的数组 → 元素是 ABS；再经「实参→形参」「元组返回」传播
    # 只有下标被证明是 ABS 才报错；判不出来一律放过。
    #
    # ⚑ 三条设计要点，全是这一轮踩出来的：
    #   1) **必须按作用域解析**，不能只看全局名字集合。本项目 `k` 既是通道循环的计数器
    #      （ABS），又是 kindOf() 里的局部量 `int k = 4`；`b` 既是枢轴数组里的 ABS，
    #      又是重要位回扫循环的计数器（`for b = 0 to mjN - 1`）。只看名字必然误判
    #      —— 第一版就因此把修好的 `high[off]` 判成了硬伤，还顺手触发了一轮自我怀疑。
    #   2) **判定规则必须单调**：只能往 ABS/OFF 里加，绝不下带否定的结论。第一版写成
    #      「`bar_index - X` 且 X 不是 BIG → 结果是 BIG」，在 `tX1` 还没推出来的那一轮
    #      就把 `off` 加进了 BIG，之后再也不会撤 → 第二次误报。拆成两条独立规则后，
    #      结果与迭代顺序无关。
    #   3) 「边界里有没有数字」要用**独立数字字面量**判断：`tX1` / `x2` / `y1` 这些
    #      **变量名自带数字**，用 `re.search(r"\d", bound)` 会把 `for k = tX1 to tX2`
    #      误判成计数循环 —— 第三次误报。
    # ⚠ 宁可漏报也不能误报 —— 误报会诱导人写没用的偏移变量。

    def _split_args(s):
        out, depth, cur = [], 0, ""
        for ch in s:
            if ch in "([":
                depth += 1
            elif ch in ")]":
                depth -= 1
            if ch == "," and depth == 0:
                out.append(cur)
                cur = ""
            else:
                cur += ch
        out.append(cur)
        return [a.strip() for a in out if a.strip()]

    fn_hdr = re.compile(r"^([A-Za-z_]\w*)\s*\(([^)]*)\)\s*=>")
    for_re3 = re.compile(r"^\s*for\s+([A-Za-z_]\w*)\s*=\s*(.+?)\s+to\s+(.+?)(?:\s+by\s+.+)?\s*$")
    asg_re3 = re.compile(r"^\s*(?:var\s+|varip\s+)?(?:(?:int|float|bool)\s+)?"
                         r"([A-Za-z_]\w*)\s*(?::=|=)\s*(?!=)(.+)$")
    num_lit = re.compile(r"(?<![\w.])\d+(?![\w.])")

    func_params, func_param_names = {}, set()
    for raw in lines:
        hm = fn_hdr.match(code_of(raw))
        if hm:
            ps = [re.findall(r"[A-Za-z_]\w*", a)[-1] for a in _split_args(hm.group(2))]
            func_params[hm.group(1)] = ps
            func_param_names.update(p for p in ps if p)

    # 每个 for 循环的作用域行区间：(起行, 止行, 计数器名, 下界, 上界)，全部 0-based
    loops = []
    for idx0, raw in enumerate(lines):
        fm = for_re3.match(code_of(raw))
        if not fm:
            continue
        base = len(raw) - len(raw.lstrip(" "))
        j = idx0 + 1
        while j < len(lines):
            rr = lines[j]
            if rr.strip() and (len(rr) - len(rr.lstrip(" "))) <= base:
                break
            j += 1
        loops.append((idx0, j, fm.group(1), fm.group(2).strip(), fm.group(3).strip()))

    ABS, OFF, ABS_ARR = {"bar_index"}, set(), set()

    def classify(e, idx0, depth=0):
        """表达式是 'abs'（绝对序号）／'off'（往回根数）／None（判不出来）。"""
        if depth > 6:
            return None
        e = e.strip()
        if not e:
            return None
        if num_lit.fullmatch(e):
            return "off"                      # 字面量 → 计数
        if e == "bar_index":
            return "abs"
        if e.startswith("input.int("):
            return "off"                      # 输入参数是「根数 / 条数」量级
        m = re.fullmatch(r"bar_index\s*([-+])\s*(.+)", e)
        if m:
            op, rest = m.group(1), m.group(2).strip()
            c = classify(rest, idx0, depth + 1)
            if c is None:                     # `bar_index - (某表达式 + 1)` 取首个名字
                lead = re.match(r"([A-Za-z_]\w*|\d+)", rest)
                c = classify(lead.group(1), idx0, depth + 1) if lead else None
            if op == "+":
                return "abs"
            if c == "off":
                return "abs"                  # bar_index - 小量/计数 → 仍是绝对序号
            if c == "abs":
                return "off"                  # bar_index - 绝对序号 → 偏移（修好后的写法）
            return None
        if re.fullmatch(r"[A-Za-z_]\w*", e):
            return resolve(e, idx0, depth + 1)
        cm = re.fullmatch(r"int\s*\(\s*(.+?)\s*\)", e)
        if cm:
            return classify(cm.group(1), idx0, depth + 1)
        if "array.size(" in e:
            return "off"                      # 数组长度是「根数」量级
        for arr in re.findall(r"array\.get\s*\(\s*([A-Za-z_]\w*)", e):
            if arr in ABS_ARR:
                return "abs"
        return None

    def resolve(name, idx0, depth=0):
        """名字在第 idx0 行处的语义：最近的同名 for 计数器 > 形参 > 全局。"""
        if depth > 6:
            return None
        best = None
        for a, b, cn, lo, hi in loops:
            if cn == name and a < idx0 < b and (best is None or a > best[0]):
                best = (a, lo, hi)
        if best is not None:
            cls = (classify(best[1], idx0, depth + 1), classify(best[2], idx0, depth + 1))
            if "abs" in cls:
                return "abs"
            return "off" if "off" in cls else None
        if name in func_param_names:
            return None                       # 形参语义未知 → 放过
        if name in ABS and name in OFF:
            return None                       # 同名两种语义 → 判不出来
        if name in ABS:
            return "abs"
        return "off" if name in OFF else None

    def propagate():
        for _ in range(10):
            changed = False
            for idx0, raw in enumerate(lines):
                code = code_of(raw).rstrip()
                if not code.strip():
                    continue
                fm = for_re3.match(code)
                if fm:
                    cls = (classify(fm.group(2).strip(), idx0),
                           classify(fm.group(3).strip(), idx0))
                    if "abs" in cls:
                        if fm.group(1) not in ABS:
                            ABS.add(fm.group(1))
                            changed = True
                    elif "off" in cls and fm.group(1) not in OFF:
                        OFF.add(fm.group(1))
                        changed = True
                am = asg_re3.match(code)
                if am:
                    cl = classify(am.group(2), idx0)
                    if cl == "abs" and am.group(1) not in ABS:
                        ABS.add(am.group(1))
                        changed = True
                    elif cl == "off" and am.group(1) not in OFF:
                        OFF.add(am.group(1))
                        changed = True
                for arr, ex in re.findall(r"array\.push\s*\(\s*([A-Za-z_]\w*)\s*,\s*([^)]*)\)", code):
                    if arr not in ABS_ARR and classify(ex, idx0) == "abs":
                        ABS_ARR.add(arr)
                        changed = True
                cm2 = re.search(r"\b([A-Za-z_]\w*)\s*\((.*)\)\s*$", code)
                if cm2 and cm2.group(1) in func_params:
                    for pname, a in zip(func_params[cm2.group(1)], _split_args(cm2.group(2))):
                        if pname and pname not in ABS_ARR and a in ABS_ARR:
                            ABS_ARR.add(pname)
                            changed = True
            if not changed:
                break

    def apply_tuple_returns():
        """函数体末句 `[v1, v2, ...]` 里是 ABS 的位置 → 调用处解构出来的名字也是 ABS。"""
        pos_abs = {}
        for i, raw in enumerate(lines):
            hm = fn_hdr.match(code_of(raw))
            if not hm:
                continue
            base = len(raw) - len(raw.lstrip(" "))
            body, j = [], i + 1
            while j < len(lines):
                rr = lines[j]
                if rr.strip() and (len(rr) - len(rr.lstrip(" "))) <= base:
                    break
                if rr.strip() and not rr.lstrip(" ").startswith("//"):
                    body.append(code_of(rr).strip())
                j += 1
            if body:
                tm = re.fullmatch(r"\[([^\]]+)\]", body[-1])
                if tm:
                    pos_abs[hm.group(1)] = [v.strip() in ABS for v in tm.group(1).split(",")]
        for raw in lines:
            dm = re.match(r"^\s*\[([^\]]+)\]\s*=\s*([A-Za-z_]\w*)\s*\(", code_of(raw))
            if dm and dm.group(2) in pos_abs:
                for o, isb in zip([o.strip() for o in dm.group(1).split(",")],
                                  pos_abs[dm.group(2)]):
                    if isb:
                        ABS.add(o)

    for _ in range(3):
        propagate()
        apply_tuple_returns()

    idx_re = re.compile(r"(?<![\w.$])([A-Za-z_]\w*)\s*\[\s*([A-Za-z_]\w*)\s*\]")
    for i, raw in enumerate(lines):
        for series, idx in idx_re.findall(code_of(raw)):
            if resolve(idx, i) != "abs":
                continue
            fix = ("偏移变量（`bar_index - x` 之类）" if idx == "bar_index"
                   else f"`{series}[bar_index - {idx}]`")
            errs.append(f"{i + 1}: `{series}[{idx}]` 的下标 `{idx}` 是 bar_index 量级的**绝对序号**，"
                        f"而 `[]` 只接受「往回根数」→ 轻则取错 K 线（不报错），"
                        f"重则运行时报 Invalid number of bars back（0..10000）。"
                        f"应写成 {fix}")

    return errs, warns


# ══════════════════ 主流程 ══════════════════

def check(path: Path):
    errs, warns = [], []
    lines = path.read_text(encoding="utf-8").splitlines()

    e, w = check_declaration(lines)
    errs += e
    warns += w
    e, w = check_semantics(lines)
    errs += e
    warns += w

    for i, raw in enumerate(lines, 1):
        if "\t" in raw:
            errs.append(f"{i}: 含 TAB 字符（Pine 只接受空格缩进）")
        stripped = raw.lstrip(" ")
        if not stripped or stripped.startswith("//"):
            continue
        indent = len(raw) - len(stripped)
        if indent % 4 != 0:
            errs.append(f"{i}: 缩进 {indent} 不是 4 的倍数 → {raw.strip()[:60]}")
        code = code_of(raw)
        if code.count("(") != code.count(")"):
            warns.append(f"{i}: 本行圆括号不配对 ({code.count('(')} vs {code.count(')')}) → {stripped[:60]}")
        for ch in FULLWIDTH:
            if ch in code:
                errs.append(f"{i}: 代码位置（非字符串/注释）出现全角字符 {ch!r} → {stripped[:60]}")
                break

    clean = [code_of(l) for l in lines]
    text = "\n".join(clean)
    if text.count("(") != text.count(")"):
        errs.append(f"文件级圆括号不平衡: {text.count('(')} vs {text.count(')')}")
    if text.count("[") != text.count("]"):
        errs.append(f"文件级方括号不平衡: {text.count('[')} vs {text.count(']')}")
    return errs, warns


def main():
    paths = [Path(p) for p in sys.argv[1:]]
    if not paths:
        paths = sorted(Path(__file__).parent.glob("*.pine"))
    total = 0
    for p in paths:
        errs, warns = check(p)
        total += len(errs)
        print(f"\n=== {p.name} ===")
        if not errs and not warns:
            print("  OK：未发现硬伤")
        for e in errs:
            print(f"  [ERROR] {e}")
        for w in warns[:10]:
            print(f"  [warn ] {w}")
        if len(warns) > 10:
            print(f"  ... 另外 {len(warns) - 10} 条警告")
    print(f"\n合计硬伤 {total} 处")
    return 1 if total else 0


if __name__ == "__main__":
    sys.exit(main())
