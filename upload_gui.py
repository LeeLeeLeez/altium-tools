# -*- coding: utf-8 -*-
"""
upload_gui.py —— 图形界面上传器（双击即可，不用敲命令 / 不用 bat）

把「Altium 工具集」推到 GitHub。底层走 `gh_upload.py`：
Python 读明文 + GitHub REST API 建 commit，**不用 git.exe**（DLP 透明加密会让 git 提交乱码）。

用法：
    双击本文件；或命令行：
        "C:\\Users\\admin\\AppData\\Local\\Programs\\Python\\Python312\\pythonw.exe" upload_gui.py
    填 Token → 点【开始上传】。

Token 获取：https://github.com/settings/tokens
            Generate new token (classic) → 勾 repo
"""
import os
import queue
import sys
import threading
import time
import traceback
import webbrowser

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import gh_upload  # noqa: E402

# ---- 风格：优先复用统一的浅色主题模块（本目录自带 gui_style.py）----
try:
    import gui_style as gs
    _P = gs.PALETTE
    BG = _P.get("bg", "#F5F7FA")
    SURFACE = _P.get("surface", "#FFFFFF")
    BORDER = _P.get("border", "#E1E7EF")
    TEXT = _P.get("text", "#1F2937")
    MUTED = _P.get("muted", "#6B7280")
    ACCENT = _P.get("accent", "#2563EB")
    ACCENT_HOVER = _P.get("accent_hover", "#1D4ED8")
    OK_C = _P.get("ok", "#16A34A")
    WARN_C = "#D97706"
    ERR_C = _P.get("danger", "#EF4444")
    FONT = (getattr(gs, "FONT_FAMILY", "Microsoft YaHei UI"), 9)
    _HAS_GS = True
except Exception:                       # 单独把本文件拷走也能跑
    BG, SURFACE, BORDER = "#F5F7FA", "#FFFFFF", "#E1E7EF"
    TEXT, MUTED, ACCENT, ACCENT_HOVER = "#1F2937", "#6B7280", "#2563EB", "#1D4ED8"
    OK_C, WARN_C, ERR_C = "#16A34A", "#D97706", "#EF4444"
    FONT = ("Microsoft YaHei UI", 9)
    _HAS_GS = False

TOKEN_FILE = os.path.join(HERE, ".gh_token")
DEFAULT_REPO = "altium-tools"
TITLE = "上传 Altium 工具集 → GitHub"


