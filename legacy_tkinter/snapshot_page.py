#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI「工程快照」页 —— 一键按规则新建工程快照。

规则见 snapshot_core.py。本页只负责：选根目录 → 扫描 → 预览 → 执行 → 看日志。
根目录、最近用过的几个根目录、上次生成的目标路径都写 JSON 配置，换项目直接选。
"""
from __future__ import annotations

import os
import subprocess
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk

import gui_style as gs
import snapshot_core as SC

DEFAULT_ROOT = r"E:\project\800-6\PCB_prj\A4_prj"
MAX_RECENT = 6


class SnapshotPage(ttk.Frame):
    def __init__(self, master, app, log_fn=None):
        super().__init__(master)
        self.app = app
        self.log = log_fn or (lambda s: None)
        self.scan_info = None
        self.last_dst = ""
        self._build()

    # ------------------------------------------------------------ 界面
    def _build(self):
        outer = ttk.Frame(self, padding=(14, 12))
        outer.pack(fill="both", expand=True)

        head = ttk.Frame(outer)
        head.pack(fill="x")
        ttk.Label(head, text="工程快照", style="Title.TLabel").pack(side="left")
        ttk.Label(head, text="日期文件夹 → 时间戳文件夹 → 拷工程本体 → PrjPcb 加时间戳后缀",
                  style="Muted.TLabel").pack(side="left", padx=(12, 0))

        pw = ttk.PanedWindow(outer, orient="vertical")
        pw.pack(fill="both", expand=True, pady=(12, 0))

        top = ttk.Frame(pw)
        pw.add(top, weight=0)

        # ---------------- ① 快照库位置
        card = gs.card(top, "① 快照库位置")
        card.pack(fill="x")

        row = ttk.Frame(card)
        row.pack(fill="x", padx=12, pady=(10, 6))
        ttk.Label(row, text="根目录").pack(side="left")
        self.v_root = tk.StringVar()
        self.cb_root = ttk.Combobox(row, textvariable=self.v_root, width=76)
        self.cb_root.pack(side="left", padx=(10, 6))
        self.cb_root.bind("<Return>", lambda e: self.on_scan())
        self.cb_root.bind("<<ComboboxSelected>>", lambda e: self.on_scan())
        ttk.Button(row, text="浏览…", command=self.on_browse).pack(side="left")
        ttk.Button(row, text="扫描", command=self.on_scan).pack(side="left",
                                                               padx=(6, 0))

        self.lbl_state = ttk.Label(card, text="尚未扫描",
                                   style="Muted.TLabel", wraplength=980,
                                   justify="left")
        self.lbl_state.pack(anchor="w", padx=12, pady=(0, 4))

        self.lbl_note = ttk.Label(card, text="", style="Muted.TLabel",
                                  wraplength=980, justify="left",
                                  foreground=gs.PALETTE.get("danger", "#EF4444"))
        self.lbl_note.pack(anchor="w", padx=12, pady=(0, 6))

        ttk.Label(card, text=(
            "约定：根目录下按 <YYYYMMDD>/<YYYYMMDDHHMM>/ 存放各轮快照；"
            "只拷工程本体（.SchDoc/.PcbDoc/.BomDoc/.PrjPcb/.PrjPcbStructure 等），"
            "History、__Previews、_copy_/_plain_/.bak_/zip 一律跳过。"),
            style="Muted.TLabel", justify="left", wraplength=980).pack(
            fill="x", padx=12, pady=(0, 12))

        # ---------------- ② 新建
        card2 = gs.card(top, "② 新建")
        card2.pack(fill="x", pady=(10, 0))

        self.lbl_plan = ttk.Label(card2, text="点「扫描」后这里会显示将要生成的目标与待拷文件数。",
                                  style="Muted.TLabel", wraplength=980,
                                  justify="left")
        self.lbl_plan.pack(anchor="w", padx=12, pady=(10, 6))

        btns = ttk.Frame(card2)
        btns.pack(fill="x", padx=12, pady=(0, 12))
        self.btn_preview = ttk.Button(btns, text="预览（不落盘）",
                                      command=self.on_preview)
        self.btn_preview.pack(side="left")
        self.btn_create = ttk.Button(btns, text="新建快照", style="Accent.TButton",
                                     command=self.on_create)
        self.btn_create.pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="打开快照目录",
                   command=self.on_open_dir).pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="定位 PrjPcb",
                   command=self.on_reveal_prjpcb).pack(side="left", padx=(8, 0))

        # ---------------- ③ 输出
        bottom = ttk.Frame(pw)
        pw.add(bottom, weight=1)
        lcard = gs.card(bottom, "输出")
        lcard.pack(fill="both", expand=True)
        tw = ttk.Frame(lcard)
        tw.pack(fill="both", expand=True, padx=12, pady=(8, 12))
        self.txt = tk.Text(tw, height=12, wrap="word", state="disabled",
                           **gs.text_kw())
        sb = ttk.Scrollbar(tw, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ------------------------------------------------------------ 日志
    def _say(self, msg):
        line = (msg.splitlines()[0][:130] if msg and msg.splitlines() else "")
        self.txt.configure(state="normal")
        self.txt.insert("end", msg.rstrip() + "\n")
        self.txt.see("end")
        self.txt.configure(state="disabled")
        try:
            self.txt.update_idletasks()
        except Exception:
            pass
        if line:
            self.log(msg)

    # ------------------------------------------------------------ 根目录
    def on_browse(self):
        cur = self.v_root.get().strip() or DEFAULT_ROOT
        init = cur if os.path.isdir(cur) else os.path.dirname(cur)
        p = filedialog.askdirectory(title="选择工程快照根目录",
                                    initialdir=init or ".")
        if p:
            self.v_root.set(os.path.normpath(p))
            self._remember_root(self.v_root.get())
            self.on_scan()

    def _remember_root(self, p):
        vals = [x for x in (self.cb_root.cget("values") or []) if x and x != p]
        vals.insert(0, p)
        self.cb_root.configure(values=vals[:MAX_RECENT])

    # ------------------------------------------------------------ 扫描
    def on_scan(self):
        root = self.v_root.get().strip()
        if not root:
            self.lbl_state.configure(text="请先选根目录")
            return
        if not os.path.isdir(root):
            self.lbl_state.configure(text="根目录不存在：%s" % root)
            self.lbl_note.configure(text="")
            self.scan_info = None
            self.btn_create.configure(state="disabled")
            self.btn_preview.configure(state="disabled")
            return

        info = SC.scan(root)
        self.scan_info = info
        snaps = info["snaps"]
        if not snaps:
            self.lbl_state.configure(
                text="该目录下还没有任何 <YYYYMMDD>/<YYYYMMDDHHMM>/ 快照。"
                     "首次使用请手工建一个基准快照。")
            self.lbl_note.configure(text="")
            self.btn_create.configure(state="disabled")
            self.btn_preview.configure(state="disabled")
            return

        src = info["source"]
        self.btn_create.configure(state="normal")
        self.btn_preview.configure(state="normal")
        self.lbl_state.configure(
            text="共 %d 个日期目录 / %d 个快照　|　源：%s　最后写入 %s"
                 % (len(info["dates"]), len(snaps), src.rel, src.mtime_text))
        self.lbl_note.configure(text=("⚠️ " + info["note"]) if info["note"] else "")
        self._say("扫描 %s" % root)
        self._say("    源快照 %s，最后写入 %s" % (src.rel, src.mtime_text))
        if info["note"]:
            self._say("    ⚠️ %s" % info["note"])

    # ------------------------------------------------------------ 预览
    def _need_ready(self):
        if not self.scan_info or not self.scan_info.get("source"):
            messagebox.showinfo("先扫描", "请先选根目录并点「扫描」，确认源快照。")
            return None
        return self.scan_info["source"]

    def on_preview(self):
        src = self._need_ready()
        if not src:
            return
        plan = SC.make_plan(self.v_root.get().strip(), src.path, datetime.now())
        self._print_plan(plan, title="预览（未写盘）")

    def _print_plan(self, plan, title="计划"):
        self._say("—" * 40)
        self._say("%s：%s" % (title, plan.dst))
        self._say("  源 %s" % os.path.relpath(plan.src, plan.root))
        self._say("  待拷 %d 个文件 / %s（只含工程本体）"
                  % (len(plan.files), SC.human(plan.total_bytes)))
        for rel, _ap in plan.files:
            self._say("     + %s" % rel)
        for rel, nf, nb in plan.skipped_dirs:
            self._say("     [跳过目录] %s  %d 个 / %s"
                      % (rel, nf, SC.human(nb)))
        if plan.skipped_files:
            self._say("     [跳过文件] %d 个 / %s"
                      % (len(plan.skipped_files), SC.human(plan.skipped_bytes)))
        for a, b in plan.renames:
            self._say("     改名 %s → %s" % (a, os.path.basename(b)))
        if plan.pcb_note:
            self._say("     ⚠️ %s" % plan.pcb_note)
        self.lbl_plan.configure(
            text="目标：%s\n待拷 %d 个文件 / %s" %
                 (plan.dst, len(plan.files), SC.human(plan.total_bytes)))

    # ------------------------------------------------------------ 执行
    def on_create(self):
        src = self._need_ready()
        if not src:
            return
        root = self.v_root.get().strip()
        # 重新生成计划：预览与执行之间可能跨分钟，ts 要以现在为准
        plan = SC.make_plan(root, src.path, datetime.now())
        if not plan.files:
            messagebox.showwarning("没有可拷的文件",
                                   "源快照里没找到工程本体文件，检查白名单/工程名。")
            return
        if not messagebox.askyesno(
                "新建快照",
                "源：%s\n最后写入：%s\n\n目标：%s\n待拷：%d 个文件 / %s\n\n继续？"
                % (src.rel, src.mtime_text, plan.dst, len(plan.files),
                   SC.human(plan.total_bytes))):
            return

        self.btn_create.configure(state="disabled")
        self.app.set_status("正在新建快照 …")
        try:
            self._print_plan(plan, title="执行")
            res = SC.create(plan, progress=self._say)
        except Exception as e:
            self.btn_create.configure(state="normal")
            self._say("新建失败：%s: %s" % (type(e).__name__, e))
            self.app.set_status("新建失败")
            messagebox.showerror("新建失败", "%s: %s" % (type(e).__name__, e))
            return
        self.btn_create.configure(state="normal")

        self.last_dst = res["dst"]
        if res["ok"]:
            self._say("✔ 校验通过：%d 个文件，size + sha256 全对" % res["count"])
            self._say("   打开工程：%s" % res["prjpcb"])
            self.app.set_status("快照已建好：%s" % os.path.basename(res["dst"]))
            if messagebox.askyesno("已建好", "快照已建好：\n%s\n\n要打开该目录吗？"
                                   % res["dst"]):
                self._open_path(res["dst"])
        else:
            self._say("✘ 有问题：")
            for k, label in (("missing", "缺失"), ("size_bad", "大小不符"),
                             ("sha_bad", "sha256 不符")):
                for rel in res.get(k) or []:
                    self._say("   [%s] %s" % (label, rel))
            for e in res.get("errors") or []:
                self._say("   [异常] %s" % e)
            self.app.set_status("新建快照有异常")
            messagebox.showwarning("有异常", "复制或校验有问题，详见输出面板。")
        self.on_scan()          # 刷新源（新快照可能成为下一个源）

    # ------------------------------------------------------------ 杂项
    @staticmethod
    def _open_path(p):
        try:
            if os.path.isdir(p):
                os.startfile(p)
            else:
                subprocess.Popen('explorer /select,"%s"' % os.path.normpath(p))
        except Exception:
            pass

    def on_open_dir(self):
        p = self.last_dst if (self.last_dst and os.path.isdir(self.last_dst)) else ""
        if not p and self.scan_info and self.scan_info.get("source"):
            p = self.scan_info["source"].path
        if p:
            self._open_path(p)
        else:
            self._say("还没有目标目录，先扫描/新建一次。")

    def on_reveal_prjpcb(self):
        p = self.last_dst
        if not p or not os.path.isdir(p):
            self._say("还没有新建过快照，先点「新建快照」。")
            return
        hit = ""
        for n in sorted(os.listdir(p)):
            if n.lower().endswith(".prjpcb"):
                hit = os.path.join(p, n)
                break
        if hit:
            self._open_path(hit)
        else:
            self._say("该目录下没有 .PrjPcb")

    # ------------------------------------------------------------ 配置
    def save_cfg(self):
        return {
            "snap_root": self.v_root.get().strip(),
            "snap_roots": list(self.cb_root.cget("values") or [])[:MAX_RECENT],
            "snap_last_dst": self.last_dst,
        }

    def load_cfg(self, cfg):
        root = (cfg.get("snap_root") or "").strip() or DEFAULT_ROOT
        self.cb_root.configure(
            values=(cfg.get("snap_roots") or [])[:MAX_RECENT] or [root])
        self.v_root.set(root)
        self.last_dst = cfg.get("snap_last_dst") or ""
        if os.path.isdir(root):
            self.on_scan()
