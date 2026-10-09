#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Altium 叠层文件（*.stackup）解析 / 批量改厚 —— **共用逻辑层**。

CLI 薄封装见 `scripts/stackup_edit.py`；GUI 见同目录 `main.py` 的「叠层设计」页。
（沿用项目既有模式：逻辑放这里共用，CLI 只做参数解析，避免两份实现走散。）

为什么用它
----------
改 PCB 层叠原先只能靠 UIA 逐格写 Layer Stack Manager 的 WPF 网格，
而读一次网格要 57~66 秒（describe_window depth=9）。

Altium 的 LSM 自带**叠层文件**通道（本机 AD25 实测，命令定义见
System/Altium.LayerStackManager.rcs）：

    File 菜单：  Load Stackup From File...   (PLLSM:LoadTemplateFromFile)
                 Save As...                  (PLLSM:SaveCopyToFile)
                 Save to PCB                 (PLLSM:Save)
                 Export CSV...               (PLLSM:ExportCsv)
    Tools 菜单： Presets -> Open Preset %1   (PLLSM:OpenPreset)

快路径 = **导出 -> 改文本 -> 导入**。

铜层厚度存了「三份」，必须同时改
--------------------------------
    COPTHICK          引擎字段
    $LSM$Thickness    <- LSM 网格 Thickness 列读它
    $LSM$Weight       <- LSM 网格 Weight 列读它（枚举 0.5/1/1.5/2/3...）
介质层两份：DIELHEIGHT + $LSM$Thickness。
只改 COPTHICK 的实测后果：导入后界面上 Thickness 与 Weight 一个都不变。

导入这一步 MCP 驱动不了（实测「打开」按钮按不动）=> 固定交用户手动。
PcbDoc 本体是 DLP 密文（幻数 %TSD-Hea）=> 不能离线改 PcbDoc。

自检
----
    python stackup_file.py --check
