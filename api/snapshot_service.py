"""工程快照 —— 扫描 / 预览 / 新建（移植自旧版 snapshot_page.py）。

核心算法全在 `snapshot_core.py`（纯标准库、无 tkinter），这里只做
「对象 → JSON」的序列化，以及浏览器拿不到服务器路径时的目录浏览。
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys

import snapshot_core as SC

from . import config_store

DEFAULT_ROOT = r"E:\project\800-6\PCB_prj\A4_prj"
MAX_RECENT = 6


def _snap(s) -> dict:
    if s is None:
        return None
    return {
        "date": getattr(s, "date", ""),
        "hhmm": getattr(s, "hhmm", ""),
        "path": getattr(s, "path", ""),
        "rel": getattr(s, "rel", ""),
        "mtime": getattr(s, "mtime", 0),
        "mtimeText": getattr(s, "mtime_text", "—"),
    }


def _plan(p) -> dict:
    files = []
    for rel, ap in p.files:
        try:
            size = os.path.getsize(ap)
        except OSError:
            size = 0
        files.append({"rel": rel, "abs": ap, "size": size})
    return {
        "root": p.root,
        "src": p.src,
        "ts": p.ts,
        "today": p.today,
        "todayDir": p.today_dir,
        "dst": p.dst,
        "keepProj": p.keep_proj,
        "pcbNote": p.pcb_note,
        "files": files,
        "skippedDirs": [{"rel": r, "nfiles": n, "nbytes": b}
                        for r, n, b in p.skipped_dirs],
        "skippedFiles": [{"rel": r, "size": s} for r, s in p.skipped_files],
        "renames": [{"from": a, "to": b} for a, b in p.renames],
        "totalBytes": p.total_bytes,
        "skippedBytes": p.skipped_bytes,
        "human": SC.human(p.total_bytes),
        "prjpcb": p.prjpcb_name(),
    }


def scan(root: str) -> dict:
    """扫描快照库：有哪些日期目录、哪些快照、源工程是哪个。"""
    root = (root or "").strip()
    if not root:
        raise ValueError("请先填写快照库根目录")
    if not os.path.isdir(root):
        raise ValueError(f"根目录不存在：{root}")
    info = SC.scan(root)
    snaps = [_snap(s) for s in info.get("snaps", [])]
    dates = []
    for item in info.get("dates", []) or []:
        if isinstance(item, (tuple, list)) and len(item) == 2:
            d, lst = item
            dates.append({"date": d, "snaps": [_snap(s) for s in lst]})
    return {
        "ok": True,
        "root": root,
        "snaps": snaps,
        "source": _snap(info.get("source")),
        "note": info.get("note"),
        "dates": dates,
        "counts": {"dates": len(dates), "snaps": len(snaps)},
    }


def plan(root: str) -> dict:
    """预览（只算不写）：将要生成什么、要拷哪些文件。"""
    root = (root or "").strip()
    if not root or not os.path.isdir(root):
        raise ValueError(f"根目录不存在：{root}")
    info = SC.scan(root)
    src = info.get("source")
    if src is None:
        raise ValueError("没有找到可作为源的工程目录")
    p = SC.make_plan(root, src.path, datetime.datetime.now())
    return {"ok": True, "plan": _plan(p)}


def create(root: str) -> dict:
    """真执行：建目录 → 复制 → 改名 → 逐文件比 size + sha256。"""
    root = (root or "").strip()
    if not root or not os.path.isdir(root):
        raise ValueError(f"根目录不存在：{root}")
    info = SC.scan(root)
    src = info.get("source")
    if src is None:
        raise ValueError("没有找到可作为源的工程目录")
    p = SC.make_plan(root, src.path, datetime.datetime.now())
    if not p.files:
        raise ValueError("没有可拷的文件")

    log: list = []
    res = dict(SC.create(p, progress=lambda m: log.append(m)))
    res["ok"] = bool(res.get("ok"))
    res["log"] = log
    res["plan"] = _plan(p)
    if res.get("ok"):
        config_store.update_config({"snap_last_dst": res.get("dst", "")})
    return res


def browse(path: str) -> dict:
    """服务器端目录浏览（浏览器选不到本机路径）。"""
    path = (path or "").strip() or DEFAULT_ROOT
    path = os.path.abspath(path)
    out = {"path": path, "parent": None, "dirs": [], "exists": False}
    if not os.path.isdir(path):
        return out
    out["exists"] = True
    parent = os.path.dirname(path)
    if parent and parent != path:
        out["parent"] = parent
    try:
        for n in sorted(os.listdir(path)):
            full = os.path.join(path, n)
            if os.path.isdir(full):
                out["dirs"].append({"name": n, "path": full})
    except OSError as e:
        out["error"] = str(e)
    return out


def reveal(path: str) -> dict:
    """在资源管理器里打开（Windows）。"""
    path = (path or "").strip()
    if not path:
        raise ValueError("路径为空")
    if not os.path.exists(path):
        raise ValueError(f"路径不存在：{path}")
    try:
        if sys.platform.startswith("win"):
            if os.path.isdir(path):
                os.startfile(path)  # noqa: S606
            else:
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(path) or path])
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"打开失败：{e}")
    return {"ok": True, "path": path}


def config() -> dict:
    """快照页的配置（根目录 + 最近目录列表）。"""
    cfg = config_store.get_config()
    return {
        "snapRoot": cfg.get("snap_root") or "",
        "snapRoots": list(cfg.get("snap_roots") or []),
        "snapLastDst": cfg.get("snap_last_dst") or "",
        "defaultRoot": DEFAULT_ROOT,
    }


def save_config(patch: dict) -> dict:
    roots = list(patch.get("snapRoots") or [])
    keep = []
    for r in roots:
        if r and r not in keep:
            keep.append(r)
    keep = keep[-MAX_RECENT:]
    out = {
        "snapRoot": patch.get("snapRoot", ""),
        "snapRoots": keep,
        "snapLastDst": patch.get("snapLastDst", ""),
    }
    config_store.update_config(out)
    return config()