class Uploader(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(TITLE)
        self.geometry("700x600")
        self.minsize(600, 480)
        self.configure(bg=BG)

        # 尽量套用全局主题（gu 的 clam 深度定制）
        if _HAS_GS:
            for fn in ("apply_theme", "setup_style"):
                f = getattr(gs, fn, None)
                if callable(f):
                    try:
                        f(self)
                        break
                    except Exception:
                        pass

        st = ttk.Style()
        try:
            st.theme_use("clam")
        except Exception:
            pass
        st.configure("Accent.TButton", background=ACCENT, foreground="#FFFFFF",
                     borderwidth=0, padding=6)
        st.map("Accent.TButton", background=[("active", ACCENT_HOVER)])
        st.configure("TLabel", background=BG, foreground=TEXT)

        self.q = queue.Queue()
        self.v_tok = tk.StringVar()
        self.v_repo = tk.StringVar(value=DEFAULT_REPO)
        self.v_msg = tk.StringVar()
        self.v_branch = tk.StringVar()
        self.v_tag = tk.StringVar()
        self.v_pub = tk.IntVar(value=1)
        self.v_remember = tk.IntVar(value=0)
        self.v_exe = tk.IntVar(value=1)
        self.v_noproxy = tk.IntVar(value=0)
        self.v_show = tk.IntVar(value=0)

        if os.path.isfile(TOKEN_FILE):
            try:
                saved = open(TOKEN_FILE, encoding="utf-8").read().strip()
                saved, _ch = gh_upload.sanitize_token(saved)
                if saved:
                    self.v_tok.set(saved)
                    self.v_remember.set(1)
            except Exception:
                pass

        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")

        ttk.Label(top, text="GitHub Token", font=(FONT[0], 10, "bold")).grid(
            row=0, column=0, sticky="w")
        self.e_tok = ttk.Entry(top, textvariable=self.v_tok, show="•", width=54)
        self.e_tok.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        ttk.Button(top, text="去获取", width=8,
                   command=lambda: webbrowser.open(
                       "https://github.com/settings/tokens")).grid(
            row=0, column=3, padx=(6, 0))

        ttk.Label(top, text="仓库名").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.v_repo, width=32).grid(
            row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(top, text="提交说明（可留空）").grid(
            row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.v_msg, width=54).grid(
            row=2, column=1, columnspan=3, sticky="ew", padx=(8, 0), pady=(8, 0))

        ttk.Label(top, text="发布 Release").grid(row=3, column=0, sticky="w",
                                                 pady=(8, 0))
        ttk.Entry(top, textvariable=self.v_tag, width=32).grid(
            row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(top, text="填 v1.0.0 就顺带发版本；留空 = 只提交不发布",
                  foreground=MUTED).grid(row=3, column=2, columnspan=2,
                                         sticky="w", padx=(8, 0), pady=(8, 0))

        ttk.Label(top, text="目标分支（留空 = 默认分支）").grid(
            row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(top, textvariable=self.v_branch, width=32).grid(
            row=4, column=1, sticky="w", padx=(8, 0), pady=(8, 0))
        ttk.Label(top, text="例：dev（不存在会以默认分支为基准新建）",
                  foreground=MUTED).grid(row=4, column=2, columnspan=2,
                                         sticky="w", padx=(8, 0), pady=(8, 0))

        row5 = ttk.Frame(top)
        row5.grid(row=5, column=1, columnspan=3, sticky="w", padx=(8, 0),
                  pady=(8, 0))
        ttk.Radiobutton(row5, text="公开（才能收 star）", variable=self.v_pub,
                        value=1).pack(side="left")
        ttk.Radiobutton(row5, text="私有", variable=self.v_pub,
                        value=0).pack(side="left", padx=(12, 0))
        ttk.Checkbutton(row5, text="记住 Token（存到本地 .gh_token）",
                        variable=self.v_remember).pack(side="left", padx=(18, 0))

        row6 = ttk.Frame(top)
        row6.grid(row=6, column=1, columnspan=3, sticky="w", padx=(8, 0),
                  pady=(6, 0))
        ttk.Checkbutton(row6, text="打包 exe 并作为附件上传（约 40 秒）",
                        variable=self.v_exe).pack(side="left")
        ttk.Checkbutton(row6, text="不走代理（直连）",
                        variable=self.v_noproxy).pack(side="left", padx=(18, 0))
        ttk.Checkbutton(row6, text="显示 Token 明文（核对用）",
                        variable=self.v_show,
                        command=self._toggle_show).pack(side="left", padx=(18, 0))
        top.columnconfigure(1, weight=1)

        bar = ttk.Frame(self, padding=(12, 0))
        bar.pack(fill="x")
        self.btn = ttk.Button(bar, text="开始上传", style="Accent.TButton",
                              command=self.start)
        self.btn.pack(side="left")
        ttk.Button(bar, text="先体检（不联网）",
                   command=self.check).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="打开仓库页",
                   command=self.open_repo).pack(side="left", padx=(8, 0))
        self.status = ttk.Label(bar, text="待上传 %d 个文件" % len(gh_upload.FILES),
                                foreground=MUTED)
        self.status.pack(side="left", padx=(14, 0))

        self.txt = scrolledtext.ScrolledText(self, wrap="word", height=18,
                                             font=("Consolas", 10), bg=SURFACE,
                                             fg=TEXT, relief="flat",
                                             highlightthickness=1,
                                             highlightbackground=BORDER)
        self.txt.pack(fill="both", expand=True, padx=12, pady=10)
        self.txt.insert("end",
                        "填好 Token 后点【开始上传】。\n"
                        "首次运行会自动建库，之后每次都是一个新 commit。\n"
                        "上传的是 gh_upload.FILES 里列出的 %d 个文件；\n"
                        "目录里的 __pycache__ / _*.py / *.bak_* 等不会被带上。\n\n"
                        % len(gh_upload.FILES))
        self.txt.configure(state="disabled")

        self.after(100, self._pump)

    # ---------- 显示开关 ----------
    def _toggle_show(self):
        """切换 Token 框：圆点 <-> 明文，方便核对有没有粘错东西。"""
        try:
            self.e_tok.configure(show="" if self.v_show.get() else "•")
        except Exception:
            pass

    # ---------- 日志 ----------
    def _log(self, s=""):
        s = str(s)
        self.q.put(("log", s))
        # 落盘 —— 原来只在文本框，关窗就没了，出问题无从追查
        try:
            with open(os.path.join(HERE, "gh_upload.log"), "a",
                      encoding="utf-8") as fh:
                fh.write(s + "\n")
        except Exception:
            pass

    def _pump(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.txt.configure(state="normal")
                    self.txt.insert("end", data + "\n")
                    self.txt.see("end")
                    self.txt.configure(state="disabled")
                elif kind == "done":
                    self.btn.configure(state="normal")
                    self.status.configure(text="完成", foreground=OK_C)
                    if messagebox.askyesno("上传完成",
                                           "%s\n\n现在打开仓库页？" % data):
                        webbrowser.open(data)
                elif kind == "warn":
                    head, url = data
                    self.btn.configure(state="normal")
                    self.status.configure(text="部分完成", foreground=WARN_C)
                    self._log("")
                    self._log("========== 部分完成 ==========")
                    self._log(head)
                    self._log("仓库: %s" % url)
                    messagebox.showwarning(
                        "部分完成",
                        "%s\n\n仓库已更新（代码已推送），但上面这些没做完。\n%s"
                        % (head[:700], url))
                elif kind == "err":
                    head, tb = data if isinstance(data, tuple) else (data, "")
                    self.btn.configure(state="normal")
                    self.status.configure(text="失败", foreground=ERR_C)
                    self._log("")
                    self._log("========== 失败 ==========")
                    self._log(head)
                    if tb:
                        self._log(tb)
                        # 完整堆栈落盘，下次不用靠截图
                        try:
                            with open(os.path.join(HERE,
                                                   "gh_upload_error.log"),
                                      "a", encoding="utf-8") as fh:
                                fh.write("\n===== %s =====\n%s\n%s\n"
                                         % (time.strftime("%Y-%m-%d %H:%M:%S"),
                                            head, tb))
                            self._log("(完整堆栈已写入 gh_upload_error.log)")
                        except Exception:
                            pass
                    messagebox.showerror("上传失败", head[:900])
        except queue.Empty:
            pass
        self.after(120, self._pump)

    # ---------- 动作 ----------
    def check(self):
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("end", "=== 本地文件体检（不联网）===\n")
        tot = 0
        bad = 0
        for f in gh_upload.FILES:
            p = os.path.join(HERE, f)
            if not os.path.isfile(p):
                bad += 1
                self.txt.insert("end", "  缺失 %-32s\n" % f)
                continue
            d = open(p, "rb").read()
            if d[:4] == b"%TSD":
                bad += 1
                self.txt.insert("end", "  密文 %-32s %8d B\n" % (f, len(d)))
            else:
                tot += len(d)
                self.txt.insert("end", "  OK   %-32s %8d B\n" % (f, len(d)))
        self.txt.insert("end", "\n合计 %d 个文件 / %.1f KB   ——  %s\n"
                        % (len(gh_upload.FILES), tot / 1024.0,
                           "全部就绪，可以上传 ✓" if not bad
                           else "有 %d 项有问题 ✗" % bad))
        self.txt.configure(state="disabled")
        self.status.configure(
            text=("体检通过" if not bad else "体检发现 %d 项问题" % bad),
            foreground=(OK_C if not bad else ERR_C))

    def open_repo(self):
        repo = self.v_repo.get().strip() or DEFAULT_REPO
        webbrowser.open("https://github.com/%s/%s" % ("<你的用户名>", repo))

    def start(self):
        # 先体检 token
        raw_tok = self.v_tok.get()
        if gh_upload.looks_masked(raw_tok):
            messagebox.showerror(
                "填的是圆点，不是 Token",
                "Token 框里是 %d 个圆点（密码框的掩码字符），不是真正的 token。\n\n"
                "GitHub 只在【生成的那一刻】显示一次明文（形如 ghp_xxxx，40 位）。\n"
                "  1) 点【去获取】重新生成一个（勾 repo 权限）\n"
                "  2) 明文显示时立刻复制，粘进 Token 框\n"
                "  3) 勾上下面的「显示 Token 明文」可以核对粘对了没有"
                % len(raw_tok.strip()))
            return
        token, _tips = gh_upload.check_token(raw_tok)
        if _tips:
            self.v_tok.set(token)
            messagebox.showwarning(
                "Token 体检有可疑之处",
                "本地体检发现：\n\n• " + "\n• ".join(_tips) +
                "\n\n已经按上面说的修整过了（框里显示的就是实际要用的值）。\n"
                "classic token 一定是 ghp_ 开头的【40 位】；\n"
                "建议勾上【显示 Token 明文（核对用）】再核对一眼。")
        repo = self.v_repo.get().strip() or DEFAULT_REPO
        msg = self.v_msg.get().strip()
        branch = self.v_branch.get().strip()
        tag = self.v_tag.get().strip()
        public = (self.v_pub.get() == 1)
        # 勾了"打包 exe"却没填 tag -> 自动补一个，而不是静默丢掉 exe
        if self.v_exe.get() and not tag:
            tag = gh_upload.default_release_tag()
            self.v_tag.set(tag)
        if not token:
            messagebox.showwarning("缺 Token",
                                   "先填 GitHub Token（勾 repo 权限那个）。")
            return
        if self.v_remember.get():
            try:
                open(TOKEN_FILE, "w", encoding="utf-8").write(token)
            except Exception:
                pass
        elif os.path.isfile(TOKEN_FILE):
            try:
                os.remove(TOKEN_FILE)
            except Exception:
                pass

        self.btn.configure(state="disabled")
        self.status.configure(text="上传中…", foreground=ACCENT)
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.configure(state="disabled")

        def work():
            try:
                if self.v_noproxy.get():
                    gh_upload.set_no_proxy()
                    self._log("已禁用代理，走直连。")
                url = gh_upload.do_upload(
                    token, repo, message=msg, public=public, log=self._log,
                    branch=branch, release_tag=(tag or None),
                    release_notes=msg,
                    with_exe=bool(self.v_exe.get() and tag))
                self.q.put(("done", url))
            except gh_upload.PartialUpload as e:
                self.q.put(("warn", (str(e), e.url)))
            except SystemExit as e:
                self.q.put(("err", (str(e), "")))
            except Exception as e:
                tb = traceback.format_exc()
                # 弹窗会被截断 —— 把"真正的原因"放最前面，堆栈进日志框
                head = "%s: %s" % (type(e).__name__, e)
                self.q.put(("err", (head, tb)))

        threading.Thread(target=work, daemon=True).start()


def main():
    Uploader().mainloop()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        try:
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror("启动失败", err[:900])
        except Exception:
            print(err)
