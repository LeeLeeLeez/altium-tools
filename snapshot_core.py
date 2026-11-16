#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""工程快照 —— 纯逻辑层（只用标准库，不依赖 tkinter，可整段移植到别的项目）

目录约定
--------
    <根目录>/<YYYYMMDD>/<YYYYMMDDHHMM>/<工程文件>

「新建」四步
------------
1. 在根目录下建当天日期文件夹（已存在则复用）
2. 在其下建当前时间戳文件夹（同分钟重复则自动升到秒）
3. 把「上一个快照」里的工程本体拷过来
4. 拷来的 .PrjPcb / .PrjPcbStructure 文件名加时间戳后缀（先剥旧后缀，避免叠加）

只拷工程本体
------------
扩展名白名单 PROJ_BODY_EXTS 之外的一律不拷（_copy_ / _plain_ / .bak_ / *.zip / *_check 之类
扩展名对不上白名单，自动淘汰）。另跳过 History/、__Previews/、旧工程名的日志/输出版目录。

源快照怎么选
------------
🔴 按「工程本体文件的最新 mtime」选，**不是**按目录名时间戳。
   建完新快照不一定会切过去继续干活，往往还在上一个目录里改；
   只看目录名会复制到过时内容（2026-11-15 踩过）。
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from datetime import datetime

# ---------------------------------------------------------------- 常量
DATE_RE = re.compile(r"^(\d{8})$")
# 时间戳命名（2026-11-16 起「年_月日_时分秒」，如 2026_1116_100845）
# 旧格式 202611161000 / 20261102_0909 仍要能识别，历史快照不能丢。
TS_NEW_RE = re.compile(r"^(\d{4})_(\d{4})_(\d{6})$")
TS_OLD_RE = re.compile(r"^(\d{8})_?(\d{4})?(\d{0,2})?$")
# 文件名尾部已有的时间戳后缀（新旧两种都要能剥）
TS_TAIL_RE = re.compile(r"_(?:\d{4}_\d{4}_\d{6}|\d{8}_?\d{4}(?:\d{2})?)$")
LOG_OUT_RE = re.compile(r"^Project (?:Logs|Outputs) for (.+)$", re.IGNORECASE)

# 工程本体 = 工程真正引用的设计文档 + 工程文件
PROJ_BODY_EXTS = (".SchDoc", ".PcbDoc", ".BomDoc", ".PrjPcb", ".PrjPcbStructure",
                  ".OutJob", ".SchLib", ".PcbLib", ".Harness")
PROJ_SUFFIXES = (".PrjPcb", ".PrjPcbStructure")   # 要加时间戳后缀的
SKIP_DIR_NAMES = {"history", "__previews"}        # 小写比较，任意层级


def human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%.1f %s" % (n, u)
        n /= 1024.0
    return "%.1f TB" % n


def sha256(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


# ---------------------------------------------------------------- 快照枚举
class Snapshot(object):
    """一个时间戳快照。"""

    __slots__ = ("date", "hhmm", "path", "mtime")

    def __init__(self, date: str, hhmm: str, path: str, mtime: float):
        self.date = date
        self.hhmm = hhmm
        self.path = path
        self.mtime = mtime

    def __repr__(self):
        return "<Snapshot %s/%s>" % (self.date, os.path.basename(self.path))

    @property
    def rel(self) -> str:
        return "%s/%s" % (self.date, os.path.basename(self.path))

    @property
    def mtime_text(self) -> str:
        if not self.mtime:
            return "—"
        return datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M")


def body_mtime(path: str) -> float:
    """快照里「工程本体」最近一次写入时间。copy2 保留 mtime，复制品不会冒充更新。"""
    mx = 0.0
    for cur, dirs, names in os.walk(path):
        dirs[:] = [d for d in dirs
                   if d.lower() not in SKIP_DIR_NAMES and not LOG_OUT_RE.match(d)]
        for n in names:
            if n.endswith(PROJ_BODY_EXTS):
                try:
                    mx = max(mx, os.path.getmtime(os.path.join(cur, n)))
                except OSError:
                    pass
    return mx


def fmt_ts(now: datetime) -> str:
    """时间戳文件夹名 / PrjPcb 后缀：年_月日_时分秒。"""
    return now.strftime("%Y_%m%d_%H%M%S")


def parse_ts(name: str):
    """解析快照目录名，返回 (date8, hhmmss6)；不是时间戳目录则 None。"""
    m = TS_NEW_RE.match(name)
    if m:
        return (m.group(1) + m.group(2), m.group(3))
    m = TS_OLD_RE.match(name)
    if m and m.group(2):
        return (m.group(1), (m.group(2) + (m.group(3) or "")).ljust(6, "0"))
    if m:                                  # 纯 8 位：老式只到日的目录
        return (m.group(1), "000000")
    return None


def list_snapshots(root: str):
    """返回 [Snapshot]，按目录名时间升序。"""
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root)):
        dpath = os.path.join(root, name)
        if not os.path.isdir(dpath) or not DATE_RE.match(name):
            continue
        for sub in sorted(os.listdir(dpath)):
            spath = os.path.join(dpath, sub)
            if not os.path.isdir(spath):
                continue
            parsed = parse_ts(sub)
            if not parsed:
                continue                      # 如 'parse'、'kicad_prj'
            out.append(Snapshot(parsed[0], parsed[1], spath,
                                body_mtime(spath)))
    out.sort(key=lambda s: (s.date, s.hhmm))
    return out


