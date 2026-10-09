#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUI「叠层设计」页 —— 把叠层计算 + `.stackup` 文件读写固化在一起。

组合的两块能力
--------------
1. **叠层设计计算**（`stackup_design.py`，一比一复刻
   `matrix_transformer_design.html` 的「🎛 PCB 叠层与板厚」）：
   层序列 P/S/A/B/G → 板厚 / 仿真厚度 / MMF / 原副边界面数。
2. **真实板子对接**（`stackup_file.py`）：读 AD 导出的 `.stackup`，
   把设计结果写回新文件，再由用户在 LSM 里导入。

层命名（用户指定）
------------------
铜层名体现「层号 + 网络」：`top` - `L1_B` - `L2_A` - … - `Bot`

面板结构
--------
    左  叠层参数（层数 / GND 位置 / 整流 / 铜厚模式 / 介质）
    中  逐层表（类型 + 铜厚）+ 色块条
    右  计算结果 + 与 AD 板子对接 + 日志
"""

from __future__ import annotations

import math
import os
import tkinter as tk
from tkinter import ttk, messagebox

import gui_style as gs
import stackup_design as D
import stackup_file as SF
import stackup_build as BK

# 类型 → 色块颜色（沿用 HTML 的分层配色思路）
TYPE_COLOR = {
    "P": "#2563EB",   # 原边 蓝
    "S": "#16A34A",   # 副边 绿
    "A": "#0EA5E9",   # 副边A 青
    "B": "#14B8A6",   # 副边B 青绿
    "G": "#6B7280",   # GND 灰
}
TYPE_LABEL = {"P": "P 原边", "S": "S 副边", "A": "A 副边A", "B": "B 副边B", "G": "G GND"}
TYPE_FROM_LABEL = {v: k for k, v in TYPE_LABEL.items()}

CU_CHOICES = [D.cu_oz_text(x) for x in D.CU_OZ_OPTIONS]      # ['0.33','0.5','1','2','3','4']


def _fmt_mm(um: float) -> str:
    return f"{um / 1000.0:.4f}"


class _ScrollBox(ttk.Frame):
    """可滚动的纵向容器（ttk 没有现成的）。"""

    def __init__(self, master, **kw):
        ttk.Frame.__init__(self, master, **kw)
        self.canvas = tk.Canvas(self, bg=gs.PALETTE["surface"],
                                highlightthickness=0, bd=0)
        vs = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=vs.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.inner = ttk.Frame(self.canvas)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner)
        self.canvas.bind("<Configure>", self._on_canvas)
        # 鼠标滚轮
        self.canvas.bind_all("<MouseWheel>", self._on_wheel, add="+")

    def _on_inner(self, _e=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas(self, e):
        self.canvas.itemconfigure(self._win, width=e.width)

    def _on_wheel(self, e):
        try:
            if self.canvas.winfo_ismapped():
                self.canvas.yview_scroll(int(-e.delta / 120), "units")
        except Exception:
            pass


class MMFCanvas(tk.Canvas):
    """MMF 分布图（复刻 HTML `mtxStkDrawMMF` L806，方向按本工具「顶层在上」）。

    - 纵轴 = 层序（第 1 层在最上，与左侧层表一致；HTML 是底在上，数值不受影响）
    - 横轴 = 安匝 MMF，范围 ±Mmax，Mmax = 各状态 peak × 1.2
    - 每个状态一条折线：从 `(MMF=0, 顶边)` 起，逐层连到该层累积 MMF；全波 2 条、全桥 1 条
    """

    PAD_L, PAD_R, PAD_T, PAD_B = 46, 12, 12, 28
    COLORS = ("#111827", "#6B7280")
    DASHES = (None, (6, 4))

    def __init__(self, master, height: int = 190, **kw):
        tk.Canvas.__init__(self, master, height=height, bd=0,
                           highlightthickness=0, bg=gs.PALETTE["surface"], **kw)
        self._data = None
        self.bind("<Configure>", lambda e: self._redraw())

    def set_data(self, seq, mmf_result):
        self._data = (list(seq), mmf_result)
        self._redraw()

    def clear(self):
        self._data = None
        self._redraw()

    def _redraw(self):
        self.delete("all")
        W = max(self.winfo_width(), 140)
        H = max(self.winfo_height(), 110)
        p = gs.PALETTE
        if not self._data:
            self.create_text(W / 2, H / 2, text="（无 MMF 数据）", fill=p["muted"])
            return
        seq, m = self._data
        L = len(seq)
        plotW = W - self.PAD_L - self.PAD_R
        plotH = H - self.PAD_T - self.PAD_B
        if L == 0 or plotW < 30 or plotH < 30:
            return
        th = plotH / L
        peaks = [st.get("peak", 0.0) for st in m.get("states", [])]
        Mmax = max(peaks + [0.0]) * 1.2
        Mmax = max(Mmax, 1.0)

        def x(v):
            return self.PAD_L + (v + Mmax) / (2 * Mmax) * plotW

        def yc(i):
            return self.PAD_T + i * th + th / 2

        # 横向层分隔线
        for i in range(1, L):
            y = self.PAD_T + i * th
            self.create_line(self.PAD_L, y, self.PAD_L + plotW, y, fill="#F0F2F5")
        # 纵向网格
        for g in range(-int(math.ceil(Mmax)), int(math.ceil(Mmax)) + 1):
            self.create_line(x(g), self.PAD_T, x(g), self.PAD_T + plotH, fill="#EEF1F5")
        # 零线
        self.create_line(x(0), self.PAD_T, x(0), self.PAD_T + plotH,
                         fill="#C7CCD4", dash=(4, 3))
        # 各状态折线
        states = m.get("states", [])
        for si, st in enumerate(states):
            pts = [x(0), self.PAD_T]
            for i, v in enumerate(st.get("mmfAfter", [])):
                pts += [x(v), yc(i)]
            self.create_line(*pts, fill=self.COLORS[si % 2], width=2,
                             dash=self.DASHES[si % 2])
        # 层号
        for i in range(L):
            self.create_text(self.PAD_L - 6, yc(i), text=str(i + 1), anchor="e",
                             fill=p["muted"], font=(gs.FONT_FAMILY, 7))
        tiny = (gs.FONT_FAMILY, 7)
        self.create_text(x(0), self.PAD_T + plotH + 12, text="0", fill=p["muted"],
                         font=tiny, anchor="center")
        self.create_text(x(Mmax), self.PAD_T + plotH + 12, text=f"+{Mmax:.0f}",
                         fill=p["muted"], font=tiny, anchor="center")
        self.create_text(x(-Mmax), self.PAD_T + plotH + 12, text=f"-{Mmax:.0f}",
                         fill=p["muted"], font=tiny, anchor="center")
        # 图例
        lx = self.PAD_L + 4
        for si in range(len(states)):
            ly = self.PAD_T + 6 + si * 12
            self.create_line(lx, ly, lx + 18, ly, fill=self.COLORS[si % 2], width=2,
                             dash=self.DASHES[si % 2])
            self.create_text(lx + 24, ly, anchor="w", font=tiny, fill=p["muted"],
                             text=("状态 1（正半周）" if si == 0 else "状态 2（负半周）")
                             if len(states) > 1 else "全桥（单态）")


class StackupDesignPage(ttk.Frame):
    """「叠层设计」页面。放在侧边栏 PCB 操作 分组下。"""

    def __init__(self, master, app, log_fn=None):
        ttk.Frame.__init__(self, master)
        self.app = app
        self.log = log_fn or (lambda m: None)
        # 逐层数据
        self.seq: list[str] = []
        self.cu_oz: list[float] = []
        self._rows: list[dict] = []
        self._src_file: str | None = None      # 读入的模板 .stackup
        self._src_layers = None
        self._strip_labels: list[str] = []
        self._strip_h = 360
        # 「确认叠层」状态：None = 未确认（层交换页读不到层名）
        self.confirmed_names = None
        self.confirmed_seq = None
        self.confirm_listeners = []
        self._build()

    # ================================================================ 构建
    def _build(self):
        outer = ttk.Frame(self, padding=(14, 12))
        outer.pack(fill="both", expand=True)
        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="叠层设计", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="层序列 P/S/A/B/G → 板厚 · 仿真厚度 · MMF    "
                             "层名规则：top - L1_x - … - Bot",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))

        pw = gs.paned(outer, orient="h")
        pw.pack(fill="both", expand=True, pady=(12, 0))

        left = ttk.Frame(pw)
        pw.add(left, minsize=250)
        mid = ttk.Frame(pw)
        pw.add(mid, minsize=330)
        right = ttk.Frame(pw)
        pw.add(right, minsize=300)

        self._build_params(left)
        # 中列最下方：确认叠层（确认后「层交换」页才能读到层名）
        bar = ttk.Frame(mid)
        bar.pack(side="bottom", fill="x", pady=(8, 0))
        self.btn_confirm = ttk.Button(bar, text="确认叠层", style="Accent.TButton",
                                      command=self.confirm_design)
        self.btn_confirm.pack(side="left")
        self.lbl_confirm = ttk.Label(
            bar, text="未确认 —— 点左侧按钮固定当前叠层", style="Muted.TLabel")
        self.lbl_confirm.pack(side="left", padx=(10, 0))

        midp = gs.paned(mid, orient="v")
        midp.pack(fill="both", expand=True)
        t1 = ttk.Frame(midp)
        midp.add(t1, minsize=200)
        t2 = ttk.Frame(midp)
        midp.add(t2, minsize=190)
        self._build_table(t1)
        self._build_mmf(t2)
        self._build_right(right)

        self._load_cfg()
        self.rebuild(keep_edits=False)

    # ---------------------------------------------------------------- 左：参数
    def _build_params(self, host):
        card = gs.card(host, "叠层参数")
        card.pack(fill="both", expand=True)
        g = ttk.Frame(card)
        g.pack(fill="x", padx=12, pady=(8, 4))

        self.v = {}
        def row(r, label, key, default, width=8, hint=""):
            ttk.Label(g, text=label).grid(row=r, column=0, sticky="w", pady=3, padx=(0, 8))
            var = tk.StringVar(value=str(default))
            ttk.Entry(g, textvariable=var, width=width).grid(row=r, column=1, sticky="w", pady=3)
            self.v[key] = var
            if hint:
                ttk.Label(g, text=hint, style="Muted.TLabel").grid(
                    row=r, column=2, sticky="w", padx=(8, 0))

        row(0, "原边层数 Lp", "Lp", 8)
        row(1, "副边层数 Ls", "Ls", 8)
        row(2, "GND 层数 Lgnd", "Lgnd", 2)
        row(3, "GND 位置", "gnd", "", width=12, hint="逗号分隔；留空=自动取顶/底")

        ttk.Label(g, text="整流方式").grid(row=4, column=0, sticky="w", pady=(6, 3))
        self.v_rect = tk.StringVar(value="fullwave")
        rf = ttk.Frame(g)
        rf.grid(row=4, column=1, columnspan=2, sticky="w", pady=(6, 3))
        ttk.Radiobutton(rf, text="全波", value="fullwave",
                        variable=self.v_rect, command=self._on_param).pack(side="left")
        ttk.Radiobutton(rf, text="全桥", value="fullbridge",
                        variable=self.v_rect, command=self._on_param).pack(side="left", padx=(8, 0))

        row(5, "原边匝数 Np", "Np", 8, hint="须整除 Lp")
        row(6, "副边匝数 Ns", "Ns", 4, hint="须整除 Larm")

        ttk.Separator(card).pack(fill="x", padx=12, pady=8)
        cm = ttk.Frame(card)
        cm.pack(fill="x", padx=12)
        ttk.Label(cm, text="铜厚模式").pack(anchor="w")
        self.v_cumode = tk.StringVar(value="global")
        cmf = ttk.Frame(cm)
        cmf.pack(anchor="w", pady=(2, 6))
        for val, txt in (("global", "按原副边"), ("perlayer", "逐层单独指定")):
            ttk.Radiobutton(cmf, text=txt, value=val, variable=self.v_cumode,
                            command=self._on_cumode).pack(side="left", padx=(0, 8))

        self.f_cu = ttk.Frame(card)
        self.f_cu.pack(fill="x", padx=12)
        for i, (key, label, default) in enumerate(
                (("ozP", "原边铜厚", "2"), ("ozS", "副边铜厚", "2"), ("ozG", "GND 铜厚", "4"))):
            ttk.Label(self.f_cu, text=label).grid(row=i, column=0, sticky="w", pady=2, padx=(0, 8))
            var = tk.StringVar(value=default)
            cb = ttk.Combobox(self.f_cu, textvariable=var, values=CU_CHOICES,
                              width=10, state="readonly")
            cb.grid(row=i, column=1, sticky="w", pady=2)
            cb.bind("<<ComboboxSelected>>", lambda e: self._on_param())
            self.v[key] = var

        ttk.Separator(card).pack(fill="x", padx=12, pady=8)
        dm = ttk.Frame(card)
        dm.pack(fill="x", padx=12, pady=(0, 6))
        ttk.Label(dm, text="层间距 (µm)").grid(row=0, column=0, columnspan=2, sticky="w")
        for i, (key, label, default) in enumerate(
                (("dPP", "P–P", "200"), ("dSS", "副边/GND–副边", "300"),
                 ("dPS", "P–副边", "150")), start=1):
            ttk.Label(dm, text=label).grid(row=i, column=0, sticky="w", pady=2, padx=(0, 8))
            var = tk.StringVar(value=default)
            ttk.Entry(dm, textvariable=var, width=10).grid(row=i, column=1, sticky="w", pady=2)
            self.v[key] = var

        btns = ttk.Frame(card)
        btns.pack(fill="x", padx=12, pady=(8, 12))
        ttk.Button(btns, text="重建叠层序列", style="Accent.TButton",
                   command=lambda: self.rebuild(keep_edits=False)).pack(side="left")
        ttk.Button(btns, text="按原副边同步铜厚",
                   command=self._sync_cu).pack(side="left", padx=(8, 0))

    # ---------------------------------------------------------------- 中：逐层表
    def _build_table(self, host):
        card = gs.card(host, "叠层序列（自上而下：top → Bot）")
        card.pack(fill="both", expand=True)

        hdr = ttk.Frame(card)
        hdr.pack(fill="x", padx=12, pady=(8, 2))
        for txt, w in (("#", 4), ("层名", 12), ("类型", 12), ("铜厚", 10), ("下方介质 µm", 11)):
            ttk.Label(hdr, text=txt, style="Muted.TLabel", width=w, anchor="w").pack(side="left")

        body = ttk.Frame(card)
        body.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.box = _ScrollBox(body)
        self.box.pack(side="left", fill="both", expand=True)
        strip_wrap = ttk.Frame(body)
        strip_wrap.pack(side="left", fill="y", padx=(8, 0))
        ttk.Label(strip_wrap, text="色块", style="Muted.TLabel").pack(anchor="n")
        self.strip = tk.Canvas(strip_wrap, width=54, height=420, bd=0,
                               highlightthickness=0, bg=gs.PALETTE["surface"])
        self.strip.pack(fill="y", expand=True)
        self.lbl_strip = ttk.Label(strip_wrap, text="", style="Muted.TLabel",
                                   wraplength=150, justify="left")
        self.lbl_strip.pack(anchor="w", pady=(4, 0))

    def _clear_rows(self):
        for w in self.box.inner.winfo_children():
            w.destroy()
        self._rows.clear()

    # ---------------------------------------------------------------- 中下：MMF 图
    def _build_mmf(self, host):
        card = gs.card(host, "MMF 磁动势分布（纵轴=层序 顶→底，横轴=安匝）")
        card.pack(fill="both", expand=True)
        self.mmf = MMFCanvas(card, height=190)
        self.mmf.pack(fill="both", expand=True, padx=12, pady=(8, 12))

    # ---------------------------------------------------------------- 右：结果
    def _build_right(self, host):
        card = gs.card(host, "计算结果")
        card.pack(fill="x")
        self.lbl_res = ttk.Label(card, text="—", justify="left", style="Card.TLabel")
        self.lbl_res.pack(anchor="w", padx=12, pady=(8, 10))

        fcard = gs.card(host, "与 AD 板子对接")
        fcard.pack(fill="x", pady=(10, 0))
        self.lbl_file = ttk.Label(fcard, text="未读入模板 —— 写出时将「从零生成」", style="Muted.TLabel",
                                  wraplength=280, justify="left")
        self.lbl_file.pack(anchor="w", padx=12, pady=(8, 6))
        fb = ttk.Frame(fcard)
        fb.pack(fill="x", padx=12, pady=(0, 12))
        ttk.Button(fb, text="读入 .stackup", command=self.on_open_stackup).pack(side="left")
        ttk.Button(fb, text="写出 .stackup", style="Accent.TButton",
                   command=self.on_write_stackup).pack(side="left", padx=(8, 0))
        ttk.Label(fcard,
                  text="模板可选：读入 LSM 导出的 .stackup ⇒ 保留板子的材料/过孔跨度等设置；\n"
                       "不读入也能写出（从零生成，用 AD 预设形状 + 本工具默认材料）。",
                  style="Muted.TLabel", wraplength=300, justify="left").pack(
            anchor="w", padx=12, pady=(0, 6))
        ttk.Label(fcard, text="流程：调设计 → 写出 → LSM 里 File→Load Stackup From File 导入",
                  style="Muted.TLabel", wraplength=300, justify="left").pack(
            anchor="w", padx=12, pady=(0, 10))

        lcard = gs.card(host, "日志")
        lcard.pack(fill="both", expand=True, pady=(10, 0))
        tw = ttk.Frame(lcard)
        tw.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.txt = tk.Text(tw, height=8, wrap="word", state="disabled", **gs.text_kw())
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

    # ================================================================ 参数读写
    def _num(self, key, default=0.0):
        try:
            return float(self.v[key].get())
        except (ValueError, KeyError):
            return default

    def _int(self, key, default=0):
        try:
            return int(float(self.v[key].get()))
        except (ValueError, KeyError):
            return default

    def _params(self) -> dict:
        return dict(
            Lp=max(0, self._int("Lp", 8)), Ls=max(0, self._int("Ls", 8)),
            Lgnd=max(0, self._int("Lgnd", 2)), gnd=self.v["gnd"].get().strip(),
            rect=self.v_rect.get(), Np=self._num("Np", 32), Ns=self._num("Ns", 4),
            cumode=self.v_cumode.get(),
            ozP=float(self.v["ozP"].get() or 2), ozS=float(self.v["ozS"].get() or 2),
            ozG=float(self.v["ozG"].get() or 4),
            dPP=self._num("dPP", 200), dSS=self._num("dSS", 300), dPS=self._num("dPS", 150),
        )

    def _on_param(self):
        """参数变化 → 重建序列（保留已编辑的铜厚 / 类型，长度够的话）。"""
        self.rebuild(keep_edits=True)

    def _on_cumode(self):
        per = self.v_cumode.get() == "perlayer"
        state = "disabled" if per else "readonly"
        for w in self.f_cu.winfo_children():
            if isinstance(w, ttk.Combobox):
                w.configure(state=state)
        self._say("铜厚模式：" + ("逐层单独指定（下方逐层下拉生效）" if per
                                else "按原副边（全局铜厚生效）"))
        self._recompute()

    # ================================================================ 重建序列
    def rebuild(self, keep_edits: bool = True):
        p = self._params()
        old_seq, old_oz = list(self.seq), list(self.cu_oz)
        try:
            seq = D.build_seq(p["Lp"], p["Ls"], p["Lgnd"], p["rect"], p["gnd"])
        except ValueError as e:
            self.lbl_res.configure(text=f"⚠️ {e}")
            self._say(f"⚠️ {e}")
            return
        self.seq = seq
        if keep_edits and len(old_oz) == len(seq):
            self.cu_oz = list(old_oz)
        else:
            self.cu_oz = D.cu_list_from_global(seq, p["ozP"], p["ozS"], p["ozG"])
            self.cu_oz = [x / D.OZ_TO_UM for x in self.cu_oz]      # 存 oz
        self._render_rows()
        self._recompute()
        self.invalidate_design("重建序列")
        self._restore_pending_confirm()

    def _restore_pending_confirm(self):
        """启动时：若配置里存的确认层名与当前重建结果完全一致，自动恢复确认。"""
        pend = getattr(self, "_pending_confirm", None)
        if not pend:
            return
        now = D.layer_names(self.seq) if self.seq else []
        if list(pend) == list(now):
            self.confirmed_names = list(now)
            self.confirmed_seq = list(self.seq)
            self.lbl_confirm.configure(
                text="已确认 " + str(len(now)) + " 个铜层（来自配置）")
            self._notify_confirm()
        self._pending_confirm = None

    def _render_rows(self):
        self._clear_rows()
        for i, t in enumerate(self.seq):
            bg = gs.PALETTE["surface"]
            rf = ttk.Frame(self.box.inner)
            rf.pack(fill="x", pady=1)
            ttk.Label(rf, text=str(i + 1), width=4, anchor="w").pack(side="left")
            name = D.layer_names(self.seq)[i]
            ttk.Label(rf, text=name, width=12, anchor="w").pack(side="left")

            tvar = tk.StringVar(value=TYPE_LABEL[t])
            cb = ttk.Combobox(rf, textvariable=tvar, values=list(TYPE_LABEL.values()),
                              width=10, state="readonly")
            cb.pack(side="left")
            cb.bind("<<ComboboxSelected>>",
                    lambda e, idx=i, var=tvar: self._on_type(idx, var.get()))

            ovar = tk.StringVar(value=D.cu_oz_text(self.cu_oz[i]))
            ob = ttk.Combobox(rf, textvariable=ovar, values=CU_CHOICES,
                              width=8, state="readonly")
            ob.pack(side="left", padx=(4, 0))
            ob.bind("<<ComboboxSelected>>",
                    lambda e, idx=i, var=ovar: self._on_oz(idx, var.get()))

            d = self._gap_after(i)
            ttk.Label(rf, text=("—" if d is None else f"{d:g}"), width=11,
                      anchor="w", style="Muted.TLabel").pack(side="left", padx=(6, 0))
            self._rows.append(dict(type=cb, oz=ob))
        self._draw_strip()

    def _on_type(self, idx, label):
        t = TYPE_FROM_LABEL.get(label, "P")
        self.seq[idx] = t
        self._render_rows()
        self._recompute()
        self.invalidate_design("层类型/层名改动")

    def _on_oz(self, idx, txt):
        try:
            self.cu_oz[idx] = float(txt)
        except ValueError:
            return
        self._recompute()

    def _gap_after(self, i):
        """第 i 层与第 i+1 层之间的介质厚度（µm）；最后一层返回 None。"""
        if i >= len(self.seq) - 1:
            return None
        p = self._params()
        a, b = self.seq[i], self.seq[i + 1]
        if a == "G" or b == "G":
            return p["dSS"]
        if a == "P" and b == "P":
            return p["dPP"]
        if a == "P" or b == "P":
            return p["dPS"]
        return p["dSS"]

    def _sync_cu(self):
        p = self._params()
        for i, t in enumerate(self.seq):
            self.cu_oz[i] = p["ozP"] if t == "P" else (p["ozG"] if t == "G" else p["ozS"])
        self._render_rows()
        self._recompute()
        self._say(f"已按原副边同步 {len(self.seq)} 层铜厚"
                  f"（P←{p['ozP']:g}oz, S/A/B←{p['ozS']:g}oz, G←{p['ozG']:g}oz）")

    # ================================================================ 计算
    def _compute(self) -> dict | None:
        if not self.seq:
            return None
        p = self._params()
        if p["cumode"] == "perlayer":
            cu_um = D.cu_list_from_oz(self.cu_oz)
            mode = "逐层单独指定"
        else:
            cu_um = D.cu_list_from_global(self.seq, p["ozP"], p["ozS"], p["ozG"])
            mode = f"按原副边（P {D.cu_um_label(p['ozP']):g}µm / " \
                   f"S {D.cu_um_label(p['ozS']):g}µm / G {D.cu_um_label(p['ozG']):g}µm）"
        t = D.thickness(self.seq, cu_um, p["dPP"], p["dSS"], p["dPS"])
        # 安匝：ATp = Np/Lp，ATs = 全桥 ? Np/Ls : 2·Np/Ls（HTML L875-876，用 Np 不是 Ns）
        ATp, ATs = D.ampere_turns(p["Np"], p["Lp"], p["Ns"], p["Ls"], p["rect"])
        m = D.mmf(self.seq, ATp, ATs, p["rect"])
        parP, parS = D.parallel_per_turn(p["Lp"], p["Np"], p["Ls"], p["Ns"], p["rect"])
        return dict(t=t, m=m, mode=mode, cu_um=cu_um, iface=D.interfaces(self.seq),
                    errs=D.validate(p["Lp"], p["Ls"], p["Lgnd"], p["rect"], p["Np"], p["Ns"]),
                    ATp=ATp, ATs=ATs,
                    labels=D.layer_labels(self.seq, parP, parS))

    # ---------------------------------------------------------------- 确认叠层
    def add_confirm_listener(self, fn):
        """注册「确认状态变化」回调（层交换页用它刷新层名下拉）。"""
        self.confirm_listeners.append(fn)

    def _notify_confirm(self):
        for fn in list(self.confirm_listeners):
            try:
                fn()
            except Exception:
                pass

    def confirm_design(self):
        """固定当前叠层设计；层名由此对外可见。"""
        if not self.seq:
            self._say("⚠️ 没有可确认的叠层序列")
            return
        names = D.layer_names(self.seq)
        self.confirmed_names = list(names)
        self.confirmed_seq = list(self.seq)
        self.lbl_confirm.configure(
            text=f"已确认 {len(names)} 个铜层（{names[0]} … {names[-1]}）")
        self._notify_confirm()
        self.save_cfg()
        self._say("✅ 已确认叠层：" + str(len(names)) + " 个铜层\n   " +
                  " / ".join(names[:4]) + " … " + names[-1])

    def invalidate_design(self, reason: str = ""):
        """叠层设计一旦改动，之前的确认即失效。"""
        if self.confirmed_names is None:
            return
        self.confirmed_names = None
        self.confirmed_seq = None
        self.lbl_confirm.configure(text="⚠️ 叠层已改动 —— 需重新确认")
        self._notify_confirm()
        self._say("⚠️ 叠层设计已改动（" + reason + "），确认失效，请重新点「确认叠层」。")

    def _recompute(self):
        r = self._compute()
        if not r:
            self.lbl_res.configure(text="—")
            self.mmf.clear()
            return
        t, m = r["t"], r["m"]
        counts = {k: self.seq.count(k) for k in "PSABG"}
        names = D.layer_names(self.seq)
        warn = ""
        if r["errs"]:
            warn = "⚠️ " + "\n⚠️ ".join(r["errs"]) + "\n\n"
        txt = (
            warn +
            f"层数 {len(self.seq)}    P {counts['P']} / S {counts['S']} / "
            f"A {counts['A']} / B {counts['B']} / G {counts['G']}\n"
            f"铜厚模式：{r['mode']}\n\n"
            f"总板厚（铜+介质）  {_fmt_mm(t['total'])} mm\n"
            f"  铜合计           {_fmt_mm(t['cu'])} mm\n"
            f"  介质合计         {_fmt_mm(t['diel'])} mm\n"
            f"仿真厚度(去最外2层) {_fmt_mm(t['simTotal'])} mm\n\n"
            f"安匝 ATp/ATs       {r['ATp']:.3f} / {r['ATs']:.3f} A\n"
            f"原副边界面数       {r['iface']}\n"
            f"MMF peak           {m['peak']:.1f} A\n"
            f"MMF integral       {m['integral']:.1f} A\n"
            f"MMF 对称偏差       {m['sym']:.1f} A\n\n"
            f"层名序列：\n  " + " - ".join(names[:3]) + " … " + " - ".join(names[-2:])
        )
        self.lbl_res.configure(text=txt)
        self.mmf.set_data(self.seq, m)

    def _draw_strip(self):
        c = self.strip
        c.delete("all")
        n = len(self.seq) or 1
        h = max(360, n * 14)
        c.configure(scrollregion=(0, 0, 54, h), height=min(460, h))
        p = self._params()
        parP, parS = D.parallel_per_turn(p["Lp"], p["Np"], p["Ls"], p["Ns"], p["rect"])
        labels = D.layer_labels(self.seq, parP, parS) if self.seq else []
        for i, t in enumerate(self.seq):
            y0 = i * (h / n)
            y1 = (i + 1) * (h / n)
            c.create_rectangle(2, y0, 52, y1 - 1, fill=TYPE_COLOR.get(t, "#ccc"),
                               outline="#ffffff")
            if n <= 26 or i % 2 == 0:
                c.create_text(27, (y0 + y1) / 2, text=f"{i+1}{t}", fill="#ffffff",
                              font=(gs.FONT_FAMILY, 7))
        c.bind("<Motion>", lambda e: self._strip_hover(e, h / n))
        self._strip_labels = labels
        self._strip_h = h

    def _strip_hover(self, e, row_h):
        try:
            i = int(self.strip.canvasy(e.y) // row_h)
        except Exception:
            return
        if 0 <= i < len(self.seq):
            nm = D.layer_names(self.seq)[i]
            lb = self._strip_labels[i] if i < len(self._strip_labels) else ""
            self.lbl_strip.configure(text=f"#{i+1} {nm}\n绕组 {lb}")

    # ================================================================ 文件对接
    def on_open_stackup(self):
        from tkinter import filedialog
        init = r"E:\AI_model\800_6_VPDB\stackup"
        path = filedialog.askopenfilename(
            title="选择 AD 导出的叠层文件",
            initialdir=init if os.path.isdir(init) else None,
            filetypes=[("Altium 叠层文件", "*.stackup"), ("所有文件", "*.*")])
        if not path:
            return
        try:
            s = SF.Stackup(path)
        except Exception as e:
            messagebox.showerror("读入失败", f"{e}")
            self._say(f"❌ 读入失败: {e}")
            return
        self._src_file = path
        self._src_layers = s
        cop = [l for l in s.physical if l.is_copper]
        die = [l for l in s.physical if l.is_dielectric]
        self.lbl_file.configure(
            text=f"模板：{os.path.basename(path)}\n"
                 f"铜 {len(cop)} 层 / 介质 {len(die)} 层\n"
                 f"当前铜层名：{', '.join(l.name for l in cop[:3])} …")
        self._say(f"✅ 读入 {os.path.basename(path)}：铜 {len(cop)} / 介质 {len(die)}")
        # 用板子的铜层数对齐设计层数
        if len(cop) != len(self.seq):
            self._say(f"ℹ️ 模板铜层 {len(cop)} 层，当前设计 {len(self.seq)} 层 —— "
                      f"写出时会要求两者一致。")

    def build_output(self, src_file: str | None, out_path: str) -> dict:
        """写出 `.stackup`。**不弹窗**，便于测试与复用。

        - `src_file` 给了 ⇒ **模板模式**：套用你板子导出的文件，保留其材料 / Feature /
          Via Span 等设置，只改「铜层厚度 + 层名」与「内侧介质厚度」。
        - `src_file` 为 None ⇒ **从零生成**：用 `stackup_build` 按 AD 自带预设的 token 形状
          生成（形状已逐 key 比对通过），但材料 / Dk / 过孔跨度等为本工具默认值，
          **不会带上你板子已有的那些设置**。

        Returns: dict(ok, mode, out, size, changed, names, cu_um, gaps, n_cop, n_die)
        Raises:  ValueError 层数不符等可预期错误
        """
        r = self._compute()
        if not r:
            raise ValueError("当前没有可用的叠层序列")
        p = self._params()
        if p["cumode"] == "perlayer":
            cu_um = D.cu_list_from_oz(self.cu_oz)
        else:
            cu_um = D.cu_list_from_global(self.seq, p["ozP"], p["ozS"], p["ozG"])
        names = D.layer_names(self.seq)
        mm = SF.MIL_TO_MM
        gaps = [self._gap_after(i) for i in range(len(self.seq) - 1)]

        if not src_file:
            # ---------- 从零生成（无需模板）----------
            cu_mil = [u / 1000.0 / mm for u in cu_um]
            diel_mil = [g / 1000.0 / mm for g in gaps]
            kinds = ["plane" if t == "G" else "signal" for t in self.seq]
            diel_types = [2 if i % 2 else 1 for i in range(len(gaps))]
            txt = BK.build_stackup_text(
                len(self.seq), names, cu_mil, diel_mil,
                kinds=kinds, diel_types=diel_types)
            blob = b"\xef\xbb\xbf" + txt.encode("utf-8")
            with open(out_path, "wb") as f:
                f.write(blob)
            return dict(ok=True, mode="从零生成", out=out_path, size=len(blob),
                        changed=True, names=names, cu_um=cu_um, gaps=gaps,
                        n_cop=len(self.seq), n_die=len(self.seq) + 1)

        # ---------- 模板模式 ----------
        s = SF.Stackup(src_file)
        cop = [l for l in s.physical if l.is_copper]
        die = [l for l in s.physical if l.is_dielectric]
        if len(cop) != len(self.seq):
            raise ValueError(f"模板铜层 {len(cop)} 层，设计 {len(self.seq)} 层，必须一致。")
        inner = die[1:-1]
        if len(inner) != max(0, len(self.seq) - 1):
            raise ValueError(f"模板内侧介质 {len(inner)} 个，设计需要 {len(self.seq) - 1} 个。")

        for lay, um, nm in zip(cop, cu_um, names):
            lay.set_thickness(f"{um / 1000.0 / mm:.4f}mil")   # 三份同步
            lay.set("NAME", nm)
            # 子叠层的层名也要跟着改，否则 LSM 里显示的仍是旧名
            for k, _v, _i in list(lay.tokens):
                if k.endswith("}NAME"):
                    lay.set(k, nm)

        for i, lay in enumerate(inner):
            g = gaps[i]
            if g is not None:
                lay.set_thickness(f"{g / 1000.0 / mm:.4f}mil")

        changed, size = s.save(out_path)
        return dict(ok=True, mode="套用模板", out=out_path, size=size, changed=changed,
                    names=names, cu_um=cu_um, gaps=gaps,
                    n_cop=len(cop), n_die=len(die))

    def on_write_stackup(self):
        try:
            res = self.build_output(self._src_file, self._default_out_path())
        except ValueError as e:
            messagebox.showerror("无法写出", str(e))
            self._say(f"❌ {e}")
            return
        extra = ("" if self._src_file else
                 "\n   ⚠️ 从零生成：材料/Dk/过孔跨度用本工具默认值，"
                 "不含你板子已有的材料库/阻抗等设置")
        self._say(f"✅ 已写出（{res['mode']}）{res['out']}（{res['size']} 字节）\n"
                  f"   铜 {res['n_cop']} 层改名：{res['names'][0]} / {res['names'][1]} … "
                  f"{res['names'][-1]}\n"
                  f"   介质 {res['n_die']} 层"
                  f"（中间 {len(res['gaps'])} 段按设计）" + extra + "\n"
                  f"   下一步：LSM → File → Load Stackup From File… → 选该文件 → File → Save to PCB")
        messagebox.showinfo("已写出", f"已写出（{res['mode']}）：\n{res['out']}\n\n"
                                      f"请在 LSM 里 File → Load Stackup From File… 导入，\n"
                                      f"再 File → Save to PCB 生效。")

    def _default_out_path(self) -> str:
        if self._src_file:
            base = os.path.splitext(os.path.basename(self._src_file))[0]
            return os.path.join(os.path.dirname(self._src_file),
                                f"{base}_design.stackup")
        d = r"E://AI_model//800_6_VPDB//stackup"
        if not os.path.isdir(d):
            d = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(d, "stackup_design.stackup")

    # ================================================================ 配置
    def cfg_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "altium_tools_config.json")

    def _load_cfg(self):
        cfg = gs.load_json_cfg(self.cfg_path(), {})
        for k, var in self.v.items():
            if k in cfg:
                var.set(str(cfg[k]))
        if "rect" in cfg:
            self.v_rect.set(cfg["rect"])
        if "cumode" in cfg:
            self.v_cumode.set(cfg["cumode"])
        saved = list(cfg.get("stk_confirmed") or [])
        self._pending_confirm = saved or None
        self._on_cumode_quiet()

    def _on_cumode_quiet(self):
        per = self.v_cumode.get() == "perlayer"
        for w in self.f_cu.winfo_children():
            if isinstance(w, ttk.Combobox):
                w.configure(state="disabled" if per else "readonly")

    def save_cfg(self):
        # ⚠️ 与 main.py 的「画中点短线」页共用同一个 JSON ⇒ 必须**读-合并-写**，
        #    否则后写的会把先写的整段覆盖掉。
        cfg = gs.load_json_cfg(self.cfg_path(), {})
        cfg.update({k: var.get() for k, var in self.v.items()})
        cfg["rect"] = self.v_rect.get()
        cfg["cumode"] = self.v_cumode.get()
        cfg["stk_confirmed"] = list(self.confirmed_names or [])
        gs.save_json_cfg(self.cfg_path(), cfg)
