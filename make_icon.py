#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 AltiumTools 的程序图标 `altium_tools.ico`（多尺寸）。

为什么要有这个脚本（而不是塞一个二进制 ico 进仓库）
----------------------------------------------------
1. 可复现：配色/形状改一行就能重出，不依赖某次手工绘图。
2. 本项目已有"生成物必须能由生成器重建"的规矩，图标同理。
3. 尺寸档位是**显式**的，避免"16px 下糊成一团"这种事后才发现的问题。

图标含义
--------
蓝底圆角方（GUI 主色 #2563EB→#1D4ED8）+ 三条白色铜层 + 中间一条过孔把三层串起来。
即"叠层 + 过孔"，正是这套工具在干的事。三条层比两条更能在 16px 下读出"层"。

用法
----
    <系统Python3.12> make_icon.py                 # 生成 altium_tools.ico
    <系统Python3.12> make_icon.py --preview       # 另存 _icon_preview.png 便于肉眼验收
    <系统Python3.12> make_icon.py --out D:\\x.ico

依赖：Pillow。**只在打包/出图时用到，运行期不需要**（spec 里 PIL 属于 excludes，
运行期图标走 .ico + Tk iconbitmap，见 main.py）。
"""
from __future__ import annotations

import argparse
import os
import sys

from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "altium_tools.ico")

# 与 gui_style.PALETTE 取同值，勿随意改
ACCENT_TOP = (37, 99, 235)      # #2563EB
ACCENT_BOT = (29, 78, 216)      # #1D4ED8
WHITE = (255, 255, 255, 255)    # 铜层
HOLE = (23, 62, 173, 255)       # 过孔孔壁（比底色更深，16px 下才看得出"孔"）

# Windows 会按场景挑：16 任务栏小图 / 32 标题栏 / 48 资源管理器 / 256 大图标
SIZES = [16, 20, 24, 32, 40, 48, 64, 128, 256]
SS = 4                          # 超采样倍率，先大后缩才有抗锯齿


def _rounded_mask(size: int, radius: int) -> Image.Image:
    m = Image.new("L", (size, size), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, size - 1, size - 1],
                                        radius=radius, fill=255)
    return m


def _vgradient(size: int) -> Image.Image:
    g = Image.new("RGB", (1, size))
    px = g.load()
    for y in range(size):
        t = y / max(1, size - 1)
        px[0, y] = tuple(
            int(round(ACCENT_TOP[i] + (ACCENT_BOT[i] - ACCENT_TOP[i]) * t))
            for i in range(3)
        )
    return g.resize((size, size), Image.NEAREST)


def render(size: int = 256) -> Image.Image:
    """画出 size×size 的图标（内部按 SS 倍超采样）。"""
    S = size * SS
    # ---- 底：圆角 + 竖向渐变 ----
    bg = _vgradient(S).convert("RGBA")
    bg.putalpha(_rounded_mask(S, int(S * 0.21)))

    d = ImageDraw.Draw(bg)

    # ---- 三条铜层：白条，圆端，等宽等厚 ----
    # 几何按比例定义，保证任何尺寸下比例一致。
    # 第 1 版做过"三层 + 一条竖条穿过"，预览后发现 16px 下读起来像不等号/树，
    # 改成"三层 + 中间一个过孔环（donut）"——轮廓更闭合，小尺寸更清楚。
    bar_w = S * 0.66
    bar_h = S * 0.12
    x0 = (S - bar_w) / 2.0
    gap = S * 0.07
    y_top = S * 0.5 - (3 * bar_h + 2 * gap) / 2.0
    ys = [y_top + i * (bar_h + gap) for i in range(3)]
    for y in ys:
        d.rounded_rectangle([x0, y, x0 + bar_w, y + bar_h],
                            radius=bar_h / 2.0, fill=WHITE)

    # ---- 过孔：中间那层正中的深色钻孔 ----
    # 第 2 版试过"环（白环+深芯）"，预览发现外径会跟上下的层粘在一起、像朵花；
    # 且 16px 下环径只剩 1px 出头。改成**单颗深色钻孔**：轮廓简单、缩放稳。
    cy = ys[1] + bar_h / 2.0
    cx = S / 2.0
    r = bar_h * 0.46
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=HOLE)

    return bg.resize((size, size), Image.LANCZOS)


def build(out: str = DEFAULT_OUT, preview: bool = False) -> str:
    master = render(256)

    # 逐尺寸重画（比单纯缩放 256 在 16/20px 下更利落）
    frames = [render(s) for s in SIZES]
    frames[-1].save(out, format="ICO",
                    sizes=[(s, s) for s in SIZES], append_images=frames[:-1])
    # ICO 的权威写法：用最大帧 save + append_images + sizes
    master.save(out, format="ICO", sizes=[(s, s) for s in SIZES])

    if preview:
        pv = os.path.join(HERE, "_icon_preview.png")
        sheet = Image.new("RGBA", (256 + 3 * 48 + 40, 256), (245, 247, 250, 255))
        sheet.paste(master, (0, 0), master)
        x = 256 + 16
        for s in (48, 32, 16):
            sheet.paste(render(s), (x, 8), render(s))
            x += s + 12
        sheet.save(pv)
        print("preview:", pv)

    return out


def check(path: str) -> int:
    """校验：文件存在、是 ICO、且含全部期望尺寸。"""
    if not os.path.isfile(path):
        print("FAIL: 没生成", path)
        return 1
    raw = open(path, "rb").read()
    if raw[:4] != b"\x00\x00\x01\x00":
        print("FAIL: 不是 ICO 头", raw[:4])
        return 1
    n = int.from_bytes(raw[4:6], "little")
    got = []
    for i in range(n):
        off = 6 + i * 16
        w = raw[off] or 256
        got.append(w)
    ok = sorted(got) == sorted(SIZES)
    print("ICO 尺寸档位:", sorted(got), "->", "OK" if ok else "与期望不符 %s" % SIZES)
    print("大小: %.1f KB" % (len(raw) / 1024.0))
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="生成 altium_tools.ico")
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--preview", action="store_true",
                    help="另存 _icon_preview.png，便于肉眼验收")
    a = ap.parse_args(argv)
    p = build(a.out, a.preview)
    print("written:", p)
    return check(p)


if __name__ == "__main__":
    sys.exit(main())