def scan(root: str) -> dict:
    """扫描整个快照库，返回 GUI 需要的摘要。"""
    snaps = list_snapshots(root)
    if not snaps:
        return {"root": root, "snaps": [], "source": None, "note": None,
                "dates": []}

    by_time = max(snaps, key=lambda s: (s.mtime, s.date + s.hhmm))
    newest_name = snaps[-1]
    note = None
    if newest_name.path != by_time.path:
        note = ("目录名最新的是 %s，但最后写入的工程文件在 %s ⇒ 用后者"
                "（前者建完后没有新的保存动作）"
                % (newest_name.rel, by_time.rel))

    dates = {}
    for s in snaps:
        dates.setdefault(s.date, []).append(s)
    return {
        "root": root,
        "snaps": snaps,
        "source": by_time,
        "note": note,
        "dates": sorted(dates.items(), reverse=True),
    }


# ---------------------------------------------------------------- 选哪些文件
def find_proj_stem(src: str):
    """源快照里的工程名（*.PrjPcb 去后缀）。"""
    try:
        for n in sorted(os.listdir(src)):
            if n.lower().endswith(".prjpcb"):
                return os.path.splitext(n)[0]
    except OSError:
        pass
    return None


def resolve_log_keep(src: str, keep_proj):
    """决定保留哪组 `Project Logs/Outputs for <X>`。

    优先 X == 当前工程名；若源里还没有当前名的目录（刚建完就再建一次），
    退回保留时间戳最新的那一组，免得上一轮日志整批丢掉。
    """
    names = []
    try:
        for n in sorted(os.listdir(src)):
            m = LOG_OUT_RE.match(n)
            if m and os.path.isdir(os.path.join(src, n)):
                names.append((n, m.group(1)))
    except OSError:
        return set()
    if not names:
        return set()
    xs = {x for _, x in names}
    if keep_proj and keep_proj in xs:
        target = keep_proj
    else:
        def key(x):
            m = re.search(r"(\d{8})_?(\d{4})?$", x)
            if not m:
                return ("00000000", "0000")
            return (m.group(1), m.group(2) or "0000")
        target = max(xs, key=key)
    return {n for n, x in names if x == target}


def walk_files(src: str, keep_proj=None):
    """返回 (要拷文件 [(rel, abs)], 跳过目录 [(rel, nfiles, nbytes)], 跳过文件 [(rel, size)])。"""
    files, skipped, skipped_files = [], [], []
    keep_dirs = resolve_log_keep(src, keep_proj)

    def dir_stat(p):
        nf = nb = 0
        for c, _, ns in os.walk(p):
            for n in ns:
                nf += 1
                try:
                    nb += os.path.getsize(os.path.join(c, n))
                except OSError:
                    pass
        return nf, nb

    for cur, dirs, names in os.walk(src):
        keep = []
        for d in sorted(dirs):
            full = os.path.join(cur, d)
            rel = os.path.relpath(full, src)
            if d.lower() in SKIP_DIR_NAMES:
                nf, nb = dir_stat(full)
                skipped.append((rel, nf, nb))
                continue
            if LOG_OUT_RE.match(d) and d not in keep_dirs:
                nf, nb = dir_stat(full)
                skipped.append((rel, nf, nb))
                continue
            keep.append(d)
        dirs[:] = keep
        for n in sorted(names):
            ap = os.path.join(cur, n)
            rel = os.path.relpath(ap, src)
            if not n.endswith(PROJ_BODY_EXTS):
                skipped_files.append((rel, os.path.getsize(ap)))
                continue
            files.append((rel, ap))
    return files, skipped, skipped_files


