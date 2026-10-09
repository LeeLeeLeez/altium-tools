#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""
从零生成 Altium 叠层文件（`*.stackup`）—— 不需要先导出模板。

依据
----
形状**逐 token 抄自 AD 自带预设**
`<AD>\System\LayerStackManager\Presets\*.stackup`（AD 自己就能加载它们，
所以照这个形状生成的文件 AD 也应能加载）。

关键发现
--------
- 顶层段：`STACKUPVERSION=1` → `LAYERMASTERSTACK_V8*` → `DISPLAYUNIT=1` →
  **再重复一次 `LAYERMASTERSTACK_V8ID`** → `LAYERSUBSTACK_V8_0*`（AD 就是这么写的）
- 层顺序：32 个 Mechanical（倒序 32→1，最后一个 `MECHENABLED=True`）→
  Top Paste / Top Overlay / Top Solder → **Top Layer** → Dielectric 1 →
  (MidLayer + Dielectric)… → **Bottom Layer** → Bottom Solder / Bottom Overlay / Bottom Paste
- 🔴 **最外两层铜用 `LAYERID`**（Top=16777217、Bottom=16842751），
  **中间层不带 LAYERID，改用 `TYPE=SIGNAL|INTERNAL_PLANE`**，AD 按顺序+类型重建；
  中间介质同理用 `TYPE=DIELECTRIC`；只有**第 1 个介质**带 `LAYERID=17039361`。
- 每层都带一个 `_{子叠层GUID}CONTEXT=0`。

