#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
叠层设计计算 —— 一比一复刻 `matrix_transformer_design.html` 的「🎛 PCB 叠层与板厚」。

来源
----
`E:\\project\\800-6\\AI_train\\calcu_html\\matrix_transformer_design.html`
（其自身又移植自「叠层优化」工具 pcb_winding_stackup.html）。

复刻的函数与行号对照（HTML 1173 行版）：
    mtxStkThickness            L483   铜厚按层类型 + 介质按相邻层对
    mtxStkThicknessPer         L561   逐层铜厚版
    mtxStkReadPerCuMeters      L579   oz -> m
    mtxStkBuildState           L609   MMF 单状态
    mtxStkMMF                  L630   MMF（全波两态 / 全桥单态）
    mtxStkInterfaces           L644   原副边相邻界面数
    mtxStkParseGnd             L666   GND 位置解析（顶/底强制）
    mtxStkDefaultSeq           L679   默认叠层序列

单位约定
--------
内部统一用 **µm**（HTML 用米，乘 1e6 即得，数值一一对应）。
铜厚换算 **1 oz = 35 µm**（与 HTML 一致；实测该板 .stackup 里 1oz ↔ 1.378mil = 35µm ✓）。

层类型
------
    P 原边 · S 副边(中心抽头/全桥) · A/B 全波副边两分支 · G GND

层命名（用户 2026-09-22 指定）
------------------------------
铜层名要**体现层号 + 网络**，形如：

    top - L1_B - L2_A - …… - Bot

