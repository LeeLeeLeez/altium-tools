#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Altium 工具集（GUI）

界面风格遵循本机统一规范：tkinter/ttk 现代浅色（clam 深度定制），
左侧竖排图标侧边栏 + 分组，所有大内容区可拖拽调尺寸，输入写 JSON 配置持久化。

左侧分组
--------
- 原理图操作   （当前为占位，后续在此分类下加页）
- PCB 操作      → 「画中点短线」：内部 2 个 tab —— 画竖直短线 / 画水平短线
                → 「叠层设计」
                → 「层交换」

运行（必须用系统 Python 3.12，隔离 venv 的 3.13 没有 tkinter）
--------------------------------------------------------------
    "C:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python312\\python.exe" main.py
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import tkinter as tk
from tkinter import ttk

import gui_style as gs
import altium_bridge as ab
import midpoint_tab as MT
import stackup_page as SP
import swap_page as SWP

CFG_PATH = os.path.join(_HERE, "altium_tools_config.json")

DEFAULTS = {
    "y0": 6337.0,          # 短线起点 Y (mil)
    "length": 39.0,        # 长度 (mil)  39 mil ≈ 0.9906 mm
    "width": 4.0,          # 线宽 (mil)
    "layer": "",           # 空 = 跟随选中线所在层
}



# ====================================================================== 主程序
class App:
    def __init__(self):
        self.cfg = gs.load_json_cfg(CFG_PATH, DEFAULTS)
        for k, v in DEFAULTS.items():
            self.cfg.setdefault(k, v)

        self.app = gs.init("Altium 工具集", size=(1180, 780),
                           minsize=(960, 620), appid="WorkBuddy.AltiumTools")
        self.app.protocol("WM_DELETE_WINDOW", self._on_close)

        self._bridge: ab.AltiumBridge | None = None
        self.mid_tabs: dict = {}

        self.nav = gs.sidebar(self.app)
        self.nav.pack(fill="both", expand=True)

        # 状态栏
        tk.Frame(self.app, bg=gs.PALETTE["border"], height=1).pack(fill="x",
                                                                  side="bottom")
        bar = ttk.Frame(self.app)
        bar.pack(fill="x", side="bottom")
        self.lbl_status = ttk.Label(bar, text="就绪", style="Status.TLabel")
        self.lbl_status.pack(side="left", padx=10, pady=4)


        # ---------------- 分组 1：原理图操作 ----------------
        self.pg_sch = ttk.Frame(self.nav.body)
        self.nav.add(self.pg_sch, text="概览", icon="code", group="原理图操作")
        self._build_schematic_placeholder(self.pg_sch)

        # ---------------- 分组 2：PCB 操作 ----------------
        self.pg_mid = ttk.Frame(self.nav.body)
        self.nav.add(self.pg_mid, text="画中点短线", icon="layers", group="PCB 操作")
        self._build_midpoint_page(self.pg_mid)

        self.pg_stk = ttk.Frame(self.nav.body)
        self.nav.add(self.pg_stk, text="叠层设计", icon="quilt", group="PCB 操作")
        self.stk = SP.StackupDesignPage(self.pg_stk, self, log_fn=self._log)
        self.stk.pack(fill="both", expand=True)

        # 层交换：层名下拉来自「叠层设计」页点过「确认叠层」之后的层名
        self.pg_swap = ttk.Frame(self.nav.body)
        self.nav.add(self.pg_swap, text="层交换", icon="equalizer", group="PCB 操作")
        self.swp = SWP.SwapPage(self.pg_swap, self, self.stk, log_fn=self._log)
        self.swp.pack(fill="both", expand=True)

        self.nav.select(1)          # 默认停在「画中点短线」

    # ============================================================ 原理图占位页
    def _build_schematic_placeholder(self, page: ttk.Frame):
        wrap = ttk.Frame(page, padding=(18, 16))
        wrap.pack(fill="both", expand=True)
        ttk.Label(wrap, text="原理图操作", style="Title.TLabel").pack(anchor="w")
        ttk.Label(wrap, text="本分类下的功能待添加。",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 0))
        box = gs.card(wrap, "规划中的功能")
        box.pack(fill="both", expand=True, pady=(14, 0))
        ttk.Label(
            box,
            justify="left", style="Muted.TLabel",
            text=("• 符号 / 器件批量处理\n"
                  "• 网络与连线检查\n"
                  "• 参数表导入导出\n\n"
                  "（新增页面：把新的 ttk.Frame 加到 nav.body，\n"
                  "  再用 nav.add(..., group=\"原理图操作\") 即可。）"),
        ).pack(anchor="w", padx=14, pady=12)

    # ============================================================ PCB · 画中点
    def _build_midpoint_page(self, page: ttk.Frame):
        """「画中点短线」页：内部两个 tab —— 画竖直短线 / 画水平短线。"""
        wrap = ttk.Frame(page, padding=(14, 12))
        wrap.pack(fill="both", expand=True)

        nb = ttk.Notebook(wrap)
        nb.pack(fill="both", expand=True)
        self.nb_mid = nb
        self.mid_tabs = {}
        for orient, text in (("v", "画竖直短线"), ("h", "画水平短线")):
            tab = MT.MidpointTab(nb, self, orient)
            nb.add(tab, text=text)
            tab.load_cfg(self.cfg)
            self.mid_tabs[orient] = tab

    # ============================================================ 桥接 / 状态
    def bridge(self) -> ab.AltiumBridge:
        """懒加载共享的桥接实例（两个中点 tab 共用同一条连接）。"""
        if self._bridge is None:
            self._bridge = ab.AltiumBridge()
        return self._bridge

    def set_status(self, text: str):
        lbl = getattr(self, "lbl_status", None)
        if lbl is not None:
            lbl.configure(text=text)

    def after(self, ms: int, fn):
        """让子页面能往主线程排回调。

        App 自身**不是** widget（根窗口在 self.app），所以不能直接 after()；
        这里转发一层，子页面写 self.app.after(...) 即可。
        """
        return self.app.after(ms, fn)

    def active_mid_tab(self):
        """当前正在显示的中点 tab（竖直/水平）。"""
        try:
            return self.mid_tabs["vh"[self.nb_mid.index("current")]]
        except Exception:
            return None

    def _log(self, msg: str):
        """给「叠层设计」「层交换」页当 log_fn：转投到当前显示的中点 tab 日志。"""
        tab = self.active_mid_tab()
        line = (msg.splitlines()[0][:120] if msg and msg.splitlines() else "")
        if tab is not None:
            tab.log(msg)
        if line:
            self.set_status(line)

    # ============================================================ 杂项
    def _save_cfg(self):
        # ⚠️ 与「叠层设计」「层交换」页共用同一个 JSON ⇒ **读-合并-写**，
        #    别整段覆盖。两个中点 tab 各存各的键。
        cfg = gs.load_json_cfg(CFG_PATH, {})
        for t in self.mid_tabs.values():
            cfg.update(t.save_cfg())
        gs.save_json_cfg(CFG_PATH, cfg)

    def _on_close(self):
        self._save_cfg()
        try:
            self.stk.save_cfg()
        except Exception:
            pass
        try:
            cfg = gs.load_json_cfg(CFG_PATH, {})
            cfg.update(self.swp.save_cfg())
            gs.save_json_cfg(CFG_PATH, cfg)
        except Exception:
            pass
        try:
            if self._bridge is not None:
                self._bridge.close()
        except Exception:
            pass
        self.app.destroy()

    def run(self):
        self.app.mainloop()


def main() -> int:
    App().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
