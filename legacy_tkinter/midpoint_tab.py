#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「画中点短线」的一个 tab —— 竖直 / 水平两个方向共用同一份实现。

两种方向只差一件事：**哪个坐标固定、哪个变化**

| 方向 | 选中对象 | 取中点 | 新线 |
|---|---|---|---|
| 竖直 `v` | 2 条**竖直**线（X 不同） | X 中点 | 在 X 中点画一条竖线，Y 从 起点Y 到 起点Y+长度 |
| 水平 `h` | 2 条**水平**线（Y 不同） | Y 中点 | 在 Y 中点画一条横线，X 从 起点X 到 起点X+长度 |

其余（防重、落笔、**读回验证**、日志、后台线程）两边完全一致，所以合成一个类，
由 `orient` 决定差异，避免两份代码走散。

铁律（与项目记忆一致）
----------------------
- `pcb_place_tracks` 无幂等 ⇒ 落笔前必须**按坐标防重**。
- 桥接回执**不可信**，落笔后必须**另起一次读回**，且 X/Y 两种量化候选都要查
  （量化是截断不是四舍五入）。
"""

from __future__ import annotations

import queue
import threading
import traceback

import tkinter as tk
from tkinter import ttk

import gui_style as gs
import altium_bridge as ab

LEN_PRESETS = [
    ("39 mil  (0.9906 mm)", 39.0),
    ("40 mil  (1.0160 mm)", 40.0),
    ("19.685 mil (0.5 mm)", 19.685),
    ("39.370079 mil (1 mm 精确值)", 39.370079),
]

LAYER_CHOICES = ["", "Mechanical1", "Mechanical2", "Mechanical13",
                 "KeepOutLayer", "TopLayer", "BottomLayer"]


def _spec(orient: str) -> dict:
    if orient == "v":
        return dict(
            title="在两条竖线的中点画竖直短线",
            hint="选中两条竖线 → 读取 → 画线",
            require="必须恰好 2 条竖直 track（同一层）",
            start_label="起点 Y (mil)",
            btn="画中点短线",
            word="竖直线",
            keys=("mv_start", "mv_len", "mv_width", "mv_layer", "mv_force"),
            legacy=("y0", "length", "width", "layer"),
            defaults=(6337.0, 39.0, 4.0, ""),
        )
    return dict(
        title="在两条水平线的中点画水平短线",
        hint="选中两条水平线 → 读取 → 画线",
        require="必须恰好 2 条水平 track（同一层）",
        start_label="起点 X (mil)",
        btn="画中点短线",
        word="水平线",
        keys=("mh_start", "mh_len", "mh_width", "mh_layer", "mh_force"),
        legacy=("h_x0", "h_length", "h_width", "h_layer"),
        defaults=(6337.0, 39.0, 4.0, ""),
    )


class MidpointTab(ttk.Frame):
    """一个方向（竖直/水平）的完整界面 + 行为。"""

    def __init__(self, master, app, orient: str, log_fn=None):
        ttk.Frame.__init__(self, master)
        if orient not in ("v", "h"):
            raise ValueError("orient 只能是 'v' 或 'h'")
        self.app = app
        self.orient = orient
        self.o = _spec(orient)
        self.extra_log = log_fn
        self._q: queue.Queue = queue.Queue()
        self._busy = False
        # 🔴 工作线程**不能**碰 Tk（连 after() 都会抛
        #    "main thread is not in main loop"）⇒ worker 只写这个普通属性，
        #    由主线程的 _pump 去刷新列表。
        self._pending_list = None
        self._build()
        self.app.after(80, self._pump)

    # ================================================================ 构建
    def _build(self):
        outer = ttk.Frame(self, padding=(14, 12))
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text=self.o["title"], style="Title.TLabel").pack(side="left")
        ttk.Label(head, text=self.o["hint"], style="Muted.TLabel").pack(
            side="left", padx=(12, 0))

        pw = gs.paned(outer, orient="h")
        pw.pack(fill="both", expand=True, pady=(12, 0))

        # -------- 左：选中对象 --------
        left = gs.card(pw, "当前选中对象")
        pw.add(left, minsize=270)
        ttk.Label(left, text=self.o["require"], style="Muted.TLabel").pack(
            anchor="w", padx=12, pady=(8, 4))
        lw = ttk.Frame(left)
        lw.pack(fill="both", expand=True, padx=12, pady=(0, 6))
        self.lst_sel = tk.Listbox(lw, height=8, **gs.listbox_kw())
        sb1 = ttk.Scrollbar(lw, orient="vertical", command=self.lst_sel.yview)
        self.lst_sel.configure(yscrollcommand=sb1.set)
        self.lst_sel.pack(side="left", fill="both", expand=True)
        sb1.pack(side="right", fill="y")
        rowb = ttk.Frame(left)
        rowb.pack(fill="x", padx=12, pady=(0, 12))
        self.btn_read = ttk.Button(rowb, text="读取选中对象", command=self.on_read)
        self.btn_read.pack(side="left")

        # -------- 右：参数 + 日志（可上下拖拽）--------
        right = gs.paned(pw, orient="v")
        pw.add(right, minsize=340)
        pcard = gs.card(right, "参数")
        right.add(pcard, minsize=180)

        grid = ttk.Frame(pcard)
        grid.pack(fill="x", padx=12, pady=(10, 4))
        d_start, d_len, d_width, d_layer = self.o["defaults"]
        self.var_start = tk.StringVar(value=str(d_start))
        self.var_len = tk.StringVar(value=str(d_len))
        self.var_width = tk.StringVar(value=str(d_width))
        self.var_layer = tk.StringVar(value=str(d_layer))
        self.var_force = tk.BooleanVar(value=False)

        def lab(text, r, hint=""):
            ttk.Label(grid, text=text).grid(row=r, column=0, sticky="w",
                                            pady=4, padx=(0, 8))
            if hint:
                ttk.Label(grid, text=hint, style="Muted.TLabel").grid(
                    row=r, column=2, sticky="w", padx=(8, 0))

        lab(self.o["start_label"], 0)
        ttk.Entry(grid, textvariable=self.var_start, width=16).grid(
            row=0, column=1, sticky="w", pady=4)

        lab("长度", 1)
        ttk.Entry(grid, textvariable=self.var_len, width=16).grid(
            row=1, column=1, sticky="w", pady=4)
        cbo = ttk.Combobox(grid, state="readonly", width=26,
                           values=[t for t, _ in LEN_PRESETS])
        cbo.grid(row=1, column=2, sticky="w", padx=(8, 0), pady=4)

        def on_preset(_e=None):
            for t, v in LEN_PRESETS:
                if t == cbo.get():
                    self.var_len.set(f"{v:g}")
                    break
        cbo.bind("<<ComboboxSelected>>", on_preset)

        lab("线宽 (mil)", 2)
        ttk.Entry(grid, textvariable=self.var_width, width=16).grid(
            row=2, column=1, sticky="w", pady=4)

        lab("目标层", 3, "留空 = 跟随选中线")
        ttk.Combobox(grid, textvariable=self.var_layer, width=16,
                     values=LAYER_CHOICES).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Checkbutton(grid, text="允许重合（--force）",
                        variable=self.var_force).grid(
            row=4, column=0, columnspan=2, sticky="w", pady=(4, 0))

        btns = ttk.Frame(pcard)
        btns.pack(fill="x", padx=12, pady=(6, 12))
        self.btn_draw = ttk.Button(btns, text=self.o["btn"],
                                   style="Accent.TButton", command=self.on_draw)
        self.btn_draw.pack(side="left")
        ttk.Button(btns, text="清空日志", command=self.clear_log).pack(
            side="left", padx=(8, 0))

        lcard = gs.card(right, "日志")
        right.add(lcard, minsize=120)
        tw = ttk.Frame(lcard)
        tw.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.txt = tk.Text(tw, height=8, wrap="word", state="disabled",
                           **gs.text_kw())
        sb2 = ttk.Scrollbar(tw, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb2.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")

        self.log("提示：在 AD 里选中两条%s，然后点「读取选中对象」。"
                 % ("竖线" if self.orient == "v" else "水平线"))
        self.log("长度说明：桥接坐标量化到整数 mil，1 mm 无法精确表达 → "
                 "39 mil = 0.9906 mm 或 40 mil = 1.0160 mm。")

    # ================================================================ 日志
    def log(self, msg: str):
        self.txt.configure(state="normal")
        self.txt.insert("end", msg.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")
        if self.extra_log:
            self.extra_log(msg)

    def clear_log(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

    # ================================================================ 后台
    def _run(self, title: str, fn):
        if self._busy:
            self.log("⚠️ 上一个操作还在进行中，请稍候。")
            return
        self._busy = True
        self.btn_draw.state(["disabled"])
        self.btn_read.state(["disabled"])
        self.app.set_status(f"{title} …")

        def worker():
            try:
                out = fn(self.app.bridge())
                self._q.put(("ok", title, out))
            except ab.BridgeTimeout as e:
                self._q.put(("timeout", title, f"{e}\n\n{ab.BridgeTimeout.HINT}"))
            except Exception as e:  # noqa: BLE001
                self._q.put(("err", title, f"{e}\n{traceback.format_exc(limit=3)}"))

        threading.Thread(target=worker, daemon=True).start()

    def _pump(self):
        try:
            while True:
                kind, title, payload = self._q.get_nowait()
                self._busy = False
                self.btn_draw.state(["!disabled"])
                self.btn_read.state(["!disabled"])
                if self._pending_list is not None:      # 主线程刷新列表
                    self._fill_list(self._pending_list)
                    self._pending_list = None
                if kind == "ok":
                    self.app.set_status(f"{title} 完成")
                    if payload:
                        self.log(str(payload))
                elif kind == "timeout":
                    self.app.set_status(f"{title} 失败：桥接无响应")
                    self.log(f"❌ [{title}] 桥接无响应\n{payload}")
                else:
                    self.app.set_status(f"{title} 失败")
                    self.log(f"❌ [{title}] 出错：{payload}")
        except queue.Empty:
            pass
        self.app.after(80, self._pump)

    # ================================================================ 读取
    def on_read(self):
        vertical = (self.orient == "v")

        def job(br: ab.AltiumBridge) -> str:
            doc = br.active_document()
            tracks = br.selected_tracks()
            objs = br.selected_objects()
            out = [f"活动文档：{doc.get('file_name') or '(无)'}"]
            out.append(f"选中对象：{len(objs)} 个")
            for t in tracks:
                out.append("  " + t.as_row())
            if len(objs) != len(tracks):
                out.append(f"  （其中 {len(objs) - len(tracks)} 个不是 track）")

            want = "竖直线" if vertical else "水平线"
            ok = (all(t.is_vertical for t in tracks) if vertical
                  else all(t.is_horizontal for t in tracks))
            if len(tracks) == 2 and ok:
                try:
                    mid = (ab.midpoint_of_two_verticals(tracks) if vertical
                           else ab.midpoint_of_two_horizontals(tracks))
                    axis = "X" if vertical else "Y"
                    out.append(f"→ 中点 {axis} = {mid:.4f} mil  "
                               f"（量化后 {ab.quantize_mil(mid)}）")
                except ValueError as e:
                    out.append(f"→ {e}")
            elif len(tracks) == 2:
                out.append(f"→ 选中的不全是{want}，无法取中点。")
            else:
                out.append(f"→ 需要恰好 2 条{want}。")

            self._pending_list = list(tracks)
            return "\n".join(out)

        self._run("读取选中对象", job)

    def _fill_list(self, tracks):
        self.lst_sel.delete(0, "end")
        if not tracks:
            self.lst_sel.insert("end", "（没有选中 track）")
            return
        for t in tracks:
            self.lst_sel.insert("end", t.as_row())

    # ================================================================ 画线
    def on_draw(self):
        vertical = (self.orient == "v")
        try:
            start = float(self.var_start.get())
            length = float(self.var_len.get())
            width = float(self.var_width.get())
        except ValueError:
            self.log(f"❌ 参数格式错误：{self.o['start_label']} / 长度 / 线宽 必须是数字。")
            return
        if length <= 0:
            self.log("❌ 长度必须为正数。")
            return
        layer_override = self.var_layer.get().strip()
        force = bool(self.var_force.get())
        end = start + length

        def job(br: ab.AltiumBridge) -> str:
            out = []
            tracks = br.selected_tracks()
            if vertical:
                mid = ab.midpoint_of_two_verticals(tracks)      # 校验在内部
                layer = layer_override or tracks[0].layer
                out.append(f"源线 X：{tracks[0].x1:g} / {tracks[1].x1:g}")
                out.append(f"中点 X：{mid:.4f} mil（量化后 {ab.quantize_mil(mid)}）")
                out.append(f"目标线：({mid:.4f}, {start:g}) -> ({mid:.4f}, {end:g})  "
                           f"layer={layer} width={width:g} len={length:g} mil")
                dup = br.find_duplicate(mid, start, end, layer)
                if dup and not force:
                    out.append(f"⚠️ 目标位置已存在 {len(dup)} 条同规格线，已停止"
                               f"（勾选「允许重合」可强制落笔）。")
                    self._pending_list = list(tracks)
                    return "\n".join(out)
                res = br.place_vline(mid, start, end, layer, width)
                out.append(f"放置回执：placed={res.get('placed')} "
                           f"failed={res.get('failed')}")
                found, hits = br.verify_vline(mid, start, end, layer)
                axis_txt = f"X={ab.quantize_candidates(mid)}"
                ctr = (found.x1 - mid) if found else 0.0
            else:
                mid = ab.midpoint_of_two_horizontals(tracks)
                layer = layer_override or tracks[0].layer
                out.append(f"源线 Y：{tracks[0].y1:g} / {tracks[1].y1:g}")
                out.append(f"中点 Y：{mid:.4f} mil（量化后 {ab.quantize_mil(mid)}）")
                out.append(f"目标线：({start:g}, {mid:.4f}) -> ({end:g}, {mid:.4f})  "
                           f"layer={layer} width={width:g} len={length:g} mil")
                dup = br.find_duplicate_h(mid, start, end, layer)
                if dup and not force:
                    out.append(f"⚠️ 目标位置已存在 {len(dup)} 条同规格线，已停止"
                               f"（勾选「允许重合」可强制落笔）。")
                    self._pending_list = list(tracks)
                    return "\n".join(out)
                res = br.place_hline(mid, start, end, layer, width)
                out.append(f"放置回执：placed={res.get('placed')} "
                           f"failed={res.get('failed')}")
                found, hits = br.verify_hline(mid, start, end, layer)
                axis_txt = f"Y={ab.quantize_candidates(mid)}"
                ctr = (found.y1 - mid) if found else 0.0

            out.append(f"读回验证：{axis_txt} 命中 {len(hits)} 条")
            for t in hits:
                mark = "  <== 本次目标" if (found and t is found) else ""
                out.append("  " + t.as_row() + mark)
            if found:
                out.append(f"✅ 验证通过：({found.x1:g}, {found.y1:g}) -> "
                           f"({found.x2:g}, {found.y2:g})   量化误差 {ctr:+.4f} mil")
            else:
                out.append("❌ 未找到与预期坐标匹配的线，请人工核查。")
            return "\n".join(out)

        self._run("画中点短线", job)

    # ================================================================ 配置
    def save_cfg(self) -> dict:
        k = self.o["keys"]
        return {
            k[0]: self.var_start.get(),
            k[1]: self.var_len.get(),
            k[2]: self.var_width.get(),
            k[3]: self.var_layer.get(),
        }

    def load_cfg(self, cfg: dict):
        k = self.o["keys"]
        leg = self.o["legacy"]
        for new, old, var in ((k[0], leg[0], self.var_start),
                              (k[1], leg[1], self.var_len),
                              (k[2], leg[2], self.var_width),
                              (k[3], leg[3], self.var_layer)):
            if new in cfg:
                var.set(str(cfg[new]))
            elif old in cfg:            # 兼容旧版单一 tab 的键
                var.set(str(cfg[old]))
        if k[4] in cfg:
            try:
                self.var_force.set(bool(cfg[k[4]]))
            except Exception:
                pass