class Plan(object):
    """一次「新建」的完整计划（预览就是只算不写）。"""

    def __init__(self, root, src, ts, now):
        self.root = root
        self.src = src
        self.ts = ts
        self.now = now
        self.today = now.strftime("%Y%m%d")
        self.today_dir = os.path.join(root, self.today)
        self.dst = os.path.join(self.today_dir, ts)
        self.keep_proj = find_proj_stem(src)
        self.files, self.skipped_dirs, self.skipped_files = walk_files(
            src, self.keep_proj)
        self.files.sort()
        self.pcb_note = None
        pcbs = [(r, a) for r, a in self.files if r.lower().endswith(".pcbdoc")]
        if len(pcbs) > 1:
            pcbs.sort(key=lambda t: os.path.getmtime(t[1]), reverse=True)
            for rel, ap in pcbs[1:]:
                self.files.remove((rel, ap))
                self.skipped_files.append((rel, os.path.getsize(ap)))
            self.pcb_note = ("多个 .PcbDoc，只取最新：%s（%s）"
                             % (os.path.basename(pcbs[0][1]),
                                datetime.fromtimestamp(
                                    os.path.getmtime(pcbs[0][1])
                                ).strftime("%m-%d %H:%M")))
        self.renames = []
        for rel, ap in self.files:
            base = os.path.basename(rel)
            if base.endswith(PROJ_SUFFIXES):
                stem, ext = os.path.splitext(base)
                clean = TS_TAIL_RE.sub("", stem) or stem
                newbase = "%s_%s%s" % (clean, ts, ext)
                if newbase != base:
                    self.renames.append(
                        (rel, os.path.join(os.path.dirname(rel), newbase)))

    @property
    def total_bytes(self) -> int:
        return sum(os.path.getsize(p) for _, p in self.files)

    @property
    def skipped_bytes(self) -> int:
        return sum(s for _, s in self.skipped_files)

    def rename_map(self) -> dict:
        return dict(self.renames)

    def prjpcb_name(self):
        """新快照里最终那个 .PrjPcb 的相对名。"""
        rmap = self.rename_map()
        for rel, _ap in self.files:
            if rel.lower().endswith(".prjpcb"):
                return rmap.get(rel, rel)
        return None

    def prjpcb_path(self) -> str:
        n = self.prjpcb_name()
        return os.path.join(self.dst, n) if n else ""


def pick_ts_name(today_dir: str, now: datetime) -> str:
    """时间戳 = 年_月日_时分秒；同一秒重复则加 _2/_3。"""
    ts = fmt_ts(now)
    if not os.path.exists(os.path.join(today_dir, ts)):
        return ts
    base, i = ts, 2
    while os.path.exists(os.path.join(today_dir, ts)):
        ts = "%s_%d" % (base, i)
        i += 1
    return ts


def make_plan(root: str, src: str, now: datetime) -> Plan:
    today = now.strftime("%Y%m%d")
    ts = pick_ts_name(os.path.join(root, today), now)
    return Plan(root, src, ts, now)


# ---------------------------------------------------------------- 执行
def create(plan: Plan, progress=None) -> dict:
    """真执行：建目录 → 复制 → 改名 → 逐文件比 size+sha256。

    progress(msg) 用于往 GUI 日志里写进度，可选。
    """
    say = progress or (lambda s: None)
    res = {"ok": False, "dst": plan.dst, "errors": [], "missing": [],
           "size_bad": [], "sha_bad": [], "count": 0, "prjpcb": ""}

    try:
        os.makedirs(plan.dst, exist_ok=True)
    except Exception as e:
        res["errors"].append("建目录失败: %s" % e)
        return res

    for rel, ap in plan.files:
        out = os.path.join(plan.dst, rel)
        try:
            os.makedirs(os.path.dirname(out), exist_ok=True)
            # copy2：保留 mtime；Python 进程复制不会触发 DLP 把明文重写成密文
            shutil.copy2(ap, out)
        except Exception as e:
            res["errors"].append("%s -> %s" % (rel, e))

    for a, b in plan.renames:
        srcf = os.path.join(plan.dst, a)
        if os.path.exists(srcf):
            try:
                os.rename(srcf, os.path.join(plan.dst, b))
            except Exception as e:
                res["errors"].append("改名失败 %s: %s" % (a, e))

    rmap = plan.rename_map()
    for rel, ap in plan.files:
        tgt = os.path.join(plan.dst, rmap.get(rel, rel))
        if not os.path.exists(tgt):
            res["missing"].append(rel)
            continue
        res["count"] += 1
        if os.path.getsize(tgt) != os.path.getsize(ap):
            res["size_bad"].append(rel)
            continue
        try:
            if sha256(tgt) != sha256(ap):
                res["sha_bad"].append(rel)
        except Exception as e:
            res["errors"].append("校验失败 %s: %s" % (rel, e))

    res["prjpcb"] = plan.prjpcb_path()
    res["ok"] = (not res["errors"] and not res["missing"]
                 and not res["size_bad"] and not res["sha_bad"]
                 and res["count"] == len(plan.files))
    say("完成：%d/%d 个文件，%s" % (res["count"], len(plan.files),
                                  human(plan.total_bytes)) if res["ok"]
        else "有问题：见下方明细")
    return res