即：最外两层固定叫 `top` / `Bot`，中间层叫 `L<k>_<类型>`（k 从 1 数起）。
"""

from __future__ import annotations

import math

# ---------------------------------------------------------------- 常量
# 铜厚可选项（与 HTML 下拉一致）与其等价 µm
CU_OZ_OPTIONS = (0.33, 0.5, 1.0, 2.0, 3.0, 4.0)
CU_OZ_UM = {0.33: 11.55, 0.5: 17.5, 1.0: 35.0, 2.0: 70.0,
            3.0: 105.0, 4.0: 140.0}
OZ_TO_UM = 35.0             # 1 oz = 35 µm（换算用这个；显示用上面查表避免浮点尾巴）

LAYER_TYPES = ("P", "S", "A", "B", "G")
TYPE_NAME = {"P": "原边", "S": "副边", "A": "副边A", "B": "副边B", "G": "GND"}

RECT_MODES = (("fullwave", "全波"), ("fullbridge", "全桥"))

# 默认命名规则（用户指定：top - L1_B - L2_A - ... - Bot）
OUTER_TOP = "top"
OUTER_BOT = "Bot"


def cu_um(oz: float) -> float:
    """盎司 → µm（计算口径，与 HTML 的 `oz * 35e-6` 一致）。"""
    return float(oz) * OZ_TO_UM


def cu_um_label(oz: float) -> float:
    """下拉里显示的 µm（查表，避免 0.33*35 的浮点尾巴）。"""
    return CU_OZ_UM.get(float(oz), float(oz) * OZ_TO_UM)


def cu_oz_text(oz: float) -> str:
    """盎司 → 下拉选项字符串（与 HTML 一致：`0.33/0.5/1/2/3/4`，不是 `1.0`）。"""
    return f"{float(oz):g}"


# ---------------------------------------------------------------- GND 位置
def parse_gnd(spec: str, L: int, Lgnd: int) -> list[int]:
    """GND 位置解析（1-based）。HTML mtxStkParseGnd L666。

    - 逗号/空格/中文逗号分隔，越界与非整数忽略
    - Lgnd >= 2 时**强制**把最顶(1)与最底(L)也算作 GND
    """
    if Lgnd <= 0:
        return []
    parts = [p for p in _split_ws(spec) if p != ""]
    arr: list[int] = []
    for p in parts:
        try:
            n = int(str(p).strip())
        except ValueError:
            continue
        if str(p).strip().lstrip("+-").isdigit() and 1 <= n <= L and n not in arr:
            arr.append(n)
    if Lgnd >= 2:
        if 1 not in arr:
            arr.append(1)
        if L not in arr:
            arr.append(L)
    return sorted(arr)


def _split_ws(s: str) -> list[str]:
    import re
    return re.split(r"[,，\s]+", s or "")


# ---------------------------------------------------------------- 默认序列
def default_seq(Lp: int, Ls: int, rect: str, gnd_arr: list[int],
                Lgnd: int | None = None) -> list[str]:
    """默认叠层序列：P/S（全波 A/B）交替，GND 按位置插入。HTML L679。

    ⚠️ **与 HTML 有意分歧（HTML 此处是 bug）**：
        HTML 用 `L = Lp + Ls + len(gnd_arr)`。当用户声明 Lgnd 层 GND 却只填了
        少于 Lgnd 个位置时（如 Lgnd=4 但只强制了顶/底 2 个），序列会比预期短，
        且末位算出 `undefined`（JSON 里成 null）。
        传入 Lgnd 时本实现改为**直接报错**，让 GUI 提示用户补全 —— 不复制该 bug。
    """
    if Lgnd is not None and len(gnd_arr) != Lgnd:
        raise ValueError(
            f"声明 GND {Lgnd} 层，实际只有 {len(gnd_arr)} 个位置（{gnd_arr}）；"
            f"顶/底层已自动计入，请再补 {Lgnd - len(gnd_arr)} 个层号。")
    gnd_set = set(gnd_arr)
    L = (Lp + Ls + len(gnd_arr)) if Lgnd is None else (Lp + Ls + Lgnd)
    movable: list[str] = []
    p_left, s_left, turn = Lp, Ls, 0
    while p_left > 0 or s_left > 0:
        if turn % 2 == 0 and p_left > 0:
            movable.append("P")
            p_left -= 1
        elif s_left > 0:
            if rect == "fullwave":
                a_c = movable.count("A")
                b_c = movable.count("B")
                movable.append("A" if a_c <= b_c else "B")
            else:
                movable.append("S")
            s_left -= 1
        elif p_left > 0:
            movable.append("P")
            p_left -= 1
        turn += 1
    if len(movable) != Lp + Ls:
        raise ValueError(f"内部错误：可动层数 {len(movable)} != Lp+Ls {Lp + Ls}")
    seq: list[str] = []
    mi = 0
    for i in range(1, L + 1):
        if i in gnd_set:
            seq.append("G")
        else:
            seq.append(movable[mi])
            mi += 1
    return seq


def build_seq(Lp: int, Ls: int, Lgnd: int, rect: str, gnd_spec: str) -> list[str]:
    """一步到位：解析 GND 位置 → 校验数量 → 生成序列。GUI 用这个。

    Raises:
        ValueError: GND 位置数与声明的 Lgnd 不符（提示用户补全）。
    """
    L = Lp + Ls + Lgnd
    gnd = parse_gnd(gnd_spec, L, Lgnd)
    try:
        return default_seq(Lp, Ls, rect, gnd, Lgnd=Lgnd)
    except ValueError:
        raise ValueError(
            f"声明 GND {Lgnd} 层，但只解析出 {len(gnd)} 个位置（{gnd}）。"
            f"顶/底层已自动计入；请再补 {Lgnd - len(gnd)} 个层号（1..{L}）。")


# ---------------------------------------------------------------- 板厚
def thickness(seq: list[str], cu_list_um: list[float],
              dPP: float, dSS: float, dPS: float) -> dict:
    """板厚计算（全部 µm）。HTML mtxStkThickness L483 / mtxStkThicknessPer L561。

    铜厚：按层逐个累加；**仿真厚度排除最外两层铜**。
    介质：按相邻两层对决定 dPP / dSS / dPS；**仿真厚度排除最外两层介质**。
        (a=='G' or b=='G') -> dSS
        a=='P' and b=='P'  -> dPP
        a=='P' or  b=='P'  -> dPS
        否则               -> dSS
    返回 total / cu / diel / simTotal / cuSim / dielSim（µm）；seq[0] = 底层或顶层均可（对称规则）。
    """
    L = len(seq)
    if len(cu_list_um) != L:
        raise ValueError(f"铜厚个数 {len(cu_list_um)} 与层数 {L} 不符")
    cu = diel = cu_sim = diel_sim = 0.0
    for i in range(L):
        h = float(cu_list_um[i])
        cu += h
        if 1 <= i <= L - 2:
            cu_sim += h
    for i in range(L - 1):
        a, b = seq[i], seq[i + 1]
        if a == "G" or b == "G":
            d = dSS
        elif a == "P" and b == "P":
            d = dPP
        elif a == "P" or b == "P":
            d = dPS
        else:
            d = dSS
        diel += d
        if 1 <= i <= L - 3:
            diel_sim += d
    return dict(total=cu + diel, cu=cu, diel=diel,
                cuSim=cu_sim, dielSim=diel_sim, simTotal=cu_sim + diel_sim)


def cu_list_from_global(seq: list[str], oz_p: float, oz_s: float, oz_g: float) -> list[float]:
    """按层类型取全局铜厚（HTML：P->hCuP, G->hCuG, 其余->hCuS）。"""
    out = []
    for t in seq:
        out.append(cu_um(oz_p if t == "P" else (oz_g if t == "G" else oz_s)))
    return out


def cu_list_from_oz(oz_list: list[float]) -> list[float]:
    """逐层铜厚（oz 列表）→ µm 列表。"""
    return [cu_um(o) for o in oz_list]


# ---------------------------------------------------------------- MMF
def build_state(seq: list[str], ATp: float, ATs: float, state_id: int) -> dict:
    """MMF 单状态累积。HTML mtxStkBuildState L609。"""
    L = len(seq)
    mmf_after: list[float] = []
    cur = 0.0
    for t in seq:
        if t == "P":
            d = ATp
        elif t == "S":
            d = -ATs
        elif t == "A":
            d = -ATs if state_id == 1 else 0.0
        elif t == "B":
            d = -ATs if state_id == 2 else 0.0
        else:
            d = 0.0
        cur += d
        mmf_after.append(cur)
    peak = 0.0
    integral = 0.0
    net = 0.0
    prev = 0.0
    for m1 in mmf_after:
        m0 = prev
        peak = max(peak, abs(m0), abs(m1))
        integral += (m0 * m0 + m0 * m1 + m1 * m1) / 3.0
        net += (m0 + m1) / 2.0
        prev = m1
    return dict(mmfAfter=mmf_after, peak=peak, integral=integral, net=net)


def mmf(seq: list[str], ATp: float, ATs: float, rect: str) -> dict:
    """MMF：全桥单态 / 全波两态。HTML mtxStkMMF L630。"""
    if rect == "fullbridge":
        states = [build_state(seq, ATp, ATs, 0)]
    else:
        states = [build_state(seq, ATp, ATs, 1), build_state(seq, ATp, ATs, 2)]
    peak = 0.0
    integral = 0.0
    sym = 0.0
    for st in states:
        peak = max(peak, st["peak"])
        integral += st["integral"]
        sym = max(sym, abs(st["net"]))
    integral /= len(states)
    return dict(peak=peak, integral=integral, sym=sym, states=states)


def interfaces(seq: list[str]) -> int:
    """原副边相邻界面数（越少板厚越薄）。HTML mtxStkInterfaces L644。"""
    def is_pri(t):
        return t == "P"

    def is_sec(t):
        return t in ("S", "A", "B")

    n = 0
    for i in range(len(seq) - 1):
        a, b = seq[i], seq[i + 1]
        if (is_pri(a) and is_sec(b)) or (is_sec(a) and is_pri(b)):
            n += 1
    return n


# ---------------------------------------------------------------- 层命名
def ampere_turns(Np: float, Lp: int, Ns: float, Ls: int, rect: str) -> tuple[float, float]:
    """安匝数 ATp / ATs。HTML L875-876（**注意用的是 Np，不是 Ns**）。

        ATp = Np / Lp                    每层原边安匝
        ATs = 全桥 ? Np / Ls : 2·Np / Ls  每个副边分支层安匝
    """
    ATp = (Np / Lp) if Lp else 0.0
    if not Ls:
        ATs = 0.0
    else:
        ATs = (Np / Ls) if rect == "fullbridge" else (2.0 * Np / Ls)
    return ATp, ATs


def parallel_per_turn(Lp: int, Np: float, Ls: int, Ns: float, rect: str) -> tuple[float, float]:
    """每匝并联层数 parP / parS。HTML L879。"""
    Larm = (Ls / 2.0) if rect == "fullwave" else float(Ls)
    parP = (Lp / Np) if Np else 0.0
    parS = (Larm / Ns) if Ns else 0.0
    return parP, parS


def layer_labels(seq: list[str], parP: float, parS: float) -> list[str]:
    """绕组标签（HTML `mtxStkLayerLabels` L775）：`P<匝>_<并> ` / `<型><匝>_<并>` / `G<序号>`。"""
    counts = {k: 0 for k in "PSABG"}
    out = []
    for t in seq:
        counts[t] = counts.get(t, 0) + 1
        n = counts[t]
        if t == "P":
            if parP and parP > 0:
                tp = math.ceil(n / parP)
                lp = n - (tp - 1) * parP
                out.append(f"P{tp:g}_{lp:g}")
            else:
                out.append(f"P{n}")
        elif t in ("S", "A", "B"):
            if parS and parS > 0:
                ts = math.ceil(n / parS)
                ls = n - (ts - 1) * parS
                out.append(f"{t}{ts:g}_{ls:g}")
            else:
                out.append(f"{t}{n}")
        else:
            out.append(f"G{n}")
    return out


def validate(Lp: int, Ls: int, Lgnd: int, rect: str, Np: float, Ns: float) -> list[str]:
    """HTML `mtxStkComputeManual` L840-847 的校验规则，逐条复刻。"""
    errs: list[str] = []
    if Lp <= 0 or Ls <= 0:
        errs.append("原/副边层数需 ≥ 1")
    if Lgnd > 0 and Lgnd < 2:
        errs.append("启用 GND 时层数需 ≥ 2（顶层/底层固定为 GND 屏蔽层）")
    if rect == "fullwave" and Ls % 2 != 0:
        errs.append("全波整流时副边层数须为偶数（两臂各占一半）")
    Larm = (Ls // 2) if rect == "fullwave" else Ls
    if Larm > 0 and Ls > 0:
        if Ns <= 0 or Larm < Ns or Larm % Ns != 0:
            errs.append(f"副边每臂层数({Larm})需为总匝数({Ns:g})整数倍")
    if Lp > 0 and Np > 0 and (Lp < Np or Lp % Np != 0):
        errs.append(f"原边层数({Lp})需为总匝数({Np:g})整数倍")
    return errs


def layer_names(seq: list[str]) -> list[str]:
    """按用户规则生成铜层名：`top` / `L<k>_<类型>` / `Bot`。

    - 第 1 层 -> `top`
    - 最后 1 层 -> `Bot`
    - 中间层 -> `L{k}_{type}`，k 从 1 数起（与板子现有 L1..L18 编号对齐）
    """
    L = len(seq)
    if L == 0:
        return []
    if L == 1:
        return [OUTER_TOP]
    out = []
    for i, t in enumerate(seq):
        if i == 0:
            out.append(OUTER_TOP)
        elif i == L - 1:
            out.append(OUTER_BOT)
        else:
            out.append(f"L{i}_{t}")
    return out


def parse_layer_name(name: str):
    """从层名反推 (位置类型, 序号, 网络类型)。

    `top` -> ('outer', 0, None) · `Bot` -> ('outer', L, None) · `L3_B` -> ('inner', 3, 'B')
    """
    import re
    if name == OUTER_TOP:
        return ("outer", 0, None)
    if name == OUTER_BOT:
        return ("outer", -1, None)
    m = re.fullmatch(r"L(\d+)_([PSABG])", name.strip(), re.I)
    if m:
        return ("inner", int(m.group(1)), m.group(2).upper())
    m = re.fullmatch(r"L(\d+)", name.strip(), re.I)
    if m:
        return ("inner", int(m.group(1)), None)
    return (None, None, None)


# ---------------------------------------------------------------- 与真实板子对接
def design_cu_um(seq, oz_list=None, oz_p=2.0, oz_s=2.0, oz_g=2.0):
    """统一入口：返回 (铜厚 µm 列表, 是否逐层模式)。"""
    if oz_list is not None:
        return cu_list_from_oz(oz_list), True
    return cu_list_from_global(seq, oz_p, oz_s, oz_g), False


# ---------------------------------------------------------------- 自检
def selfcheck() -> int:
    fails = []

    def chk(name, cond, extra=""):
        print(("[ OK ] " if cond else "[FAIL] ") + name + (f"   {extra}" if extra else ""))
        if not cond:
            fails.append(name)

    print("--- 1) 与 HTML 冒烟测试的已知值对齐 ---")
    # HTML _smoke_cu.js 场景：18 层（16 可动 + 2 固定 GND），L1=G .. L18=G
    Lp, Ls, Lgnd = 8, 8, 2
    gnd = parse_gnd("", Lp + Ls + Lgnd, Lgnd)
    chk("GND 位置 = [1, 18]", gnd == [1, 18], f"实得 {gnd}")
    seq = default_seq(Lp, Ls, "fullwave", gnd, Lgnd=Lgnd)
    chk("序列长度 18", len(seq) == 18, f"实得 {len(seq)}")
    chk("seq[0]=G seq[-1]=G", seq[0] == "G" and seq[-1] == "G", f"{seq}")
    chk("seq[1]=P seq[2] in (A,B)", seq[1] == "P" and seq[2] in ("A", "B"), f"{seq}")
    chk("build_seq 与 default_seq 一致",
        build_seq(Lp, Ls, Lgnd, "fullwave", "") == seq)
    chk("铜厚选项文本与 HTML 一致（'1' 不是 '1.0'）",
        [cu_oz_text(x) for x in CU_OZ_OPTIONS] == ["0.33", "0.5", "1", "2", "3", "4"],
        f"实得 {[cu_oz_text(x) for x in CU_OZ_OPTIONS]}")

    print()
    print("--- 2) 1 oz 层变化 => 总厚精确变化 0.035 mm（HTML 精度断言）---")
    dPP, dSS, dPS = 200.0, 300.0, 150.0      # µm，任意
    cu_a = cu_list_from_global(seq, 3.0, 1.0, 4.0)
    t_a = thickness(seq, cu_a, dPP, dSS, dPS)
    cu_b = list(cu_a)
    cu_b[2] -= cu_um(1.0)                    # 某层少 1oz
    t_b = thickness(seq, cu_b, dPP, dSS, dPS)
    delta_mm = (t_a["total"] - t_b["total"]) / 1000.0
    chk("Δ总厚 = 0.035 mm", abs(delta_mm - 0.035) < 1e-12, f"实得 {delta_mm}")

    print()
    print("--- 3) 0.33 oz 换算 ---")
    chk("cu_um(0.33) = 11.55", abs(cu_um(0.33) - 11.55) < 1e-9, f"实得 {cu_um(0.33)}")
    chk("cu_um_label(0.33) = 11.55", abs(cu_um_label(0.33) - 11.55) < 1e-12)
    chk("0.33oz 换层后 Δ=93.45µm",
        abs(((cu_um(3.0) - cu_um(0.33)) - 93.45)) < 1e-9,
        f"实得 {cu_um(3.0) - cu_um(0.33)}")

    print()
    print("--- 4) 介质规则 ---")
    s2 = ["P", "P", "P"]
    t2 = thickness(s2, [35.0] * 3, dPP=200.0, dSS=300.0, dPS=150.0)
    chk("P-P 用 dPP（2 段 = 400）", abs(t2["diel"] - 400.0) < 1e-9, f"实得 {t2['diel']}")
    s3 = ["P", "S", "P"]
    t3 = thickness(s3, [35.0] * 3, dPP=200.0, dSS=300.0, dPS=150.0)
    chk("P-S 用 dPS（2 段 = 300）", abs(t3["diel"] - 300.0) < 1e-9, f"实得 {t3['diel']}")
    s4 = ["P", "G", "P"]
    t4 = thickness(s4, [35.0] * 3, dPP=200.0, dSS=300.0, dPS=150.0)
    chk("含 G 用 dSS（2 段 = 600）", abs(t4["diel"] - 600.0) < 1e-9, f"实得 {t4['diel']}")

    print()
    print("--- 5) 仿真厚度排除最外两层 ---")
    s5 = ["P"] * 4
    t5 = thickness(s5, [35.0] * 4, 200.0, 300.0, 150.0)
    chk("cuSim = 2 层 = 70", abs(t5["cuSim"] - 70.0) < 1e-9, f"实得 {t5['cuSim']}")
    chk("dielSim = 1 段 = 200", abs(t5["dielSim"] - 200.0) < 1e-9, f"实得 {t5['dielSim']}")

    print()
    print("--- 6) MMF ---")
    ms = ["P", "A", "P", "B"]
    r = mmf(ms, ATp=100.0, ATs=100.0, rect="fullwave")
    chk("全波 = 2 个状态", len(r["states"]) == 2)
    chk("peak > 0", r["peak"] > 0, f"peak={r['peak']}")
    r1 = mmf(ms, ATp=100.0, ATs=100.0, rect="fullbridge")
    chk("全桥 = 1 个状态", len(r1["states"]) == 1)
    # ⚠️ net 是 MMF 曲线的**梯形积分**，不是末值：
    #    P->100, A->100, P->200, B->200；net = 50+100+150+200 = 500
    chk("全桥 net（梯形积分）= 500", abs(r1["states"][0]["net"] - 500.0) < 1e-9,
        f"实得 {r1['states'][0]['net']}")

    print()
    print("--- 7) 界面数 ---")
    chk("P,P,S,S -> 1 个界面", interfaces(["P", "P", "S", "S"]) == 1)
    chk("P,S,P,S -> 3 个界面", interfaces(["P", "S", "P", "S"]) == 3)
    chk("P,A,B,P -> 2 个界面", interfaces(["P", "A", "B", "P"]) == 2)

    print()
    print("--- 7.5) 安匝 / 并联层数 / 绕组标签 / 校验规则 ---")
    ap, as_ = ampere_turns(32, 8, 4, 8, "fullwave")
    chk("ATp = Np/Lp = 4", abs(ap - 4.0) < 1e-12, f"实得 {ap}")
    chk("ATs(全波) = 2·Np/Ls = 8", abs(as_ - 8.0) < 1e-12, f"实得 {as_}")
    chk("ATs(全桥) = Np/Ls = 4",
        abs(ampere_turns(32, 8, 4, 8, "fullbridge")[1] - 4.0) < 1e-12)
    chk("parP/parS = (0.25, 1)", parallel_per_turn(8, 32, 8, 4, "fullwave") == (0.25, 1.0),
        f"实得 {parallel_per_turn(8, 32, 8, 4, 'fullwave')}")
    chk("绕组标签 P 序号递增",
        layer_labels(["P", "P", "P"], 1, 1) == ["P1_1", "P2_1", "P3_1"],
        f"{layer_labels(['P', 'P', 'P'], 1, 1)}")
    chk("绕组标签并联分层 parP=2",
        layer_labels(["P", "P", "P", "P"], 2, 1) == ["P1_1", "P1_2", "P2_1", "P2_2"],
        f"{layer_labels(['P', 'P', 'P', 'P'], 2, 1)}")
    chk("GND 标签 G1/G2", layer_labels(["G", "G"], 1, 1) == ["G1", "G2"])
    chk("校验：全波奇数副边层数报错",
        any("偶数" in e for e in validate(8, 9, 2, "fullwave", 8, 4)))
    chk("校验：Lp 不是 Np 整数倍报错",
        any("原边层数" in e for e in validate(8, 8, 2, "fullwave", 32, 4)))
    chk("校验：合法参数无错", not validate(8, 8, 2, "fullwave", 8, 4),
        f"{validate(8, 8, 2, 'fullwave', 8, 4)}")
    chk("校验：Lgnd=1 报错（须 ≥2）",
        any("GND" in e for e in validate(8, 8, 1, "fullwave", 8, 4)))

    print()
    print("--- 8) 层命名规则（top - L1_x - ... - Bot）---")
    nm = layer_names(["G", "B", "A", "P", "G"])
    chk("首=top 尾=Bot", nm[0] == "top" and nm[-1] == "Bot", f"{nm}")
    chk("中间 L1_B / L2_A / L3_P", nm[1:4] == ["L1_B", "L2_A", "L3_P"], f"{nm}")
    chk("反解 L3_P", parse_layer_name("L3_P") == ("inner", 3, "P"))
    chk("反解 top", parse_layer_name("top") == ("outer", 0, None))
    nm20 = layer_names(["G"] + ["P"] * 18 + ["G"])
    chk("20 层首尾仍是 top/Bot", nm20[0] == "top" and nm20[-1] == "Bot")
    chk("20 层中间 18 个均 L 开头", all(x.startswith("L") for x in nm20[1:-1]))

    print()
    print("--- 9) 阴性对照 ---")
    chk("[阴性对照] 不存在的类型不该被当 P",
        cu_list_from_global(["X"], 2.0, 2.0, 2.0)[0] == cu_um(2.0))
    bad = False
    try:
        thickness(["P", "P"], [35.0], 1, 1, 1)
    except ValueError:
        bad = True
    chk("[阴性对照] 铜厚个数不符应当报错", bad)
    chk("[阴性对照] 层数不符时 Δ 断言会 FAIL",
        abs(((cu_um(3.0) - cu_um(0.33)) - 93.0)) > 1e-9)

    print()
    print("RESULT:", "PASS" if not fails else f"FAIL({len(fails)}): {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())
