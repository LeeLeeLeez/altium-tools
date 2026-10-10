#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI「叠层覆盖」页 —— 把 A 层内容删除、把 B 层内容复制到 A 层，B 层保留。

骨架与「层交换」页一致：读取**当前 PCB 的真实叠层**（层名 + 铜厚）填 A/B 下拉，
再生成 DelphiScript（带时间戳文件名）交给 AD 运行。
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox

import gui_style as gs
import overwrite_script as OS

_HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT_DIR = os.path.join(os.path.dirname(os.path.dirname(_HERE)),
                          "scripts", "altium_swap")


class OverwritePage(ttk.Frame):
    def __init__(self, master, app, stk_page, log_fn=None):
        super().__init__(master)
        self.app = app
        self.stk = stk_page
        self.log = log_fn or (lambda s: None)
        self.names = []
        self.stack_rows = []
        self._build()

    # ------------------------------------------------------------ 界面
    def _build(self):
        outer = ttk.Frame(self, padding=(14, 12))
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="叠层覆盖", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="A 层清空 -> B 层内容复制到 A 层，B 层保留",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))

        # 注意：ttk.PanedWindow 没有 -sashwidth / -sashrelief（那是 tk.PanedWindow 的）
        pw = ttk.PanedWindow(outer, orient="vertical")
        pw.pack(fill="both", expand=True, pady=(12, 0))

        top = ttk.Frame(pw)
        pw.add(top, weight=0)
        card = gs.card(top, "① 选层（建议先读板子）")
        card.pack(fill="x")

        self.lbl_state = ttk.Label(
            card, text="尚未读取叠层 —— 请先点「读取当前 PCB 叠层」",
            style="Muted.TLabel", wraplength=900, justify="left")
        self.lbl_state.pack(anchor="w", padx=12, pady=(8, 10))

        grid = ttk.Frame(card)
        grid.pack(fill="x", padx=12)
        ttk.Label(grid, text="层 A（被覆盖 / 会被清空）").grid(
            row=0, column=0, sticky="w", pady=4)
        self.v_a = tk.StringVar()
        self.cb_a = ttk.Combobox(grid, textvariable=self.v_a, width=24,
                                 state="disabled")
        self.cb_a.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=4)

        ttk.Label(grid, text="层 B（来源 / 保留不动）").grid(
            row=1, column=0, sticky="w", pady=4)
        self.v_b = tk.StringVar()
        self.cb_b = ttk.Combobox(grid, textvariable=self.v_b, width=24,
                                 state="disabled")
        self.cb_b.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=4)

        self.v_repour = tk.BooleanVar(value=False)
        self.chk_repour = ttk.Checkbutton(
            grid,
            text="重新铺铜（按目标层规则重算；不勾选 = 保留搬过来的铺铜形状）",
            variable=self.v_repour)
        self.chk_repour.grid(row=2, column=0, columnspan=2, sticky="w",
                             pady=(8, 0))

        btns = ttk.Frame(card)
        btns.pack(fill="x", padx=12, pady=(10, 12))
        self.btn_read = ttk.Button(btns, text="读取当前 PCB 叠层",
                                   command=self.on_read_stack)
        self.btn_read.pack(side="left")
        self.btn_gen = ttk.Button(btns, text="生成覆盖脚本",
                                  style="Accent.TButton",
                                  command=self.on_generate)
        self.btn_gen.pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="打开脚本目录",
                   command=self.on_open_dir).pack(side="left", padx=(8, 0))

        ttk.Label(card, text=(
            "生成的是一份 DelphiScript（文件名带时间戳）：到 AD 里 "
            "File → Run Script… 选刚生成的那个 .PrjScr，过程名 OverwriteLayer。\n"
            "跑完先看计数（A 应等于原 B 的数量、B 不变），确认无误再按 Ctrl+S 保存。"),
            style="Muted.TLabel", justify="left").pack(fill="x", padx=12,
                                                       pady=(0, 12))

        bottom = ttk.Frame(pw)
        pw.add(bottom, weight=1)
        lcard = gs.card(bottom, "输出")
        lcard.pack(fill="both", expand=True)
        tw = ttk.Frame(lcard)
        tw.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.txt = tk.Text(tw, height=10, wrap="word", state="disabled",
                           **gs.text_kw())
        sb = ttk.Scrollbar(tw, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _say(self, msg):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")
        self.log(msg)

    # ------------------------------------------------------------ 读板子叠层
    def on_read_stack(self):
        try:
            self.btn_read.configure(state="disabled")
        except Exception:
            pass
        self.app.set_status("读取 PCB 叠层 …")
        try:
            br = self.app.bridge()
            r = br.layer_stackup()
        except Exception as e:
            self.btn_read.configure(state="normal")
            self.app.set_status("读取叠层失败")
            self._say("读取叠层失败：%s: %s" % (type(e).__name__, e))
            messagebox.showerror("读取叠层失败",
                                 "%s: %s\n\n请确认 AD 已打开 .PcbDoc "
                                 "且桥接轮询在运行。" % (type(e).__name__, e))
            return
        self.btn_read.configure(state="normal")
        if isinstance(r, dict) and r.get("_error"):
            self._say("桥接返回错误：%s" % r["_error"])
            return
        rows = (r or {}).get("layers") or []
        if not rows:
            self._say("板子没返回叠层信息（可能没有打开 .PcbDoc）")
            return

        copper = [x for x in rows
                  if float(x.get("copper_thickness_mils") or 0) > 0]
        copper.sort(key=lambda x: int(x.get("order") or 0))
        names = [str(x.get("name") or "") for x in copper]
        self.names, self.stack_rows = names, copper

        self.cb_a.configure(values=names, state="readonly")
        self.cb_b.configure(values=names, state="readonly")
        self.btn_gen.configure(state="normal")
        board = (r or {}).get("board_name") or "(未知板)"
        self.lbl_state.configure(
            text="来源：当前 PCB 实测 —— %s，共 %d 个铜层" % (board, len(names)))

        self._say("已读取当前 PCB 叠层：%s" % board)
        for i, x in enumerate(copper):
            self._say("     %2d. %-10s 铜厚 %.4f mil"
                      % (i + 1, x.get("name"),
                         float(x.get("copper_thickness_mils") or 0)))
        if self.v_a.get() not in names:
            self.v_a.set(names[0] if names else "")
        if self.v_b.get() not in names or self.v_b.get() == self.v_a.get():
            self.v_b.set(names[1] if len(names) > 1
                         else (names[0] if names else ""))
        self.app.set_status("叠层已读取")

    # ------------------------------------------------------------ 生成脚本
    def on_generate(self):
        a, b = self.v_a.get(), self.v_b.get()
        try:
            OS.validate_pair(a, b)
        except OS.LayerPickError as e:
            messagebox.showerror("层选择不合法", str(e))
            self._say("层选择不合法：%s" % e)
            return
        try:
            repour = bool(self.v_repour.get())
            pas, prj = OS.write_script(SCRIPT_DIR, a, b, repour=repour)
        except Exception as e:
            messagebox.showerror("生成失败", "%s" % e)
            self._say("生成失败: %s" % e)
            return
        body = open(pas, "rb").read().decode("ascii")
        self._say("已生成：\n   %s\n   %s" % (pas, prj))
        self._say("   层 A %s（清空后接收 B 的内容）\n   层 B %s（保持不变）"
                  % (a, b))
        self._say("   重新铺铜：%s%s"
                  % ("ON  —— 多边形会按目标层 connect style 重算"
                     if repour else "OFF —— 搬过来的铺铜形状原样保留",
                     "" if repour else "（默认）"))
        self._say("   .pas %d 字节，纯 ASCII / CRLF" % len(body))
        self._say("下一步：AD 里 File → Run Script… → %s → OverwriteLayer"
                  % os.path.basename(prj))

    def on_open_dir(self):
        try:
            os.makedirs(SCRIPT_DIR, exist_ok=True)
            os.startfile(SCRIPT_DIR)
        except Exception as e:
            self._say("打开目录失败: %s" % e)

    def refresh_layers(self):
        if not self.names:
            self.cb_a.configure(values=[], state="disabled")
            self.cb_b.configure(values=[], state="disabled")
            self.btn_gen.configure(state="disabled")

    # ------------------------------------------------------------ 配置
    def save_cfg(self):
        return {"ow_a": self.v_a.get(), "ow_b": self.v_b.get()}

    def load_cfg(self, cfg):
        if cfg.get("ow_a"):
            self.v_a.set(cfg["ow_a"])
        if cfg.get("ow_b"):
            self.v_b.set(cfg["ow_b"])
