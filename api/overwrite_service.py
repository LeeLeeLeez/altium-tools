"""叠层覆盖 —— A 层清空 → B 层内容复制到 A（B 保留）。

移植自旧版 `overwrite_page.py` 的 `on_generate`。
"""

from __future__ import annotations

import os

import overwrite_script as OS

from . import paths

SCRIPT_DIR = paths.script_out_dir("scripts", "altium_swap")

# 复制方式：下拉显示的是**长文案**，值必须是干净 token
COPY_MODES = [
    ("api", "api       - 快；多边形由 AD 自己重铺（形状按目标层规则）"),
    ("clipboard", "clipboard - 走 AD 原生复制粘贴；铺铜随复制一起搬（较慢）"),
]

COPY_MODE_LABELS = [{"value": v, "label": lbl} for v, lbl in COPY_MODES]


def validate(a: str, b: str) -> dict:
    try:
        OS.validate_pair(a, b)
    except OS.LayerPickError as e:
        return {"ok": False, "a": a, "b": b, "error": str(e)}
    return {"ok": True, "a": a, "b": b}


def generate(a: str, b: str, repour: bool = False,
             copy_mode: str = "api") -> dict:
    if copy_mode not in ("api", "clipboard"):
        raise ValueError(f"copy_mode 只能是 api / clipboard，收到 {copy_mode!r}")
    try:
        OS.validate_pair(a, b)
    except OS.LayerPickError as e:
        raise ValueError(str(e))

    pas, prj = OS.write_script(SCRIPT_DIR, a, b, repour=repour,
                               copy_mode=copy_mode)
    body = open(pas, "rb").read().decode("ascii")

    log = [
        f"已生成：\n   {pas}\n   {prj}",
        f"   层 A {a}（清空后接收 B 的内容）\n   层 B {b}（保持不变）",
        f"   复制方式：{copy_mode}",
        "   重新铺铜：%s%s" % (
            "ON  —— 多边形会按目标层 connect style 重算"
            if repour else "OFF —— 搬过来的铺铜形状原样保留",
            "" if repour else "（默认）"),
        f"   .pas {len(body)} 字节，纯 ASCII / CRLF",
        f"下一步：AD 里 File → Run Script… → "
        f"{os.path.basename(prj)} → OverwriteLayer",
    ]
    return {
        "ok": True,
        "pasPath": pas,
        "prjPath": prj,
        "stem": os.path.splitext(os.path.basename(pas))[0],
        "repour": repour,
        "repourMode": "REPOUR" if repour else "NO-REPOUR",
        "copyMode": copy_mode,
        "bytes": len(body),
        "encoding": "ascii",
        "lineEnding": "crlf",
        "procedure": "OverwriteLayer",
        "reportFile": "overwrite_layer_report.txt",
        "log": log,
    }


def preview(path: str) -> dict:
    try:
        with open(path, "rb") as f:
            body = f.read().decode("ascii", errors="replace")
    except OSError as e:
        raise ValueError(f"读取失败: {e}")
    return {"ok": True, "path": path, "body": body}