"""

from __future__ import annotations

import argparse
import os
import re
import sys

# 1 oz 铜 = 35 µm（与 Altium 层叠面板一致；1.5oz=0.0525mm、2oz=0.07mm、3oz=0.105mm）
OZ_TO_MM = 0.035
MIL_TO_MM = 0.0254

_LAYER_RE = re.compile(r"^LAYER_V8_(\d+)(.*)$")


# ---------------------------------------------------------------- 单位换算
def to_mil(text: str) -> float:
    """把 '0.0525mm' / '1.4mil' / '1.5oz' 统一换算成 mil。"""
    s = str(text).strip().lower().replace(" ", "")
    m = re.match(r"^([0-9.]+)(mm|mil|um|µm|oz|in)?$", s)
    if not m:
        raise ValueError(f"无法识别的厚度写法: {text!r}")
    v = float(m.group(1))
    u = m.group(2) or "mil"
    if u == "mm":
        return v / MIL_TO_MM
    if u == "mil":
        return v
    if u in ("um", "µm"):
        return v / 1000.0 / MIL_TO_MM
    if u == "in":
        return v * 1000.0
    if u == "oz":
        return v * OZ_TO_MM / MIL_TO_MM
    raise ValueError(f"不支持的单位: {u}")


def fmt_mil(v: float) -> str:
    """mil 数值 → 简洁字符串（去掉多余小数）。"""
    s = f"{v:.4f}".rstrip("0").rstrip(".")
    return s or "0"


# ---------------------------------------------------------------- 铜厚 / Weight
# 1 oz = 0.035 mm = 1.37795 mil（该板文件里实测 1oz ↔ COPTHICK=1.378mil，一致）
_STD_OZ = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 5.0, 6.0,
           8.0, 10.0, 12.0, 14.0, 20.0]


def oz_to_mil(oz: float) -> float:
    return oz * OZ_TO_MM / MIL_TO_MM


def oz_of_mil(mil: float, tol: float = 0.01):
    """mil → 最接近的标准盎司数；超出容差返回 None。"""
    for oz in _STD_OZ:
        if abs(oz_to_mil(oz) - mil) <= max(tol, mil * 0.005):
            return oz
    return None


def weight_text(text: str, mil: float):
    """决定 `$LSM$Weight` 该写什么。

    - 用户直接写 `2oz` ⇒ 就用它。
    - 写 `0.07mm` / `2.7559mil` ⇒ 换算后若能对上标准盎司（容差 1%）才写，
      否则返回 None（**不硬写**：Weight 是枚举列，写非标准值会被静默规整）。
    """
    s = str(text).strip().lower().replace(" ", "")
    if s.endswith("oz"):
        try:
            return f"{float(s[:-2]):g}oz"
        except ValueError:
            return None
    oz = oz_of_mil(mil)
    return None if oz is None else f"{oz:g}oz"


# ---------------------------------------------------------------- 解析
class Layer:
    """一个物理层的 `LAYER_V8_<n>*` token 组。

    ⚠️ 修改必须**同时写回 Stackup.parts**（真正参与输出的那一份），
    否则 `Stackup.text()` 仍会输出旧值 —— 这正是本模块踩过的坑。
    """

    __slots__ = ("idx", "tokens", "start", "end", "_stk")

    def __init__(self, idx: int, stk: "Stackup", start: int, end: int):
        self.idx = idx
        self._stk = stk
        self.start = start
        self.end = end
        self.tokens = []        # [[key, value, part_index], ...]

    # -- 取值 --
    def get(self, field: str, default=None):
        for k, v, _ in self.tokens:
            if k == field:
                return v
        return default

    def set(self, field: str, value: str) -> bool:
        """改字段值。

        🔴 必须保留 token 的**完整前缀**（`LAYER_V8_35`）——只换 `=` 之后的部分。
        曾经直接写成 `f"{key}={value}"`，结果 `LAYER_V8_35COPTHICK=1.4mil`
        被替换成 `COPTHICK=2.7559mil`，前缀丢失 ⇒ 该层从叠层里**整个消失**
        （8 铜层变 7 铜层，层数被静默改掉）。
        """
        for t in self.tokens:
            if t[0] == field:
                i = t[2]
                prefix = self._stk.parts[i].split("=", 1)[0]
                self._stk.parts[i] = f"{prefix}={value}"
                t[1] = value
                return True
        return False

    # -- 分类 --
    @property
    def name(self) -> str:
        return self.get("NAME", "") or ""

    @property
    def layer_id(self) -> str:
        return self.get("LAYERID", "") or ""

    @property
    def is_copper(self) -> bool:
        return self.get("COPTHICK") is not None

    @property
    def is_dielectric(self) -> bool:
        return self.get("DIELHEIGHT") is not None

    @property
    def is_physical(self) -> bool:
        return self.is_copper or self.is_dielectric

    def thickness_mil(self):
        if self.is_copper:
            raw = self.get("COPTHICK")
        elif self.is_dielectric:
            raw = self.get("DIELHEIGHT")
        else:
            return None
        try:
            return to_mil(raw)
        except ValueError:
            return None

    def lsm_thickness_mil(self):
        """LSM 网格 Thickness 列读的那个字段（`$LSM$Thickness`）。"""
        raw = self.get("$LSM$Thickness")
        if raw is None:
            return None
        try:
            return to_mil(raw)
        except ValueError:
            return None

    def weight(self):
        """LSM 网格 Weight 列读的那个字段（`$LSM$Weight`），是枚举字符串。"""
        return self.get("$LSM$Weight")

    def sync_state(self) -> str:
        """`ok` / `MISMATCH(...)` / `n/a`。"""
        a, b = self.thickness_mil(), self.lsm_thickness_mil()
        if b is None:
            return "n/a"
        if a is None:
            return f"MISMATCH(无主字段, LSM={b:g})"
        if abs(a - b) > 0.01:
            return f"MISMATCH(主={a:g} LSM={b:g})"
        return "ok"

    def set_thickness(self, text: str) -> dict:
        """写厚度。

        🔴 铜层的厚度在叠层文件里存了**三份**，必须一起写，否则 LSM 界面不跟着变：
            `COPTHICK`          —— 引擎字段
            `$LSM$Thickness`    —— **LSM 网格 Thickness 列读它**
            `$LSM$Weight`       —— **LSM 网格 Weight 列读它**（枚举：0.5/1/1.5/2/3…）
        介质层两份：`DIELHEIGHT` + `$LSM$Thickness`。

        （只改 `COPTHICK` 的后果已实测：导入后 LSM 里 Thickness 与 Weight 纹丝不动，
          表现为「只有部分层生效、weight 与 thickness 对不上」。）
        """
        mil = to_mil(text)
        t = f"{fmt_mil(mil)}mil"
        done: dict = {}
        if self.is_copper:
            done["COPTHICK"] = self.set("COPTHICK", t)
            done["$LSM$Thickness"] = self.set("$LSM$Thickness", t)
            w = weight_text(text, mil)
            done["$LSM$Weight"] = self.set("$LSM$Weight", w) if w else None
        elif self.is_dielectric:
            done["DIELHEIGHT"] = self.set("DIELHEIGHT", t)
            done["$LSM$Thickness"] = self.set("$LSM$Thickness", t)
        else:
            raise ValueError(f"层 {self.name!r} 既非铜层也非介质，不能设厚度")
        return done

    def __repr__(self):
        return f"<Layer {self.idx} {self.name!r} {'铜' if self.is_copper else '介质'}>"


class Stackup:
    def __init__(self, path: str):
        self.path = path
        raw = open(path, "rb").read()
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        self.parts = text.split("|")        # parts[0] 通常为 ''（首个 '|' 之前）
        self._group_layers()

    def _group_layers(self):
        self.layers: list[Layer] = []
        by_idx: dict[int, Layer] = {}
        for i, p in enumerate(self.parts):
            m = _LAYER_RE.match(p)
            if not m:
                continue
            rest = m.group(2)
            if "=" not in rest:
                continue
            idx = int(m.group(1))
            key, _, val = rest.partition("=")
            lay = by_idx.get(idx)
            if lay is None:
                lay = Layer(idx, self, i, i + 1)
                by_idx[idx] = lay
                self.layers.append(lay)
            else:
                lay.end = i + 1
            lay.tokens.append([key, val, i])

    # -- 视图 --
    @property
    def physical(self) -> list[Layer]:
        """按层序号升序返回叠层里的物理层（铜 + 介质）。"""
        return [l for l in sorted(self.layers, key=lambda x: x.idx)
                if l.is_physical]

    def describe(self) -> str:
        out = [f"文件: {os.path.basename(self.path)}",
               f"铜层 {sum(1 for l in self.layers if l.is_copper)} 个, "
               f"介质 {sum(1 for l in self.layers if l.is_dielectric)} 个", ""]
        out.append(f"{'#':>3} {'层名':<22}{'类型':<6}{'厚度(mil)':>10}"
                   f"{'厚度(mm)':>11} {'Weight':>7}  {'同步':<22}{'Dk':<6}{'材料'}")
        out.append("-" * 106)
        total = 0.0
        for n, l in enumerate(self.physical, 1):
            t = l.thickness_mil()
            if t is not None:
                total += t
            kind = "铜" if l.is_copper else "介质"
            mm = f"{t * MIL_TO_MM:.4f}" if t is not None else ""
            dk = l.get("DIELCONST", "") if l.is_dielectric else ""
            mat = l.get("DIELMATERIAL", "") if l.is_dielectric else ""
            w = (l.weight() or "") if l.is_copper else ""
            out.append(f"{n:>3} {l.name:<22}{kind:<6}"
                       f"{(fmt_mil(t) if t is not None else ''):>10}{mm:>11} "
                       f"{w:>7}  {l.sync_state():<22}{dk:<6}{mat}")
        out.append("-" * 106)
        out.append(f"合计厚度 {fmt_mil(total)} mil = {total * MIL_TO_MM:.4f} mm")
        bad = [l.name for l in self.physical if l.sync_state().startswith("MISMATCH")]
        if bad:
            out.append(f"⚠️ {len(bad)} 个层的主字段与 $LSM$Thickness 不一致: "
                       + ", ".join(bad))
        return "\n".join(out)

    # -- 选层 --
    def resolve(self, sel: str) -> list[Layer]:
        """选择器：'#3' 第3个物理层 / 'L3' 铜层第3个 / 精确层名 / 正则。"""
        sel = sel.strip()
        phys = self.physical
        if sel.startswith("#"):
            k = int(sel[1:])
            if not 1 <= k <= len(phys):
                raise SystemExit(f"物理层序号越界: {sel}（共 {len(phys)} 层）")
            return [phys[k - 1]]
        m = re.fullmatch(r"[Ll](\d+)", sel)
        if m:
            coppers = [l for l in phys if l.is_copper]
            k = int(m.group(1))
            if not 1 <= k <= len(coppers):
                raise SystemExit(f"铜层序号越界: {sel}（共 {len(coppers)} 个铜层）")
            return [coppers[k - 1]]
        hits = [l for l in phys if l.name == sel]
        if hits:
            return hits
        try:
            rx = re.compile(sel)
            hits = [l for l in phys if rx.search(l.name)]
        except re.error as e:
            raise SystemExit(f"选择器既不是层名也不是合法正则: {sel!r} ({e})")
        if not hits:
            raise SystemExit(f"没有层匹配 {sel!r}。现有层："
                             + ", ".join(l.name for l in phys))
        return hits

    # -- 写盘 --
    def blob(self) -> bytes:
        data = "|".join(self.parts)
        if self.bom:
            data = "\ufeff" + data
        return data.encode("utf-8")

    def save(self, out_path: str) -> tuple[bool, int]:
        blob = self.blob()
        old = open(self.path, "rb").read()
        with open(out_path, "wb") as f:
            f.write(blob)
        return blob != old, len(blob)


# ---------------------------------------------------------------- 自检
PRESET_DIR = (r"D:\Program Files\Altium\AD22\System"
              r"\LayerStackManager\Presets")
# 真实工程导出的叠层文件放这儿（含 $LSM$* 字段，与自带预设结构不同）
BOARD_DIR = r"E:\AI_model\800_6_VPDB\stackup"


def selfcheck() -> int:
    """往返一致性 + 改值真实生效 + 不污染原文件 + 阴性对照。"""
    import glob
    import tempfile

    files = sorted(glob.glob(os.path.join(PRESET_DIR, "*.stackup")))
    if not files:
        print(f"找不到预设文件: {PRESET_DIR}")
        return 1
    fails = []

    def chk(name, cond):
        print(("[ OK ] " if cond else "[FAIL] ") + name)
        if not cond:
            fails.append(name)

    print("--- 1) 未改动往返必须逐字节相同 ---")
    for f in files:
        s = Stackup(f)
        same = s.blob() == open(f, "rb").read()
        phys = s.physical
        cop = sum(1 for l in phys if l.is_copper)
        die = sum(1 for l in phys if l.is_dielectric)
        print(("[ OK ] " if same else "[FAIL] ")
              + f"{os.path.basename(f):<22} 铜{cop:>3} 介质{die:>3} "
                f"物理{len(phys):>3}  {len(s.blob())} B")
        if not same:
            fails.append(f)

    print()
    print("--- 2) 改值必须真实生效（写到临时文件再解析回来读）---")
    src = files[4] if len(files) > 4 else files[0]      # Eight Layer
    tmp = os.path.join(tempfile.gettempdir(), "_t_stackup_check.stackup")
    s = Stackup(src)
    target_cop = next(l for l in s.physical if l.is_copper)
    target_die = next(l for l in s.physical if l.is_dielectric)
    cop_before = target_cop.thickness_mil()
    die_before = target_die.thickness_mil()
    cop_name, die_name = target_cop.name, target_die.name
    target_cop.set_thickness("2oz")          # -> 2.7559 mil
    target_die.set_thickness("0.2mm")        # -> 7.874 mil
    changed, size = s.save(tmp)
    chk("改动后 blob 与原文不同", changed)

    s2 = Stackup(tmp)
    got_cop = next(l for l in s2.physical if l.name == cop_name).thickness_mil()
    got_die = next(l for l in s2.physical if l.name == die_name).thickness_mil()
    chk(f"重新解析铜层 {cop_name!r} 读回 2oz "
        f"({cop_before:.4f} -> {got_cop:.4f} mil, 期望 2.7559)",
        abs(got_cop - to_mil("2oz")) < 0.01)
    chk(f"重新解析介质 {die_name!r} 读回 0.2mm "
        f"({die_before:.4f} -> {got_die:.4f} mil, 期望 7.8740)",
        abs(got_die - to_mil("0.2mm")) < 0.01)
    # 🔴 回归断言：改厚度绝不能改变层数（曾因丢 LAYER_V8_<n> 前缀导致整层消失）
    n_before = len(s.physical)
    n_after = len(s2.physical)
    c_before = sum(1 for l in s.physical if l.is_copper)
    c_after = sum(1 for l in s2.physical if l.is_copper)
    chk(f"改厚度后层数不变（物理 {n_before}->{n_after}, "
        f"铜 {c_before}->{c_after}）",
        n_before == n_after and c_before == c_after)
    chk("改厚度后所有层名保持原样",
        [l.name for l in s.physical] == [l.name for l in s2.physical])

    print()
    print("--- 3) 原预设不得被污染 ---")
    chk("原文件字节未变（我们只写临时文件）",
        Stackup(src).blob() == open(src, "rb").read())

    print()
    print("--- 3.5) 真实工程叠层（带 $LSM$* 字段）三份厚度必须同步 ---")
    import glob as _glob
    board = [f for f in _glob.glob(os.path.join(BOARD_DIR, "*.stackup"))
             if "allCu" not in os.path.basename(f)]
    if not board:
        print(f"  （跳过：{BOARD_DIR} 下没有工程叠层文件）")
    else:
        bf = board[0]
        sb = Stackup(bf)
        print(f"  源: {os.path.basename(bf)}  "
              f"铜 {sum(1 for l in sb.physical if l.is_copper)} 个")
        base_bad = [l.name for l in sb.physical
                    if l.sync_state().startswith("MISMATCH")]
        chk(f"基线（未改动）主字段与 $LSM$Thickness 已同步（不一致: {base_bad}）",
            not base_bad)

        tmp2 = os.path.join(tempfile.gettempdir(), "_t_board_sync.stackup")
        coppers = [l for l in sb.physical if l.is_copper]
        n_cop = len(coppers)
        for l in coppers:
            l.set_thickness("2oz")
        sb.save(tmp2)
        sb2 = Stackup(tmp2)
        c2 = [l for l in sb2.physical if l.is_copper]
        chk(f"铜层数不变（{n_cop} -> {len(c2)}）", n_cop == len(c2))
        bad_t = [l.name for l in c2
                 if abs((l.thickness_mil() or 0) - to_mil("2oz")) > 0.01]
        bad_s = [l.name for l in c2
                 if abs((l.lsm_thickness_mil() or 0) - to_mil("2oz")) > 0.01]
        bad_w = [l.name for l in c2 if (l.weight() or "") != "2oz"]
        chk(f"全部铜层 COPTHICK == 2oz（不符: {bad_t}）", not bad_t)
        chk(f"全部铜层 $LSM$Thickness == 2oz（不符: {bad_s}）", not bad_s)
        chk(f"全部铜层 $LSM$Weight == 2oz（不符: {bad_w}）", not bad_w)
        chk("改后 sync_state 全为 ok",
            all(not l.sync_state().startswith("MISMATCH")
                for l in sb2.physical))
        chk("原工程文件字节未变",
            Stackup(bf).blob() == open(bf, "rb").read())
        if os.path.exists(tmp2):
            os.remove(tmp2)

    print()
    print("--- 4) 阴性对照 ---")
    s3 = Stackup(src)
    chk("[阴性对照] 什么都不改时 blob 必须等于原文",
        s3.blob() == open(src, "rb").read())
    s3.physical[0].set_thickness("9oz")
    chk("[阴性对照] 改一个字段后 blob 必须不再等于原文",
        s3.blob() != open(src, "rb").read())
    try:
        s3.resolve("绝对不存在的层名")
        chk("[阴性对照] 不存在的层名应当报错", False)
    except SystemExit:
        chk("[阴性对照] 不存在的层名正确报错", True)

    if os.path.exists(tmp):
        os.remove(tmp)

    print()
    print("RESULT:", "PASS" if not fails else f"FAIL({len(fails)}): {fails}")
    return 0 if not fails else 1


# ---------------------------------------------------------------- 入口
def _argv_check() -> bool:
    """`--check` / `-c` 走自检；无参数时给出提示。"""
    import argparse
    ap = argparse.ArgumentParser(description="Altium 叠层文件解析/改厚（共用逻辑层）")
    ap.add_argument("--check", "-c", action="store_true", help="跑自检")
    args = ap.parse_args()
    if not args.check:
        ap.print_help()
        return False
    return True


if __name__ == "__main__":
    import sys
    # 让 `python stackup_file.py --check` 可用（CLI 薄封装见 scripts/stackup_edit.py）
    sys.exit(selfcheck() if _argv_check() else 0)
