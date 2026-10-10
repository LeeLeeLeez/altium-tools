#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI「层交换」页 —— 把两层的图元互换，落地成可执行的 DelphiScript。

与「叠层设计」页的关系
----------------------
本页**只从已确认的叠层设计**里取层名：

    叠层设计页 → 点「确认叠层」 → 本页下拉才有内容

未确认时两个下拉禁用并给出提示 —— 因为层名必须来自用户认可的叠层，
而不是随手从板上猜一个。

工作方式
--------
点「生成交换脚本」→ 写出 `scripts/altium_swap/swap_layers.pas` + `.PrjScr`
（层符号由层名映射而来）→ **用户到 AD 里 File > Run Script 手动执行**。
桥接无法代跑任意脚本函数，这一步只能人工。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk, messagebox

import gui_style as gs
import swap_script as SS

SCRIPT_DIR = r"E:\AI_model\800_6_VPDB\scripts\altium_swap"


class SwapPage(ttk.Frame):
    """「层交换」页面。构造时传入叠层设计页，用于读取已确认的层名。"""

    def __init__(self, master, app, stk_page, log_fn=None):
        ttk.Frame.__init__(self, master)
        self.app = app
        self.stk = stk_page
        self.log = log_fn or (lambda m: None)
        self.names: list[str] = []
        self._build()
        # 叠层设计一旦确认/失效，本页跟着刷新
        self.stk.add_confirm_listener(self.refresh_layers)
        self.refresh_layers()

    # ================================================================ 构建
    def _build(self):
        outer = ttk.Frame(self, padding=(14, 12))
        outer.pack(fill="both", expand=True)
        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="层交换", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="把两层铜箔上的全部图元互换（排除 via / board cutout / 元件）",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))

        pw = gs.paned(outer, orient="h")
        pw.pack(fill="both", expand=True, pady=(12, 0))
        left = ttk.Frame(pw)
        pw.add(left, minsize=340)
        right = ttk.Frame(pw)
        pw.add(right, minsize=380)

        # ---------------- 左：层选择 ----------------
        card = gs.card(left, "层选择")
        card.pack(fill="x")
        self.lbl_state = ttk.Label(card, text="—", style="Muted.TLabel",
                                   wraplength=460, justify="left")
        self.lbl_state.pack(anchor="w", padx=12, pady=(8, 10))

        grid = ttk.Frame(card)
        grid.pack(fill="x", padx=12)
        ttk.Label(grid, text="层 A（原始）").grid(row=0, column=0, sticky="w", pady=4)
        self.v_a = tk.StringVar()
        self.cb_a = ttk.Combobox(grid, textvariable=self.v_a, width=22, state="disabled")
        self.cb_a.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=4)
        self.cb_a.bind("<<ComboboxSelected>>", lambda e: self._on_pick())

        ttk.Label(grid, text="层 B（目标）").grid(row=1, column=0, sticky="w", pady=4)
        self.v_b = tk.StringVar()
        self.cb_b = ttk.Combobox(grid, textvariable=self.v_b, width=22, state="disabled")
        self.cb_b.grid(row=1, column=1, sticky="w", padx=(10, 0), pady=4)
        self.cb_b.bind("<<ComboboxSelected>>", lambda e: self._on_pick())

        self.lbl_map = ttk.Label(card, text="", style="Muted.TLabel",
                                 wraplength=460, justify="left")
        self.lbl_map.pack(anchor="w", padx=12, pady=(8, 0))
        ttk.Label(card, text="中转层由脚本自动挑选（第一个空闲的 MidLayer）",
                  style="Muted.TLabel").pack(anchor="w", padx=12, pady=(2, 0))

        btns = ttk.Frame(card)
        btns.pack(fill="x", padx=12, pady=(10, 12))
        self.btn_gen = ttk.Button(btns, text="生成交换脚本", style="Accent.TButton",
                                  command=self.on_generate, state="disabled")
        self.btn_gen.pack(side="left")
        self.btn_read = ttk.Button(self.btn_gen.master,
                                   text="读取当前 PCB 叠层",
                                   command=self.on_read_stack)
        self.btn_read.pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="打开脚本目录",
                   command=self.on_open_dir).pack(side="left", padx=(8, 0))

        note = gs.card(left, "执行方式（必须人工）")
        note.pack(fill="x", pady=(10, 0))
        ttk.Label(note, justify="left", wraplength=460, style="Muted.TLabel",
                  text="1. 在 AD 里先只打开目标 .PcbDoc\n"
                       "2. File → Run Script… → 选刚生成的那个 .PrjScr\n"
                       "3. 过程名选 SwapLayers\n"
                       "4. 核对弹窗上的层名与数量，再按 OK\n"
                       "5. Ctrl+S 保存；不满意就 Ctrl+Z\n\n"
                       "脚本会先把 A 层图元搬到中转层，再把 B 层搬到 A，\n"
                       "最后把中转层搬到 B —— 中转是为了避免两层互相打架。"
                  ).pack(anchor="w", padx=12, pady=(8, 12))

        # ---------------- 右：日志 / 预览 ----------------
        lcard = gs.card(right, "生成结果 / 预览")
        lcard.pack(fill="both", expand=True)
        tw = ttk.Frame(lcard)
        tw.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.txt = tk.Text(tw, height=20, wrap="word", state="disabled", **gs.text_kw())
        sb = ttk.Scrollbar(tw, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def _say(self, msg: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")
        self.log(msg)

    # ================================================================ 刷新
    def refresh_layers(self):
        """从叠层设计页拉取已确认的层名；未确认则禁用。"""
        names = list(getattr(self.stk, "confirmed_names", None) or [])
        self.names = names
        if not names:
            self.cb_a.configure(values=[], state="disabled")
            self.cb_b.configure(values=[], state="disabled")
            self.btn_gen.configure(state="disabled")
            self.lbl_state.configure(
                text="⚠️ 尚未确认叠层 —— 请先到「叠层设计」页，"
                     "点第二列下方的「确认叠层」，本页才能读到层名。")
            self._say("层名来源失效：叠层设计未确认（或设计已改动）。")
            return
        self.cb_a.configure(values=names, state="readonly")
        self.cb_b.configure(values=names, state="readonly")
        self.btn_gen.configure(state="normal")
        self.lbl_state.configure(
            text=f"来源：叠层设计已确认，共 {len(names)} 个铜层"
                 f"（{names[0]} … {names[-1]}）")
        # 默认：A = 第一层(top)，B = 名字里带 L1 的那个
        if self.v_a.get() not in names:
            self.v_a.set(names[0])
        if self.v_b.get() not in names or self.v_b.get() == self.v_a.get():
            cand = next((n for n in names if n.startswith("L1")), None)
            if cand is None or cand == self.v_a.get():
                cand = names[1] if len(names) > 1 else names[0]
            self.v_b.set(cand)
        self._on_pick()

    def _on_pick(self):
        a, b = self.v_a.get(), self.v_b.get()
        if a not in self.names or b not in self.names:
            self.lbl_map.configure(text="")
            return
        try:
            sa = SS.symbol_for_name(a)
            sb = SS.symbol_for_name(b)
        except SS.LayerPickError as e:
            self.lbl_map.configure(text=f"⚠️ {e}")
            self.btn_gen.configure(state="disabled")
            return
        if sa == sb:
            self.lbl_map.configure(text="⚠️ 两个层不能相同")
            self.btn_gen.configure(state="disabled")
            return
        self.btn_gen.configure(state="normal")
        self.lbl_map.configure(text=f"{a} → {sa}\n{b} → {sb}")

    # ================================================================ 生成
    def on_generate(self):
        a, b = self.v_a.get(), self.v_b.get()
        try:
            sa, sb = SS.validate_pair(a, b)
        except SS.LayerPickError as e:
            messagebox.showerror("层选择不合法", str(e))
            self._say(f"❌ {e}")
            return
        try:
            pas, prj = SS.write_script(SCRIPT_DIR, a, b)
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("生成失败", f"{e}")
            self._say(f"❌ 生成失败: {e}")
            return
        body = open(pas, "rb").read().decode("ascii")
        picks = body.count("If TryPick(")
        self._say(f"✅ 已生成：\n   {pas}\n   {prj}")
        self._say(f"   层 A {a} → {sa}\n   层 B {b} → {sb}\n"
                  f"   中转候选 {picks} 个（已自动跳过 A/B）\n"
                  f"   .pas {os.path.getsize(pas)} B，纯 ASCII / CRLF")
        self._say(f"→ 下一步：AD 里 File → Run Script… → {os.path.basename(prj)} → SwapLayers")
        messagebox.showinfo("已生成",
                            f"已写出脚本：\n{pas}\n\n"
                            f"层 A：{a}  ({sa})\n层 B：{b}  ({sb})\n\n"
                            f"请在 AD 里 File → Run Script… 选 {os.path.basename(prj)}，\n"
                            f"过程名 SwapLayers。")

    # ================================================================ 读板子叠层
    def on_read_stack(self):
        """读【当前 PCB】的真实叠层（各铜层 + 层名 + 铜厚），用它填 A/B 下拉。

        为什么要读板子而不是只信叠层设计：
          层名是叠层设计重命名过的，名字里的数字 **不等于** 栈内位置，
          也不等于 AD 的 MidLayer 序号。只有读板子才知道哪个名字对应哪一层。
        """
        try:
            self.btn_read.configure(state="disabled")
        except Exception:
            pass
        self.app.set_status("读取 PCB 叠层 …")
        try:
            br = self.app.bridge()
            r = br.layer_stackup()
        except Exception as e:                      # noqa: BLE001
            self.btn_read.configure(state="normal")
            self.app.set_status("读取叠层失败")
            self._say(f"❌ 读取叠层失败：{type(e).__name__}: {e}")
            messagebox.showerror(
                "读取叠层失败",
                f"{type(e).__name__}: {e}\n\n"
                "请确认 AD 已打开电路板（.PcbDoc）并处于活动状态，"
                "且桥接轮询在运行。")
            return
        self.btn_read.configure(state="normal")

        if isinstance(r, dict) and r.get("_error"):
            self._say(f"❌ 桥接返回错误：{r['_error']}")
            return
        rows = (r or {}).get("layers") or []
        if not rows:
            self._say("❌ 板子没返回叠层信息（可能没有打开 .PcbDoc）")
            return

        # 只取铜层（介质层 copper_thickness_mils = 0），按 order 排
        copper = [x for x in rows
                  if float(x.get("copper_thickness_mils") or 0) > 0]
        copper.sort(key=lambda x: int(x.get("order") or 0))
        names = [str(x.get("name") or "") for x in copper]
        self.stack_names = names
        self.stack_rows = copper

        self.cb_a.configure(values=names, state="readonly")
        self.cb_b.configure(values=names, state="readonly")
        self.btn_gen.configure(state="normal")

        board = (r or {}).get("board_name") or "(未知板)"
        self.lbl_state.configure(
            text=f"来源：**当前 PCB 实测** —— {board}，共 {len(names)} 个铜层")

        self._say(f"✅ 已读取当前 PCB 叠层：{board}")
        self._say(f"   共 {len(rows)} 层，其中铜层 {len(copper)} 个：")
        for i, x in enumerate(copper):
            self._say("     %2d. %-10s 铜厚 %.4f mil"
                      % (i + 1, x.get("name"), float(x.get("copper_thickness_mils") or 0)))

        # 当前 A/B 若不在板子上，明确警告（之前的错就出在这里）
        bad = [n for n in (self.v_a.get(), self.v_b.get()) if n and n not in names]
        if bad:
            self._say("   ⚠️ 当前选中的 %s 不在本板叠层里 —— 已改为板上的名字"
                      % "、".join(bad))
        if self.v_a.get() not in names:
            self.v_a.set(names[0])
        if self.v_b.get() not in names or self.v_b.get() == self.v_a.get():
            self.v_b.set(names[1] if len(names) > 1 else names[0])
        self._on_pick()
        self.app.set_status("叠层已读取")

    def on_open_dir(self):
        try:
            os.makedirs(SCRIPT_DIR, exist_ok=True)
            os.startfile(SCRIPT_DIR)          # noqa: S606  (Windows only)
        except Exception as e:  # noqa: BLE001
            self._say(f"⚠️ 打开目录失败: {e}")

    # ================================================================ 配置
    def save_cfg(self) -> dict:
        return {"swap_a": self.v_a.get(), "swap_b": self.v_b.get()}

    def load_cfg(self, cfg: dict):
        if isinstance(cfg, dict):
            if cfg.get("swap_a"):
                self.v_a.set(cfg["swap_a"])
            if cfg.get("swap_b"):
                self.v_b.set(cfg["swap_b"])
            self._on_pick()
