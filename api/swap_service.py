"""层交换 —— 生成 AD 的 DelphiScript（.pas + .PrjScr）。

移植自旧版 `swap_page.py` 的 `_on_pick` / `on_generate`。
脚本本身由 `swap_script.py` 生成（它没有 tkinter 依赖），这里只做校验 + 落盘 + 日志。
"""

from __future__ import annotations

import os

import swap_script as SS

from . import paths

SCRIPT_DIR = paths.script_out_dir("scripts", "altium_swap")


def validate(a: str, b: str) -> dict:
    """层名 → AD 层符号，并检查 A/B 不能相同。"""
    try:
        sa, sb = SS.validate_pair(a, b)
    except SS.LayerPickError as e:
        return {"ok": False, "a": a, "b": b, "error": str(e)}
    return {"ok": True, "a": a, "b": b, "symA": sa, "symB": sb,
            "map": f"{a} → {sa}\n{b} → {sb}"}


def generate(a: str, b: str) -> dict:
    """生成交换脚本，返回落盘路径与日志。"""
    try:
        sa, sb = SS.validate_pair(a, b)
    except SS.LayerPickError as e:
        raise ValueError(str(e))

    pas, prj = SS.write_script(SCRIPT_DIR, a, b)
    body = open(pas, "rb").read().decode("ascii")
    picks = body.count("If TryPick(")

    log = [
        f"✅ 已生成：\n   {pas}\n   {prj}",
        f"   层 A {a} → {sa}\n   层 B {b} → {sb}\n"
        f"   中转候选 {picks} 个（已自动跳过 A/B）\n"
        f"   .pas {os.path.getsize(pas)} B，纯 ASCII / CRLF",
        f"→ 下一步：AD 里 File → Run Script… → "
        f"{os.path.basename(prj)} → SwapLayers",
    ]
    return {
        "ok": True,
        "pasPath": pas,
        "prjPath": prj,
        "stem": os.path.splitext(os.path.basename(pas))[0],
        "symA": sa,
        "symB": sb,
        "candidates": picks,
        "bytes": os.path.getsize(pas),
        "encoding": "ascii",
        "lineEnding": "crlf",
        "procedure": "SwapLayers",
        "reportFile": "swap_layers_report.txt",
        "log": log,
    }


def preview(path: str) -> dict:
    """读回脚本内容（给前端做预览）。"""
    try:
        with open(path, "rb") as f:
            body = f.read().decode("ascii", errors="replace")
    except OSError as e:
        raise ValueError(f"读取失败: {e}")
    return {"ok": True, "path": path, "body": body}