⚠️ 与「导出模板」模式的取舍
--------------------------
从零生成的是**通用的**层叠（材料/Dk/Df/过孔跨度/Feature 都是本文件给的默认值），
**不会带上你板子里已有的那些设置**。若要保留板子自己的材料库/阻抗/Via Span，
仍应先用 LSM `File → Save As…` 导出一次当模板（GUI 里会把该路径缓存复用）。
"""

from __future__ import annotations

import datetime
import re
import uuid

# 规范 LAYERID
LID_TOP = 16777217          # 0x01000001  Top Layer
LID_BOTTOM = 16842751       # 0x0100FFFF  Bottom Layer
LID_DIEL1 = 17039361        # 0x01040001  Dielectric 1
LID_MECH_HI = 16908320      # Mechanical 32
LID_TOP_PASTE = 16973832
LID_TOP_OVERLAY = 16973830
LID_TOP_SOLDER = 16973834
LID_BOT_SOLDER = 16973835
LID_BOT_OVERLAY = 16973831
LID_BOT_PASTE = 16973833

MIL_TO_MM = 0.0254


def _g() -> str:
    return "{" + str(uuid.uuid4()).upper() + "}"


def _mil(mm_or_mil: float, unit: str = "mil") -> str:
    v = mm_or_mil / MIL_TO_MM if unit == "mm" else mm_or_mil
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return f"{s or '0'}mil"


def build_stackup_text(
    n_cu: int,
    layer_names: list[str],
    cu_mil: list[float],
    diel_mil: list[float],
    *,
    dk_diel: float = 4.2,
    dk_fr4: float = 4.8,
    mat_pp: str = "PP-006",
    mat_core: str = "FR-4",
    diel_types: list[int] | None = None,
    kinds: list[str] | None = None,
    pullback_mil: float = 20.0,
    dk_sr: float = 3.5,
    sr_mil: float = 0.4,
    master_name: str = "Master layer stack",
    substack_name: str = "Board Layer Stack",
    style: int = 3,
) -> str:
    """生成完整 `.stackup` 文本。

    Args:
        n_cu: 铜层数（含最外两层）
        layer_names: 铜层名，长度 = n_cu（如 top / L1_B / … / Bot）
        cu_mil:    每层铜厚 (mil)，长度 = n_cu
        diel_mil:  铜层之间的介质厚 (mil)，长度 = n_cu - 1
        diel_types: 每段介质的 DIELTYPE（1=core, 2=prepreg），长度 = n_cu - 1
                    （HTML 的模型只有厚度，这里给默认：交替 core/prepreg）
        kinds:      中间铜层的种类，`"signal"` 或 `"plane"`，长度 = n_cu
                    （只有 1..n_cu-2 会被用到）。plane 生成
                    `TYPE=INTERNAL_PLANE` + `PULLBACKDISTANCE`，signal 生成
                    `TYPE=SIGNAL` + `COMPONENTPLACEMENT` —— 与 AD 预设一致。
                    GND 层建议用 plane（内电层），其余用 signal。
    Raises:
        ValueError: 长度不一致或 n_cu < 2
    """
    if n_cu < 2:
        raise ValueError("至少需要 2 个铜层（Top/Bottom）")
    if len(layer_names) != n_cu or len(cu_mil) != n_cu:
        raise ValueError(f"铜层名/铜厚 长度须为 {n_cu}")
    if len(diel_mil) != n_cu - 1:
        raise ValueError(f"介质段数须为 {n_cu - 1}")
    if diel_types is None:
        diel_types = [2 if i % 2 else 1 for i in range(n_cu - 1)]
    if len(diel_types) != n_cu - 1:
        raise ValueError(f"diel_types 长度须为 {n_cu - 1}")
    if kinds is None:
        kinds = ["signal"] * n_cu
    if len(kinds) != n_cu:
        raise ValueError(f"kinds 长度须为 {n_cu}")

    sub = _g()
    parts: list[str] = [""]
    parts += [
        "STACKUPVERSION=1",
        f"STACKUPDOCUMENTID={_g()}",
        f"STACKUPDOCUMENTREVISIONID={_g()}",
        "STACKUPDOCUMENTREVISIONDATE="
        + datetime.datetime.now().strftime("%m/%d/%Y %H:%M:%S"),
        f"LAYERMASTERSTACK_V8ID={_g()}",
        f"LAYERMASTERSTACK_V8NAME={master_name}",
        "LAYERMASTERSTACK_V8ISFLEX=False",
        "LAYERMASTERSTACK_V8SHOWTOPDIELECTRIC=False",
        "LAYERMASTERSTACK_V8SHOWBOTTOMDIELECTRIC=False",
        f"LAYERMASTERSTACK_V8STYLE={style}",
        "DISPLAYUNIT=1",
    ]
    # 预设里 LAYERMASTERSTACK_V8ID 会出现第二次（AD 自己的写法，照抄）
    stem = [p for p in parts if p.startswith("LAYERMASTERSTACK_V8ID=")][0]
    parts.append(stem)
    parts += [
        f"LAYERSUBSTACK_V8_0ID={sub}",
        f"LAYERSUBSTACK_V8_0NAME={substack_name}",
        "LAYERSUBSTACK_V8_0ISFLEX=False",
        "LAYERSUBSTACK_V8_0TYPE=0",
        "LAYERSUBSTACK_V8_0SHOWTOPDIELECTRIC=False",
        "LAYERSUBSTACK_V8_0SHOWBOTTOMDIELECTRIC=False",
    ]

    cnt = 0

    def lay(fields: list[tuple[str, str]]) -> None:
        """发射一层。

        🔴 token 顺序必须与 AD 一致：`CONTEXT` 紧跟 `NAME`，**在**类型字段之前
        （曾写在最后 ⇒ 形状指纹全错）。`_{sub}CONTEXT` 的 GUID 只包一层大括号。
        """
        nonlocal cnt
        i = cnt
        out: list[tuple[str, str]] = []
        for k, v in fields:
            out.append((k, v))
            if k == "NAME":
                out.append((f"_{sub}CONTEXT", "0"))
        for k, v in out:
            parts.append(f"LAYER_V8_{i}{k}={v}")
        cnt += 1

    # ---- 32 个机械层（32 → 1，最后一个 MECHENABLED=True）----
    for k in range(32):
        lay([
            ("LAYERID", str(LID_MECH_HI - k)),
            ("ID", _g()),
            ("NAME", f"Mechanical {32 - k}"),
            ("MECHENABLED", "True" if k == 31 else "False"),
        ])

    # ---- 顶层辅助层 ----
    lay([("LAYERID", str(LID_TOP_PASTE)), ("ID", _g()), ("NAME", "Top Paste")])
    lay([("LAYERID", str(LID_TOP_OVERLAY)), ("ID", _g()), ("NAME", "Top Overlay")])
    lay([("LAYERID", str(LID_TOP_SOLDER)), ("ID", _g()), ("NAME", "Top Solder"),
         ("DIELTYPE", "3"), ("DIELCONST", f"{dk_sr:g}"),
         ("DIELHEIGHT", _mil(sr_mil)), ("DIELMATERIAL", "Solder Resist")])

    # ---- 铜层 + 介质交替 ----
    for i in range(n_cu):
        nm = layer_names[i]
        if i == 0:                                  # 最外层：用 LAYERID
            lay([("LAYERID", str(LID_TOP)), ("ID", _g()), ("NAME", nm),
                 ("COPTHICK", _mil(cu_mil[i])), ("COMPONENTPLACEMENT", "1")])
        elif i == n_cu - 1:                         # 最外层：用 LAYERID
            lay([("LAYERID", str(LID_BOTTOM)), ("ID", _g()), ("NAME", nm),
                 ("COPTHICK", _mil(cu_mil[i])), ("COMPONENTPLACEMENT", "2")])
        else:                                       # 中间层：用 TYPE
            if kinds[i] == "plane":                 # 内电层（GND/电源）
                lay([("TYPE", "INTERNAL_PLANE"), ("ID", _g()), ("NAME", nm),
                     ("COPTHICK", _mil(cu_mil[i])),
                     ("PULLBACKDISTANCE", _mil(pullback_mil))])
            else:                                   # 信号层
                lay([("TYPE", "SIGNAL"), ("ID", _g()), ("NAME", nm),
                     ("COPTHICK", _mil(cu_mil[i])), ("COMPONENTPLACEMENT", "0")])
        if i < n_cu - 1:
            dname = f"Dielectric {i + 1}"
            if i == 0:                              # 第 1 个介质带 LAYERID
                fields = [("LAYERID", str(LID_DIEL1)), ("ID", _g()), ("NAME", dname)]
            else:                                   # 其余用 TYPE
                fields = [("TYPE", "DIELECTRIC"), ("ID", _g()), ("NAME", dname)]
            dt = diel_types[i]
            fields += [
                ("DIELTYPE", str(dt)),
                ("DIELCONST", f"{dk_fr4 if dt == 1 else dk_diel:g}"),
                ("DIELHEIGHT", _mil(diel_mil[i])),
                ("DIELMATERIAL", mat_core if dt == 1 else mat_pp),
            ]
            lay(fields)

    # ---- 底层辅助层 ----
    lay([("LAYERID", str(LID_BOT_SOLDER)), ("ID", _g()),
         ("NAME", "Bottom Solder"), ("DIELTYPE", "3"),
         ("DIELCONST", f"{dk_sr:g}"), ("DIELHEIGHT", _mil(sr_mil)),
         ("DIELMATERIAL", "Solder Resist")])
    lay([("LAYERID", str(LID_BOT_OVERLAY)), ("ID", _g()), ("NAME", "Bottom Overlay")])
    lay([("LAYERID", str(LID_BOT_PASTE)), ("ID", _g()), ("NAME", "Bottom Paste")])

    return "|".join(parts)


# ---------------------------------------------------------------- 自检
def _ref_preset(n_cu: int) -> str:
    return (r"D:\Program Files\Altium\AD22\System\LayerStackManager\Presets"
            + {2: r"\Two Layer.stackup", 4: r"\Four Layer.stackup",
               6: r"\Six Layer.stackup", 8: r"\Eight Layer.stackup",
               10: r"\10 Layer.stackup"}[n_cu])


def _key_sequence(text: str, drop_doc_tokens: bool = True) -> list[str]:
    """把文件规整成「结构指纹」：去掉具体值、GUID、层名，只留 段/层的 key 序列。

    `drop_doc_tokens=True` 时忽略 `STACKUPDOCUMENT*` ——
    自带预设没有这 3 个 token，而 **AD 真实导出的板子文件有**，
    本生成器选择保留（更贴近真实导出），故比对时两边都剔除再比。
    """
    sub = re.search(r"LAYERSUBSTACK_V8_0ID=\{([^}]+)\}", text)
    subguid = sub.group(1) if sub else "?"
    out: list[str] = []
    for tok in text.split("|"):
        if not tok:
            continue
        if drop_doc_tokens and tok.startswith("STACKUPDOCUMENT"):
            continue
        m = re.match(r"LAYER_V8_(\d+)(.*)", tok)
        if m:
            k = m.group(2).partition("=")[0]
            k = k.replace("_{" + subguid + "}", "_{S}")
            # 层名/唯一 ID 属于「值」，不进指纹
            if m.group(2).startswith("ID=") or m.group(2).startswith("NAME="):
                k = k.split("=")[0]
            out.append(f"L[{k}]")
        else:
            out.append(tok.partition("=")[0])
    return out


def selfcheck() -> int:
    fails = []

    def chk(name, cond, extra=""):
        print(("[ OK ] " if cond else "[FAIL] ") + name + (f"   {extra}" if extra else ""))
        if not cond:
            fails.append(name)

    print("--- 1) 生成的 token 形状必须与 AD 自带预设**逐 key 一致** ---")

    def ref_kinds(text: str) -> list[str]:
        """从参考预设里读出中间层的 kind（只有中间层带 TYPE=SIGNAL/INTERNAL_PLANE）。"""
        out = []
        for tok in text.split("|"):
            m = re.match(r"LAYER_V8_\d+TYPE=(SIGNAL|INTERNAL_PLANE)$", tok)
            if m:
                out.append("signal" if m.group(1) == "SIGNAL" else "plane")
        return out

    for n in (2, 4, 6, 8, 10):
        ref = open(_ref_preset(n), "rb").read().decode("utf-8-sig")
        names = [f"CU{i}" for i in range(n)]
        k = ["signal"] + ref_kinds(ref) + ["signal"]
        assert len(k) == n, f"{n}: kinds {len(k)}"
        mine = build_stackup_text(n, names, [1.4] * n, [10.0] * (n - 1), kinds=k)
        a, b = _key_sequence(ref), _key_sequence(mine)
        same = a == b
        if not same:
            diff = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y][:3]
            chk(f"{n} 铜层形状一致", False,
                f"长度 {len(a)} vs {len(b)}；首处不同 {diff}")
        else:
            chk(f"{n} 铜层形状一致（{len(a)} 个 key，中间层 kind={k[1:-1]}）", True)

    print()
    print("--- 1.5) 生成器额外带 AD 真实导出才有的 STACKUPDOCUMENT*（预设没有）---")
    mine20 = build_stackup_text(2, ["a", "b"], [1.4, 1.4], [10.0])
    chk("含 STACKUPDOCUMENTID", "STACKUPDOCUMENTID=" in mine20)
    chk("含 STACKUPDOCUMENTREVISIONID", "STACKUPDOCUMENTREVISIONID=" in mine20)
    chk("含 STACKUPDOCUMENTREVISIONDATE", "STACKUPDOCUMENTREVISIONDATE=" in mine20)
    chk("预设确实没有这 3 个 token",
        "STACKUPDOCUMENT" not in open(_ref_preset(2), "rb").read().decode("utf-8-sig"))

    print()
    print("--- 2) 生成的文件能被自家解析器读回，且层数/厚度正确 ---")
    import os
    import sys
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import stackup_file as SF
    import tempfile
    n = 20
    names = ["top"] + [f"L{i}_P" for i in range(1, n - 1)] + ["Bot"]
    cu = [2.7559] * n
    dl = [2.8, 7.874] * 10
    dl = dl[: n - 1]
    txt = build_stackup_text(n, names, cu, dl)
    p = os.path.join(tempfile.gettempdir(), "_t_build.stackup")
    with open(p, "wb") as f:
        f.write(b"\xef\xbb\xbf" + txt.encode("utf-8"))
    s = SF.Stackup(p)
    cop = [l for l in s.physical if l.is_copper]
    die = [l for l in s.physical if l.is_dielectric]
    chk(f"铜层 {n} 个", len(cop) == n, f"实得 {len(cop)}")
    chk(f"介质 {n + 1} 个（{n - 1} 段 + 上下阻焊）", len(die) == n + 1, f"实得 {len(die)}")
    chk("层名 = 传入的层名", [l.name for l in cop] == names, f"{[l.name for l in cop][:3]}…")
    chk("铜厚 = 2.7559mil", all(abs(l.thickness_mil() - 2.7559) < 1e-6 for l in cop))
    inner = die[1:-1]
    chk("内侧介质厚度 = 传入值",
        all(abs(l.thickness_mil() - g) < 1e-6 for l, g in zip(inner, dl)))
    os.remove(p)

    print()
    print("--- 3) 负数例 ---")
    for bad, why in (((1, ["a"], [1.0], []), "只有 1 个铜层"),
                     ((3, ["a", "b", "c"], [1.0], [1.0]), "铜厚个数不符"),
                     ((3, ["a", "b", "c"], [1.0] * 3, [1.0]), "介质段数不符")):
        try:
            build_stackup_text(*bad)
            chk(f"[应报错] {why}", False)
        except ValueError:
            chk(f"[应报错] {why}", True)

    print()
    print("RESULT:", "PASS" if not fails else f"FAIL({len(fails)}): {fails}")
    return 0 if not fails else 1


if __name__ == "__main__":
    import sys
    sys.exit(selfcheck())
